# Verification — 194 A system ship wait returns before the Bash limit

**Result:** pass
**Commit:** cfcd878a · **Base:** cebb9360 · **Trace:** 4/4 criteria named by tests (`tests/cplat/test_194_system_ship_wait.py`)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-194.1 | met | `test_a_wait_with_constant_progress_ends_at_its_timeout_ac_194_1`, `test_the_default_timeout_bounds_the_call_at_550_seconds_ac_194_1`, `test_a_wait_without_progress_ends_within_its_timeout_plus_ten_ac_194_1`, `test_a_repo_that_ends_is_recorded_at_the_first_poll_after_its_result_ac_194_1` | `scripts/cplat/shipwait.py:96` (`begin` set once, never reset), `:120`/`:126` (progress only sets a flag), `:128-131` (ended repo recorded, poll again), `:139` (`min(interval, left)` sleep) | Tests assert `T <= slept <= T+10` with constant progress and without, `540..550` for the default, and an ended repo recorded at slept 40, not at the deadline. `PROGRESS_CAP` removed. |
| AC-194.2 | met | `test_progress_then_timeout_prints_the_wait_action_and_one_wait_line_ac_194_2`, `test_with_json_stdout_holds_only_the_wait_action_and_stderr_the_wait_line_ac_194_2`, `test_the_wait_line_names_the_timeout_as_a_whole_number_ac_194_2`, `test_a_new_commit_in_the_clone_is_progress_ac_194_2`, `test_a_session_started_again_is_progress_ac_194_2` | `scripts/cplat/shipwait.py:134-135` (returns `REACHED`, the wait action, the exact `WAIT:` line), `scripts/cplat/appship.py:364-366` (action, then line to stdout / stderr with `--json`), `:369` (result `progress`), `scripts/cplat/waits.py:145` | Tests check the exact line, that it appears once and last, that the preceding lines equal plain `next` output, that `--json` stdout parses to the same JSON as `next --json` with the line on stderr, and exit 0. All three progress sources (phase, commit, AC-155.5 restart) are covered. |
| AC-194.3 | met | `test_no_progress_for_the_whole_call_keeps_the_timeout_lines_and_exit_2_ac_194_3`, `test_progress_before_the_end_of_the_call_is_not_a_timeout_ac_194_3` | `scripts/cplat/shipwait.py:136-138` | Exact `TIMEOUT:` line with `running: shop-api (build)`, followed by `run the same…`, exit 2, no `WAIT:` line. |
| AC-194.4 | met | `test_the_system_ship_prompt_runs_a_wait_again_and_escalates_after_three_timeouts_in_a_row_ac_194_4`, `test_the_changed_rule_has_a_register_entry_quoting_the_prompt_ac_194_4`, `test_the_rule_register_checks_and_the_prompt_stays_within_its_size_ac_194_4` | `plugins/system/commands/ship.md:41`, `docs/rules/plugins/system/commands/ship.yml:48` (R15, practice, spec 194) | The prompt test checks structure (spec 168): `WAIT:`, `TIMEOUT:`, "three … in a row", `--cause environment`, and that "at most twice" is gone. The register entry quotes the prompt verbatim, and `rulescheck.check` (which includes the size check) passes. The "a `WAIT:` resets the count" part is covered by "in a row" and by the prompt wording. It is not pinned further, because spec 168 forbids pinning prompt wording in tests. |

## Non-goals

`component ship wait`, `system ship land` and the other waits are unchanged (the `land` bullet in `ship.md` keeps "at most twice"; `ship_wait` in `shipwait.py` is untouched). `--timeout` has no cap. The reached/answer/start/escalate path is unchanged (`shipwait.py` returns early when the action is not `wait`). No template-owned layout was changed. ✔

## Deviations from the plan

- `tests/cplat/test_194_system_ship_wait.py` is in no task's `files`. It is the frozen acceptance test, so this is acceptable.
- `docs/specs/148-transient-errors-never-stop-a-run/spec.md` is in no task's `files`. It strikes out AC-148.7 as superseded by AC-194.1, as the spec's "(replaces AC-148.7)" requires. Acceptable.
- The changelog fragment ends `(#194)`, and the plan asks for the PR number. This is minor: fix it before the PR if the PR number differs (`cplat platform pr-check` checks it).
- All tasks are `done: true`. The contract matches `design.md`: signature `(code, action|None, lines)`, the progress result `(0, wait action, [WAIT line])`, `<T>` = `int(T)`, and a repo first seen mid-call sets its baseline only (`marks.get(rid) is None`).

## Contract

Matches `design.md`. ✔

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
