# Verification — 082 Sessions do not collide: claimed issues and specs required

**Result:** pass
**Base:** b1fb9a6 · **Trace:** 2/2 criteria named by tests · `scripts/ci-local.sh` green: 657 passed, 4 skipped (`pytest -n auto`)

| Criterion | Verdict | Tests |
|---|---|---|
| AC-082.1 | met | `tests/cplat/test_claims.py::test_claim_labels_assigns_and_names_the_branch`, `tests/cplat/test_claims.py::test_a_claim_for_another_branch_stops_the_second_session`, `tests/cplat/test_claims.py::test_ship_start_claims_and_escalate_releases` |
| AC-082.2 | met | `tests/cplat/test_claims.py::test_platform_prs_that_close_an_issue_carry_a_spec`, `tests/cplat/test_claims.py::test_the_rule_runs_in_ci` |

## Notes

Claims are best effort offline; tests never call GitHub (autouse stub in conftest).

## Deviations from the plan

None; specs 077–084 were implemented in one change with the plans written alongside (all tasks done).
