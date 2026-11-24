# Verification — 177 Triage asks reporters plainly and closes what needs no work

**Commit:** cb1ababe · **Base:** 4a217287 (spec work judged on 7898135b..HEAD) · **Trace:** 4/4 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-177.1 | met | `tests/cplat/test_177_triage_close.py::test_the_batch_carries_the_forms_and_the_missing_fields_of_a_form_filed_issue_ac_177_1`, `::test_a_needs_info_row_needs_the_missing_fields_ac_177_1`, `::test_the_missing_list_must_hold_every_missing_field_of_the_form_ac_177_1`, `::test_the_missing_list_names_only_fields_of_the_form_ac_177_1`, `::test_an_issue_filed_without_a_form_needs_the_matching_form_in_its_row_ac_177_1`, `::test_the_overview_shows_the_missing_fields_of_a_needs_info_row_ac_177_1`; `tests/cplat/test_177_triage_reporter.py::test_form_of_lists_the_required_fields_that_are_absent_blank_or_no_response_ac_177_1`, `::test_form_of_picks_the_form_with_the_most_matching_headings_ac_177_1`; `tests/cplat/test_177_triage_prompt.py::test_the_prompt_limits_questions_to_the_user_to_what_the_user_may_know_ac_177_1` | `scripts/cplat/triage_reporter.py:28`, `:63`; `scripts/cplat/triage_batch.py:44` (form per entry in `_entry`); `scripts/cplat/triage_view.py:109`; `plugins/issue/commands/triage.md:24` | Missing fields are script-checked with the exact contract errors. The split of questions (user versus reporter comment) is prompt behaviour; its only testable surface is the prompt sentence at `triage.md:24`, which the test asserts. The prompt leaves out the spec's examples ("who the reporter is, whether the problem is known"). |
| AC-177.2 | met | `test_177_triage_close.py::test_a_comment_to_an_outside_reporter_with_internal_terms_is_refused_ac_177_2`, `::test_a_label_name_is_an_internal_term_ac_177_2`, `::test_a_needs_info_comment_must_thank_the_reporter_ac_177_2`, `::test_a_needs_info_comment_must_ask_for_each_missing_field_ac_177_2`, `::test_the_public_commands_are_allowed_in_a_comment_to_an_outside_reporter_ac_177_2`, `::test_a_writer_may_get_internal_terms_and_needs_no_thanks_ac_177_2`, `::test_the_shown_comment_ends_with_the_days_and_reopen_sentence_ac_177_2`, `::test_the_days_in_the_comment_follow_the_project_setting_ac_177_2`, `::test_act_posts_the_comment_with_the_days_sentence_and_keeps_the_issue_open_ac_177_2`; `test_177_triage_reporter.py::test_internal_terms_finds_spec_numbers_labels_and_commands_ac_177_2` (8 cases), `::test_the_footer_names_the_days_and_the_reopen_promise_ac_177_2` | `scripts/cplat/triage_reporter.py:79`, `:94`, `:99`; `scripts/cplat/triage_view.py:128` (writers exempt through `triage_facts.is_writer`), `:336` (footer with the configured days) | Thanks, each missing item, no internal terms except the two public commands, and the days-and-reopen sentence are all asserted on the shown and the posted comment. |
| AC-177.3 | met | `test_177_triage_close.py::test_act_posts_the_comment_then_closes_the_issue_as_not_planned_ac_177_3` (question, duplicate, wontfix), `::test_a_duplicate_comment_links_the_original_ac_177_3`, `::test_an_unconfirmed_row_is_never_closed_ac_177_3`, `::test_the_other_classes_are_never_closed_ac_177_3`, `::test_an_unattended_run_refuses_to_close_before_any_write_ac_177_3`, `::test_the_confirmation_says_which_rows_close_as_not_planned_ac_177_3`, `::test_close_one_runs_one_gh_close_with_the_reason_and_its_undo_ac_177_3`; `test_177_triage_prompt.py::test_the_closing_hard_rule_keeps_its_register_id_and_enforcement_ac_177_3` | `scripts/cplat/triage.py:213`, `:219`; `scripts/cplat/triage_view.py:337-339` (`Duplicate of #N` prefix, close only for closing classes); `scripts/cplat/triage_act.py:173`, `:195` (close after the comment, only named rows); `docs/rules/plugins/issue/commands/triage.yml` R4 | The comment-before-close order and `--reason "not planned"` are asserted on the gh calls. |
| AC-177.4 | met | `test_177_triage_close.py::test_a_needs_info_issue_silent_for_14_days_is_proposed_for_closing_ac_177_4`, `::test_a_needs_info_issue_silent_for_13_days_stays_skipped_ac_177_4`, `::test_the_days_come_from_the_project_setting_ac_177_4`, `::test_a_silent_issue_needs_no_row_and_appears_in_the_confirmation_ac_177_4`, `::test_act_closes_a_silent_issue_with_the_final_comment_only_when_named_ac_177_4`, `::test_a_silent_issue_is_not_closed_by_a_headless_run_ac_177_4`, `::test_a_reporter_comment_after_the_close_queues_the_closed_issue_ac_177_4`, `::test_a_comment_by_someone_else_after_the_close_does_not_queue_it_ac_177_4`, `::test_act_reopens_a_requeued_issue_before_its_labels_and_comment_ac_177_4`; `test_177_triage_reporter.py::test_the_final_comment_invites_the_reporter_to_comment_to_reopen_ac_177_4`, `::test_needs_info_close_days_defaults_to_14_ac_177_4`, `::test_needs_info_close_days_refuses_anything_but_a_whole_number_of_at_least_one_ac_177_4` | `scripts/cplat/settings.py:221`; `scripts/cplat/triage_batch.py:126` (silent threshold), `:136` (requeue of a closed `needs-info` issue); `scripts/cplat/triage_reporter.py:104`; `scripts/cplat/triage_view.py:313` (silent: final comment, close, no label change); `scripts/cplat/triage_act.py:191` (reopen before the labels) | The 13 versus 14 day boundary, the configured days and the close-only-when-named behaviour are all asserted. |

