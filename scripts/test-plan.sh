#!/usr/bin/env bash
# Tests for templates/gitops-app/scripts/plan.py (ADR-011): validation, topo order, lifecycle.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/scripts" "$tmp/docs/plan"
cp "$here/templates/gitops-app/scripts/plan.py" "$tmp/scripts/"
plan() { (cd "$tmp" && bash "$here/scripts/uv-script.sh" scripts/plan.py "$@"); }
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

cp "$here/tests/fixtures/plans/billing.md" "$tmp/docs/plan/"
plan validate >/dev/null 2>&1 && ok "valid plan passes" || bad "valid plan passes"

cp "$here/tests/fixtures/plans/bad-cycle.md" "$tmp/docs/plan/"
if plan validate >/dev/null 2>&1; then bad "invalid plan rejected"; else ok "invalid plan rejected"; fi
out=$(plan validate bad-cycle 2>&1 || true)
echo "$out" | grep -q "unknown repo\|cycle" && ok "reports dependency problem" || bad "reports dependency problem: $out"
rm "$tmp/docs/plan/bad-cycle.md"

out=$(plan show billing)
echo "$out" | grep -q "Level 1" && echo "$out" | grep -A2 "Level 1" | grep -q shop-models && ok "topo level 1 is the library" || bad "topo order: $out"
echo "$out" | grep -A2 "Level 3" | grep -q shop-web && ok "topo level 3 is the web app" || bad "topo level 3"

plan list | grep -q "billing.*draft" && ok "list shows draft" || bad "list shows draft"
plan start billing >/dev/null; plan list | grep -q "in_progress" && ok "start -> in_progress" || bad "start"
plan done billing shop-models | grep -q "1/3" && ok "done tracks progress" || bad "done progress"
plan done billing shop-api >/dev/null; plan done billing shop-web | grep -q "completed" && ok "all done -> completed" || bad "completed"
plan list | grep -q "(no active plans)" && ok "completed hidden by default" || bad "completed hidden"
plan list --all | grep -q "billing.*completed" && ok "--all shows completed" || bad "--all"
plan validate >/dev/null 2>&1 && ok "plan still valid after edits" || bad "valid after edits"

cp "$here/tests/fixtures/plans/billing.md" "$tmp/docs/plan/billing2.md"; sed -i.bak 's/plan_id: billing/plan_id: billing2/' "$tmp/docs/plan/billing2.md"; rm -f "$tmp/docs/plan/billing2.md.bak"
plan abandon billing2 | grep -q abandoned && ok "abandon" || bad "abandon"
exit $fail
