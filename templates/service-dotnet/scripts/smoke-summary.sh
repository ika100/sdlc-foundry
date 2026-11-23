#!/usr/bin/env bash
# Turns the TRX reports of `dotnet test` into the smoke result lines (platform-owned, spec 091).
# Usage: bash scripts/smoke-summary.sh <results-dir>
# One `PASS|FAIL|SKIP  <path>::<method>` line per test, where <path> is the tests/ file that declares the test's class,
# then `smoke: <p> passed, <f> failed, <s> skipped`, or `0 smoke tests`. Exit 2 without a report, 1 when a test failed.
set -uo pipefail

dir="${1:-}"
reports=()
if [ -n "$dir" ] && [ -d "$dir" ]; then
  while IFS= read -r f; do reports+=("$f"); done < <(find "$dir" -name '*.trx' | sort)
fi
if [ "${#reports[@]}" -eq 0 ]; then
  echo "smoke-summary: no TRX report" >&2
  exit 2
fi

# <test id> <outcome> <class> <name>, one per test (TRX: UnitTestResult carries the outcome, UnitTest/TestMethod the class).
rows="$(awk '
  function attr(line, key,    m) {
    if (match(line, " " key "=\"[^\"]*\"")) { m = substr(line, RSTART + length(key) + 3, RLENGTH - length(key) - 4); return m }
    return ""
  }
  /<UnitTestResult / { outcome[attr($0, "testId")] = attr($0, "outcome"); name[attr($0, "testId")] = attr($0, "testName") }
  /<UnitTest / { current = attr($0, "id") }
  /<TestMethod / { class[current] = attr($0, "className") }
  END { for (id in outcome) printf "%s\t%s\t%s\n", outcome[id], class[id], name[id] }
' "${reports[@]}" | sort -t "$(printf '\t')" -k2,2 -k3,3)"

if [ -z "$rows" ]; then
  echo "0 smoke tests"
  exit 0
fi

pass=0 fail=0 skip=0
while IFS="$(printf '\t')" read -r outcome class name; do
  method="${name#"$class".}"
  short="${class##*.}"
  file="$(grep -rlE "(class|record)[[:space:]]+$short\b" tests --include='*.cs' 2>/dev/null | sort | head -n 1)"
  case "$outcome" in
    Passed) verdict=PASS; pass=$((pass + 1)) ;;
    NotExecuted | Inconclusive | Pending) verdict=SKIP; skip=$((skip + 1)) ;;
    *) verdict=FAIL; fail=$((fail + 1)) ;;
  esac
  echo "$verdict  ${file:-$class}::$method"
done <<< "$rows"
echo "smoke: $pass passed, $fail failed, $skip skipped"
[ "$fail" -eq 0 ]
