#!/usr/bin/env bash
# Platform-owned (spec 095): the recipes behind `devbox run deps-findings` and `devbox run deps-bump`.
#   deps.sh findings <out-file>      write pnpm audit's JSON report (production dependencies) to <out-file>
#   deps.sh bump <package> <version> move <package> to <version> in pnpm-lock.yaml
# Only package.json, pnpm-lock.yaml and pnpm-workspace.yaml ever change.
set -euo pipefail

[ "${1:-}" = "--" ] && shift
cmd="${1:-}"
[ $# -gt 0 ] && shift
[ "${1:-}" = "--" ] && shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

findings() {
  local out="${1:-}"
  if [ -z "$out" ]; then
    echo "usage: devbox run deps-findings <out-file>" >&2
    exit 2
  fi
  rm -f "$out"
  # pnpm audit exits non-zero when it finds vulnerabilities; the report on stdout is still valid JSON
  pnpm audit --prod --json > "$out" || true
  if ! node -e 'JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"))' "$out" 2>/dev/null; then
    echo "deps-findings: pnpm audit wrote no valid JSON report" >&2
    exit 1
  fi
}

locked_versions() { # the versions pnpm-lock.yaml has for $1, one per line
  [ -f pnpm-lock.yaml ] || return 0
  awk -v pkg="$1" '
    /^[^ #]/ { inpk = ($0 ~ /^packages:/) }
    inpk && /^  [^ ]/ {
      k = substr($0, 3)
      sub(/^[\047"]/, "", k)
      if (index(k, pkg "@") == 1) {
        v = substr(k, length(pkg) + 2)
        sub(/[(\047":].*$/, "", v)
        print v
      }
    }' pnpm-lock.yaml
}

is_direct() {
  node -e '
    const p = JSON.parse(require("fs").readFileSync("package.json", "utf8"));
    const n = process.argv[1];
    process.exit(n in (p.dependencies || {}) || n in (p.devDependencies || {}) ? 0 : 1);
  ' "$1"
}

below_exists() { # exit 0 when some locked copy of $1 is below $2
  locked_versions "$1" | node -e '
    const key = (v) => v.replace(/^v/, "").split(/[.+-]/).map((x) => (/^\d+$/.test(x) ? Number(x) : -1));
    const cmp = (a, b) => { for (let i = 0; i < Math.max(a.length, b.length); i++) { const d = (a[i] ?? 0) - (b[i] ?? 0); if (d) return d; } return 0; };
    const want = key(process.argv[1]);
    const have = require("fs").readFileSync(0, "utf8").split("\n").filter(Boolean);
    process.exit(have.some((v) => cmp(key(v), want) < 0) ? 0 : 1);
  ' "$2"
}

bump() {
  if [ $# -ne 2 ]; then
    echo "usage: devbox run deps-bump <package> <version>" >&2
    exit 2
  fi
  local pkg="$1" ver="$2"
  if [ -z "$(locked_versions "$pkg")" ]; then
    echo "deps-bump: $pkg is not a dependency of this repo" >&2
    exit 2
  fi
  if is_direct "$pkg"; then
    pnpm update "$pkg@$ver" >&2 || { echo "deps-bump: pnpm update failed for $pkg" >&2; exit 1; }
  fi
  if ! is_direct "$pkg" || below_exists "$pkg" "$ver"; then
    node "$here/deps-override.mjs" "$pkg" "$ver" || { echo "deps-bump: cannot write the override for $pkg" >&2; exit 1; }
    pnpm install --no-frozen-lockfile >&2 || { echo "deps-bump: pnpm install failed for $pkg" >&2; exit 1; }
  fi
  if below_exists "$pkg" "$ver"; then
    echo "deps-bump: pnpm-lock.yaml still resolves $pkg below $ver" >&2
    exit 1
  fi
}

case "$cmd" in
  findings) findings "$@" ;;
  bump) bump "$@" ;;
  *) echo "usage: deps.sh findings <out-file> | bump <package> <version>" >&2; exit 2 ;;
esac
