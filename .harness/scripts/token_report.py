#!/usr/bin/env python3
"""token_report — 从 state/token-usage.jsonl 聚合 token 花费,推日报或周报。

灵感:Addy Osmani《Loop Engineering》—— "loop 跑顺了之后没人盯账单" 是安静的失败。
本脚本让账单成为每日健康报告的一部分,可观察、可预算、可告警。

用法:
  python3 scripts/token_report.py                # 默认日报(过去 24h)
  python3 scripts/token_report.py --days 7       # 周报
  python3 scripts/token_report.py --budget 5000000  # 设月预算,超 80% 告警

定价(可按公告更新——价格变动只改本字典,其余不变)。单位:每 1M tokens 的 USD。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys
from pathlib import Path

PRICING_PER_M = {
    # 仅做粗估,真实账单以 Anthropic console 为准。模型名 → (in $, out $)
    "claude-opus-4-6":           (15.0, 75.0),
    "claude-sonnet-4-6":         (3.0,  15.0),
    "claude-haiku-4-5-20251001": (0.8,   4.0),
}


def cost(model: str, in_tok: int, out_tok: int) -> float:
    pi, po = PRICING_PER_M.get(model, (3.0, 15.0))   # 未知模型按 Sonnet 估
    return (in_tok * pi + out_tok * po) / 1_000_000


def load(path: Path, since: dt.datetime) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            if dt.datetime.fromisoformat(rec["ts"]) >= since:
                out.append(rec)
        except Exception:
            continue
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--budget", type=float, default=float(os.getenv("MONTHLY_TOKEN_BUDGET", "0")),
                   help="月预算(总 tokens, in+out 合计);0 表示不检查")
    p.add_argument("--format", choices=["text", "markdown", "json"], default="markdown")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    state_dir = Path(__file__).resolve().parent.parent / "state"
    path = state_dir / "token-usage.jsonl"
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    records = load(path, since)

    if not records:
        msg = "无记录(可能 token-usage.jsonl 不存在,或窗口内无调用)。"
        print(msg if args.format != "json" else json.dumps({"records": 0, "note": msg}))
        return 0

    by_loop = collections.Counter()
    by_role = collections.Counter()
    by_model = collections.Counter()
    cost_by_loop: dict[str, float] = collections.defaultdict(float)
    total_in = total_out = 0
    total_cost = 0.0

    for r in records:
        i, o = r.get("input_tokens", 0), r.get("output_tokens", 0)
        c = cost(r.get("model", ""), i, o)
        total_in += i; total_out += o; total_cost += c
        by_loop[r.get("loop", "?")] += i + o
        by_role[r.get("role", "?")] += i + o
        by_model[r.get("model", "?")] += i + o
        cost_by_loop[r.get("loop", "?")] += c

    payload = {
        "window_days": args.days,
        "calls": len(records),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "total_tokens": total_in + total_out,
        "estimated_cost_usd": round(total_cost, 3),
        "by_loop": dict(by_loop.most_common()),
        "by_role": dict(by_role.most_common()),
        "by_model": dict(by_model.most_common()),
        "cost_by_loop_usd": {k: round(v, 3) for k, v in cost_by_loop.items()},
    }

    if args.budget > 0:
        # 月预算外推:本窗口 tokens × (30 / window_days)
        projected_monthly = (total_in + total_out) * (30 / max(args.days, 1))
        payload["projected_monthly_tokens"] = int(projected_monthly)
        payload["budget"] = args.budget
        payload["budget_usage_pct"] = round(projected_monthly / args.budget * 100, 1)
        if projected_monthly / args.budget >= 0.8:
            payload["alert"] = f"⚠ 预计月用量已达预算 {payload['budget_usage_pct']}%"

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # markdown / text
    lines = [
        f"## 🪙 Token 花费报告 · 近 {args.days} 天",
        "",
        f"- 调用次数:**{len(records)}**",
        f"- input / output:{total_in:,} / {total_out:,} tokens",
        f"- 预估费用:**${round(total_cost,2)} USD**",
    ]
    if "budget" in payload:
        lines += [
            f"- 月预算外推:{payload['projected_monthly_tokens']:,} tokens "
            f"({payload['budget_usage_pct']}%)",
        ]
        if "alert" in payload:
            lines.append(f"- {payload['alert']}")
    lines += ["", "**按 loop**:"]
    for k, v in by_loop.most_common():
        lines.append(f"  - {k}: {v:,} tokens / ${round(cost_by_loop[k],2)}")
    lines += ["", "**按 role**:"]
    for k, v in by_role.most_common():
        lines.append(f"  - {k}: {v:,} tokens")
    lines += ["", "**按 model**:"]
    for k, v in by_model.most_common():
        lines.append(f"  - {k}: {v:,} tokens")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
