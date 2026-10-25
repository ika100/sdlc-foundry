# Verification — 102 Runs stay within a budget and stop repeating failures

**Result:** pass
**Commit:** 12b81a2 (fixes in d35a3dc, 12b81a2) · **Base:** 6471a0a (merge base with origin/main) · **Trace:** 12/12 criteria named by tests (`tests/cplat/test_budget.py`, 55 tests); full suite green as reported (2186 passed)
**Cycle:** 2. Cycle 1 (e61adab) was `fail`: AC-102.9 not met; AC-102.1, .4, .5, .7 and .10 partial.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-102.1 | met | `test_budget.py::test_a_ship_starts_with_the_default_limits_and_shows_all_four`, `::test_budget_options_replace_limits_and_off_is_shown_as_off`, `::test_a_cost_limit_that_is_off_never_stops_the_run`, `::test_a_build_started_by_hand_takes_budget_options`, `::test_headless_multiplies_the_ship_defaults_by_the_specs_in_the_prompt`, `::test_headless_budget_option_applies_after_multiplying`, `::test_a_product_ship_shares_its_budget_with_the_repo_ships`, `::test_headless_and_runs_begin_print_the_limits_at_start` | `scripts/cplat/budget.py:40`, `:54-75`; limits line in `headless.py:187`, `runs.py:967`, `ship.py:1271`, `appship.py:269` | cycle-1 gap fixed: headless and `runs begin` now print the four limits |
| AC-102.2 | met | `::test_a_ship_under_headless_uses_the_headless_ledger`, `::test_a_build_attached_to_a_ship_opens_no_ledger`, `::test_budget_of_a_child_run_is_found_through_its_parent`, `::test_a_product_ship_shares_its_budget_with_the_repo_ships` | `budget.py` `root_of`, `find`, and `open_root` (a child opens nothing) | |
| AC-102.3 | met | `::test_the_check_returns_the_exhausted_limit`, `::test_cost_over_the_limit_is_the_exhausted_limit`, `::test_ci_reruns_are_counted_and_refused_when_used_up`, `::test_a_refused_ci_rerun_ends_the_wait_red_and_escalates_the_ship`, `::test_the_gate_hook_exits_2_*`, `::test_subagents_count_as_invocations`, `::test_the_gate_outside_a_run_allows`, `::test_the_pre_tool_use_hook_gates_task_and_agent`, `::test_the_hook_blocks_only_on_a_real_refusal`, `::test_headless_starts_no_session_after_the_budget_is_used_up` | `plugins/shared/hooks/hooks.json:22` (blocks only on exit 2 with `budget exhausted`), `headless.py:240-249`, `ship.py:270-273`, CI reruns in `ship.py` `CheckWatch`/`RunWatch`, `appship_sched.py:136-139` | the cycle-1 hook risk is fixed: an exit 2 from an unknown command, `uv` or argparse no longer blocks a subagent. The test runs the real hook command against fake `cplat` binaries. |
| AC-102.4 | met | `::test_a_ship_stopped_by_the_budget_is_escalated_with_the_decision_cause`, `::test_the_record_holds_the_budget_section`, `::test_a_headless_budget_stop_is_an_escalation_with_the_decision_cause` | `budget.py` `stop`/`section`; `headless.py:200` (`escalation` with cause decision); `ship.py` `budget_stop` | cycle-1 gap fixed |
| AC-102.5 | met | `::test_an_incomplete_cost_is_shown_as_unknown_not_zero`, `::test_an_unknown_cost_cannot_stop_a_run_but_time_still_does`, `::test_the_record_of_an_unknown_cost_says_unknown`, `::test_unreadable_usage_is_an_unknown_cost_never_zero` | `budget.py:267-278` (no `totals` → `unknown`), `:427` (`on_finish` starts from `unknown`) | cycle-1 gap fixed. A record that never registered a usage claim now also counts as `unknown`, which is the safe side. |
| AC-102.6 | met | `::test_a_resumed_run_continues_usage_and_notes_a_changed_limit`, `::test_idle_time_between_a_stop_and_the_resume_is_not_counted`, `::test_a_budget_stopped_ship_restarted_through_headless_continues_the_same_ledger` | `budget.py:200-213` (`_fold_previous`), `open_root` (continue, `changes`) | |
| AC-102.7 | met | `::test_headless_starts_no_session_after_the_budget_is_used_up`, `::test_max_runs_still_stops_headless_under_a_budget`, `::test_a_budget_result_line_maps_to_the_budget_stop_reason`, `::test_a_budget_stopped_ship_restarted_through_headless_continues_the_same_ledger` | `budget.py:96-106` (`work_key`), used at `headless.py:186`, `ship.py:190`, `runs.py:917`, `appship_state.py:184` | cycle-1 gap fixed: one key per repo and resolved spec id(s). A headless prompt with several specs gets its own key (`a+b`, the multiplied budget). This is different work, so it is acceptable. |
| AC-102.8 | met | `::test_the_record_holds_the_budget_section` (`gates == not run`), `::test_a_refused_ci_rerun_ends_the_wait_red_and_escalates_the_ship` | `runs.finish` gate fill (unchanged); a refused rerun keeps the check failed | a refused CI check is reported red, never as passed |
| AC-102.9 | met | `::test_three_equivalent_failures_without_progress_stop_the_run` (now stops on the 2nd), `::test_progress_starts_the_count_again`, `::test_failures_that_are_not_equivalent_do_not_stop_the_run`, `::test_the_attempt_command_exits_3_and_escalates_with_the_reason` (`[0, 3]`), `::test_the_attempt_command_reads_the_error_from_a_file_and_names_progress`, `::test_durations_do_not_make_failures_differ` | `budget.py:43` (`STOP_AFTER = 2`), `:535-538` | cycle-1 `not met` fixed. Four test changes are marked with a comment; each moves the boundary to the spec's "2 in a row, the third attempt is not made". The two progress tests now use counts that fall every time, so they still prove "progress resets the count" and do not weaken it. One test name still says "three" (cosmetic). |
| AC-102.10 | met | `::test_the_snapshot_holds_stage_excerpt_files_criteria_and_attempts`, `::test_the_snapshot_redacts_secrets`, `::test_an_escalation_writes_a_snapshot_that_never_reaches_the_run_record`, `::test_runs_end_escalated_writes_a_snapshot`, `::test_an_app_ship_escalation_writes_a_snapshot`, `::test_headless_stops_write_a_snapshot` | `budget.py` `snapshot`; writers in `ship.py:326`, `runs.py:933` (end escalated), `appship_state.py:266`, `headless.py:246`, `:274` | the cycle-1 gap is fixed for escalations and headless stops. `runs end --outcome failed` writes none, which is acceptable (a hard failure, not a stage the run can resume at). |
| AC-102.11 | met | `::test_a_passed_stage_on_the_same_head_and_inputs_is_skipped`, `::test_a_new_commit_makes_a_passed_stage_stale`, `::test_changed_inputs_make_a_passed_stage_run_again`, `::test_runs_gate_records_a_verified_stage`, `::test_resume_starts_with_the_snapshot_and_the_failing_stage` | `budget.py` `decisions`, `_resume`; `plugins/svc/references/build-resume.md:8`, `plugins/svc/commands/build.md:109` | the resume step is in build only, and `ship.md` has none. Acceptable, because ship resumes through build. Snapshots from `runs end` and headless use the stage names `end` and `headless`, which are not in `STAGES`; resume still prints their excerpt first. |
| AC-102.12 | met | `::test_a_failed_stage_runs_again`, `::test_a_skipped_stage_is_never_read_as_a_pass`, `::test_an_unreadable_stage_result_runs_again`, `::test_nothing_is_skipped_without_any_recorded_result` | `budget.py` `decisions` (only `passed` with the same HEAD and inputs is `skip`) | |

