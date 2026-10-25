#!/usr/bin/env bash
# devbox run smoke: run the @smoke Playwright tests against a running deployment (platform-owned, spec 091).
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

json="$(mktemp)"
summary="$(mktemp)"
trap 'rm -f "$json" "$summary"' EXIT

if ! pnpm exec playwright install chromium >&2; then
  echo "FAIL  (smoke recipe)"
  exit 1
fi
PLAYWRIGHT_JSON_OUTPUT_NAME="$json" pnpm exec playwright test --grep @smoke --pass-with-no-tests --reporter=list,json >&2
rc=$?
node scripts/smoke-summary.mjs "$json" >"$summary"
src=$?

# The runner itself failed (browser missing, config error) without a failing test: no reliable result lines.
if [ "$src" -ne 0 ] || { [ "$rc" -ne 0 ] && ! grep -q '^FAIL  ' "$summary"; }; then
  echo "FAIL  (smoke recipe)"
  exit 1
fi
cat "$summary"
exit "$rc"
