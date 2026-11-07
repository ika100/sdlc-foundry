# Verification — 148 Transient errors and slow progress never stop a run

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-148.1 | `tests/cplat/test_148_transient_errors.py::test_a_call_that_never_reached_github_runs_again_ac_148_1`, `tests/cplat/test_148_transient_errors.py::test_a_call_safe_to_repeat_runs_again_after_a_reset_or_5xx_ac_148_1`, `tests/cplat/test_148_transient_errors.py::test_a_write_that_may_have_reached_github_fails_at_once_ac_148_1` |
| AC-148.2 | `tests/cplat/test_148_transient_errors.py::test_create_and_push_are_two_steps_ac_148_2`, `tests/cplat/test_148_transient_errors.py::test_a_create_whose_answer_was_lost_goes_on_with_the_push_ac_148_2`, `tests/cplat/test_148_transient_errors.py::test_a_failed_create_of_a_repo_that_does_not_exist_fails_ac_148_2` |
| AC-148.3 | `tests/cplat/test_148_transient_errors.py::test_resume_publishes_a_local_repo_that_never_reached_github_ac_148_3`, `tests/cplat/test_148_transient_errors.py::test_resume_skips_a_repo_that_is_on_github_with_a_commit_ac_148_3`, `tests/cplat/test_148_transient_errors.py::test_publish_only_keeps_the_bootstrap_commit_and_needs_one_ac_148_3` |
| AC-148.4 | `tests/cplat/test_148_transient_errors.py::test_an_owner_that_is_an_organisation_sets_the_org_ac_148_4`, `tests/cplat/test_148_transient_errors.py::test_an_owner_that_is_a_team_name_keeps_the_login_and_org_wins_ac_148_4` |
| AC-148.5 | `tests/cplat/test_148_transient_errors.py::test_a_root_app_with_a_comparison_error_gets_one_hard_refresh_ac_148_5`, `tests/cplat/test_148_transient_errors.py::test_an_app_behind_the_revision_is_refreshed_once_after_45_seconds_ac_148_5`, `tests/cplat/test_148_transient_errors.py::test_a_wait_that_is_ready_at_once_refreshes_nothing_ac_148_5` |
| AC-148.6 | `tests/cplat/test_148_transient_errors.py::test_land_stops_when_the_pr_cannot_be_marked_ready_ac_148_6` |
| AC-148.7 | `tests/cplat/test_148_transient_errors.py::test_progress_extends_the_wait_beyond_its_timeout_ac_148_7`, `tests/cplat/test_148_transient_errors.py::test_a_timeout_says_no_repo_made_progress_ac_148_7`, `tests/cplat/test_148_transient_errors.py::test_progress_cannot_extend_one_wait_forever_ac_148_7` |
| AC-148.8 | `tests/cplat/test_148_transient_errors.py::test_the_release_gate_names_the_recipes_tool_and_runs_the_image_scan_ac_148_8` |

In practice: journey 6 (2026-11-07) had network drops in steps 1, 3, 5, 11 and 12; every `gh` and git call that hit one ran again by itself and no step stopped (journey 5: three stops). `cplat system wait` asked Argo CD for one refresh in step 2.