## Non-goals

- Closing without confirmation: `act` closes only rows named in `--rows`, and `CPLAT_HEADLESS=1` refuses before the first write (`triage.py:213`, `triage_act.py:173`). `apply` (the single-issue path) still never closes. ✔
- Hiding secret comments: no code was added for it. ✔
- No changes to the template-owned layout and no priority or one-table changes beyond the close and missing suffixes the contract names. ✔

## Deviations from the plan

- Test files outside every task's `files`: `tests/cplat/test_176_act.py`, `test_176_view.py`, `test_196_triage_priority.py` and `test_177_triage_close.py::test_the_other_classes_are_never_closed_ac_177_3` were changed after the red commit. **Acceptable:** the user approved both changes (spec Assumptions, 2026-11-24). Every change updates only data or expectations that predate spec 177 (`missing`, the thank-you text, the close suffix, a non-closing class for AC-196.4). `test_177_triage_prompt.py` only moves its `# interface:` markers.
- `plugins/issue/commands/triage.md` last paragraph: to stay within the byte budget the newline before `> If a platform template…` was dropped, so the escalation line is now glued to the end of the step 6 text (`…show fix runs.> If…`) and no longer renders as a blockquote. The text and its hard rule are still there. **Acceptable, cosmetic.** A fix should put the newline back.
- `triage.md:38` calls the silent proposal a "`silent` row", but a silent issue needs no row (contract). This is a wording slip with no effect on behaviour. **Acceptable.**
- The R8 practice rule names only question, duplicate and wontfix. Silent `needs-info` closes are covered by the next prompt line and by the code. **Acceptable.**
- ADR-129 and its README index entry came from the planning commit (82d790f1), before the build range. **Acceptable.**

## Contract

Matches `design.md`: the `triage_reporter` functions and texts, the `needs_info_close_days` setting and its error, the batch fields (`close_after_days`, `forms`, `state`, `form`, the silent `handled`, the `waiting_closed` alias), the row error lines, `actions()` with `close` and `reopen`, the confirm/show/overview texts, `close_one`/`reopen_one`/`refuse_unattended_close`, the `act` order (reopen, labels and comment, then close), and the `closed`/`reopened` fields with the undo. The only change is that `actions()` takes `days` as a parameter (default 14), as plan t5 says. ✔

## Unresolved test-review findings

| Test | Criterion | Finding |
|---|---|---|
| none | none | The one review finding was resolved in 0f64f2ca; none remain unresolved. |

**Result:** pass

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
