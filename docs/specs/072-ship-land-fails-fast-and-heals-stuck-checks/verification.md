# Verification — 072 Ship land fails fast and heals stuck checks

**Result:** pass
**Base:** 6197700 · **Trace:** 5/5 criteria named by tests · `pytest tests/cplat`: 612 passed, 4 skipped (`scripts/ci-local.sh` green)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-072.1 | met | `tests/cplat/test_ship_checks.py::test_the_first_red_check_ends_the_wait` | `ship.py CheckWatch.poll(), wait_checks(), land()` |  |
| AC-072.2 | met | `tests/cplat/test_ship_checks.py::test_a_stale_check_is_rerun_once_then_an_error`, `::test_a_rerun_stale_check_that_recovers_merges` | `CheckWatch._heal()` (stale on two polls → `gh run rerun`) | a stale run must be seen on two polls; the checks API can lag one |
| AC-072.3 | met | `tests/cplat/test_ship_checks.py::test_a_stuck_queue_is_cancelled_and_rerun_once_then_escalated`, `::test_a_check_cancelled_for_the_rerun_is_not_red`, `::test_a_busy_runner_is_not_stuck` | `CheckWatch._heal()`, `cancel_and_rerun()`, `runner_labels()` | stuck = only queued jobs while nothing of the PR runs; a busy runner set is not healed |
| AC-072.4 | met | `tests/cplat/test_ship_checks.py::test_each_conclusion_is_printed_once_as_it_happens` | `CheckWatch.poll()` → `say()` |  |
| AC-072.5 | withdrawn | — | — | pin PRs carry no checks, so this could never fire (#113); replaced by AC-077.1 (the pin-dev run) |

## Non-goals

Required-check configuration and runner restarts stay out. ✔

## Deviations from the plan

None; specs 072–076 were implemented in one change with the plans written alongside (all tasks done).
