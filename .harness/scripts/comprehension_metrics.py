#!/usr/bin/env python3
"""comprehension_metrics — 反认知投降的结构性护栏。

灵感:Addy Osmani《Loop Engineering》尾段"cognitive surrender"——
loop 跑顺了之后,你最容易停止阅读。这个指标让"停止阅读"变得**可观察、可告警**。

三个指标(都来自客观数据,不是自评):
  1. comprehension-coverage = 本周架构师写了 summary 的 PR 数 / 本周合并 PR 总数
     - 数据源:state/comprehension-log.jsonl + GitHub API
  2. agent-proposal-modification-rate = 架构师对 agent 提议给出 review comment / 修改的比例
     - 数据源:GitHub Pull Request Reviews API
  3. pr-read-rate = 架构师在 PR 上"实际有动作"(comment/review/added commit)的比例
     - 数据源:GitHub PR events API

输出:推到 daily-health 周一报告里。任意一项触红线,健康报告头部贴一段大字警告。

用法:
  GITHUB_TOKEN=ghp_xxx GITHUB_REPO=org/repo ARCHITECT_LOGIN=yourname \\
    python3 scripts/comprehension_metrics.py --days 7 --format markdown

零凭证 mock:
  python3 scripts/comprehension_metrics.py --mock
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "state"

# 红线阈值——任意触发,daily-health 头部大字警告
THRESHOLDS = {
    "comprehension_coverage_min": 0.05,    # 至少 5% PR 架构师写了 summary
    "agent_modification_rate_min": 0.10,   # 至少 10% agent 提议被架构师改动
    "pr_read_rate_min": 0.30,              # 至少 30% PR 架构师有动作
}


def load_log() -> list[dict]:
    path = STATE / "comprehension-log.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def fetch_github(days: int, repo: str, architect: str, token: str) -> dict:
    """从 GitHub 拉本窗口内合并的 PR + 架构师在它们上的活动。"""
    import requests
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    # 1. 本窗口内合并到 main 的 PR
    prs_resp = requests.get(
        f"https://api.github.com/repos/{repo}/pulls",
        headers=headers,
        params={"state": "closed", "base": "main", "per_page": 100, "sort": "updated",
                "direction": "desc"},
        timeout=20,
    )
    prs_resp.raise_for_status()
    merged = [p for p in prs_resp.json()
              if p.get("merged_at") and p["merged_at"] >= since]

    if not merged:
        return {"merged_prs": 0, "architect_acted_on": 0, "architect_modified": 0}

    acted_on = modified = 0
    for pr in merged:
        # PR 上架构师的评论 / review
        reviews = requests.get(pr["url"] + "/reviews", headers=headers, timeout=20).json()
        comments = requests.get(pr["url"] + "/comments", headers=headers, timeout=20).json()
        architect_review = any(r.get("user", {}).get("login") == architect for r in reviews)
        architect_comment = any(c.get("user", {}).get("login") == architect for c in comments)
        if architect_review or architect_comment:
            acted_on += 1
        # 修改:要求 changes / 提交了进一步 commit
        if any(r.get("state") == "CHANGES_REQUESTED" and r.get("user", {}).get("login") == architect
               for r in reviews):
            modified += 1

    return {"merged_prs": len(merged), "architect_acted_on": acted_on,
            "architect_modified": modified}


def mock_github() -> dict:
    """Demo 数据,展示告警形态。"""
    return {"merged_prs": 47, "architect_acted_on": 6, "architect_modified": 2}


def compute(days: int, gh: dict) -> dict:
    log = load_log()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    comprehended = sum(1 for r in log
                       if "ts" in r and dt.datetime.fromisoformat(r["ts"]) >= cutoff)

    merged = gh.get("merged_prs", 0)
    acted = gh.get("architect_acted_on", 0)
    modified = gh.get("architect_modified", 0)

    if merged == 0:
        return {"window_days": days, "merged_prs": 0,
                "note": "窗口内无合并 PR,跳过指标计算。"}

    metrics = {
        "window_days": days,
        "merged_prs": merged,
        "comprehended_prs": comprehended,
        "comprehension_coverage": round(comprehended / merged, 3),
        "architect_acted_on": acted,
        "pr_read_rate": round(acted / merged, 3),
        "architect_modified": modified,
        "agent_modification_rate": round(modified / max(acted, 1), 3),
    }
    alerts = []
    if metrics["comprehension_coverage"] < THRESHOLDS["comprehension_coverage_min"]:
        alerts.append(f"⚠ comprehension-coverage = {metrics['comprehension_coverage']:.0%} "
                      f"(红线 {THRESHOLDS['comprehension_coverage_min']:.0%}):你停止阅读了。"
                      "去 skills/weekly-comprehension-check 做这周的自检。")
    if metrics["pr_read_rate"] < THRESHOLDS["pr_read_rate_min"]:
        alerts.append(f"⚠ pr-read-rate = {metrics['pr_read_rate']:.0%} "
                      f"(红线 {THRESHOLDS['pr_read_rate_min']:.0%}):合并量远超你的参与量,"
                      "考虑收紧灰度或暂停一天降速。")
    if metrics["agent_modification_rate"] < THRESHOLDS["agent_modification_rate_min"]:
        alerts.append(f"⚠ agent-modification-rate = {metrics['agent_modification_rate']:.0%} "
                      f"(红线 {THRESHOLDS['agent_modification_rate_min']:.0%}):你在认知投降——"
                      "对 agent 提议从不修改 = 你只是按了 approve。")
    metrics["alerts"] = alerts
    return metrics


def render_markdown(m: dict) -> str:
    if m.get("note"):
        return f"## 🧠 Comprehension Metrics · 近 {m['window_days']} 天\n\n{m['note']}\n"
    lines = [
        f"## 🧠 Comprehension Metrics · 近 {m['window_days']} 天",
        "",
        f"- 合并 PR:{m['merged_prs']}",
        f"- 架构师写了 summary 的 PR:{m['comprehended_prs']} "
        f"(coverage **{m['comprehension_coverage']:.0%}**)",
        f"- 架构师在 PR 上有动作(comment/review):{m['architect_acted_on']} "
        f"(rate **{m['pr_read_rate']:.0%}**)",
        f"- 架构师要求修改的 PR:{m['architect_modified']} "
        f"(modification rate **{m['agent_modification_rate']:.0%}**)",
    ]
    if m["alerts"]:
        lines += ["", "### 🔴 红线告警"] + [f"- {a}" for a in m["alerts"]]
    else:
        lines += ["", "✅ 三项指标均在健康区间。"]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--mock", action="store_true")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.mock or not os.getenv("GITHUB_TOKEN"):
        gh = mock_github()
    else:
        repo = os.environ["GITHUB_REPO"]
        architect = os.environ["ARCHITECT_LOGIN"]
        gh = fetch_github(args.days, repo, architect, os.environ["GITHUB_TOKEN"])
    m = compute(args.days, gh)
    if args.format == "json":
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
