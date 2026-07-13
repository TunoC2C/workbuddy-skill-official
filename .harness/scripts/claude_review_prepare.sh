#!/usr/bin/env bash
# =============================================================================
# claude_review_prepare.sh -- Build a Claude Code review prompt for one pass.
#
# This script is intentionally lightweight: it prepares a trusted prompt file for
# the GitHub Action and, for dependency-only reviews with no manifest changes,
# creates a PASS review without spending Claude turns.
# =============================================================================
set -euo pipefail

PASS_NAME=""
BASE_REF="${BASE_REF:-main}"
PROMPTS_DIR="${AIFCL_PROMPTS_DIR:-prompts}"
OUT_FILE=""
REVIEW_FILE=""
DRY_RUN=0

usage() {
  sed -n '2,18p' "$0"
  cat <<'EOF'
Options:
  --pass <quality|security|performance|dependency>  Review pass to run.
  --base <ref>                          Base branch/ref, default BASE_REF or main.
  --prompts-dir <dir>                   Prompt directory, default AIFCL_PROMPTS_DIR or prompts.
  --out <file>                          Prompt file to write.
  --review-file <file>                  Review file for skipped dependency pass.
  --dry-run                             Build prompt only; do not write GitHub outputs.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --pass) PASS_NAME="$2"; shift ;;
    --base) BASE_REF="$2"; shift ;;
    --prompts-dir) PROMPTS_DIR="$2"; shift ;;
    --out) OUT_FILE="$2"; shift ;;
    --review-file) REVIEW_FILE="$2"; shift ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$PASS_NAME" in
  quality|security|performance|dependency) ;;
  "") echo "::error::Missing --pass <quality|security|performance|dependency>" >&2; exit 2 ;;
  *) echo "::error::Invalid pass: $PASS_NAME" >&2; exit 2 ;;
esac

[ -n "$OUT_FILE" ] || OUT_FILE="${RUNNER_TEMP:-/tmp}/claude-review-$PASS_NAME-prompt.md"
[ -n "$REVIEW_FILE" ] || REVIEW_FILE="${RUNNER_TEMP:-/tmp}/claude-review-$PASS_NAME.md"

prompt_path="$PROMPTS_DIR/review-$PASS_NAME.md"
if [ ! -f "$prompt_path" ]; then
  echo "::error::Prompt not found: $prompt_path" >&2
  exit 2
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "::error::claude_review_prepare.sh must run inside a git worktree." >&2
  exit 2
fi

git fetch --quiet origin "$BASE_REF" >/dev/null 2>&1 || true
review_base="origin/$BASE_REF"
if ! git rev-parse --verify "$review_base" >/dev/null 2>&1; then
  review_base="$BASE_REF"
fi

skip_review=0
if [ "$PASS_NAME" = "dependency" ]; then
  dep_changed="$(
    git diff --name-only "$review_base...HEAD" -- \
      package.json package-lock.json pnpm-lock.yaml yarn.lock bun.lockb \
      go.mod go.sum requirements.txt requirements-dev.txt pyproject.toml poetry.lock \
      Cargo.toml Cargo.lock Gemfile Gemfile.lock composer.json composer.lock \
      ':(glob)**/package.json' ':(glob)**/package-lock.json' ':(glob)**/requirements*.txt' \
      ':(glob)**/pyproject.toml' ':(glob)**/poetry.lock' \
      ':(glob)**/go.mod' ':(glob)**/go.sum' ':(glob)**/Cargo.toml' ':(glob)**/Cargo.lock' \
      2>/dev/null || true
  )"
  if [ -z "$dep_changed" ]; then
    skip_review=1
  fi
fi

mkdir -p "$(dirname "$OUT_FILE")" "$(dirname "$REVIEW_FILE")"

if [ "$skip_review" = "1" ]; then
  cat > "$REVIEW_FILE" <<'EOF'
No dependency manifest changes.

VERDICT: PASS
EOF
else
  cat "$prompt_path" > "$OUT_FILE"
  cat >> "$OUT_FILE" <<EOF

---

Claude Code review execution notes:
- Review only the diff against \`$review_base\`.
- You may inspect repository context, but do not edit files, create commits, push, or open PRs.
- Keep findings actionable and grounded in file/line references.
- End the final answer with exactly one verdict line: \`VERDICT: PASS\` or \`VERDICT: BLOCK\`.
EOF

  if [ "$PASS_NAME" = "dependency" ]; then
    cat >> "$OUT_FILE" <<'EOF'
- This is the dependency/supply-chain pass. Ignore non-dependency issues unless they directly affect dependency risk.
EOF
  fi
fi

if [ "$DRY_RUN" = "1" ]; then
  if [ "$skip_review" = "1" ]; then
    echo "DRY RUN pass=$PASS_NAME base=$review_base skip=true review_file=$REVIEW_FILE"
  else
    echo "DRY RUN pass=$PASS_NAME base=$review_base skip=false prompt=$OUT_FILE prompt_chars=$(wc -c < "$OUT_FILE" | tr -d ' ')"
  fi
  exit 0
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    echo "skip=$skip_review"
    echo "prompt_file=$OUT_FILE"
    echo "review_file=$REVIEW_FILE"
  } >> "$GITHUB_OUTPUT"
fi

if [ "$skip_review" = "1" ]; then
  echo "No dependency manifest changes. Skipping Claude Code dependency pass."
else
  echo "Prepared Claude Code prompt: $OUT_FILE"
fi
