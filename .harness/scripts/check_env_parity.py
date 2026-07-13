#!/usr/bin/env python3
"""环境一致性检查 — 六阶段流水线 CI 门禁的一部分。

校验两个 env 模板文件(如 dev / prod)拥有相同的 KEY 集合。
值可以不同(那本来就该不同),但 KEY 漂移是 prod 事故的常见根因:
某个 key 只在一个环境定义,部署到另一个环境就 NPE / KeyError。

用法:
    python scripts/check_env_parity.py config/.env.dev.example config/.env.prod.example

退出码 0 = 一致;非 0 = 有漂移(CI 变红)。
工具无关,纯标准库。
"""
from __future__ import annotations

import sys
from pathlib import Path


def load_keys(path: str) -> set[str]:
    keys: set[str] = set()
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: check_env_parity.py <env_a> <env_b>", file=sys.stderr)
        return 2

    a_path, b_path = argv[1], argv[2]
    a, b = load_keys(a_path), load_keys(b_path)

    only_a = sorted(a - b)
    only_b = sorted(b - a)

    if not only_a and not only_b:
        print(f"✅ env parity OK — {len(a)} keys match across both files.")
        return 0

    print("::error::Environment key drift detected.")
    if only_a:
        print(f"  Only in {a_path}: {', '.join(only_a)}")
    if only_b:
        print(f"  Only in {b_path}: {', '.join(only_b)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
