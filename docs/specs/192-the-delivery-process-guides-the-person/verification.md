# Verification — 192 The delivery process guides the person from triage to release

**Result:** fail
**Commit:** 6efa992e · **Base:** 8275a3a8 · **Trace:** 10/10 criteria named by tests

Phase 3: `cplat quiet test-fast` 10570 passed, 12 skipped; `cplat quiet ci` OK; acceptance and security gates passed.
The code is right for every criterion I read; three criteria fail because their tests assert less than the criterion
states (spec 165), and AC-192.4 also has a small code gap.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-192.1 | met | `tests/cplat/test_192_screen.py::test_screen_has_three_parts_in_order`, `::test_nothing_state_ends_with_walk_away`, `::test_next_changes_nothing`, `::test_same_screen_in_a_fresh_session_and_another_worktree`, `::test_same_screen_after_an_interrupted_session`, `::test_headless_has_no_questions_but_the_same_screen`; `test_192_prompts.py::test_next_command_exists_with_a_description` | `scripts/cplat/nextscreen.py:321` (three parts, `:348`), `scripts/cplat/nextstate.py:280` (read-only collect), `scripts/cplat/nextcmd.py:113`, `plugins/platform/commands/next.md` | the snapshot covers repo files, XDG state, home, refs, git status, `gh` writing verbs, claims and the run buffer |
| AC-192.2 | not met | `tests/cplat/test_192_stages.py` (all), `test_192_screen.py::test_bar_in_a_platform_repo`, `::test_bar_in_a_service_repo`, `::test_running_work_marks_its_step_as_running_on_its_own`, `::test_nothing_waiting_has_no_marked_step` | `scripts/cplat/stages.py:427` (`bar`), `:432` (`bar_step`), `scripts/cplat/nextscreen.py:98` (marks and label column `:122`, `:128`), `scripts/cplat/console/glossary.py:283`, `:303` | TEST LOOSER: the criterion puts `you are here` / `running on its own` *under* the marked step and gives running work's step a `●`; the tests only check the label is somewhere on line 2 (`"you are here" in bar_lines[1]`) and, for running work, the JSON `state` and the label text, never the `●` on `Build` in the screen. A label at column 0 or a running step without `●` passes. Code is right (label starts at the marked segment's column; `running` gets `●`). |
| AC-192.3 | met | `test_192_screen.py::test_stopped_run_comes_before_specs_and_issues`, `::test_group_order_of_the_also_waiting_line`, `::test_daily_budget_is_in_the_first_group`, `::test_specs_come_before_issues_and_issues_before_a_release`, `::test_release_group_alone`, `::test_oldest_first_within_a_group`, `::test_notified_item_shows_its_age`, `::test_unnotified_item_shows_no_age` | `scripts/cplat/nextstate.py:43` (group order), `:333` (`groups`), `:251` (notified age), `scripts/cplat/nextscreen.py:223` (`Also waiting`) | |
| AC-192.4 | not met | `test_192_screen.py::test_nothing_waits_nothing_runs`, `::test_runs_going_nothing_waiting`, `::test_channels_of_the_notification_settings`, `::test_notifications_off`, `::test_unreadable_source_is_named_and_never_nothing`, `::test_bad_notification_file_is_a_named_source` | `scripts/cplat/nextscreen.py:334` (nothing case), `:235` (runs), `:283` (channels), `:217` + `:28` (source and hint), `scripts/cplat/nextquestions.py:287` (Try again) | TEST LOOSER: "names the source **and what may be missing**" — the tests assert only `Could not read` and `GitHub` / `notification`, which the source name alone satisfies; the hint (`a GitHub login (gh auth status) or the network`, `a valid notify.yaml`) is never asserted. Code gap: `nextscreen.py:336` prints the parked count only when it is above 0, while the criterion says the screen gives "the number of parked items" and design.md fixes `<n> parked item(s).` unconditionally; the test covers only 2 parked. |
| AC-192.5 | not met | `test_192_screen.py::test_draft_block_with_judgement`, `::test_assumption_without_judgement_is_the_first_unstruck_one`, `::test_draft_without_judgement_has_no_empty_field`, `::test_size_classes`, `::test_size_has_a_time_only_from_three_comparable_runs`, `::test_size_has_no_number_with_two_runs`; `test_192_questions.py::test_approve_choices`, `::test_one_draft_has_no_approve_all`, `::test_a_draft_with_an_open_question_is_asked_first_and_not_approved_with_the_rest`, `::test_only_one_sub_screen_lists_two_specs_oldest_first` | `scripts/cplat/nextscreen.py:146` (draft block), `scripts/cplat/nextstate.py:163` (estimates per size, this repo only, `:168`, `:179`), `:82` (`size_of`), `scripts/cplat/nextquestions.py:205`, `:224` | TEST LOOSER: the time needs ≥3 comparable runs **of that size** **recorded in the repo**; the 3-run test uses runs whose specs all have the draft's size and the same repo, so an estimate that ignores size or repo passes. No test has 3 runs of another size (or another repo) and expects no number. Code is right (`by_size[size_of(...)]`, `r.get("repo") != slug`). |
| AC-192.6 | met | `test_192_questions.py::test_at_most_four_questions_per_page`, `::test_one_page_has_no_page_text`, `::test_later_puts_an_item_off`, `::test_later_option_carries_the_items_for_the_next_call`, `::test_every_step_can_be_gone_through_by_choosing`, `::test_how_tells_the_session_what_to_do`; `test_192_prompts.py::test_next_command_runs_cplat_next_json_and_follows_how` | `scripts/cplat/nextquestions.py:316` (pages `:334`), `:174` (recommended first), `:179` (Later), `scripts/cplat/nextcmd.py:32` (`HOW`) | |
| AC-192.7 | met | `test_192_questions.py::test_approve_names_each_outward_action_and_the_irreversible_one`, `::test_nothing_outward_runs_before_the_choice`, `::test_show_details_option_on_every_outward_question`, `::test_triage_details_list_labels_and_a_comment`, `::test_release_actions_say_what_cannot_be_undone`, `::test_assumptions_sub_screen_lists_actions_with_targets`, `::test_record_argv_names_the_option_and_items`; `test_192_prompts.py::test_next_command_never_chooses_for_the_person` | `scripts/cplat/nextquestions.py:50` (actions), `:161` (description, `cannot_undo`, `undo`), `scripts/cplat/nextscreen.py:244`, `:250` (sub-screens) | |
| AC-192.8 | met | `test_192_prompts.py::test_prompt_ends_with_the_hand_over`, `::test_hand_over_sentence_ends_the_prompt`, `::test_the_procedure_is_not_copied_into_the_prompts`; `test_192_questions.py::test_first_question_is_the_next_step_as_a_choice_with_the_recommended_option_first`, `::test_command_lines_are_secondary_details` | hand-over sentence in `plugins/component/commands/{spec,build,ship,release}.md`, `plugins/issue/commands/triage.md`, `plugins/platform/commands/release.md`, `plugins/system/commands/{spec,ship}.md`; `scripts/cplat/nextquestions.py:167` (`Runs …` after the label) | |
| AC-192.9 | met | `test_192_screen.py::test_no_line_is_wider_than_80_columns`, `::test_width_of_the_issue_and_release_screens`, `::test_width_of_a_release_screen`, `::test_no_colour_codes`, `::test_every_state_symbol_comes_with_a_word`, `::test_ascii_step_numbers_on_a_six_step_bar`, `::test_ascii_mode_has_no_symbols`, `::test_utf8_mode_has_the_symbols`, `::test_a_terminal_that_is_not_utf8_gets_ascii`, `::test_ascii_stuck_marker`, `::test_long_lists_show_five_and_the_rest`, `::test_ids_follow_the_description`, `::test_internal_words_do_not_appear` | `scripts/cplat/nextscreen.py:60` (`wrap`), `:315` (ASCII), `:78` (cut at 5), `scripts/cplat/nextstate.py:71` (`plain`), `scripts/cplat/nextcmd.py:68` (`ascii_mode`) | |
| AC-192.10 | met | `test_192_person_time.py` (all 8); `test_192_questions.py::test_record_argv_names_the_option_and_items`; `test_runs_report.py::test_json_output_has_stable_keys_and_nothing_else_on_stdout`; `test_runs_report_unclassified.py::test_the_json_report_has_the_unclassified_key` | `scripts/cplat/nextcmd.py:144` (cap 10, even split `:153`), `scripts/cplat/runs.py:628` (`person_answer`), `scripts/cplat/runs_report.py:250` (`aggregate_person`), `:282` (text block, `–`) | |

