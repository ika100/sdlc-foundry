#!/usr/bin/env bash
# Platform-owned (spec 095): the recipes behind `devbox run deps-findings` and `devbox run deps-bump`.
#   deps.sh findings <out-file>              write trivy's JSON report (HIGH, CRITICAL) to <out-file>
#   deps.sh bump <groupId>:<artifactId> <v>  pin the artifact to <v> in pom.xml
# Maven has no lock file: pom.xml is the resolved record, and the only file that ever changes.
# OWASP Dependency-Check names no fixed versions, so the findings always come from trivy (the audit recipe's own fallback).
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
  mvn -B -q dependency:resolve >&2 || { echo "deps-findings: mvn dependency:resolve failed" >&2; exit 1; }
  trivy fs --offline-scan --scanners vuln --severity HIGH,CRITICAL --format json --output "$out" --skip-dirs target --skip-dirs .devbox . >&2 \
    || { echo "deps-findings: trivy failed" >&2; exit 1; }
  [ -s "$out" ] || { echo "deps-findings: trivy wrote no report" >&2; exit 1; }
}

resolved() { # the version Maven resolves for $1:$2, empty when the artifact is not in the dependency tree
  local tree
  tree="$(mktemp)"
  rm -f "$tree"
  mvn -B -q dependency:tree "-Dincludes=$1:$2" "-DoutputFile=$tree" >&2 || { rm -f "$tree"; echo "deps-bump: mvn dependency:tree failed" >&2; return 1; }
  if [ -s "$tree" ]; then
    # lines look like `+- g:a:jar:1.2.3:compile` or `g:a:jar:classifier:1.2.3:compile`
    grep -F -- "$1:$2:" "$tree" | awk -F: '{ print (NF >= 6 ? $(NF - 1) : $4) }' | sort -V | head -n 1 || true
  fi
  rm -f "$tree"
}

bump() {
  if [ $# -ne 2 ]; then
    echo "usage: devbox run deps-bump <package> <version>" >&2
    exit 2
  fi
  local ga="$1" ver="$2" g a have
  if ! printf '%s' "$ga" | grep -q -E '^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$'; then
    echo "deps-bump: $ga is not a <groupId>:<artifactId>" >&2
    exit 2
  fi
  g="${ga%%:*}"
  a="${ga#*:}"
  have="$(resolved "$g" "$a")" || exit 1
  if [ -z "$have" ]; then
    echo "deps-bump: $ga is not a dependency of this repo" >&2
    exit 2
  fi
  java "$here/PomDeps.java" set "$ga" "$ver" >&2 || { echo "deps-bump: cannot edit pom.xml for $ga" >&2; exit 1; }
  have="$(resolved "$g" "$a")" || exit 1
  if [ -z "$have" ] || [ "$(printf '%s\n%s\n' "$ver" "$have" | sort -V | head -n 1)" != "$ver" ]; then
    echo "deps-bump: pom.xml still resolves $ga to ${have:-nothing}, below $ver" >&2
    exit 1
  fi
}

case "$cmd" in
  findings) findings "$@" ;;
  bump) bump "$@" ;;
  *) echo "usage: deps.sh findings <out-file> | bump <package> <version>" >&2; exit 2 ;;
esac
