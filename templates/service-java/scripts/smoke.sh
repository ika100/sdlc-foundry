#!/usr/bin/env bash
# devbox run smoke: run the smoke-tagged tests against a running deployment (platform-owned, spec 091).
# Prints `PASS|FAIL|SKIP  <path>::<name>` per test, then `smoke: <p> passed, <f> failed, <s> skipped`
# (or `0 smoke tests`). Exit 2 without SMOKE_BASE_URL, 1 when a test or the runner fails.
set -uo pipefail

base="${SMOKE_BASE_URL:-}"
if [ -z "$base" ]; then
  echo "ERROR: SMOKE_BASE_URL is not set: devbox run smoke runs the smoke tests against a running deployment, e.g. SMOKE_BASE_URL=https://<host> devbox run smoke" >&2
  exit 2
fi
while [ "${base%/}" != "$base" ]; do base="${base%/}"; done
export SMOKE_BASE_URL="$base"

reports=target/surefire-reports
rm -rf "$reports"   # reports of an earlier `mvn verify` are not smoke results
mvn -B -q test -Dgroups=smoke -Dsurefire.failIfNoSpecifiedTests=false -Djacoco.skip=true
rc=$?
summary="$(java scripts/SmokeSummary.java "$reports" 2>&1)"
srv=$?

# The runner itself failed (compile error, no JVM ...) without a failing test: no reliable result lines.
if [ "$srv" -ne 0 ] || { [ "$rc" -ne 0 ] && ! printf '%s\n' "$summary" | grep -q '^FAIL  '; }; then
  [ "$srv" -ne 0 ] && printf '%s\n' "$summary" >&2
  echo "FAIL  (smoke recipe)"
  exit 1
fi
printf '%s\n' "$summary"
exit "$rc"
