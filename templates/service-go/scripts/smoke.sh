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

raw="$(mktemp)"
summary="$(mktemp)"
trap 'rm -f "$raw" "$summary"' EXIT

go test -count=1 -json -run '^TestSmoke' ./... >"$raw"
rc=$?
go run scripts/smoke-summary.go <"$raw" >"$summary"
src=$?

# The runner itself failed (go missing, summary program broken) without a failing test: no reliable result lines.
if [ "$src" -ne 0 ] || { [ "$rc" -ne 0 ] && ! grep -q '^FAIL  ' "$summary"; }; then
  tail -n 40 "$raw" >&2
  echo "FAIL  (smoke recipe)"
  exit 1
fi
cat "$summary"
exit "$rc"
