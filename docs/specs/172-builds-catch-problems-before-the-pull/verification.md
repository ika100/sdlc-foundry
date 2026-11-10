# Verification — 172 Builds catch problems before the pull request

**Result:** pass
**Commit:** f6a2b05 · **Base:** b4ff411 · **Trace:** 8/8 criteria named by tests

Cycle 2. Since cycle 1 (ae38989) only three test files changed (commit f6a2b05, +52 lines, no code). The four
`TEST LOOSER` items of cycle 1 (AC-172.3, .5, .6, .7) now assert their criteria as written, and the code they cover
is unchanged. `devbox run test-fast`: 9186 passed, 12 skipped; `devbox run ci` OK.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-172.1 | met | `tests/cplat/test_172_test_diff.py::test_a_new_test_file_and_a_new_test_in_an_untouched_file_are_not_reported_ac_172_1`, `::test_the_cli_reports_nothing_for_them_with_and_without_task_ac_172_1`, `::test_a_change_to_a_red_tests_file_is_still_reported_ac_172_1`, `::test_the_deletion_of_a_red_tests_file_is_still_reported_ac_172_1`, `::test_a_file_committed_inside_the_red_tests_unit_is_frozen_too_ac_172_1` | `scripts/cplat/testdiff_select.py:33` (`frozen_files`), `:13` (`red_commits`); `scripts/cplat/spec.py:662` | Unchanged since cycle 1. Covers a new file, a new test in an untouched file, with and without `--task`, a change and a deletion of a frozen file, and the red-tests unit up to the frozen commit. |
| AC-172.2 | met | `test_172_test_diff.py::test_without_a_red_tests_commit_the_old_selection_and_one_note_apply_ac_172_2`, `::test_the_cli_prints_the_fallback_line_before_the_files_ac_172_2`, `::test_a_red_tests_commit_before_the_given_base_means_fallback_ac_172_2` | `scripts/cplat/spec.py:668` (note), `:1585` (base as typed) | Unchanged since cycle 1. Exactly one `fallback:` line, then the old selection. |
| AC-172.3 | met | `tests/cplat/test_172_quiet.py::test_arguments_after_dashes_reach_devbox_test_fast_unchanged_ac_172_3`, `::test_a_failure_with_arguments_prints_the_summary_with_the_arguments_ac_172_3`, `::test_a_flaky_failure_with_arguments_is_rerun_alone_as_before_ac_172_3`, `::test_other_forms_are_refused_with_the_usage_line_and_exit_2_ac_172_3`, `::test_the_platform_test_fast_runs_only_the_given_tests_ac_172_3`, `::test_every_template_test_fast_recipe_ends_in_the_arguments_ac_172_3`, **new** `::test_a_python_template_test_fast_runs_only_the_given_file_or_k_expression_ac_172_3` (`:193`) | `scripts/cplat/quiet.py:69` (`_parse`), `:110`; `scripts/test-fast.sh`; `templates/service-python/devbox.json:18`, `templates/library-python/devbox.json:17` | The new test takes each Python template's real `test-fast` recipe, runs the runner part after `--` with pytest on a two-file tree, and asserts: no arguments → all 3 tests; `tests/test_two.py` → only `test_gamma`; `-k "alpha or gamma"` → only those two. A test path before `"$@"` would now fail it. The seam swaps `uv run` for the current interpreter and drops the `smoke_pytest` plugin; the selection arguments are the template's own. |
| AC-172.4 | met | `tests/cplat/test_172_build_tests.py::test_a_task_gets_its_criteria_tests_and_its_own_test_files_ac_172_4`, `::test_the_json_form_…`, `::test_a_task_without_test_files_falls_back_…`, `::test_a_go_task_…`, `::test_a_java_task_…`, `::test_an_unknown_task_or_a_task_with_load_is_an_error_ac_172_4`, `::test_the_coder_runs_its_own_tests_not_the_whole_suite_ac_172_4`, `::test_the_whole_suite_still_runs_once_in_2_5_and_ci_in_phase_3_ac_172_4` | `scripts/cplat/buildtests.py:110-113`; `scripts/cplat/buildcmd.py:237`; `plugins/component/commands/build.md:55-56` | Unchanged since cycle 1. |
| AC-172.5 | met | `test_172_quiet.py::test_repeat_without_tests_or_with_n_outside_2_to_5_is_refused_ac_172_5`, `::test_n_runs_start_at_the_same_time_and_all_pass_ac_172_5`, `::test_the_limits_of_n_are_accepted_ac_172_5`, `::test_a_test_that_fails_under_load_and_passes_alone_is_flaky_exit_3_ac_172_5`, `::test_the_count_is_the_number_of_runs_the_test_failed_in_ac_172_5`, `::test_a_test_that_fails_alone_too_exits_1_and_never_0_ac_172_5`, `::test_one_flaky_and_one_failing_test_exit_1_and_name_the_flaky_one_ac_172_5`, `::test_a_failure_that_names_no_test_exits_1_without_reruns_ac_172_5` (tightened, `:285`) | `scripts/cplat/quiet_repeat.py:29` (Popen ×n), `:44-52` (summary, then not-attributable line), `:69` (flaky line), `:87` (exit 3) | The tightened test now also asserts that the failure summary is printed: the title `FAILED (exit 1): devbox run test-fast -- tests/test_x.py` and the log's `RuntimeError: no tests ran`. That matches `quiet_repeat.py:44` and `:51`. |
| AC-172.6 | met | `test_172_build_tests.py::test_the_load_run_names_the_acceptance_files_and_the_files_the_build_changed_ac_172_6`, `::test_the_load_run_json_form_ac_172_6`, `::test_the_load_run_is_skipped_…`, `::test_a_java_build_never_runs_under_load_ac_172_6`, `::test_the_load_run_is_step_2_6_between_2_5_and_phase_3_ac_172_6`, **new** `::test_step_2_6_sends_failing_tests_to_a_coder_and_repeats_after_the_tester_fix_ac_172_6` (`:188`), `::test_the_load_run_reference_tells_the_tester_to_fix_the_harness_only_ac_172_6` | `scripts/cplat/buildtests.py:81-100`; `plugins/component/commands/build.md:85` (2.6), `:79` (2.5 coder route); `plugins/component/references/build-load-run.md:3-7` | The new test asserts the exit-1 route (`Exit 1 → failing tests to a coder as in 2.5`, and 2.5 sends them to `a coder of a task covering that criterion`), the exit-3 route to the reference, and in the reference the order tester fix → `test-diff $RED` (person's approval) → `Run the repeated run again; after 2 rounds` escalate. The texts match `build.md:79`, `:85` and `build-load-run.md:5-7`. |
| AC-172.7 | met | `tests/cplat/test_172_signoff_merge.py::test_a_branch_with_an_unsigned_commit_is_refused_and_nothing_changes_ac_172_7`, `::test_the_hint_names_the_worktree_that_has_the_branch_ac_172_7`, `::test_after_the_rebase_the_merge_goes_through_ac_172_7`, **new** `::test_the_build_prompt_rebases_with_signoff_and_merges_again_without_asking_ac_172_7` (`:82`), `::test_a_merge_commit_without_sign_off_is_named_too_ac_172_7`, `::test_a_signed_branch_merges_in_the_platform_repo_ac_172_7`, `::test_other_repos_merge_unsigned_branches_as_before_ac_172_7` | `scripts/cplat/buildcmd.py:135-146`; `scripts/cplat/signoff.py:14`; `plugins/component/commands/build.md:64` | The new prompt test reads the 2.4 step-1 line about commits without `Signed-off-by` and asserts `Exit 1`, `git -C <worktree> rebase --signoff <sha>` and, right after it, `merge again without asking`. That covers the criterion's second sentence; the `cplat` half was already fully proven in cycle 1. |
| AC-172.8 | met | `tests/cplat/test_172_hidden_rules.py::test_an_instruction_with_a_condition_classed_not_a_rule_fails_ac_172_8`, `::test_a_statement_of_fact_with_a_condition_passes_as_not_a_rule_ac_172_8`, `::test_the_cli_fails_with_the_finding_in_text_and_json_ac_172_8`, `::test_what_reads_as_an_instruction_ac_172_8`, `::test_the_verb_list_is_the_one_of_the_design_ac_172_8` | `scripts/cplat/promptrules.py:275` (`instruction`), `IMPERATIVES`; `scripts/cplat/rulescheck.py:165-168` | Unchanged since cycle 1. The repo-wide rules check passes in `devbox run ci`. |

## Non-goals

- Freezing (spec 169) and tightening (spec 165) are unchanged: `frozen_base` is used as before (`spec.py:1586`). ✔
- `--repeat` refuses to run without named tests, so the whole suite never repeats (`quiet.py:69-90`). `ci`, `test` and e2e do not repeat. ✔
- No agent may change a frozen acceptance test without the person: `build-load-run.md:6` routes test-diff exit 1 through `build-test-approval.md`. ✔
- `build merge` adds no sign-off to task commits; it refuses them (`buildcmd.py:135-146`). ✔
- The sign-off check runs only for `repo_shape == "platform"` (`test_other_repos_merge_unsigned_branches_as_before_ac_172_7`). ✔
- The gitops shapes have no `TEST_FAST` entry and get `none: … runs no test runner`. ✔
- A flagged `not a rule` entry has no override. ✔
- No spec-171 file is touched. ✔
- No template-owned layout (header, footer, navigation) and no template file changed; the new template test only reads `devbox.json`. ✔

## Deviations from the plan

Unchanged since cycle 1; the tightening commit touches only the three acceptance test files.

- `docs/adr/094-a-build-runs-each-coder-on-its-own-tests-and-new-tests-under-load.md` is in no task's `files`. Acceptable: `design.md` names ADR-094 as the durable decision, and t9 adds its index row.
- `tests/cplat/conftest.py` (f5d0c35, after the red commit) is in no task's `files`. It adds an autouse fixture that removes `CPLAT_*` variables. Acceptable: harness only, no acceptance assertion, not frozen.
- `devbox.json` `test-fast` differs from design 3 (`if [ $# -eq 0 ]; then <literal suite line>; else bash scripts/test-fast.sh "$@"; fi`). Acceptable: spec 127 pins the literal suite line, and the user approved the matching test change.
- t7 rewords planner R3 instead of splitting it into two entries (`planner.md:30`). Acceptable: the rules check and the test-154 wording both pass.
- `docs/rules/plugins/component/commands/build.yml` is in t6's `files` but did not change. Acceptable: no new rule sentence in `build.md` needed an entry, and the rules check passes.
- Every task is `done: true`.

## Contract

Matches `design.md` sections 1–7, apart from the `devbox.json` recipe and the t7 rewording above. The sign-off hint (`buildcmd.py:145`) matches the design; `signoff.unsigned` uses git's `%h` short sha.

## Tightened acceptance tests

Tightened by the tester in f6a2b05 after cycle 1, recorded by `test-diff --tighten`. Each change only adds assertions or a test; none is removed or loosened.

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_172_quiet.py` | AC-172.3: the template case only checked that the recipe ends in `"$@"`; new parametrized test runs each Python template's runner and checks file and `-k` selection | yes |
| `tests/cplat/test_172_quiet.py` | AC-172.5: the not-attributable case did not check that the failure summary is printed; now asserts the summary title and the log excerpt | yes |
| `tests/cplat/test_172_build_tests.py` | AC-172.6: no test for the exit-1 route to a coder or the repeated run after the tester's fix; new test asserts both and their order in the reference | yes |
| `tests/cplat/test_172_signoff_merge.py` | AC-172.7: no test for "Phase 2 rebases and merges again without asking"; new prompt test reads the 2.4 step-1 line | yes |

Two earlier acceptance-test changes, both approved by the user (round 171 standing order, 2026-11-10):

| File | Change | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_172_test_diff.py` | `why.startswith("fewer assertions")` → `why` (truthy) | yes: AC-172.1 only asks that the file is "reported as before", without a verdict text |
| `tests/cplat/test_172_quiet.py` | the recipe equals `bash scripts/test-fast.sh "$@"` → the recipe contains it | yes: the pass-through is proven by `test_the_platform_test_fast_runs_only_the_given_tests_ac_172_3` |

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
