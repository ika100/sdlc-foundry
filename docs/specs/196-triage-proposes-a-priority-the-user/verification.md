# Verification — 196 Triage and new specs propose a priority the user confirms

**Result:** pass
**Commit:** 17736cf (cycle 2) · **Base:** 65720b0 · **Trace:** 12/12 criteria named by tests

Cycle 2: the only code-side change since cycle 1 (de63bb8) is commit 17736cf, which adds two AC-196.11 tests. The verdicts for AC-196.1 to .10 and .12 carry over from cycle 1, because no implementation file changed.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-196.1 | met | `tests/cplat/test_196_triage_priority.py::test_a_bug_small_change_or_feature_row_shows_one_priority_and_a_reason_of_at_most_60_characters_ac_196_1`, `::test_the_confirmation_line_names_the_priority_and_its_reason_ac_196_1`, `::test_the_other_classes_show_no_priority_ac_196_1`; `tests/cplat/test_196_priority_levels.py::test_every_proposal_reason_fits_60_characters_ac_196_1` | `scripts/cplat/triage_view.py:297` (head `<class>, <P> (<reason>)`), `scripts/cplat/triage_view.py:308` (JSON `priority`, `priority_reason`, `decide`), `scripts/cplat/triage_batch.py:120` | the tests assert that none of the five no-priority classes carries a level |
| AC-196.2 | met | `test_196_triage_priority.py::test_a_proposal_names_a_definition_phrase_of_its_level_ac_196_2`, `::test_a_missing_reason_with_p1_becomes_the_fallback_reason_ac_196_2`, `::test_a_reason_that_names_no_definition_of_the_level_is_refused_ac_196_2`; `test_196_priority_levels.py::test_a_reason_naming_a_phrase_of_its_level_is_a_proposal_reason_ac_196_2` | `scripts/cplat/priority.py:22`, `scripts/cplat/triage_view.py:87` | matching an issue to a definition is the triager's judgement (`plugins/issue/commands/triage.md:23`); cplat checks that the reason names a definition phrase of its level |
| AC-196.3 | met | `test_196_triage_priority.py::test_a_priority_label_on_the_issue_wins_whatever_the_text_suggests_ac_196_3`, `::test_more_than_one_priority_label_proposes_the_most_urgent_and_marks_the_row_ac_196_3`, `::test_a_row_with_several_labels_stays_to_decide_until_the_user_decided_ac_196_3` | `scripts/cplat/triage_view.py:124`, `scripts/cplat/triage_view.py:150`, `scripts/cplat/priority.py:38` | |
| AC-196.4 | met | `test_196_triage_priority.py::test_confirm_set_shows_the_new_priority_with_the_reason_changed_by_you_ac_196_4`, `::test_a_run_without_confirmation_writes_no_label_and_makes_no_spec_ac_196_4`, `::test_an_unattended_act_with_a_priority_change_refuses_before_any_write_ac_196_4`, `::test_the_triage_prompt_changes_a_priority_through_confirm_set_ac_196_4` | `scripts/cplat/triage_view.py:343` (`--set`), `scripts/cplat/triage.py:204`, `scripts/cplat/triage_act.py:163` (refusal before the first write), `plugins/issue/commands/triage.md:31` | "no spec in an unconfirmed run" depends on the prompt's OK gate, as design.md decided |
| AC-196.5 | met | `test_196_triage_priority.py::test_a_confirmed_priority_replaces_the_one_on_the_issue_when_the_command_acts_ac_196_5`, `::test_two_priority_labels_in_one_apply_are_refused_before_any_github_call_ac_196_5`, `::test_a_class_that_gets_no_priority_leaves_the_existing_priority_label_ac_196_5`, `::test_adding_a_priority_label_removes_every_other_one_in_the_same_edit_ac_196_5` | `scripts/cplat/triage.py:228`, `scripts/cplat/triage.py:234` | the user-approved row change (`priority_decided: true`, 2026-11-17) matches how `confirm --set` writes a confirmed change |
| AC-196.6 | met | `test_196_spec_priority.py::test_a_spec_made_from_a_confirmed_feature_takes_the_confirmed_priority_ac_196_6`; `test_196_triage_priority.py::test_a_confirmed_feature_row_gets_the_matching_label_ac_196_6` | `scripts/cplat/spec.py:1607`, `scripts/cplat/spec_priority.py:79`, `plugins/issue/commands/triage.md:35` (`--priority <P>`) | |
| AC-196.7 | met | `test_196_triage_priority.py::test_a_feature_added_to_a_spec_with_another_priority_names_both_and_the_way_to_change_it_ac_196_7`, `::test_the_json_summary_lists_the_priority_notes_ac_196_7`, `::test_a_spec_with_the_same_priority_adds_no_note_ac_196_7` | `scripts/cplat/triage_act.py:132`, `scripts/cplat/triage_act.py:199` | the test asserts the spec file is unchanged |
| AC-196.8 | met | `test_196_triage_priority.py::test_setup_labels_creates_the_three_priority_labels_and_leaves_existing_ones_ac_196_8`; `test_196_dispatch_order.py::test_the_p1_bug_comes_before_the_older_p2_bug_under_the_default_rules_ac_196_8`, `::test_a_spec_at_p1_comes_before_an_older_numbered_spec_at_p2_ac_196_8`, `::test_the_documented_default_rules_name_label_p0_first_ac_196_8` | `scripts/cplat/triage.py:38` (labels), `scripts/cplat/dispatch_policy.py:36`, `docs/dispatch.md` | |
| AC-196.9 | met | `test_196_dispatch_order.py::test_the_default_priority_rules_are_p0_bug_p1_spec_order_oldest_ac_196_9`, `::test_a_ready_p0_issue_comes_before_an_older_bug_and_the_p1_and_p2_items_ac_196_9`, `::test_a_spec_at_p0_comes_before_an_older_bug_issue_ac_196_9`, `::test_a_repo_that_sets_its_own_priority_rules_is_ordered_by_them_unchanged_ac_196_9`, `::test_prioritize_..._ac_196_9`, `::test_skip_..._ac_196_9` | `scripts/cplat/dispatch_policy.py:36` | the 196 prioritize test does not check that the pin is dropped once the item starts; `tests/cplat/test_167_ready_order.py::test_prioritize_puts_the_item_first_until_it_starts_and_survives_a_restart_ac_167_5` checks this on the unchanged code |
| AC-196.10 | met | `test_196_spec_priority.py::test_a_new_spec_with_no_priority_given_gets_the_fallback_proposal_ac_196_10`, `::test_the_product_manager_proposal_replaces_the_fallback_line_ac_196_10`, `::test_a_user_change_sets_the_priority_and_records_changed_by_you_ac_196_10`, `::test_approving_the_spec_approves_the_shown_priority_ac_196_10`, `::test_show_prints_the_priority_line_after_the_counts_ac_196_10`, `::test_the_spec_commands_propose_show_and_change_the_priority_through_cplat_ac_196_10`, `::test_the_product_manager_replies_with_a_priority_line_ac_196_10` | `scripts/cplat/spec_priority.py:89`, `scripts/cplat/spec_priority.py:113`, `scripts/cplat/spec.py:895`, `scripts/cplat/spec.py:1682`, `plugins/component/commands/spec.md:37`, `plugins/component/commands/spec.md:75`, `plugins/system/commands/spec.md:35`, `plugins/system/commands/spec.md:47`, `plugins/svc/agents/product-manager.md:53` | showing the finish block again is prompt behaviour; only structure tests check it, which is the platform's convention (spec 168) |
| AC-196.11 | met | `test_196_spec_priority.py::test_a_priority_passed_with_the_option_is_given_by_you_ac_196_11`, `::test_the_single_priority_label_of_the_tracked_issue_is_taken_ac_196_11`, `::test_several_priority_labels_take_the_most_urgent_and_mark_the_decision_ac_196_11`, `::test_a_tracked_issue_without_a_priority_label_gets_the_proposal_ac_196_11`, `::test_an_amend_leaves_the_priority_and_its_changelog_line_untouched_ac_196_11`, `::test_the_amend_path_of_the_spec_command_runs_no_priority_step_ac_196_11[component,system]` | `scripts/cplat/spec_priority.py:79`, `scripts/cplat/spec.py:1522`, `scripts/cplat/spec.py:1095` (`set_status` writes no priority), `plugins/component/commands/spec.md:34`, `plugins/component/commands/spec.md:41` (section C has no `spec priority`), `plugins/system/commands/spec.md:38` | cycle 2: the tests now check the `--amend` clause. After `set-status … draft --reason "amend: …"`, the front-matter `priority`, the priority Changelog lines and the priority state are unchanged. Section C of both spec commands holds no `spec priority` call (structure test, marked `# interface:`). If the user types `priority P<n>` at F after an amend, that is the AC-196.10 change choice, not a re-proposal |
| AC-196.12 | met | `test_196_spec_priority.py::test_an_unattended_new_spec_with_no_priority_is_a_proposal_ac_196_12`, `::test_an_unattended_new_spec_records_a_proposal_even_for_a_given_priority_ac_196_12`, `::test_an_unattended_issue_label_is_a_proposal_too_ac_196_12`, `::test_an_unattended_run_may_propose_but_not_change_a_priority_ac_196_12`, `::test_an_approval_by_the_dispatcher_leaves_the_priority_a_proposal_ac_196_12`; `test_196_console_panel.py::test_a_proposed_priority_is_shown_as_a_proposal_not_yet_approved_ac_196_12` and the other three | `scripts/cplat/spec_priority.py:30`, `scripts/cplat/spec_priority.py:132`, `scripts/cplat/spec.py:1195`, `scripts/cplat/console/panels.py:238` | |

