#!/usr/bin/env python3
"""Triage 引擎 — 自愈反馈环的第 2 拍。

流程:
  1. 从可观测后端 + Sentry 拉最近 N 小时的错误
  2. 按指纹聚类
  3. 对每个簇做"九维严重度打分"
  4. 去重后建/更新工单(closed 复现则重开),含样本日志/受影响用户/端点/建议路径
  5. 用模型为每个簇生成"建议调查路径"

设计原则:每个工具只做一个阶段。本脚本不做修复、不做部署——只负责"发现并下单"。

本地试跑(零凭证、零副作用):
    OBSERVABILITY_BACKEND=mock TRACKER=github-dryrun python scripts/triage_engine.py
"""
from __future__ import annotations

import os

from _adapters import (
    Cluster,
    ModelAdapter,
    ObservabilityAdapter,
    TrackerAdapter,
    append_triage_history,
    fetch_sentry_issues,
    load_known_fingerprints,
    load_known_flakes,
)

# 九个严重度维度及其权重(总和=1.0)。这是把"模糊的严重度"变成"可排序的分数"的核心。
# 团队可按自身业务调权重——但要显式、版本化,而不是凭感觉。
DIMENSIONS: dict[str, float] = {
    "frequency": 0.18,        # 发生次数
    "user_impact": 0.18,      # 受影响用户数
    "endpoint_criticality": 0.12,  # 端点是否核心(支付/登录…)
    "level": 0.10,            # error vs fatal
    "is_regression": 0.12,    # 是否是已修复又复发
    "breadth": 0.08,          # 跨多少端点/服务
    "trend": 0.08,            # 是否在上升
    "revenue_path": 0.08,     # 是否触及收入路径
    "data_integrity": 0.06,   # 是否可能损坏数据
}

CRITICAL_ENDPOINT_HINTS = ("pay", "billing", "checkout", "auth", "login", "webhook")
REVENUE_HINTS = ("pay", "billing", "checkout", "subscription", "invoice")
DATA_HINTS = ("delete", "migrate", "write", "update", "corrupt", "integrity")

# 分数 >= 此阈值才建单,避免噪音淹没信号
FILE_THRESHOLD = float(os.getenv("TRIAGE_THRESHOLD", "0.35"))


def cluster_errors(events) -> dict[str, Cluster]:
    clusters: dict[str, Cluster] = {}
    for e in events:
        fp = e.fingerprint()
        c = clusters.get(fp)
        if c is None:
            c = Cluster(fingerprint=fp, service=e.service, sample_message=e.message, count=0)
            clusters[fp] = c
        c.count += 1
        if e.user_id:
            c.affected_users.add(e.user_id)
        if e.endpoint:
            c.affected_endpoints.add(e.endpoint)
        if len(c.samples) < 5:
            c.samples.append(e)
        if e.level == "fatal":
            c.sample_message = e.message
    return clusters


def _norm(x: float, cap: float) -> float:
    return min(x / cap, 1.0)


def score_cluster(c: Cluster, known_fingerprints: set[str]) -> None:
    msg = c.sample_message.lower()
    eps = " ".join(c.affected_endpoints).lower()
    fatal = any(s.level == "fatal" for s in c.samples)

    d = {
        "frequency": _norm(c.count, cap=50),
        "user_impact": _norm(len(c.affected_users), cap=25),
        "endpoint_criticality": 1.0 if any(h in eps for h in CRITICAL_ENDPOINT_HINTS) else 0.2,
        "level": 1.0 if fatal else 0.5,
        "is_regression": 1.0 if c.fingerprint in known_fingerprints else 0.0,
        "breadth": _norm(len(c.affected_endpoints), cap=5),
        "trend": 0.5,  # 占位:接入时用与昨日对比的环比变化填充
        "revenue_path": 1.0 if any(h in eps or h in msg for h in REVENUE_HINTS) else 0.0,
        "data_integrity": 1.0 if any(h in msg for h in DATA_HINTS) else 0.0,
    }
    c.dimensions = d
    c.score = round(sum(d[k] * w for k, w in DIMENSIONS.items()), 3)