## Normalisation as implemented (`budget.py:494-511`; spec 108 depends on it)

The text is the last 40 lines of the error. The steps run in this order:

1. ISO timestamps `YYYY-MM-DD[T ]HH:MM:SS[.frac][Z|±HH[:]MM]` are removed. A bare date stays.
2. Clock times `H:MM:SS[.frac]` are removed. `HH:MM` stays.
3. Durations `\b\d+(\.\d+)? ?(ms|s|m)\b` are removed (new in cycle 2).
4. UUIDs become `<id>`.
5. Paths with at least one `/` become `<path>`. A bare file name stays.
6. Lowercase hex runs of 7 or more characters with at least one digit become `<id>`. Uppercase and letter-only hex are not matched; any decimal number of 7 or more digits is.
7. `line N` becomes `line`.
8. `:N` or `:N:M` after a word character or `>` is removed.
9. Whitespace is collapsed.

Equivalent means the same stage and the same `sha1(normalised)[:12]`. Progress means the failing count went down, or a name in the previous failing set is gone.

design.md (12b81a2) now names durations and "the last 2". It still does not say that bare dates, `HH:MM` and uppercase hex are kept. Spec 108 should take this list, not the design text.

## Non-goals

No context pruning, no new price or usage measurement (only `peek`), no per-stage limits, no benchmark, no service or new agent. The 3-fix-round and two-idle-session stops are unchanged. ✔ The two non-goal lines added to `spec.md` are the coordinator's, and the user is told about them separately; they are not counted against the build.

## Deviations from the plan

- `scripts/cplat/appship_state.py`, `docs/adr/043-*.md` and `tests/cplat/conftest.py` (clears `CLAUDE_CODE_SESSION_ID`) are outside every task's `files`. All three are acceptable.
- No plugin version bump yet. Acceptable under the repo's release-commit practice, but the `PreToolUse` hook and the `build.md` change must be in the next release.
- The coder's deviations from cycle 1 are still accepted: (1) under headless the cost is read from the headless run only, (2) `gate` refuses and the next code safe point escalates, (3) `allow_rerun` checks only reruns, (4) `on_finish` runs from `runs.finish`.
- New in cycle 2: a root counts one invocation for its own session only when `CLAUDE_CODE_SESSION_ID` is set and the run is not headless (`budget.py:237`). Acceptable. If Claude Code does not export that variable to the Bash tool, the interactive root session is not counted: one invocation too few, never a block.

## Contract

Matches `design.md` as updated in 12b81a2: the CLI, `--budget` on the four roots, the ledger (key = `work_key`, `stop.at` added), the record section, and stopping after 2. ✔

## Remaining risks (no criterion)

- A ship resumed with the same `run_id` after an interruption without a stop (session closed, state kept) keeps `current.started_at`. Wall-clock minutes then include the idle gap. Only a stop folds and restarts the clock (`_fold_previous`).
- Ledgers stay open until a `done` tree, and `budgets/` is never pruned.
