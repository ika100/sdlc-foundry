# Verification — 193 Building and releasing run on their own and interrupt only to ask

**Result:** pass
**Commit:** ec23f7f8 · **Base:** e642dd43 · **Trace:** 8/8 criteria named by tests

Scope: only spec 193's criteria and non-goals. The branch also has commits from specs 190 and 198 and from #790/#791
(`staging.py`, `promote.py`, `platrelease*.py`, `release_hold.py`, `merge_lock.py`, `envlimit.py`, `holdcmd.py`, `spec.py`,
`runs.py`, `cplat.py`). Those are not judged here.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-193.1 | met | `tests/cplat/test_193_queue.py::test_queue_is_numbered_in_plan_order_with_what_you_get`, `::test_estimates_only_from_three_comparable_runs`, `::test_two_comparable_runs_give_no_estimate_and_no_total`, `::test_only_runs_of_the_same_kind_are_comparable_and_a_total_needs_every_entry`, `::test_tokens_today_line_and_the_need_only_when_known`, `::test_build_question_choices_and_steps`, `::test_not_now_starts_nothing_and_the_queue_stays_a_waiting_item`; `tests/cplat/test_193_verbs.py::test_the_build_starts_that_many_items_at_once`, `::test_start_detach_spawns_the_loop_in_its_own_session` | `scripts/cplat/dispatch_cycle.py:330` (preview), `scripts/cplat/nextbuild.py:110` (median of 3 or more comparable runs), `scripts/cplat/nextbuildscreen.py:90`, `scripts/cplat/nextbuildquestions.py:96`, `scripts/cplat/dispatch.py:160` | The tests check the order and the "about N min" estimates. They check that the total and the need appear only when every entry has 3 runs. They also check the exact `Tokens today` line, the labels Two/One/Not now, and that 2 or 1 items really start at once. |
| AC-193.2 | met | `tests/cplat/test_193_queue.py::test_without_policy_the_screen_offers_set_up_not_a_guide`, `::test_set_up_details_print_the_exact_file`, `::test_without_usage_the_set_up_asks_for_the_number_and_recommends_none`, `::test_not_now_without_a_policy_writes_nothing`; `tests/cplat/test_193_verbs.py::test_setup_commits_the_file_through_a_pull_request_that_merges_on_green_ci`, `::test_setup_does_not_merge_a_red_pull_request` | `scripts/cplat/dispatch_setup.py:61`, `:68`, `:72`; `scripts/cplat/nextbuildquestions.py:100-109` | The exact file text is asserted. A PR is created and merged only on green CI, and a red PR stays unmerged. After the step, `how` re-runs `cplat next` (`scripts/cplat/nextcmd.py:53-55`), which then shows the queue of AC-193.1. |
| AC-193.3 | met | `tests/cplat/test_193_progress.py::test_one_line_per_event_with_the_local_time`, `::test_head_line_and_running_items`, `::test_the_screen_prints_no_agent_output`, `::test_build_choices`, `::test_watching_changes_nothing` | `scripts/cplat/nextbuildscreen.py:131`, `:145`; `scripts/cplat/nextbuildquestions.py:122` | The tests assert the exact `HH:MM started/merged (PR #m)/finished` lines, the `Building now` block, and the three choices with their steps. |
| AC-193.4 | met | `tests/cplat/test_193_stops.py::test_decision_stop_lines_and_the_other_items`, `::test_the_age_appears_from_five_minutes`, `::test_decision_choices_put_the_recommended_answer_first`, `::test_stopping_an_item_parks_it_and_leaves_the_branch`; `tests/cplat/test_193_answer.py::test_the_answer_is_an_amendment_that_quotes_it_and_approves_when_only_the_asked_point_is_added`, `::test_the_answered_item_goes_on_from_the_phase_where_it_stopped`, `::test_the_item_goes_on_after_the_answer`, `::test_an_answer_that_changes_a_criterion_sends_the_spec_back_to_approval` | `scripts/cplat/nextbuildscreen.py:175`, `scripts/cplat/nextbuildquestions.py:182`, `scripts/cplat/dispatch_answer.py:99`, `:110`, `:127-130`; resume from the kept state in `scripts/cplat/ship.py:246-256` | Cycle 2: the fake escalation now leaves ship state with phase `build` in the worktree's git dir (`tests/cplat/dispatch_world.py:134-135`). The answer test asserts exactly `it goes on from build`, so the old `the start` output now fails. The new test checks that the next start runs `spec-007.2` in the same kept worktree and sees ship phase `build`. `ship.py` resumes from that phase (spec 087). The screen lines, the age, the options, the amendment text, the approval Changelog line, back to draft and parked stay asserted. |
| AC-193.5 | met | `tests/cplat/test_193_stops.py::test_failure_screen_says_what_happened_and_what_was_tried`, `::test_failure_tried_list_names_a_rerun_check_and_a_restarted_landing`, `::test_failure_choices`, `::test_show_the_log_prints_the_log_path_and_leaves_out_its_own_option`, `::test_budget_screen_and_choices`, `::test_raise_confirmation_shows_the_use_and_the_need`, `::test_a_number_that_is_not_above_the_limit_is_not_offered`; `tests/cplat/test_193_verbs.py::test_raising_the_budget_is_local_state_with_an_undo_and_changes_no_file`, `::test_a_raise_of_an_earlier_day_is_ignored`, `::test_a_raised_budget_lets_the_dispatcher_start_again` | `scripts/cplat/nextbuildquestions.py:160`, `:203`; `scripts/cplat/nextbuildscreen.py:204`; `scripts/cplat/dispatch_state.py:290`, `:299`; `scripts/cplat/dispatch_budget.py:180`; `scripts/cplat/dispatch.py:190` | The tests check the `Already tried` texts, both choice sets, the log path, and the second confirmation with today's use and the need. They also check `Undo:`, that the policy file and `git status` stay unchanged, and that the raise lasts for today only. |
| AC-193.6 | met | `tests/cplat/test_193_release.py::test_end_of_build_prints_the_totals_from_the_records`, `::test_a_value_that_cannot_be_read_is_left_out`, `::test_ready_to_release_lists_the_fragment_summaries_by_section`, `::test_the_release_step_follows_as_the_next_choice`, `::test_a_component_repo_reads_the_merged_titles_since_the_last_tag` | `scripts/cplat/nextbuild.py:421`, `scripts/cplat/nextbuildscreen.py:231`, `:254`, `scripts/cplat/nextstate.py:196` | Exact values are asserted (3 h 10 min, 12,400,000 tokens, 2 questions), and so are the bold fragment summaries by section. |
| AC-193.7 | met | `tests/cplat/test_193_release.py::test_release_choice_in_the_platform_repo`, `::test_collect_more_leaves_the_release_as_a_waiting_item`, `::test_manual_staging_is_promoted_before_the_release`, `::test_after_staging_runs_the_head_the_release_is_offered`, `::test_a_staging_that_moves_after_the_dev_smoke_is_never_a_step`, `::test_a_released_head_in_staging_is_offered_for_prod`, `::test_the_prod_promotion_item_offers_promote_to_prod_and_not_now` | `scripts/cplat/nextstate.py:210`, `:215`; `scripts/cplat/nextbuild.py:273-305` | The tests check the order Staging, then release, then Prod, and the `/platform:release`, `/component:release` and `/instance:promote` steps. |
| AC-193.8 | met | `tests/cplat/test_193_release.py::test_last_screen_lines`, `::test_last_screen_with_nothing_closed_and_nothing_parked`, `::test_last_screen_leaves_out_an_unreadable_time`, `::test_the_last_screen_has_no_questions_and_the_flow_document`, `::test_the_flow_is_not_done_while_something_waits` | `scripts/cplat/nextbuild.py:440`, `scripts/cplat/nextbuildscreen.py:278-289` | Every line is asserted exactly and in order. |

