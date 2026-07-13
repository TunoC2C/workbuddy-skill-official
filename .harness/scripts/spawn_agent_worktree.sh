#!/usr/bin/env bash
# =============================================================================
# spawn_agent_worktree — 给一个 agent 任务开独立的 git worktree
# -----------------------------------------------------------------------------
# 为什么需要它:
#   两个 agent 并行在同一个 working tree 上跑集成测试,docker 端口、数据库、
#   lock 文件、node_modules 都会撞。git 分支隔离 commit,但**不**隔离 fs。
#   git worktree 是同一个仓库的"独立工作目录",并发安全。
#
# 用法:
#   ./scripts/spawn_agent_worktree.sh <task-id> <command...>
#
# 示例:
#   ./scripts/spawn_agent_worktree.sh fix-billing-webhook \
#       python3 scripts/goal_loop.py --task-id fix-billing-webhook \
#         --task-file state/tasks/fix-billing-webhook.md \
#         --stop "make test-integration green"
#
# 设计:
#   - 在 .worktrees/<task-id> 下建分支 agent/<task-id>
#   - docker compose 项目名带 task-id 后缀,容器名/端口不会冲突
#   - 命令退出后 *默认* 自动清理 worktree(若有 uncommitted 改动则保留)
#   - 失败时保留 worktree 供调查;退出码透传
# =============================================================================
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <task-id> <command...>" >&2
  exit 2
fi

TASK_ID="$1"; shift
WORKTREE_DIR=".worktrees/$TASK_ID"
BRANCH="agent/$TASK_ID"
BASE_BRANCH="${BASE_BRANCH:-main}"

say() { printf '\033[1;36m[worktree:%s]\033[0m %s\n' "$TASK_ID" "$*"; }

cleanup() {
  local rc=$?
  if [ -d "$WORKTREE_DIR" ]; then
    # 有未提交改动 → 保留供调查
    if [ -n "$(cd "$WORKTREE_DIR" && git status --porcelain 2>/dev/null)" ]; then
      say "⚠ 有未提交改动,保留 $WORKTREE_DIR 供调查;手动清理:git worktree remove --force $WORKTREE_DIR"
    elif [ $rc -ne 0 ]; then
      say "⚠ 命令失败(rc=$rc),保留 worktree 供调查"
    else
      say "✓ 清理 worktree"
      git worktree remove "$WORKTREE_DIR" --force 2>/dev/null || true
      git branch -D "$BRANCH" 2>/dev/null || true
    fi
  fi
  exit $rc
}
trap cleanup EXIT

# 1. 建 worktree(若已存在则复用)
if [ -d "$WORKTREE_DIR" ]; then
  say "复用已存在的 worktree"
else
  say "创建 worktree $WORKTREE_DIR (分支 $BRANCH 基于 $BASE_BRANCH)"
  git fetch --quiet origin "$BASE_BRANCH" 2>/dev/null || true
  git worktree add -b "$BRANCH" "$WORKTREE_DIR" "$BASE_BRANCH"
fi

# 2. 隔离 docker compose 项目名 / 端口前缀,防并行撞车
# COMPOSE_PROJECT_NAME 决定容器/网络/卷名前缀;每个 task 一个独立 namespace。
export COMPOSE_PROJECT_NAME="agent_${TASK_ID//[^a-zA-Z0-9_]/_}"

# 3. 让 agent 在 worktree 里跑命令
say "运行: $*"
( cd "$WORKTREE_DIR" && env COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" "$@" )
