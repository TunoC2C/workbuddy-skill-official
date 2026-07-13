#!/usr/bin/env python3
"""goal_loop — /goal 风格的执行回路。

灵感:Addy Osmani《Loop Engineering》—— "loop 跑到一个可验证的停止条件成立为止"。
核心分工:做事的 agent 不能是判断 done 的 agent(maker/checker split)。

机制:
  1. 取一个任务规约 + 停止条件 + 起始状态
  2. 循环最多 N 次:
     a) 调 implementer agent 推进一步,产出 diff/状态变化
     b) 调 *独立的* checker agent 判断停止条件是否成立
     c) 持久化状态到 state/tasks/<task-id>.json
  3. 命中 done / 超 token 预算 / 超迭代上限 任一即停

用法:
  # 跑一个新任务
  python3 scripts/goal_loop.py \\
      --task-id fix-billing-webhook \\
      --task-file state/tasks/fix-billing-webhook.md \\
      --stop "Linear ticket OPS-142 closed AND make test-integration green" \\
      --max-iterations 6

  # 复用已有状态继续
  python3 scripts/goal_loop.py --task-id fix-billing-webhook --resume

Day 0 (无模型 key) 也能跑:adapter 会返回 stub 决定,主要用于验证骨架。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from _adapters import ModelAdapter, record_token_usage

STATE_DIR = Path("state/tasks")
STATE_DIR.mkdir(parents=True, exist_ok=True)


def state_path(task_id: str) -> Path:
    return STATE_DIR / f"{task_id}.json"


def load_state(task_id: str) -> dict:
    p = state_path(task_id)
    if p.exists():
        return json.loads(p.read_text())
    return {"task_id": task_id, "iterations": [], "tokens_used": 0, "status": "pending"}


def save_state(state: dict) -> None:
    p = state_path(state["task_id"])
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def run_implementer(task: str, state: dict) -> dict:
    """Maker——推进一步。返回这一步做了什么 + 当前对外可观察的状态。

    真实接入:把 task + state 喂给 implementer agent(Codex CLI/SDK 或自建执行器),
    让它做一步增量。这里为了让 harness 在零依赖下跑通,实现最小桩。
    """
    summary = ModelAdapter.summarize(
        f"你是 implementer agent。任务:\n{task}\n\n"
        f"已尝试 {len(state['iterations'])} 轮。上次状态:{state.get('last_outcome', '初始')}。\n"
        "请用 4~6 行说明本轮你做了什么、改了哪些文件、为什么这是离 done 更近一步。",
        model=os.getenv("IMPLEMENTER_MODEL", "claude-sonnet-4-6"),
    )
    record_token_usage(loop="goal_loop", role="implementer",
                       model=os.getenv("IMPLEMENTER_MODEL", "claude-sonnet-4-6"))
    return {"summary": summary, "ts": dt.datetime.now(dt.timezone.utc).isoformat()}


def run_checker(task: str, stop_condition: str, state: dict) -> str:
    """Checker——独立判定 done。返回 'done' | 'continue' | 'stuck'。

    Checker 故意只读 + 用不同 prompt,绝不允许它继续写代码。
    """
    prompt = (
        "你是 checker agent。**只判定停止条件是否成立,不写代码。**\n\n"
        f"任务:{task}\n停止条件:{stop_condition}\n\n"
        f"实施历史(共 {len(state['iterations'])} 轮):\n"
        + "\n".join(f"- 轮{i+1}: {it.get('summary','(空)')[:200]}"
                    for i, it in enumerate(state["iterations"]))
        + "\n\n"
        "回答只能是三个词之一(单独一行):\n"
        "  done    — 停止条件已可验证成立\n"
        "  continue — 还差什么,implementer 应继续\n"
        "  stuck   — 在循环原地踏步或方向错,需要人介入\n"
    )
    out = ModelAdapter.summarize(prompt, model=os.getenv("CHECKER_MODEL", "claude-sonnet-4-6"))
    record_token_usage(loop="goal_loop", role="checker",
                       model=os.getenv("CHECKER_MODEL", "claude-sonnet-4-6"))
    # 第一行词作判定;模型未配置时 summarize 返回的字符串以 "[模型未配置" 开头 → 视为 continue
    first = (out.splitlines()[0] if out else "").strip().lower()
    if first in {"done", "continue", "stuck"}:
        return first
    return "continue"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    p.add_argument("--task-file", help="任务规约文件(架构师写的 markdown)")
    p.add_argument("--stop", help="可验证的停止条件描述")
    p.add_argument("--max-iterations", type=int, default=6)
    p.add_argument("--max-tokens", type=int, default=int(os.getenv("GOAL_LOOP_MAX_TOKENS", "200000")))
    p.add_argument("--resume", action="store_true", help="复用已存在的 state 继续")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    state = load_state(args.task_id)

    if not args.resume:
        if not args.task_file or not args.stop:
            print("首次运行需要 --task-file 与 --stop", file=sys.stderr)
            return 2
        state["task"] = Path(args.task_file).read_text(encoding="utf-8")
        state["stop_condition"] = args.stop
        state["max_iterations"] = args.max_iterations
        state["max_tokens"] = args.max_tokens

    task = state.get("task", "")
    stop_condition = state.get("stop_condition", "")
    max_iter = state.get("max_iterations", args.max_iterations)

    print(f"▶ goal_loop {args.task_id} — 已有 {len(state['iterations'])} 轮,上限 {max_iter}")

    while len(state["iterations"]) < max_iter and state["tokens_used"] < state["max_tokens"]:
        i = len(state["iterations"]) + 1
        print(f"  轮 {i} — implementer 推进")
        step = run_implementer(task, state)
        state["iterations"].append(step)
        state["last_outcome"] = step["summary"][:200]
        save_state(state)

        print(f"  轮 {i} — checker 判定")
        verdict = run_checker(task, stop_condition, state)
        step["verdict"] = verdict
        save_state(state)
        print(f"    → {verdict}")

        if verdict == "done":
            state["status"] = "done"
            save_state(state)
            print("✅ 停止条件成立。")
            return 0
        if verdict == "stuck":
            state["status"] = "needs_human"
            save_state(state)
            print("🛑 checker 判定卡住,需人介入。")
            return 1

    # 自然超限
    state["status"] = "exhausted"
    save_state(state)
    print(f"⏹ 达上限({len(state['iterations'])} 轮 / {state['tokens_used']} tokens),未到达停止条件。需人介入。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
