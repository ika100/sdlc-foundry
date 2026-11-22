#!/usr/bin/env bash
# Platform-owned (spec 095): the recipes behind `devbox run audit`, `devbox run deps-findings` and `devbox run deps-bump`.
#   deps.sh audit                    pip-audit what uv.lock pins (#936: not the environment it runs in)
#   deps.sh findings <out-file>      write pip-audit's JSON report on uv.lock to <out-file>
#   deps.sh bump <package> <version> move <package> to <version> in uv.lock (and pyproject.toml when needed)
# Only pyproject.toml and uv.lock ever change.
set -euo pipefail

[ "${1:-}" = "--" ] && shift
cmd="${1:-}"
[ $# -gt 0 ] && shift
[ "${1:-}" = "--" ] && shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
helper="$here/deps_pyproject.py"

# pip-audit on an export of uv.lock, so the result depends on the repo, not on the Python that runs it (#936)
locked_audit() {
  local req rc=0
  req="$(mktemp)"
  if ! uv export --frozen --no-hashes --no-emit-project --all-extras > "$req"; then
    rm -f "$req"
    echo "audit: uv export of uv.lock failed" >&2
    return 1
  fi
  uv run pip-audit -r "$req" --no-deps --disable-pip "$@" || rc=$?
  rm -f "$req"
  return "$rc"
}

findings() {
  local out="${1:-}"
  if [ -z "$out" ]; then
    echo "usage: devbox run deps-findings <out-file>" >&2
    exit 2
  fi
  rm -f "$out"
  # pip-audit exits 1 when it finds vulnerabilities; the report is still written
  locked_audit -f json -o "$out" >&2 || true
  if [ ! -s "$out" ] || ! python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$out" 2>/dev/null; then
    echo "deps-findings: pip-audit wrote no valid JSON report" >&2
    exit 1
  fi
}

lock_ok() { # every locked copy of $1 is $2 or higher
  python3 "$helper" satisfied "$1" "$2"
}

bump() {
  if [ $# -ne 2 ]; then
    echo "usage: devbox run deps-bump <package> <version>" >&2
    exit 2
  fi
  local pkg="$1" ver="$2" norm
  norm="$(python3 "$helper" normalize "$pkg")"
  if [ -z "$(python3 "$helper" locked "$norm")" ]; then
    echo "deps-bump: $pkg is not a dependency of this repo" >&2
    exit 2
  fi
  # the first lock may fail when a declared specifier excludes the version: the direct path below handles that
  uv lock --upgrade-package "$norm==$ver" >&2 || true
  if ! lock_ok "$norm" "$ver"; then
    if flags="$(python3 "$helper" section "$norm")"; then
      # direct dependency: raise the lower bound where it is declared
      # shellcheck disable=SC2086
      uv add --no-sync $flags "$norm>=$ver" >&2 || { echo "deps-bump: uv add failed for $pkg" >&2; exit 1; }
    else
      # transitive dependency: one constraint in [tool.uv] constraint-dependencies
      python3 "$helper" constrain "$norm" "$ver" || { echo "deps-bump: cannot constrain $pkg" >&2; exit 1; }
      uv lock >&2 || { echo "deps-bump: uv lock failed for $pkg" >&2; exit 1; }
    fi
  fi
  if ! lock_ok "$norm" "$ver"; then
    echo "deps-bump: uv.lock still resolves $pkg below $ver" >&2
    exit 1
  fi
}

case "$cmd" in
  audit) locked_audit "$@" ;;
  findings) findings "$@" ;;
  bump) bump "$@" ;;
  *) echo "usage: deps.sh audit | findings <out-file> | bump <package> <version>" >&2; exit 2 ;;
esac
