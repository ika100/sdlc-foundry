#!/usr/bin/env bash
# Runs an inline (PEP 723) script without one uv environment per checkout (spec 209, ADR-117). Always called through `bash scripts/uv-script.sh`.
#
#   uv-script.sh [--quiet] <script.py> [args...]
#
# `uv run <script>.py` keys its script environment by the script's path, so every worktree adds one. This runs
# `uv run --no-project --with-requirements <script>.py python <script>.py` instead: uv keys that environment by the
# dependency list, so all worktrees and clones share it. The script still runs from its own path and the cwd.
# A script without a `# /// script` block keeps `uv run <script>.py` (it has no environment either way).
# Same file in every template and in the platform's scripts/ (scripts/sync-template-copies.py keeps the copies equal); keep it free of Jinja syntax.
set -euo pipefail

quiet=""
if [ "${1:-}" = "--quiet" ]; then
  quiet="--quiet"
  shift
fi
[ $# -ge 1 ] || { echo "usage: uv-script.sh [--quiet] <script.py> [args...]" >&2; exit 2; }
script="$1"
shift

# `quiet` is empty or one word, so it is passed unquoted on purpose.
if [ -f "$script" ] && grep -qx '# /// script' "$script"; then
  # requires-python, read only from inside the block (`# requires-python = ">=3.9"`).
  python="$(awk '
    $0 == "# /// script" { inblock = 1; next }
    inblock && $0 == "# ///" { exit }
    inblock && $0 ~ /^# requires-python[ ]*=/ {
      v = $0; sub(/^[^=]*=[ ]*/, "", v); gsub(/^["'\'']|["'\'']$/, "", v); print v; exit
    }' "$script")"
  if [ -n "$python" ]; then
    exec uv run $quiet --no-project --python "$python" --with-requirements "$script" python "$script" "$@"
  fi
  exec uv run $quiet --no-project --with-requirements "$script" python "$script" "$@"
fi
exec uv run $quiet "$script" "$@"