## Non-goals

The build adds none of the excluded items:

- no priority per criterion
- no new dispatcher rule kinds (the default list only gains `label:p0`)
- triage does not change an existing spec's priority (AC-196.7 only notes the difference)
- no priority buttons in the console (it shows a read-only line)
- no deadline or severity field
- the spec command files no tracking issue
- `--from-plan` is unchanged (`scripts/cplat/spec.py:1607` is only in the new-spec branch)
- no migration of existing specs

No template-owned layout changed: this is the platform repo and no template was touched. ✔

## Deviations from the plan

- `tests/cplat/test_176_act.py` changed but is in no task's `files` (one row gets `priority_decided=True`). Acceptable: under AC-196.3 the issue's label wins over a row nobody decided, so the old row-over-label test needed the confirmed form.
- `tests/cplat/test_176_view.py`: besides the planned `PLAN` update, the width limit in the assertion went from 80 to 90, and `triage_view.confirm` (`scripts/cplat/triage_view.py:326`) no longer wraps lines. Task t2 said "Change no other assertion", and spec 176's design still says "every line at most 80 columns; a longer summary wraps". Acceptable in substance, because the plan's own `PLAN` lines are longer than 80. But the change is undocumented: record the new width in design.md of 196 (or 176), because a long reason (`P0: blocks all other work` plus the decide suffix) now has no width limit.
- To keep the prompts within their size limit, the build deleted unrelated sentences:
  - `/issue:triage`: "An engine row may omit the class"
  - `/component:spec`: "the user may still insist", "print its note" (after `spec publish`), "The user stops answering → the spec stays `draft`", "(merges the PR on green CI)"
  - `/system:spec`: "Remaining questions stay in the spec and block approval", "and say its plan needs redoing", "the user can type their own"
  - product-manager: "Keep criteria user-facing" and the fold-mode hand-back sentence

  Acceptable under spec 168's size cap, since none of them was a register entry.
