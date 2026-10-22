# Verification — 074 CI runs once per change

**Result:** pass
**Base:** 6197700 · **Trace:** 2/2 criteria named by tests · `pytest tests/cplat`: 612 passed, 4 skipped (`scripts/ci-local.sh` green)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-074.1 | met | `tests/cplat/test_ci_gates.py::test_ci_runs_once_per_change` | every template's `ci.yml` (landed as #107) |  |
| AC-074.2 | met | `tests/cplat/test_ci_gates.py::test_runner_guide_recommends_a_persistent_docker_volume` | `docs/self-hosted-runners.md` |  |

## Non-goals

No registry cache; ai-ops's runner set is handed to the ai-ops session. ✔

## Deviations from the plan

None; specs 072–076 were implemented in one change with the plans written alongside (all tasks done). Parts landed first in #107/#108 from another session; this change adds the spec, tests and the rest.