## Non-goals

No build-start, build-log, interruption or end-of-build screen; no grouped triage screen; no web Inbox guidance (the
console only gains four glossary terms and one How-it-works line, which AC-192.2 asks for); no dispatcher scheduling,
gate or hard-rule change; estimates come only from recorded runs. No template-owned layout (header, footer,
navigation) changed. ✔

## Deviations from the plan

- `scripts/cplat/notify_config.py:100` is in no task's `files` (t6 changed it): an unquoted YAML `off` read as `false`
  now counts as `off`. Acceptable: needed for AC-192.4's "notifications are off", small and behaviour-preserving.
- t8/t9 list `docs/rules/plugins/{component,issue,platform,system}/commands/*.yml`, but none changed: the eight
  hand-over sentences have no register entries, against the plan ("register entries per new sentence") and A12.
  Acceptable only because `cplat platform rules check` passes in `ci` (the checker does not treat the sentence as a
  rule); worth a register entry in a follow-up.
- `plugins/issue/commands/triage.md` lost the sentence "Triage can be scheduled with `/loop` or `/schedule`; it proposes
  until the user confirms, so an unattended run is safe." (not a registered rule). Acceptable but a small loss of
  guidance; the restore commit `bec4fbba` brought back other trimmed text, not this one.
- New `docs/adr/112-delivery-screens-are-printed-by-cplat.md`: outside `files` by design (t10 notes, number known only
  at `cplat adr add`). Acceptable.
- Existing tests `tests/cplat/test_plugins_114.py`, `test_runs_report.py`, `test_runs_report_unclassified.py` updated
  for the new command and the appended `person` key. Acceptable: mechanical pins of counts and key order.
- After the red commit, `tests/cplat/test_192_prompts.py` changed only by removing trailing `# interface:` comments
  (`git diff 35856ed4..HEAD`); assertions unchanged. Acceptable.
- Prompt baseline raised 357001 → 359241 with two benchmark runs in `docs/rules/register.yml` (the plan's human step).
  Acceptable.
- Every task has `done: true`. Contract (design.md: CLI, `--json` schema 1, questions, actions, screen texts, person
  records, `how`) matches the code apart from the parked-count gap under AC-192.4.

## Contract

Matches `design.md`, except `nextscreen.py:336` omitting `<n> parked item(s).` when the count is 0.