def build_ticket_body(c: Cluster, suggestion: str) -> str:
    users = ", ".join(sorted(c.affected_users)[:10]) or "(未捕获 user_id)"
    eps = ", ".join(sorted(c.affected_endpoints)) or "(未知)"
    dims = "\n".join(f"  - {k}: {c.dimensions.get(k, 0):.2f} (权重 {w})"
                     for k, w in DIMENSIONS.items())
    samples = "\n".join(f"  [{s.level}] {s.timestamp or ''} {s.message}" for s in c.samples)
    return f"""**自动生成的 triage 工单**(指纹 `{c.fingerprint}`)

**服务**: {c.service}
**严重度分数**: {c.score}  (阈值 {FILE_THRESHOLD})
**发生次数(近窗)**: {c.count}
**受影响用户**: {users}
**受影响端点**: {eps}

**九维打分**:
{dims}

**样本日志**:
{samples}

**建议调查路径**:
{suggestion}

---
*由 triage 引擎自动创建。修复后由 verify 子流程复检并自动关闭。请勿手改标题里的 [fp:..] 标记(用于去重)。*
"""


def main() -> int:
    lookback = int(os.getenv("LOOKBACK_HOURS", "24"))
    obs = ObservabilityAdapter.create()
    tracker = TrackerAdapter.create()

    events = obs.fetch_errors(lookback) + fetch_sentry_issues(lookback)
    print(f"拉取到 {len(events)} 条错误事件(近 {lookback}h)。")

    clusters = cluster_errors(events)
    print(f"聚类得到 {len(clusters)} 个错误簇。")

    # v2: 用 state/triage-history.jsonl 做回归识别(过去 30 天 closed 过的指纹)
    history = load_known_fingerprints(within_days=30)
    flakes = load_known_flakes()
    known_regression = {fp for fp, action in history.items() if action == "closed"}
    print(f"历史指纹 {len(history)} 条;其中 closed(可能回归) {len(known_regression)};已知 flake {len(flakes)}")

    filed = 0
    for c in sorted(clusters.values(), key=lambda x: x.count, reverse=True):
        score_cluster(c, known_fingerprints=known_regression)

        # 已知 flake 自动降权(× 0.4),避免反复来回建单
        if c.fingerprint in flakes:
            c.score = round(c.score * 0.4, 3)
            print(f"  flake 降权 {c.fingerprint} → {c.score}")

        if c.score < FILE_THRESHOLD:
            print(f"  跳过低分簇 {c.fingerprint} score={c.score}")
            continue

        # 用专门的 pr-investigator skill / triage-scorer 角色调用模型给出调查建议
        suggestion = ModelAdapter.summarize(
            "你是值班 SRE,遵循 skills/pr-investigator/SKILL.md 的步骤。\n"
            "根据以下错误簇,用 4~6 条给出根因假设(每条带证据 + 30 分钟可执行的下一步)。\n"
            "如果这是回归(closed 过的指纹再出现),优先怀疑最近的反向 PR。\n\n"
            f"服务: {c.service}\n样本: {c.sample_message}\n"
            f"端点: {sorted(c.affected_endpoints)}\n次数: {c.count}\n"
            f"是否回归: {'是' if c.fingerprint in known_regression else '否'}",
            model=os.getenv("TRIAGE_MODEL", "claude-sonnet-4-6"),
            loop="triage", role="pr-investigator",
        )
        body = build_ticket_body(c, suggestion)
        title = f"[{c.service}] {c.sample_message[:80]}"

        existing = tracker.find_open_by_fingerprint(c.fingerprint)
        if existing:
            tracker.update_issue(existing["id"], body)
            state_type = (existing.get("state") or {}).get("type", "")
            if state_type in ("completed", "canceled"):
                tracker.reopen_issue(existing["id"])
                append_triage_history(fingerprint=c.fingerprint, action="reopened",
                                      score=c.score, service=c.service)
            else:
                append_triage_history(fingerprint=c.fingerprint, action="updated",
                                      score=c.score, service=c.service)
            print(f"  更新已有工单 {existing['id']}  score={c.score}")
        else:
            tid = tracker.create_issue(title, body, c.fingerprint, c.score)
            append_triage_history(fingerprint=c.fingerprint, action="created",
                                  score=c.score, service=c.service,
                                  extra={"ticket": tid})
            print(f"  新建工单 {tid}  score={c.score}")
        filed += 1

    print(f"完成:处理/下单 {filed} 个簇。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
