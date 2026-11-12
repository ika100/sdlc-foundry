# Verification — 179 Unattended runs ask less

**Result:** pass
**Commit:** bf302762 · **Base:** c5777d8b · **Trace:** 9/9 criteria named by tests (`tests/cplat/test_179_*.py`)

Scope: only spec 179's changes. The merged spec 181/182 work in the same range (journey measurement, log tailer,
`render.py`, `update.py`, templates, `test_181_*`, `*_182.py`) was not reviewed.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-179.1 | met | `test_179_plan.py::test_a_gitops_entry_with_instance_settings_and_before_merge_passes_ac_179_1`, `::test_replicas_and_resources_are_gitops_operations_ac_179_1`, `::test_an_invalid_instance_setting_operation_is_refused_with_its_message_ac_179_1`, `::test_the_order_of_a_gitops_entry_can_only_be_before_merge_ac_179_1`, `::test_entry_ops_maps_replicas_to_component_set_ac_179_1`, `::test_entry_ops_maps_resources_to_repeated_resources_options_in_mapping_order_ac_179_1`, `::test_the_slice_of_the_component_lists_the_replicas_and_resources_the_entry_sets_ac_179_1`, `::test_component_set_resources_merges_into_system_yaml_and_renders_ac_179_1`, `::test_the_planner_turns_a_stated_instance_setting_into_a_before_merge_gitops_task_ac_179_1`, `::test_ship_entry_lists_the_replicas_and_resources_operations_ac_179_1` | `templates/gitops-app/scripts/plan.py:152-163,289`, `scripts/cplat/appship.py:141-146`, `scripts/cplat/compose.py:22-35,233,339-346`, `scripts/cplat/spec.py:936-941`, `plugins/system/agents/planner.md:34-42`, `plugins/system/references/ship-entry.md:7` | Entry ops, `set --resources`, provided-by-system and the order check match the design. The planner's YAML example now parses, with all seven items indented alike (fixed in bf302762). |
| AC-179.2 | met | `test_179_plan.py::test_a_criterion_with_a_setting_and_no_gitops_task_is_refused_naming_id_and_key_ac_179_2`, `::test_every_key_of_the_criterion_is_named_in_order_of_appearance_ac_179_2`, `::test_a_plan_whose_setting_criteria_each_have_a_gitops_task_passes_ac_179_2`, `::test_withdrawn_and_commented_criteria_name_no_setting_ac_179_2`, `::test_a_word_that_only_contains_a_key_is_not_a_setting_ac_179_2`, `::test_a_criterion_that_names_host_needs_a_gitops_task_too_ac_179_2`, `::test_a_plan_in_progress_gets_the_error_ac_179_2` | `templates/gitops-app/scripts/plan.py:176-186,316` | Refuses the plan and prints the id and the keys. A passing plan is covered. Finished plans get a warning (design). |
| AC-179.3 | met | `test_179_allowlist.py::test_the_run_allowlist_names_git_rm_right_after_the_commit_ac_179_3`, `::test_a_plain_git_rm_is_allowed_and_matches_no_refused_rule_ac_179_3`, `::test_a_forced_git_rm_matches_a_refused_rule_ac_179_3`, `::test_the_forced_forms_are_on_the_refused_list_and_not_in_the_allowlist_ac_179_3`, `::test_git_removes_a_tracked_file_and_a_tracked_directory_and_refuses_an_untracked_one_ac_179_3`, `::test_removing_a_frozen_acceptance_test_is_still_flagged_by_the_test_diff_ac_179_3` | `scripts/cplat/preflight.py:44,63-64` | Every case the criterion names has an assertion: `-r`, untracked file, path outside the repo, forced forms and the test-diff flag. |
| AC-179.4 | met | `test_179_type_only.py::test_annotations_casts_and_imports_are_type_only_ac_179_4`, `::test_anything_else_is_not_type_only_and_names_the_first_failed_rule_ac_179_4`, `::test_the_check_names_a_type_only_change_in_its_line_and_exits_1_ac_179_4`, `::test_a_type_only_change_is_recorded_without_asking_and_listed_in_the_pr_ac_179_4`, `::test_tightening_does_not_accept_an_assertion_change_as_type_only_ac_179_4`, `::test_the_build_tightens_a_type_only_line_without_asking_the_person_ac_179_4` | `scripts/cplat/spec.py:630-662,742-743`, `plugins/component/references/build-tighten.md`, `plugins/component/commands/build.md` (coder prompt) | The rules of A4 are tested in Python, TS and Go. The check lists the file, `--tighten` records file, task and reason, and the PR block lists it. |
| AC-179.5 | met | `test_179_test_review.py::test_the_command_writes_an_empty_signed_commit_with_findings_and_unresolved_lines_ac_179_5`, `::test_a_review_without_findings_freezes_at_once_with_findings_zero_ac_179_5`, `::test_the_red_tests_unit_is_open_until_the_review_commit_exists_ac_179_5`, `::test_phase_1_reviews_the_tests_once_then_freezes_at_the_reviewed_commit_ac_179_5`, `::test_the_reviewer_has_a_test_review_mode_with_the_three_checks_ac_179_5` | `scripts/cplat/testreview.py:36-98`, `scripts/cplat/buildcmd.py:240`, `scripts/cplat/units.py:263`, `plugins/svc/agents/reviewer.md:35`, `plugins/component/commands/build.md` Phase 1 | All three kinds of contradiction are in the reviewer prompt. With no findings the tests freeze in one commit. |
| AC-179.6 | met | `test_179_test_review.py::test_the_tests_freeze_at_the_reviewed_commit_after_the_tester_round_ac_179_6`, `::test_the_tester_gets_the_findings_once_and_only_changes_the_tests_named_ac_179_6`, `::test_the_unresolved_findings_are_in_the_pr_block_ac_179_6`, `::test_verification_lists_the_unresolved_findings_ac_179_6`, `::test_a_second_call_writes_nothing_ac_179_5` | `scripts/cplat/testreview.py:41-53`, `scripts/cplat/runs_built.py:277-282`, `plugins/svc/agents/reviewer.md:28`, `plugins/component/commands/build.md` Phases 1 and 4 | `test-diff` compares against the reviewed commit. Open findings appear in the PR block and in `verification.md`. |
| AC-179.7 | met | `test_179_platform_notify.py::test_a_run_started_in_the_platform_repo_stores_the_shape_it_finds_ac_179_7`, `::test_the_escalation_item_carries_the_shape_only_when_known_ac_179_7`, `::test_without_a_file_the_platform_escalation_is_desktop_only_ac_179_7`, `::test_a_platform_escalation_reaches_the_desktop_and_no_issue_or_comment_is_made_ac_179_7`, `::test_an_escalation_of_another_shape_is_notified_as_today_ac_179_7` | `scripts/cplat/runs.py:309,324-331`, `scripts/cplat/runlist.py:352`, `scripts/cplat/needs.py:217`, `scripts/cplat/notify.py:180,501`, `scripts/cplat/notify_config.py:47,61-68` | The tests do not vary the cause, and they do not need to: the notifier never looks at it (`notify.py:501`). Only cause `platform` files an issue directly (`ship.py:425`). |
| AC-179.8 | met | `test_179_platform_notify.py::test_a_platform_cause_escalation_in_the_platform_repo_is_still_auto_filed_ac_179_8`, `::test_a_platform_escalation_with_the_users_github_setting_is_filed_ac_179_8`, `::test_the_user_file_wins_cell_by_cell_ac_179_8` | `scripts/cplat/notify_config.py:61-68` (`autoissue` unchanged) | The crash half rests on the unchanged `autoissue` path, which the AC-088.4 tests in `test_autoissue_ship.py:237-300` cover. Shape does not enter that path. |
| AC-179.9 | met | `test_179_smoke_findings.py::test_a_smoke_finding_is_recorded_on_the_testers_entry_ac_179_9`, `::test_the_pr_block_lists_the_smoke_file_and_the_finding_ac_179_9`, `::test_the_reviewer_reports_a_loose_smoke_test_as_a_smoke_line_not_a_failure_ac_179_9`, `::test_the_build_hands_a_smoke_finding_to_the_tester_in_the_fix_round_without_asking_ac_179_9` | `scripts/cplat/runs_agents.py:507-519`, `scripts/cplat/runs_built.py:275-276`, `plugins/svc/agents/reviewer.md:31,45`, `plugins/component/commands/build.md` Phase 4 step 3 | The build prompt has the tester tighten the test in the same round without asking, then run it. A frozen test still goes the TEST LOOSER way. |