- Follow-up, not NOT MET: two of the deleted sentences change behaviour: "An engine row may omit the class" (`/issue:triage`) and "print its note" (`/component:spec`, after `spec publish`). Restore them and shorten other wording to stay within the size limit.
- Follow-up, not NOT MET: `spec_priority.APPROVED` (`scripts/cplat/spec_priority.py:18`) does not match the approval line `approved; the old plan is <path>`, which `spec approve` writes when it sets a plan aside (`scripts/cplat/spec.py:1069`). Such an approval leaves the priority `proposed`. design.md names only `approved` and `approved by <x>`. Acceptable for now, since this is rare for a new spec; file a follow-up.
- `tests/cplat/test_196_spec_priority.py` (cycle 2, 17736cf): two AC-196.11 tests were added. The file is in no task's `files` under this name (the plan names `tests/cplat/test_spec_priority.py`). Acceptable: it is the frozen acceptance test file, tightened by the orchestrator.
- These files came from merges of `main` (#809, #817, #818, #820), not from this build: `scripts/cplat/ship.py`, `appship.py`, `scripts/e2e-scope.py`, `docs/backlog.md`, specs 126/167/204–210 and their tests, changelog fragments 784/814/815. Acceptable.
- All tasks are `done: true`.

## Contract

Matches design.md in each part:

- the `priority.py` API and the batch's `priority_levels`
- the row rules and errors, and the `confirm` text and JSON lines
- the `confirm --set` errors and the `apply` refusals
- `act`'s `priority_notes` and its text section
- the `spec new` resolution table and its stderr note
- the `spec priority` outputs and refusals
- the `show` and `list --json` fields
- the console's `data-priority` line
- the dispatcher default

One gap: the approval line with a set-aside plan (see Deviations). ✔

## Tightened acceptance tests

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_196_spec_priority.py` | AC-196.11: no test checked the `--amend` clause (cycle 1 TEST LOOSER); 17736cf adds two tests | yes. The amend's cplat step (`set-status … draft`) leaves `priority`, its Changelog lines and its state unchanged. Section C of `/component:spec` and `/system:spec` has no `spec priority` call. So the priority is neither proposed again nor changed |

## Test run

`devbox run test-fast`: 11384 passed, 1 failed. The failure is `tests/cplat/test_platform_shape_123.py::test_ac_123_16_existing_specs_keep_passing_with_the_shape_declared`, a 120 s pytest timeout under load. It passes when run alone and touches no 196 code. `tests/cplat/test_196_spec_priority.py`: 35 passed.

RESULT: pass
NOT MET: none

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
