# Verification — 067 Ship an approved spec to dev unattended

**Result:** pass
**Base:** decbfbc · **Trace:** 5/5 criteria named by tests · `pytest tests/cplat`: 563 passed, 3 skipped

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-067.1 | met | `tests/cplat/test_ship.py::test_start_resumes_and_refuses_unapproved_specs, ::test_a_spec_without_a_valid_plan_starts_with_planning, ::test_done_spec_resumes_at_the_pr` | `scripts/cplat/ship.py start(), state_path()` |  |
| AC-067.2 | met | `tests/cplat/test_ship.py::test_pr_is_opened_from_the_feature_branch_with_a_conventional_title, ::test_land_waits_for_pending_checks_and_merges_when_all_pass` | `scripts/cplat/ship.py open_pr(), land()` |  |
| AC-067.3 | met | `tests/cplat/test_ship.py::test_a_red_check_is_never_merged_and_its_log_is_returned` | `scripts/cplat/ship.py land(), failure_logs(); plugins/svc/commands/ship.md (Phase land, 3 rounds)` | the 3-round cap is enforced by the command prompt, counted by cplat |
| AC-067.4 | met | `tests/cplat/test_ship.py::test_no_merge_stops_at_a_green_pr` | `scripts/cplat/ship.py land()` |  |
| AC-067.5 | met | `tests/cplat/test_ship.py::test_deploy_waits_for_the_pin_pr_of_the_merge_commit, ::test_a_closed_pin_pr_fails_the_deploy, ::test_unlinked_repos_finish_without_waiting` | `scripts/cplat/ship.py deploy(), argo_health()` | the Argo health wait is not covered by a test (needs a cluster) |

## Non-goals

No promotion and no multi-repo flow added. ✔

## Deviations from the plan

None; the specs were implemented in one change with the plan written alongside (all tasks done).
