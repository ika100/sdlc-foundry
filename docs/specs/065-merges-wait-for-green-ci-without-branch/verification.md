# Verification — 065 Merges wait for green CI without branch protection

**Result:** pass
**Base:** decbfbc · **Trace:** 5/5 criteria named by tests · `pytest tests/cplat`: 563 passed, 3 skipped

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-065.1 | met | `tests/cplat/test_gitops.py::test_pin_prs_merge_after_green_ci_without_branch_protection` | `templates/gitops-app/.github/workflows/pin-dev.yml (jobs ci, merge); templates/gitops-app/.github/workflows/ci.yml (workflow_call, checkout ref, concurrency)` | workflow structure tested and actionlint-clean; the first live run is the gitops-app rollout |
| AC-065.2 | met | `tests/cplat/test_gitops.py::test_a_red_pin_stays_open_with_a_comment` | `pin-dev.yml merge step, CI_RESULT branch` |  |
| AC-065.3 | met | `tests/cplat/test_gitops.py::test_protected_repos_fall_back_to_auto_merge` | `pin-dev.yml merge step, fallback` |  |
| AC-065.4 | met | `tests/cplat/test_newsvc.py::test_free_plan_warning_says_merges_still_wait_for_ci, ::test_actions_permission_failure_names_the_command, ::test_settings_failure_warns_with_the_commands` | `scripts/cplat/newsvc.py (protection and pin settings)` |  |
| AC-065.5 | met | `tests/cplat/test_ship.py::test_land_waits_for_pending_checks_and_merges_when_all_pass, ::test_a_red_check_is_never_merged_and_its_log_is_returned, ::test_a_pr_without_any_check_is_never_merged` | `scripts/cplat/ship.py land()` |  |

## Non-goals

No rulesets or merge queue. ✔

## Deviations from the plan

None; the specs were implemented in one change with the plan written alongside (all tasks done).