## Non-goals

- `prod` replicas are refused by the plan check (`plan.py:156-158`), and only stated criteria become tasks. ✔
- Forced `git rm` is refused and not in the allowlist. There is no path wrapper and no history rewrite. ✔
- The review changes no tests ("write nothing", `reviewer.md:35`). One tester round and no second review. ✔
- The notify preset changes only `escalation` in `platform` repos (`notify_config.py:64`). The tests for other events and shapes are `::test_the_platform_preset_changes_no_other_event_ac_179_7` and `::test_any_other_shape_is_notified_as_today_ac_179_7`. ✔
- Type-only is decided by comparing lines only. ✔
- No template-owned layout changed. ✔

## Deviations from the plan

- Fixed in bf302762:
  - the two run-together prompt lines are split again: the coder's "Done when" and hard-rule bullets in `build.md`, and steps 1 and 2 in `build-tighten.md`;
  - the changelog fragment now names #616 for smoke findings and #642/#643 for platform escalations.
- Acceptable (the coordinator accepted it): shortening the prompts to keep their byte size dropped some practices. Five have register retirements with reasons in `docs/rules/plugins/component/commands/build.yml`: R4, R8, R14, R23, R35. Other phrases were dropped without a register entry:
  - "commit for it if it did not"
  - "skip it with `STORY-NNN` stories"
  - "skip a missing one"
  - "(git, gh and `cplat` run directly)"
  - "smoke-start it"
  - "Brief: the criterion in full and the file."

  `cplat platform rules check` passes.
- Acceptable: `plan.py:144` reworded the existing message to `needs a component (gitops operation '<kind>')`, so the design's "existing `needs a component`" text matches after the `repo <rid>:` prefix. Only `test_plan.py:180` pins it, by substring.
- Acceptable: plan t12 and t13 list `docs/rules/plugins/svc/agents/reviewer.yml` and `docs/rules/plugins/system/references/ship-entry.yml`, but neither changed. The rules check passes without new entries.
- Acceptable: the tests listed in plan tasks changed only as planned: `test_preflight_131.py` (t1), and `test_units_131.py` plus `units131_support.py` (t4). Every task is `done: true`.
- Acceptable: ADR renumbered 096 → 099 because spec 181 took 096. The links in the design, plan, changelog, `docs/unattended-delivery.md` and `docs/adr/README.md:99` all point to 099.

## Contract

Matches `design.md` sections 1–6. The `RED=` grep after the reviewed commit picks the reviewed commit itself, because it
also contains `acceptance tests for`. This is the freeze point the design intends.
