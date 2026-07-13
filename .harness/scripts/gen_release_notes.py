#!/usr/bin/env python3
"""AI 生成发布说明 — 六阶段流水线 release 阶段使用,也是"AI-native 外溢到其他职能"的一例。

从上一个 release tag 到 HEAD 的提交/合并的 PR 标题汇总,交给模型生成面向用户的发布说明。
输出到 stdout(deploy.yml 把它重定向到 RELEASE_NOTES.md 并推送到团队频道)。

本地试跑(无模型 key 时回退到原始 commit 列表):
    python scripts/gen_release_notes.py --since-last-tag
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from _adapters import ModelAdapter


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=False).stdout.strip()


def collect_commits(since_last_tag: bool) -> str:
    rng = "HEAD"
    if since_last_tag:
        last = sh("git", "describe", "--tags", "--abbrev=0", "HEAD^")
        if last:
            rng = f"{last}..HEAD"
    # 只取 subject;合并 PR 的 squash commit 通常已是可读标题
    log = sh("git", "log", rng, "--no-merges", "--pretty=format:- %s")
    return log or "(自上个发布以来无新提交)"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since-last-tag", action="store_true")
    args = p.parse_args(argv[1:])

    commits = collect_commits(args.since_last_tag)

    notes = ModelAdapter.summarize(
        "你是产品发布经理。基于以下本次发布包含的提交,写一份**面向用户**的中文发布说明:"
        "①一句话概述本次更新;②'新功能'/'改进'/'修复'分组(无内容的组省略);"
        "③用用户能懂的语言,不要出现内部代号或文件名。简洁、专业。\n\n"
        f"提交列表:\n{commits}"
    )

    if notes.startswith("[模型未配置"):
        # fail-safe:没有模型时直接给原始变更列表,也比没有强
        print("## 本次发布变更\n\n" + commits)
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
