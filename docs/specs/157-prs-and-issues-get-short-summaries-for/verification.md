# Verification — 157 Build and ship PRs start with a short summary

**Result:** pass
**Commit:** c9ce99d0 (re-verification after the AC-157.6 amendment; no code or test change since 6c47aced) · **Base:** e642dd43 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-157.1 | met | `tests/cplat/test_157_pr_summary.py::test_the_block_has_the_marker_heading_and_four_bullets_ac_157_1`, `::test_apply_replaces_every_earlier_block_never_adds_a_second_ac_157_1`, `::test_pr_open_body_starts_with_the_block_and_keeps_the_rest_ac_157_1` (with and without a run), `::test_pr_open_replaces_a_summary_block_the_body_already_has_ac_157_1`; `tests/cplat/test_runs_built_133.py` (how-built block unchanged) | `scripts/cplat/pr_summary.py:157` (render), `:180` (apply), `scripts/cplat/pr_open.py:169`, `:216` | The block goes on after `_how_built`, so the how-built block stays at the end. The test compares it with `runs_built.pr_section` |
| AC-157.2 | met | `test_157_pr_summary.py::test_changed_is_the_spec_title_with_criteria_and_files_ac_157_2`, `::test_a_component_repo_without_a_changelog_folder_never_falls_back_to_the_title_ac_157_2`, `::test_the_fragments_first_sentence_without_emphasis_is_next_ac_157_2`, `::test_the_pr_title_is_the_last_fallback_ac_157_2`, `::test_pr_open_counts_the_files_it_is_about_to_commit_ac_157_2`, `::test_an_unknown_spec_is_a_failure_not_a_title_fallback_ac_157_2` | `scripts/cplat/pr_summary.py:67`, `:51` | Exact strings asserted (`Thing title (2 criteria of spec 157, 2 files)`). The withdrawn criterion is not counted |
| AC-157.3 | met | `test_157_pr_summary.py::test_why_is_the_so_that_clause_of_the_first_story_ac_157_3`, `::test_why_lists_the_closing_references_with_issue_titles_ac_157_3`, `::test_at_most_three_references_then_and_n_more_ac_157_3`, `::test_without_story_or_reference_why_is_not_recorded_ac_157_3` | `scripts/cplat/pr_summary.py:81` | Problem text is checked to be absent. Exact `… and 2 more` |
| AC-157.4 | met | `test_157_pr_summary.py::test_review_counts_findings_fixes_and_deviations_ac_157_4`, `::test_without_a_run_the_findings_are_not_recorded_ac_157_4`, `::test_a_run_of_another_spec_is_not_used_ac_157_4`, `::test_the_verification_state_is_read_from_the_result_line_ac_157_4`, `::test_without_a_verification_file_the_state_is_not_yet_ac_157_4`, `::test_risks_lists_deviations_then_follow_ups_at_most_three_ac_157_4`, `::test_risks_are_none_recorded_without_items_ac_157_4` | `scripts/cplat/pr_summary.py:130`, `:109`, `:171` | Exact Review string with severity counts, fixed count and deviations. Risks lists deviations, then follow-ups, then `… and 2 more` |
| AC-157.5 | met | `test_157_pr_summary.py::test_values_pass_the_redaction_ac_157_5`, `::test_no_value_can_close_the_block_ac_157_5`, `::test_a_long_line_is_cut_to_300_characters_with_an_ellipsis_ac_157_5`, `::test_no_prompt_or_diff_of_the_run_reaches_the_block_ac_157_5`, `::test_free_text_of_the_orchestrators_body_does_not_reach_the_block_ac_157_5`, `::test_pr_open_with_a_failing_summary_opens_the_pr_with_one_extra_line_ac_157_5`; `test_157_pr_summary_ships.py::test_a_failing_summary_leaves_the_ship_body_unchanged_with_a_note_ac_157_5`, `::test_a_failing_summary_leaves_the_gitops_body_unchanged_with_a_note_ac_157_5` | `scripts/cplat/pr_summary.py:30`, `:176`, `:186`; `scripts/cplat/pr_open.py:169` | For `pr open`, the test checks the same exit code, a byte-identical body and exactly one extra output line |
| AC-157.6 | met | `test_157_pr_summary_ships.py::test_a_new_ship_pr_starts_with_the_block_ac_157_6`, `::test_an_existing_ship_pr_gets_the_block_by_an_edit_ac_157_6`, `::test_a_ship_pr_that_already_has_a_block_gets_it_replaced_ac_157_6`, `::test_a_gitops_pr_starts_with_the_block_of_the_system_spec_ac_157_6`, `::test_the_entry_pr_starts_with_the_block_ac_157_6`, `::test_a_current_run_adds_no_how_built_block_to_a_ship_pr_ac_157_6`, `::test_a_current_run_adds_no_how_built_block_to_a_gitops_pr_ac_157_6`, `::test_an_open_gitops_pr_is_reused_not_edited_ac_157_6` | `scripts/cplat/ship.py:654`, `:682` (component PR created, or its body updated); `scripts/cplat/appship.py:70-79` (gitops PR created, system spec), `:215-222` (entry PR created); `scripts/cplat/appship_joint.py:219`, `:571` (dev and staging PRs through `open_pr`) | Checked against the amended criterion (c9ce99d0): the block must be on PRs the system ship creates (component or gitops) and on component PRs whose body it updates. Created gitops and entry PRs get it. Component PRs get it when created, and by `gh pr edit --body-file` when updated. A reused open gitops PR is not edited: the amended criterion no longer requires that, and design.md says the same. No how-built block is added (the ship and gitops tests assert `HOW_START not in text`; `_built_block` belongs to spec 200 and runs only with `approved_test_diffs`) |
| AC-157.7 | met | `test_157_pr_summary_ships.py::test_the_command_says_cplat_adds_the_summary_to_the_pr_body_ac_157_7`, `::test_the_command_puts_the_summary_at_the_top_ac_157_7`, `::test_the_command_says_the_orchestrator_writes_no_summary_ac_157_7`, `::test_the_changelog_has_an_entry_for_568_ac_157_7` | `plugins/component/commands/build.md:116`, `plugins/component/commands/ship.md:42`, `plugins/system/commands/ship.md:49`, `plugins/component/references/build-pr.md:45`, `docs/changelog.d/568-pr-summary.added.md` | Note (still the case): the fragment lists "the plan" as a source and calls the Review line "what to review". Neither matches the contract: the sources are the spec, the fragment, git, the run and verification, and Review is the review outcome. This is not an AC failure, but it is worth correcting |

