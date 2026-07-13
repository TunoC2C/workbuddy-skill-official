#!/usr/bin/env bash
# =============================================================================
# codex_review.sh -- Four-pass PR review through Codex CLI.
#
# Auth:
#   Preferred for Pro/personal automation: OPENAI_API_KEY.
#   Preferred for Business/Enterprise workspace automation: CODEX_ACCESS_TOKEN.
#   The script logs the runner in with Codex CLI, then runs `codex exec review`
#   against the PR diff.
#
# Dry run:
#   bash scripts/codex_review.sh --pass quality --dry-run
# =============================================================================
set -euo pipefail

PASS_NAME=""
BASE_REF="${BASE_REF:-main}"
PROMPTS_DIR="${AIFCL_PROMPTS_DIR:-prompts}"
OUTPUT_DIR="${AI_REVIEW_OUTPUT_DIR:-.}"
DRY_RUN=0

usage() {
  sed -n '2,20p' "$0"
  cat <<'EOF'
Options:
  --pass <quality|security|performance|dependency>  Review pass to run.
  --base <ref>                          Base branch/ref, default BASE_REF or main.
  --prompts-dir <dir>                   Prompt directory, default AIFCL_PROMPTS_DIR or prompts.
  --output-dir <dir>                    Where to write codex-review-<pass>.md.
  --dry-run                             Build prompt and dependency skip logic only.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --pass) PASS_NAME="$2"; shift ;;
    --base) BASE_REF="$2"; shift ;;
    --prompts-dir) PROMPTS_DIR="$2"; shift ;;
    --output-dir) OUTPUT_DIR="$2"; shift ;;
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

prompt_path="$PROMPTS_DIR/review-$PASS_NAME.md"
if [ ! -f "$prompt_path" ]; then
  echo "::error::Prompt not found: $prompt_path" >&2
  exit 2
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "::error::codex_review.sh must run inside a git worktree." >&2
  exit 2
fi

git fetch --quiet origin "$BASE_REF" >/dev/null 2>&1 || true
review_base="origin/$BASE_REF"
if ! git rev-parse --verify "$review_base" >/dev/null 2>&1; then
  review_base="$BASE_REF"
fi

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
    echo "No dependency manifest changes. VERDICT: PASS"
    exit 0
  fi
fi

mkdir -p "$OUTPUT_DIR"
prompt_file="$(mktemp)"
trap 'rm -f "$prompt_file"' EXIT

cat "$prompt_path" > "$prompt_file"
cat >> "$prompt_file" <<EOF

---

Codex review execution notes:
- Review only the diff against \`$review_base\`.
- Keep findings actionable and grounded in file/line references.
- End the final answer with exactly one verdict line: \`VERDICT: PASS\` or \`VERDICT: BLOCK\`.
EOF

if [ "$PASS_NAME" = "dependency" ]; then
  cat >> "$prompt_file" <<'EOF'
- This is the dependency/supply-chain pass. Ignore non-dependency issues unless they directly affect dependency risk.
EOF
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "DRY RUN pass=$PASS_NAME base=$review_base prompt=$prompt_path prompt_chars=$(wc -c < "$prompt_file" | tr -d ' ')"
  exit 0
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "::error::Codex CLI not found. Install it with: npm install -g @openai/codex" >&2
  exit 2
fi

export CODEX_HOME="${CODEX_HOME:-${RUNNER_TEMP:-$PWD/.codex-tmp}/aifcl-codex-home}"
mkdir -p "$CODEX_HOME"
if ! codex login status >/dev/null 2>&1; then
  if [ -n "${CODEX_ACCESS_TOKEN:-}" ]; then
    printf '%s' "$CODEX_ACCESS_TOKEN" | codex login --with-access-token >/dev/null
  elif [ -n "${OPENAI_API_KEY:-}" ]; then
    printf '%s' "$OPENAI_API_KEY" | codex login --with-api-key >/dev/null
  else
    echo "::error::Missing auth. Add CODEX_ACCESS_TOKEN or OPENAI_API_KEY as a GitHub Actions secret." >&2
    exit 2
  fi
fi

output_file="$OUTPUT_DIR/codex-review-$PASS_NAME.md"
cmd=(codex exec review --base "$review_base" --ephemeral --ignore-user-config -o "$output_file")
if [ -n "${CODEX_MODEL:-}" ]; then
  cmd+=(--model "$CODEX_MODEL")
fi
cmd+=(-)

set +e
"${cmd[@]}" < "$prompt_file"
codex_status=$?
set -e

if [ "$codex_status" -ne 0 ]; then
  echo "::error::Codex review command failed with exit code $codex_status" >&2
  exit "$codex_status"
fi

if [ ! -s "$output_file" ]; then
  echo "::error::Codex review produced no output: $output_file" >&2
  exit 2
fi

if grep -Eiq '^[[:space:]]*VERDICT:[[:space:]]*BLOCK\b' "$output_file"; then
  verdict="BLOCK"
elif grep -Eiq '^[[:space:]]*VERDICT:[[:space:]]*PASS\b' "$output_file"; then
  verdict="PASS"
else
  echo "::error::Codex review output is missing VERDICT: PASS|BLOCK." >&2
  sed -n '1,120p' "$output_file" >&2
  exit 2
fi

echo "--- $PASS_NAME verdict: $verdict ---"
sed -n '1,160p' "$output_file"

if [ -n "${PR_NUMBER:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
  comment_file="$(mktemp)"
  trap 'rm -f "$prompt_file" "$comment_file"' EXIT
  if [ "$verdict" = "PASS" ]; then
    printf '✅ **Codex Review · %s · PASS**\n\n' "$PASS_NAME" > "$comment_file"
  else
    printf '🛑 **Codex Review · %s · BLOCK**\n\n' "$PASS_NAME" > "$comment_file"
  fi
  cat "$output_file" >> "$comment_file"
  GH_TOKEN="$GITHUB_TOKEN" gh pr comment "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --body-file "$comment_file" >/dev/null 2>&1 || true
fi

[ "$verdict" = "PASS" ]
