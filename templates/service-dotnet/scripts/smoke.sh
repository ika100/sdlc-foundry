#!/usr/bin/env bash
# devbox run smoke: run the xUnit tests of category `smoke` against a running deployment (platform-owned, spec 091).
# Prints `PASS|FAIL|SKIP  <path>::<name>` per test, then `smoke: <p> passed, <f> failed, <s> skipped`
# (or `0 smoke tests`). Exit 2 without SMOKE_BASE_URL, 1 when a test or the runner fails.
# SMOKE_READ_ONLY=1 (set by the platform outside dev, SMOKE_ENV names the environment) leaves out the tests of
# category `writes`, so only dev gets smoke data (#474).
set -uo pipefail

base="${SMOKE_BASE_URL:-}"
if [ -z "$base" ]; then
  echo "ERROR: SMOKE_BASE_URL is not set: devbox run smoke runs the smoke tests against a running deployment, e.g. SMOKE_BASE_URL=https://<host> devbox run smoke" >&2
  exit 2
fi
while [ "${base%/}" != "$base" ]; do base="${base%/}"; done
export SMOKE_BASE_URL="$base"
filter="Category=smoke"
if [ "${SMOKE_READ_ONLY:-}" = "1" ]; then
  echo "read-only smoke${SMOKE_ENV:+ in $SMOKE_ENV}: tests of category writes are not run" >&2
  filter="Category=smoke&Category!=writes"
fi

results="$(mktemp -d)"
summary="$(mktemp)"
trap 'rm -rf "$results" "$summary"' EXIT

dotnet test --filter "$filter" --logger "trx;LogFileName=smoke.trx" --results-directory "$results" >&2
rc=$?
bash scripts/smoke-summary.sh "$results" >"$summary"
src=$?

# The runner itself failed (build error, no report) without a failing test: no reliable result lines.
if [ "$src" -eq 2 ] || { [ "$rc" -ne 0 ] && ! grep -q '^FAIL  ' "$summary"; }; then
  echo "FAIL  (smoke recipe)"
  exit 1
fi
cat "$summary"
exit "$rc"
