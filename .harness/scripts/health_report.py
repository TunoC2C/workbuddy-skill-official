#!/usr/bin/env python3
"""每日健康报告 — 自愈反馈环的第 1 拍。

查可观测后端最近 N 小时的错误,做服务级统计,再用模型生成"执行级健康摘要",
推送到团队频道(Teams/Slack/飞书 webhook)。没人需要去要它。

本地试跑:
    OBSERVABILITY_BACKEND=mock python scripts/health_report.py
"""
from __future__ import annotations

import collections
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

from _adapters import ModelAdapter, ObservabilityAdapter, notify


def main() -> int:
    lookback = int(os.getenv("LOOKBACK_HOURS", "24"))
    obs = ObservabilityAdapter.create()
    events = obs.fetch_errors(lookback)

    by_service = collections.Counter(e.service for e in events)
    by_level = collections.Counter(e.level for e in events)
    top_msgs = collections.Counter(
        (e.service, e.message[:80]) for e in events
    ).most_common(8)

    stats_lines = [f"- {svc}: {n} 条" for svc, n in by_service.most_common()]
    top_lines = [f"- [{svc}] {msg} ×{cnt}" for (svc, msg), cnt in
                 collections.Counter((e.service, e.message[:80]) for e in events).most_common(8)]

    raw_summary = (
        f"近 {lookback}h 错误总数: {len(events)}\n"
        f"按级别: {dict(by_level)}\n"
        f"按服务:\n" + "\n".join(stats_lines) + "\n"
        f"Top 错误:\n" + "\n".join(top_lines)
    )

    ai_summary = ModelAdapter.summarize(
        "你是一名 SRE 负责人,给创始团队写每日系统健康摘要。基于以下统计,"
        "用中文写 5~8 行:①整体健康一句话定性(绿/黄/红);②最值得关注的 1~3 个问题及"
        "可能影响;③与常态相比是否异常;④建议今天优先看什么。务必简洁、面向决策,"
        "不要罗列原始数字。\n\n" + raw_summary,
        loop="daily-health", role="health-summarizer",
    )

    # v2: 接 token & comprehension 报告。这两个脚本独立可跑,在这里组装到一份。
    sections = [ai_summary]

    token_section = _run_helper(["scripts/token_report.py", "--days", "1"])
    if token_section:
        sections.append(token_section)

    # 仅周一发 comprehension(其他天数据不变,刷屏没意义)
    is_monday = dt.datetime.now(dt.timezone.utc).weekday() == 0
    if is_monday:
        comp_section = _run_helper(["scripts/comprehension_metrics.py", "--days", "7"])
        if comp_section:
            sections.append(comp_section)

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = (
        f"🩺 **每日健康报告** — {now}\n\n"
        + "\n\n".join(sections)
        + f"\n\n<details>原始统计\n\n```\n{raw_summary}\n```\n</details>\n"
        f"_一小时后 triage 引擎将自动为高严重度问题建单。_"
    )

    notify(report)
    print("健康报告已发送。")
    return 0


def _run_helper(args: list[str]) -> str | None:
    """跑同目录下另一个脚本,失败时优雅地返回 None(不让整个报告挂掉)。"""
    repo_root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            [sys.executable, *args],
            cwd=str(repo_root),
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if result.returncode != 0:
            return f"_({args[0]} 失败,跳过)_"
    except Exception as e:
        return f"_({args[0]} 异常: {e})_"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
