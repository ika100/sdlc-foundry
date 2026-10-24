#!/usr/bin/env bash
# Platform-owned (spec 095): the recipes behind `devbox run deps-findings` and `devbox run deps-bump`.
#   deps.sh findings <out-file>      write govulncheck's JSON stream to <out-file>
#   deps.sh bump <module> <version>  move <module> to <version> (go get, go mod tidy)
# Only go.mod and go.sum ever change.
set -euo pipefail

[ "${1:-}" = "--" ] && shift
cmd="${1:-}"
[ $# -gt 0 ] && shift
[ "${1:-}" = "--" ] && shift

findings() {
  local out="${1:-}"
  if [ -z "$out" ]; then
    echo "usage: devbox run deps-findings <out-file>" >&2
    exit 2
  fi
  rm -f "$out"
  # in -json mode govulncheck exits 0 even with findings; a non-zero exit is a scanner failure
  govulncheck -json ./... > "$out" || { echo "deps-findings: govulncheck failed" >&2; exit 1; }
}

bump() {
  if [ $# -ne 2 ]; then
    echo "usage: devbox run deps-bump <package> <version>" >&2
    exit 2
  fi
  local mod="$1" ver="$2" have
  if [ ! -f go.sum ] || ! awk -v m="$mod" 'index($0, m " ") == 1 { f = 1 } END { exit !f }' go.sum; then
    echo "deps-bump: $mod is not a dependency of this repo" >&2
    exit 2
  fi
  go get "$mod@$ver" >&2 || { echo "deps-bump: go get failed for $mod" >&2; exit 1; }
  go mod tidy >&2 || { echo "deps-bump: go mod tidy failed" >&2; exit 1; }
  have="$(go list -m -f '{{.Version}}' "$mod")"
  if [ "$(printf '%s\n%s\n' "$ver" "$have" | sort -V | head -n 1)" != "$ver" ]; then
    # tidy dropped the pin of a module whose packages the build does not import: keep it as one `// indirect` require
    go get "$mod@$ver" >&2 || { echo "deps-bump: go get failed for $mod" >&2; exit 1; }
    have="$(go list -m -f '{{.Version}}' "$mod")"
  fi
  if [ "$(printf '%s\n%s\n' "$ver" "$have" | sort -V | head -n 1)" != "$ver" ]; then
    echo "deps-bump: $mod resolves to $have, below $ver" >&2
    exit 1
  fi
}

case "$cmd" in
  findings) findings "$@" ;;
  bump) bump "$@" ;;
  *) echo "usage: deps.sh findings <out-file> | bump <package> <version>" >&2; exit 2 ;;
esac
