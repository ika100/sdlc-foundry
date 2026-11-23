#!/usr/bin/env bash
# Platform-owned (spec 095): the recipes behind `devbox run audit`, `devbox run deps-findings` and `devbox run deps-bump`.
#   deps.sh audit                    fail on a HIGH or CRITICAL vulnerability in a locked NuGet package (trivy)
#   deps.sh findings <out-file>      write trivy's JSON report of the locked packages to <out-file>
#   deps.sh bump <package> <version> move <package> to <version>: its PackageVersion in Directory.Packages.props (a
#                                    transitive package gets one: central transitive pinning), then the lock files
# Only Directory.Packages.props and the packages.lock.json files ever change.
set -euo pipefail

[ "${1:-}" = "--" ] && shift
cmd="${1:-}"
[ $# -gt 0 ] && shift
[ "${1:-}" = "--" ] && shift

skip=(--skip-dirs .devbox --skip-dirs '**/bin' --skip-dirs '**/obj')

audit() {
  trivy fs --scanners vuln --severity HIGH,CRITICAL --exit-code 1 "${skip[@]}" .
}

findings() {
  local out="${1:-}"
  if [ -z "$out" ]; then
    echo "usage: devbox run deps-findings <out-file>" >&2
    exit 2
  fi
  rm -f "$out"
  trivy fs --scanners vuln --format json --output "$out" "${skip[@]}" . >&2
  [ -s "$out" ] || { echo "deps-findings: trivy wrote no report" >&2; exit 1; }
}

locked_versions() { # the versions the packages.lock.json files resolve for $1 (case-insensitive), one per line
  find . -name packages.lock.json -not -path '*/bin/*' -not -path '*/obj/*' -print0 | xargs -0 awk -v pkg="$1" '
    BEGIN { want = tolower("\"" pkg "\": {") }
    index(tolower($0), want) { hit = 1; next }
    hit && /"resolved"/ { v = $0; sub(/.*"resolved":[[:space:]]*"/, "", v); sub(/".*/, "", v); print v; hit = 0 }
    hit && /}/ { hit = 0 }'
}

below_exists() { # exit 0 when some locked copy of $1 is below $2
  local v
  while IFS= read -r v; do
    [ -n "$v" ] || continue
    [ "$v" = "$2" ] && continue
    [ "$(printf '%s\n%s\n' "$v" "$2" | sort -V | head -n 1)" = "$v" ] && return 0
  done < <(locked_versions "$1")
  return 1
}

bump() {
  if [ $# -ne 2 ]; then
    echo "usage: devbox run deps-bump <package> <version>" >&2
    exit 2
  fi
  local pkg="$1" ver="$2" props=Directory.Packages.props
  if [ -z "$(locked_versions "$pkg")" ]; then
    echo "deps-bump: $pkg is not a dependency of this repo" >&2
    exit 2
  fi
  if grep -qi "<PackageVersion Include=\"$pkg\"" "$props"; then
    awk -v pkg="$pkg" -v ver="$ver" '
      index(tolower($0), tolower("<PackageVersion Include=\"" pkg "\"")) { sub(/Version="[^"]*"/, "Version=\"" ver "\"") }
      { print }' "$props" > "$props.tmp" && mv "$props.tmp" "$props"
  else
    awk -v pkg="$pkg" -v ver="$ver" '
      !done && /<\/ItemGroup>/ { print "    <PackageVersion Include=\"" pkg "\" Version=\"" ver "\" />"; done = 1 }
      { print }' "$props" > "$props.tmp" && mv "$props.tmp" "$props"
  fi
  dotnet restore --force-evaluate >&2 || { echo "deps-bump: dotnet restore failed for $pkg" >&2; exit 1; }
  if below_exists "$pkg" "$ver"; then
    echo "deps-bump: the lock files still resolve $pkg below $ver" >&2
    exit 1
  fi
}

case "$cmd" in
  audit) audit ;;
  findings) findings "$@" ;;
  bump) bump "$@" ;;
  *) echo "usage: deps.sh audit | findings <out-file> | bump <package> <version>" >&2; exit 2 ;;
esac
