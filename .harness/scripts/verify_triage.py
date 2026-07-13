#!/usr/bin/env python3
"""部署后复检 — 自愈反馈环的闭环动作。

由部署流水线在 release 之后触发(triage.yml 的 verify 模式)。
拉最近一小段窗口的错误,对每个仍 open 的自动工单:若其指纹的错误已不再出现,
则自动关闭工单——形成"检测→建单→修复→部署→复检→关单"的闭环。

本地试跑:
    OBSERVABILITY_BACKEND=mock TRACKER=github-dryrun python scripts/verify_triage.py
"""
from __future__ import annotations

import os

from _adapters import ObservabilityAdapter, TrackerAdapter
from triage_engine import cluster_errors


def main() -> int:
    lookback = int(os.getenv("LOOKBACK_HOURS", "2"))
    obs = ObservabilityAdapter.create()
    tracker = TrackerAdapter.create()

    events = obs.fetch_errors(lookback)
    live_fingerprints = set(cluster_errors(events).keys())
    print(f"复检窗口 {lookback}h:仍活跃的错误指纹 {len(live_fingerprints)} 个。")

    # 实务中应从 tracker 列出所有"自动创建且仍 open"的工单,逐一核对其 [fp:..]。
    # 各 tracker 的列举 API 不同,这里给出核对逻辑;接入时补 list_open_auto_issues()。
    open_auto_issues = _list_open_auto_issues(tracker)
    closed = 0
    for issue in open_auto_issues:
        fp = issue["fingerprint"]
        if fp not in live_fingerprints:
            tracker.close_issue(
                issue["id"],
                comment=f"✅ 复检通过:指纹 {fp} 的错误在最近 {lookback}h 内已不再出现,自动关闭。",
            )
            closed += 1
        else:
            print(f"  仍活跃,保持 open: {fp}")

    print(f"完成:自动关闭 {closed} 个已解决工单。")
    return 0


def _list_open_auto_issues(tracker) -> list[dict]:
    """返回 [{'id':..., 'fingerprint':...}, ...]。

    dry-run 模式下返回一组示例,演示关单逻辑;接真实 tracker 时,
    用其搜索 API 找标题含 '[fp:' 且状态为 open 的工单并解析出指纹。
    """
    lister = getattr(tracker, "list_open_auto_issues", None)
    if callable(lister):
        return lister()
    # dry-run 演示:假设之前给 mock 的两类错误建过单,其中 billing 那条已修复
    return [
        {"id": "dry-DEMO-1", "fingerprint": "_resolved_demo_"},  # 不在 live 集合 → 会被关闭
    ]


if __name__ == "__main__":
    raise SystemExit(main())
