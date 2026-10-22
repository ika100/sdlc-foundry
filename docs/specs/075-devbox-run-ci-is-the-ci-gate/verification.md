# Verification — 075 devbox run ci is the CI gate, locally

**Result:** pass
**Base:** 6197700 · **Trace:** 3/3 criteria named by tests · `pytest tests/cplat`: 612 passed, 4 skipped (`scripts/ci-local.sh` green)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-075.1 | met | `tests/cplat/test_ci_gates.py::test_devbox_ci_runs_the_workflow_gates_in_job_order`, `::test_shape_check_requires_the_new_recipes` | `ci` recipes and `shapes.py CORE_RECIPES` (landed as #108) | aliases count as the same gate (gitops-app `quality` = `validate`) |
| AC-075.2 | met | `tests/cplat/test_ship_checks.py::test_ship_pr_runs_devbox_ci_first_and_never_pushes_red` | `ship.py run_ci()` in `open_pr()` |  |
| AC-075.3 | met | `tests/cplat/test_ci_gates.py::test_build_and_ship_run_devbox_ci_before_pushing` | `/svc:build` Phase 3 (#108), `/svc:ship` Phase pr |  |

## Non-goals

Image builds stay in Phase 5. ✔

## Deviations from the plan

None; specs 072–076 were implemented in one change with the plans written alongside (all tasks done). Parts landed first in #107/#108 from another session; this change adds the spec, tests and the rest.