## Non-goals

- No console UI code. ✔
- No new scheduling. `dispatch_cycle.preview` only reads and reuses `_judge` and the ship-busy rule. `build` only sets the existing
  slot count. ✔
- Gates, CI, merge rules, release checks and promote checks: spec 193's commits change none of them (`ship.py` now also stores the
  question options, nothing else). The changes to release and promote modules on this branch come from #790/#791 and specs 190/198. ✔
- Triage screen, entry point, bar and screen rules of spec 192: not changed. ✔
- No new notification channels or kinds. ✔ No streaming agent output (`test_the_screen_prints_no_agent_output`). ✔
- No changes to template-owned layout (header, footer, navigation): spec 193 touches no `templates/` or `site/` file. ✔

## Deviations from the plan

- t9: `docs/rules/plugins/platform/commands/next.yml` is unchanged. The `judge_items` sentence was appended to the existing
  judgement rule in `plugins/platform/commands/next.md:11` instead of getting its own `R<n>` entry. This is acceptable because
  `cplat platform rules check` passes in the Phase 3 run. The prompt size was rebaselined in `docs/rules/register.yml` after
  benchmark runs, as the human step asks.
- t10: the ADR is `docs/adr/118-a-days-budget-raise-lives-in-local-state.md`, renumbered 116 to 117 to 118 because of clashes with
  other branches. Acceptable.
- `tests/cplat/test_186_system_ship.py` and `tests/cplat/test_ship_questions.py` are in no task's `files`. They were updated for
  the new `options` key from t3's `ship.escalate` change. Acceptable: assertions were added and none were relaxed.
- `tests/cplat/waiting.py` is in no task's `files`. It is a test helper (`poll_pause`) for the detach test. Acceptable.
- `scripts/cplat/ship.py` (t3) changed only in `escalate`. Plan t3's check that a resumed unit continues from its phase is now
  covered by `test_the_answered_item_goes_on_from_the_phase_where_it_stopped` (commit ec23f7f8). Acceptable.
- All tasks are `done: true`.

## Contract

The tests read the keys of `design.md`: `build` (`queue`, `total_minutes`, `need_tokens`, `tokens`, `loop`, `current`, `events`,
`running`, `ended`, `totals`, `flow`, `deploy`), `judge_items`, `input`, `other`, and the `cplat dispatch` verbs with their texts.
They match the design. ✔

## Tightened acceptance tests

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_193_answer.py` | AC-193.4: the answered item must continue from the phase where it stopped. The old test matched any word (`\S+`). | Yes: it asserts exactly `it goes on from build`, and a new test checks that the next run starts in the kept worktree with ship phase `build`. |
| `tests/cplat/dispatch_world.py` | Helper for the same AC-193.4 tightening: the fake escalation writes ship state with a phase, and each call records the `ship_phase` it sees. | Yes (helper). The 17 other users of the helper pass (291 tests, as reported). |

## Test changes after the red commit

- `tests/cplat/test_193_verbs.py::test_start_detach_spawns_the_loop_in_its_own_session` now patches `dispatch.sleep` with
  `poll_pause`. The user approved this change, and no assertion changed.
- Commit ec23f7f8 tightened AC-193.4 (see above).

## Notes

- Phase 3: `cplat spec check` is OK. Local CI was red only because of a pytest timeout (>120 s) in `test_platform_shape_123.py`
  under a machine load of about 110. That test is outside spec 193 and passes when run alone, so it does not count against this verdict.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
