#!/usr/bin/env bash
# =============================================================================
# local_review.sh — push 前在本地跑四趟 AI 评审,不付远端 token
# -----------------------------------------------------------------------------
# 它做什么:
#   1. 算当前分支相对 BASE(默认 main)的 diff
#   2. 把 diff + 四份 review prompt(quality/security/dependency/performance)格式化成
#      Codex 一吃就能开干的消息
#   3. 你贴进 Codex(或任何 chat LLM),拿到四趟评审结果
#
# 它不需要:
#   - GitHub Secret(没远端 API key)
#   - GitHub Actions Workflow Permissions
#   - Anthropic / OpenAI 独立 API 账号
# 完全吃你已登录的 Codex / ChatGPT / chat agent 额度。
#
# 用法:
#   bash local_review.sh                          # 默认 vs main,四段输出
#   bash local_review.sh dev                      # 改 base 为 dev 分支
#   bash local_review.sh --combined               # 一段合并 prompt,一次跑完四趟
#   bash local_review.sh --pass security          # 只跑一趟
#   bash local_review.sh --copy                   # 把 prompt 自动复制到剪贴板(macOS pbcopy)
#
# 或网络一行(不必先 clone harness):
#   bash <(curl -sSL https://raw.githubusercontent.com/WILLcis/AI--First-Coding-Loop-Codex/main/core/scripts/local_review.sh)
# =============================================================================
set -uo pipefail

BASE="main"
PASS=""
COMBINED=0
COPY=0
PROMPTS_BASE="https://raw.githubusercontent.com/WILLcis/AI--First-Coding-Loop-Codex/main/core/prompts"

while [ $# -gt 0 ]; do
  case "$1" in
    --combined) COMBINED=1 ;;
    --copy)     COPY=1 ;;
    --pass)     PASS="$2"; shift ;;
    -h|--help)  sed -n '2,30p' "$0"; exit 0 ;;
    -*)         echo "未知选项 $1" >&2; exit 2 ;;
    *)          BASE="$1" ;;
  esac
  shift
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "不在 git 仓库内" >&2; exit 2; }

# 算 diff
git fetch --quiet origin "$BASE" 2>/dev/null || true
DIFF=$(git diff "origin/$BASE...HEAD" 2>/dev/null || git diff "$BASE...HEAD")
if [ -z "$DIFF" ]; then
  echo "当前分支相对 origin/$BASE 没有 diff,无需评审。"
  exit 0
fi

# 取本仓有没有本地 prompts/(install.sh 装过的),没有就从 raw.githubusercontent 拉
fetch_prompt() {
  local name="$1"
  local local_path="prompts/review-${name}.md"
  if [ -f "$local_path" ]; then
    cat "$local_path"
  else
    curl -sSL "${PROMPTS_BASE}/review-${name}.md"
  fi
}

emit_prompt() {
  local name="$1"
  local prompt_text; prompt_text=$(fetch_prompt "$name")
  cat <<EOF

============================================================
=== Pass: $name
============================================================

$prompt_text

---

DIFF(当前分支相对 origin/$BASE):
\`\`\`diff
$DIFF
\`\`\`

请按上面规则输出发现,末尾给一行 \`VERDICT: PASS\` 或 \`VERDICT: BLOCK\`。

EOF
}

emit_combined() {
  cat <<EOF
你是这个 monorepo 的高级评审员。下面会给你四份评审 prompt(quality / security / dependency / performance),
请**一次性**对同一份 diff 跑四趟,**每趟独立结论**,最后四段 \`VERDICT\`。

EOF
  for name in quality security dependency performance; do
    cat <<EOF
============================================================
=== Pass: $name
============================================================

$(fetch_prompt "$name")

EOF
  done
  cat <<EOF

============================================================
共享 DIFF(四趟都用这一份)
============================================================
\`\`\`diff
$DIFF
\`\`\`

请按上面四段规则各跑一趟,输出形如:
  Pass 1 quality findings: ...
  VERDICT: PASS/BLOCK

  Pass 2 security findings: ...
  VERDICT: PASS/BLOCK

  Pass 3 dependency findings: ...
  VERDICT: PASS/BLOCK

  Pass 4 performance findings: ...
  VERDICT: PASS/BLOCK
EOF
}

# 输出
OUT=$(if [ "$COMBINED" = "1" ]; then
        emit_combined
      elif [ -n "$PASS" ]; then
        emit_prompt "$PASS"
      else
        for name in quality security dependency performance; do emit_prompt "$name"; done
      fi)

if [ "$COPY" = "1" ] && command -v pbcopy >/dev/null; then
  printf '%s' "$OUT" | pbcopy
  echo "✓ Prompt 已复制到剪贴板($(echo "$OUT" | wc -c | tr -d ' ') 字符)。粘到 Codex 即可。"
else
  printf '%s\n' "$OUT"
fi
