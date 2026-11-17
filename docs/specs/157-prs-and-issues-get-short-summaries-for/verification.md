# Verification — 157 Build and ship PRs start with a short summary

**Result:** fail
**Commit:** 6c47aced · **Base:** e642dd43 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-157.1 | met | `tests/cplat/test_157_pr_summary.py::test_the_block_has_the_marker_heading_and_four_bullets_ac_157_1`, `::test_apply_replaces_every_earlier_block_never_adds_a_second_ac_157_1`, `::test_pr_open_body_starts_with_the_block_and_keeps_the_rest_ac_157_1` (with and without a run), `::test_pr_open_replaces_a_summary_block_the_body_already_has_ac_157_1`; `tests/cplat/test_runs_built_133.py` (how-built block unchanged) | `scripts/cplat/pr_summary.py:157` (render), `:180` (apply), `scripts/cplat/pr_open.py:169`, `:216` | The block goes on after `_how_built`, so the how-built block stays at the end. The test compares it with `runs_built.pr_section` |
| AC-157.2 | met | `test_157_pr_summary.py::test_changed_is_the_spec_title_with_criteria_and_files_ac_157_2`, `::test_a_component_repo_without_a_changelog_folder_never_falls_back_to_the_title_ac_157_2`, `::test_the_fragments_first_sentence_without_emphasis_is_next_ac_157_2`, `::test_the_pr_title_is_the_last_fallback_ac_157_2`, `::test_pr_open_counts_the_files_it_is_about_to_commit_ac_157_2`, `::test_an_unknown_spec_is_a_failure_not_a_title_fallback_ac_157_2` | `scripts/cplat/pr_summary.py:67`, `:51` | Exact strings asserted (`Thing title (2 criteria of spec 157, 2 files)`). The withdrawn criterion is not counted |
| AC-157.3 | met | `test_157_pr_summary.py::test_why_is_the_so_that_clause_of_the_first_story_ac_157_3`, `::test_why_lists_the_closing_references_with_issue_titles_ac_157_3`, `::test_at_most_three_references_then_and_n_more_ac_157_3`, `::test_without_story_or_reference_why_is_not_recorded_ac_157_3` | `scripts/cplat/pr_summary.py:81` | Problem text is checked to be absent. Exact `… and 2 more` |
| AC-157.4 | met | `test_157_pr_summary.py::test_review_counts_findings_fixes_and_deviations_ac_157_4`, `::test_without_a_run_the_findings_are_not_recorded_ac_157_4`, `::test_a_run_of_another_spec_is_not_used_ac_157_4`, `::test_the_verification_state_is_read_from_the_result_line_ac_157_4`, `::test_without_a_verification_file_the_state_is_not_yet_ac_157_4`, `::test_risks_lists_deviations_then_follow_ups_at_most_three_ac_157_4`, `::test_risks_are_none_recorded_without_items_ac_157_4` | `scripts/cplat/pr_summary.py:130`, `:109`, `:171` | Exact Review string with severity counts, fixed count and deviations. Risks lists deviations, then follow-ups, then `… and 2 more` |
| AC-157.5 | met | `test_157_pr_summary.py::test_values_pass_the_redaction_ac_157_5`, `::test_no_value_can_close_the_block_ac_157_5`, `::test_a_long_line_is_cut_to_300_characters_with_an_ellipsis_ac_157_5`, `::test_no_prompt_or_diff_of_the_run_reaches_the_block_ac_157_5`, `::test_free_text_of_the_orchestrators_body_does_not_reach_the_block_ac_157_5`, `::test_pr_open_with_a_failing_summary_opens_the_pr_with_one_extra_line_ac_157_5`; `test_157_pr_summary_ships.py::test_a_failing_summary_leaves_the_ship_body_unchanged_with_a_note_ac_157_5`, `::test_a_failing_summary_leaves_the_gitops_body_unchanged_with_a_note_ac_157_5` | `scripts/cplat/pr_summary.py:30`, `:176`, `:186`; `scripts/cplat/pr_open.py:169` | For `pr open`, the test checks the same exit code, a byte-identical body and exactly one extra output line |
| AC-157.6 | partial | `test_157_pr_summary_ships.py::test_a_new_ship_pr_starts_with_the_block_ac_157_6`, `::test_an_existing_ship_pr_gets_the_block_by_an_edit_ac_157_6`, `::test_a_ship_pr_that_already_has_a_block_gets_it_replaced_ac_157_6`, `::test_a_gitops_pr_starts_with_the_block_of_the_system_spec_ac_157_6`, `::test_the_entry_pr_starts_with_the_block_ac_157_6`, `::test_a_current_run_adds_no_how_built_block_to_*_ac_157_6`, `::test_an_open_gitops_pr_is_reused_not_edited_ac_157_6` | `scripts/cplat/ship.py:654`, `:682`; `scripts/cplat/appship.py:73-79`, `:215-222`; `scripts/cplat/appship_joint.py:221`, `:573` | Met for component-repo PRs (opened and updated) and for new gitops PRs. Not met for gitops PRs the system ship updates: `appship.open_pr` and `entry_pr` return an existing PR untouched (`appship.py:73`, `:215`). `complete`, `publish` and the joint dev PR still push commits to that PR. A gitops PR opened before this release, or one whose summary failed at creation, never gets the block. design.md ("Existing PRs in the system ship are not edited") narrows "opens or updates", and `test_an_open_gitops_pr_is_reused_not_edited_ac_157_6` pins the narrower behaviour. This is the unresolved test-review finding below. Fix: either edit the body of a reused gitops PR (`gh pr edit --body`), or the user amends AC-157.6 to "opens" for gitops PRs |
| AC-157.7 | met | `test_157_pr_summary_ships.py::test_the_command_says_cplat_adds_the_summary_to_the_pr_body_ac_157_7`, `::test_the_command_puts_the_summary_at_the_top_ac_157_7`, `::test_the_command_says_the_orchestrator_writes_no_summary_ac_157_7`, `::test_the_changelog_has_an_entry_for_568_ac_157_7` | `plugins/component/commands/build.md:116`, `plugins/component/commands/ship.md:42`, `plugins/system/commands/ship.md:49`, `plugins/component/references/build-pr.md:45`, `docs/changelog.d/568-pr-summary.added.md` | Minor: the fragment lists "the plan" as a source and calls the Review line "what to review". Neither matches the contract (the sources are the spec, fragment, git, the run and verification; Review is the review outcome). It is not an AC failure, but worth correcting |