## Non-goals

- No agent or model text: every value comes from the spec, a fragment, git, `gh issue view`, run records or `verification.md` (`pr_summary.py:157-177`). ✔
- No issue comments (spec 158). ✔
- `runs_built.py` is unchanged and so is the how-built block. The orchestrator's PR body template in `build-pr.md` is unchanged (only the "Open it" lead-in sentence changed). ✔
- No summary in release, upgrade, fleet or cluster-repo PRs: `pr_summary` is imported only by `pr_open.py`, `ship.py` and `appship.py`. ✔
- No changelog fragments in component templates. ✔

## Deviations from the plan

- `tests/cplat/test_ship_pr_126.py` and `tests/cplat/test_built_titles_126.py` are outside every task's `files` (commit 361a4527). Older whole-body assertions now strip the summary block, and the `open_pr` call passes `spec=`. The no-edit test now allows exactly one `--body-file` edit carrying the block, which AC-157.6 requires for component PRs. Acceptable.
- `scripts/cplat/runs.py` and the spec 190/198 files show in the branch diff but come from other specs. They are not spec-157 deviations.
- All tasks t1 to t4 are `done: true`. Plugin versions: component 1.24.0 and system 1.22.0, mirrored in `marketplace.json`. ✔
- Contract: design.md's "Existing PRs in the system ship are not edited" now matches the amended AC-157.6 (user decision 2026-11-18). Resolved.

## Contract

Matches design.md with no difference: the signatures `render`/`apply`/`add`, `MAX_LINE`/`MAX_ITEMS`, the value rules, the caller placement, and the rule that existing system-ship PRs are not edited.

## Unresolved test-review findings

| Test | Criterion | Finding |
|---|---|---|
| `tests/cplat/test_157_pr_summary_ships.py::test_an_open_gitops_pr_is_reused_not_edited_ac_157_6` | AC-157.6 | Design vs criterion: resolved by the AC-157.6 amendment (c9ce99d0). The test now pins the specified behaviour |

## Test run

`cplat quiet test-fast`: one failure, `tests/cplat/test_122_final_evidence.py::test_done_lists_releases_with_their_date_and_filters_by_period`. The test depends on the calendar, is unrelated to spec 157, and is already fixed on origin/main. All spec-157 tests pass.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
