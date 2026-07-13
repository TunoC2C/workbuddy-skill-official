#!/usr/bin/env python3
"""ai_review — 模型无关的 PR 评审脚本(替代厂商专用 code-review action)。

为什么独立写:
  厂商专用 action 往往只能跑单一模型族。v2.1 起 harness 支持任意 LLM
  (Anthropic/OpenAI/DeepSeek/Qwen/Kimi/GLM/...),所以评审 workflow 不能锁死在
  某一家 action。本脚本把"读 diff → 调 LLM → 解析 VERDICT → 发评审 → 决定门禁"
  做成一段可移植的 Python,任何厂商都能跑。

用法(在 GitHub Actions 里):
  python3 scripts/ai_review.py --pass quality      # 第 1 趟:质量
  python3 scripts/ai_review.py --pass security     # 第 2 趟:安全
  python3 scripts/ai_review.py --pass dependency   # 第 3 趟:依赖

退出码:
  0 = PASS,1 = BLOCK(让 ci-gate 红),2 = 配置错误

读取的 env(在 workflow 里设):
  LLM_PROVIDER, LLM_API_KEY[, LLM_BASE_URL], LLM_MODEL_<ROLE>
  GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, BASE_REF

零凭证试跑:
  python3 scripts/ai_review.py --pass quality --mock
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from _adapters import ModelAdapter, record_token_usage

# v2.2: 支持 reusable workflow 场景——被另一个仓 uses: 调用时,prompts/ 不在 cwd 下;
# 工作流可设 AIFCL_PROMPTS_DIR=_aifcl/core/prompts 指过去。默认仍是 ./prompts。
_PROMPTS_DIR = os.getenv("AIFCL_PROMPTS_DIR", "prompts")
PROMPTS = {
    "quality":    f"{_PROMPTS_DIR}/review-quality.md",
    "security":   f"{_PROMPTS_DIR}/review-security.md",
    "dependency": f"{_PROMPTS_DIR}/review-dependency.md",
}

# 三趟与 sub-agent 的对应关系(影响 LLM_MODEL_<ROLE> 的覆盖键)
PASS_ROLE = {
    "quality":    "verifier-quality",
    "security":   "verifier-security",
    "dependency": "verifier-dependency",
}


def sh(*args: str, **kw) -> str:
    return subprocess.run(args, capture_output=True, text=True, **kw).stdout


def collect_diff(base_ref: str) -> str:
    sh("git", "fetch", "--quiet", "origin", base_ref, check=False)
    return sh("git", "diff", f"origin/{base_ref}...HEAD")


def collect_dep_diff(base_ref: str) -> str:
    """依赖趟只看依赖清单变化,降本。"""
    return sh(
        "git", "diff", f"origin/{base_ref}...HEAD", "--",
        "**/package.json", "pnpm-lock.yaml",
        "go.mod", "go.sum",
        "requirements*.txt", "pyproject.toml",
        "Cargo.toml", "Cargo.lock",
    )


def post_pr_comment(repo: str, pr: str, token: str, body: str) -> None:
    """用 gh CLI 发 PR 评论(workflow 里 gh 总是装好的)。"""
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    subprocess.run(
        ["gh", "pr", "comment", pr, "--repo", repo, "--body", body],
        env=env, check=False,
    )


def parse_verdict(text: str) -> str | None:
    """从模型输出末尾找 VERDICT: PASS|BLOCK。容错:有时模型会写在中间。

    找不到明确判定时返回 None,由调用方显式处理降级路径。
    """
    for line in reversed(text.splitlines()):
        s = line.strip().upper()
        if s.startswith("VERDICT:"):
            if "BLOCK" in s:
                return "BLOCK"
            if "PASS" in s:
                return "PASS"
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--pass", dest="pass_", required=True, choices=list(PROMPTS))
    p.add_argument("--mock", action="store_true",
                   help="不调真实 LLM,只读 prompt 与 diff,验证骨架")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    pass_name = args.pass_
    role = PASS_ROLE[pass_name]

    base_ref = os.getenv("BASE_REF", "main")
    pr = os.getenv("PR_NUMBER", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    gh_token = os.getenv("GITHUB_TOKEN", "")

    prompt_path = Path(PROMPTS[pass_name])
    if not prompt_path.exists():
        print(f"::error::找不到 prompt 文件 {prompt_path}", file=sys.stderr)
        return 2

    base_prompt = prompt_path.read_text(encoding="utf-8")

    if pass_name == "dependency":
        diff = collect_dep_diff(base_ref)
        if not diff.strip():
            print("✓ 本 PR 未改依赖,跳过依赖评审。")
            return 0
        context_label = "DEPENDENCY DIFF"
    else:
        diff = collect_diff(base_ref)
        context_label = "FULL DIFF"

    # 让 diff 太大时不至于一次性烧爆 context;按 80k tokens ≈ 320k chars 粗截
    MAX_DIFF_CHARS = int(os.getenv("AI_REVIEW_MAX_DIFF_CHARS", "320000"))
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + f"\n\n[…diff 超长,截断到 {MAX_DIFF_CHARS} 字符,这是评审噪音信号——拆 PR…]"

    full_prompt = (
        base_prompt
        + f"\n\n---\n\n{context_label}\n```diff\n{diff}\n```\n"
        + "\n请按规则输出发现,末尾给出 `VERDICT: PASS` 或 `VERDICT: BLOCK`。"
    )

    # degraded ∈ {None, "no_credentials", "model_error", "no_verdict"}
    # 评审没真正执行时不许静默放行:默认 fail-open,但要 warning + PR 评论显式说明;
    # 设 AI_REVIEW_FAIL_CLOSED=1 可改为严格 BLOCK。
    degraded = None
    if args.mock:
        print(f"=== MOCK pass={pass_name} role={role} prompt_chars={len(full_prompt)} ===")
        verdict = "PASS"
        review_body = f"[MOCK] {pass_name} pass — legacy 云 LLM 路径假装通过。"
    else:
        review_body = ModelAdapter.summarize(
            full_prompt, loop="ai-review", role=role,
        )
        if review_body.startswith("[模型未配置"):
            degraded = "no_credentials"
        elif review_body.startswith("[模型调用失败"):
            degraded = "model_error"
        raw = parse_verdict(review_body)
        if raw is None and degraded is None:
            degraded = "no_verdict"
        verdict = raw or "PASS"

    fail_closed = os.getenv("AI_REVIEW_FAIL_CLOSED", "").lower() in ("1", "true", "yes")
    if degraded:
        print(f"::warning::AI review pass={pass_name} 未真正判定({degraded})"
              f"{' — FAIL_CLOSED 开启,按 BLOCK 处理' if fail_closed else ' — 按 PASS 放行(fail-open)'}"
              f":{review_body[:160]}")
        if fail_closed:
            verdict = "BLOCK"

    print(f"--- {pass_name} verdict: {verdict} ---")
    print(review_body[:2000])

    # 发评论(真跑时)。verdict 一行单独高亮放头部,方便人扫;
    # 评审未真正执行时用 warning 头部显式区分,不许伪装成 PASS。
    if pr and repo and gh_token and not args.mock:
        if degraded and verdict != "BLOCK":
            header = (f"⚠️ **AI Review · {pass_name} · SKIPPED({degraded})** — "
                      "评审未真正执行,按 fail-open 放行。修复凭证/模型后 re-run 本 job。")
        elif degraded and verdict == "BLOCK":
            header = (f"🛑 **AI Review · {pass_name} · BLOCK(FAIL_CLOSED:{degraded})** — "
                      "评审未真正执行且严格模式开启。")
        elif verdict == "PASS":
            header = "✅ **AI Review · " + pass_name + " · PASS**"
        else:
            header = "🛑 **AI Review · " + pass_name + " · BLOCK**"
        post_pr_comment(repo, pr, gh_token, header + "\n\n" + review_body)

    return 1 if verdict == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
