#!/usr/bin/env python3
"""perf_check — 性能回归门禁。

机制:
  1. 跑一段 k6 脚本(由用户提供,见 perf-scenarios/)
  2. 读它的 summary.json,提取关键指标(p95、p99、req/s、error rate)
  3. 与 state/perf-baseline.json 的对应 scenario 基线比对
  4. 任一指标恶化超过阈值 → 退出非零(让 perf-gate 红)
  5. 在 main 分支跑时,自动用新结果**滚动更新基线**(指数平滑,避免一次抖动定永)

设计原则:
  - 第一次跑(无基线)→ 写入基线,PASS(不能 BLOCK 一个还没有过去的事)
  - PR 跑时不更新基线,只比对(防止 PR 自己拉低基线给自己开后门)
  - 多个 scenario 独立基线,互不影响

用法:
  python3 scripts/perf_check.py --scenario homepage --summary k6-summary.json
  python3 scripts/perf_check.py --scenario homepage --summary k6-summary.json --update-baseline  # 仅 main 用

env(可选,有合理默认):
  PERF_P95_REGRESSION_PCT     默认 20  (p95 恶化 > 20% 触发 BLOCK)
  PERF_ERROR_RATE_MAX         默认 0.01(错误率 > 1% 触发 BLOCK,与基线无关的硬阈值)
  PERF_BASELINE_SMOOTHING     默认 0.3(新基线 = 0.3*new + 0.7*old,指数平滑)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "state"
BASELINE_FILE = STATE / "perf-baseline.json"

P95_PCT  = float(os.getenv("PERF_P95_REGRESSION_PCT", "20"))
ERR_MAX  = float(os.getenv("PERF_ERROR_RATE_MAX",     "0.01"))
SMOOTH   = float(os.getenv("PERF_BASELINE_SMOOTHING", "0.3"))


def parse_k6_summary(path: Path) -> dict:
    """从 k6 --summary-export 的 JSON 抽核心指标。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    metrics = data.get("metrics", {})
    # k6 字段名(适配 v0.50+)
    return {
        "p95_ms":     metrics.get("http_req_duration", {}).get("values", {}).get("p(95)", 0.0),
        "p99_ms":     metrics.get("http_req_duration", {}).get("values", {}).get("p(99)", 0.0),
        "rps":        metrics.get("http_reqs", {}).get("values", {}).get("rate", 0.0),
        "error_rate": metrics.get("http_req_failed", {}).get("values", {}).get("rate", 0.0),
    }


def load_baseline() -> dict:
    if not BASELINE_FILE.exists():
        return {}
    return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


def save_baseline(baseline: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2, sort_keys=True),
                             encoding="utf-8")


def evaluate(scenario: str, current: dict, baseline: dict | None) -> tuple[str, list[str]]:
    """返回 (verdict, messages)。verdict ∈ {'PASS','BLOCK'}。"""
    messages = []

    # 错误率是绝对阈值,任何时候都查
    if current["error_rate"] > ERR_MAX:
        messages.append(
            f"🛑 error_rate = {current['error_rate']:.3%} > 上限 {ERR_MAX:.1%}"
        )

    if not baseline:
        messages.append(f"ℹ 首次跑 scenario '{scenario}',无基线,自动建立。本次:"
                        f"p95={current['p95_ms']:.1f}ms rps={current['rps']:.1f} "
                        f"err={current['error_rate']:.3%}")
        return ("BLOCK" if current["error_rate"] > ERR_MAX else "PASS"), messages

    # 基线存在 → p95 恶化比例
    base_p95 = baseline.get("p95_ms", 0)
    if base_p95 > 0:
        pct = (current["p95_ms"] - base_p95) / base_p95 * 100
        if pct > P95_PCT:
            messages.append(
                f"🛑 p95 恶化 {pct:+.1f}% > 阈值 {P95_PCT}%  "
                f"(基线 {base_p95:.1f}ms → 本次 {current['p95_ms']:.1f}ms)"
            )
        else:
            messages.append(
                f"✓ p95 {pct:+.1f}%  (基线 {base_p95:.1f}ms → 本次 {current['p95_ms']:.1f}ms)"
            )

    # rps 下降也提示(不 BLOCK,只 WARN)
    base_rps = baseline.get("rps", 0)
    if base_rps > 0:
        delta = (current["rps"] - base_rps) / base_rps * 100
        if delta < -20:
            messages.append(f"⚠ rps 下降 {delta:.1f}% (基线 {base_rps:.1f} → 本次 {current['rps']:.1f})")

    verdict = "BLOCK" if any(m.startswith("🛑") for m in messages) else "PASS"
    return verdict, messages


def update_baseline(baseline: dict, scenario: str, current: dict) -> dict:
    """指数平滑滚动基线。"""
    prev = baseline.get(scenario, {})
    new = {}
    for k, v in current.items():
        p = prev.get(k, v)   # 没旧值就直接用新值
        new[k] = round(SMOOTH * v + (1 - SMOOTH) * p, 3)
    baseline[scenario] = new
    return baseline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True, help="scenario 名,与 perf-baseline.json key 对应")
    p.add_argument("--summary", required=True, help="k6 summary JSON 路径")
    p.add_argument("--update-baseline", action="store_true",
                   help="比对完成后用新数据滚动更新基线(仅 main 分支用)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary)
    if not summary_path.exists():
        print(f"::error::summary 文件不存在 {summary_path}", file=sys.stderr)
        return 2

    current = parse_k6_summary(summary_path)
    baseline = load_baseline()
    scenario_baseline = baseline.get(args.scenario)

    verdict, messages = evaluate(args.scenario, current, scenario_baseline)
    print(f"## ⚡ Perf check · scenario={args.scenario}")
    print(f"本次:p95={current['p95_ms']:.1f}ms p99={current['p99_ms']:.1f}ms "
          f"rps={current['rps']:.1f} err={current['error_rate']:.3%}")
    for m in messages:
        print(f"  {m}")

    if args.update_baseline:
        baseline = update_baseline(baseline, args.scenario, current)
        save_baseline(baseline)
        print(f"  ↳ 基线已滚动更新(EMA α={SMOOTH})")

    print(f"VERDICT: {verdict}")
    return 1 if verdict == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