## Non-goals

- No agent or model text: every value comes from the spec, a fragment, git, `gh issue view`, run records or `verification.md` (`pr_summary.py:157-177`). ✔
- No issue comments (spec 158). ✔
- `runs_built.py` is unchanged and so is the how-built block. The orchestrator's PR body template in `build-pr.md` is unchanged (only the "Open it" lead-in sentence changed). ✔
- No summary in release, upgrade, fleet or cluster-repo PRs: `pr_summary` is imported only by `pr_open.py`, `ship.py` and `appship.py`. ✔
- No changelog fragments in component templates. ✔

## Deviations from the plan

- `tests/cplat/test_ship_pr_126.py` and `tests/cplat/test_built_titles_126.py` are outside every task's `files` (commit 361a4527). Older whole-body assertions now strip the summary block, and the `open_pr` call passes `spec=`. The no-edit test now allows exactly one `--body-file` edit carrying the block, which is what AC-157.6 requires. Acceptable.
- `scripts/cplat/runs.py` shows in the branch diff but comes from #790 (spec 190), not from this spec. Not a spec-157 deviation.
- All tasks t1 to t4 are `done: true`. Plugin versions: component 1.24.0 and system 1.22.0, mirrored in `marketplace.json`. ✔
- Contract: design.md's "Existing PRs in the system ship are not edited" is narrower than AC-157.6 ("opens or updates"). Not acceptable without the user's decision (see AC-157.6).

## Contract

Matches design.md (signatures `render`/`apply`/`add`, `MAX_LINE`/`MAX_ITEMS`, value rules, caller placement), except for the AC-157.6 difference above.

## Unresolved test-review findings

| Test | Criterion | Finding |
|---|---|---|
| `tests/cplat/test_157_pr_summary_ships.py::test_an_open_gitops_pr_is_reused_not_edited_ac_157_6` | AC-157.6 | design.md says existing gitops PRs are not edited, the criterion says "opens or updates"; needs the user |
