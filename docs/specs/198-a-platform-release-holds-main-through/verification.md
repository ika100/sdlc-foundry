# Verification — 198 A platform release holds main through the merge lock

**Result:** pass
**Commit:** fa5c71d1 · **Base:** e642dd43 · **Trace:** 9/9 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-198.1 | met | `tests/cplat/test_198_release_cmd.py::test_the_release_sets_its_hold_before_its_first_check_ac_198_1`, `::test_a_dry_run_sets_no_hold_ac_198_1`, `::test_the_release_first_waits_for_a_merge_inside_the_lock_ac_198_1`; `tests/cplat/test_198_merge_hold.py::test_the_release_waits_for_a_merge_inside_the_lock_to_end_first_ac_198_1`; `tests/cplat/test_198_release_hold.py::test_claim_records_version_start_time_and_own_process_ac_198_1` | `scripts/cplat/platrelease.py:245-246`, `scripts/cplat/merge_lock.py:108-134`, `scripts/cplat/release_hold.py:154-167` | the hold records version, `since`, pid; exact set and waiting lines asserted; the `needs-major` version detection runs before the hold (see deviations) |
| AC-198.2 | met | `test_198_merge_hold.py::test_a_merge_does_not_merge_while_another_process_holds_the_repo_ac_198_2`, `::test_the_wait_for_a_hold_does_not_count_against_the_timeout_ac_198_2`, `::test_a_merge_waits_outside_the_merge_lock_so_the_release_can_merge_ac_198_2`, `::test_a_busy_lock_after_the_hold_still_ends_as_busy_ac_198_2`; `test_198_release_hold.py::test_the_wait_says_what_it_waits_for_at_once_and_every_60_seconds_ac_198_2` | `scripts/cplat/merge_lock.py:94-99`, `scripts/cplat/release_hold.py:215-234` | waiting line at 0/60/120 s asserted verbatim; an hour of hold wait with a 30 s timeout ends without `Busy`; every cplat merge enters `held()` (`pr.py:90,120`, `ship.py:1277,1375`) |
| AC-198.3 | met | `test_198_merge_hold.py::test_a_cleared_hold_lets_the_merge_continue_within_30_seconds_ac_198_3`, `::test_a_land_waits_for_the_hold_then_merges_as_without_it_ac_198_3`, `::test_a_pr_wait_merge_waits_then_brings_a_branch_that_fell_behind_up_to_date_ac_198_3`; `test_198_release_hold.py::test_a_hold_that_expires_ends_the_wait_with_the_expired_line_ac_198_3` | `scripts/cplat/release_hold.py:220-231` (5 s poll), `scripts/cplat/merge_lock.py:97-99` | `cleared`/`expired` lines asserted; behind branch is updated (`pr update-branch`), checks rerun, then merged |
| AC-198.4 | met | `test_198_release_cmd.py::test_the_release_merges_its_own_pull_request_through_its_own_hold_ac_198_4`; `test_198_merge_hold.py::test_the_merge_of_the_holding_process_is_not_held_ac_198_4`; `test_198_release_hold.py::test_foreign_is_none_for_the_own_hold_and_the_hold_of_another_process_ac_198_4` | `scripts/cplat/release_hold.py:196-198` | |
| AC-198.5 | met | `test_198_release_cmd.py::test_the_hold_is_cleared_right_after_the_tag_is_pushed_ac_198_5`, `::test_the_hold_is_cleared_when_the_release_ends_in_an_error_ac_198_5`, `::test_the_hold_is_cleared_when_the_release_is_interrupted_ac_198_5`; `test_198_release_hold.py::test_release_removes_an_own_running_hold_only_ac_198_5` | `scripts/cplat/platrelease.py:247-251`, `scripts/cplat/platrelease_publish.py:184-185` | `release hold cleared` and file gone asserted for tag, error, Ctrl-C |
| AC-198.6 | met | `test_198_release_cmd.py::test_the_merge_stop_keeps_the_hold_for_two_hours_and_names_the_expiry_ac_198_6`, `::test_the_tag_stop_keeps_the_hold_for_two_hours_and_names_the_expiry_ac_198_6`, `::test_a_later_run_takes_the_stopped_hold_over_ties_it_to_itself_and_lifts_the_expiry_ac_198_6[with-confirm,without-confirm]`, `::test_a_run_over_an_expired_stop_sets_a_new_hold_ac_198_6`; `test_198_merge_hold.py::test_a_stopped_hold_keeps_merges_waiting_until_it_expires_ac_198_6`; `test_198_release_hold.py::test_a_later_run_takes_over_a_stopped_hold_and_lifts_the_expiry_ac_198_6` | `scripts/cplat/platrelease.py:183-186`, `scripts/cplat/platrelease_publish.py:109-120`, `scripts/cplat/release_hold.py:159-162,170-177` | expiry 2 h after stop asserted (`12:20`); the without-confirm run asserts only the take-over line, the pid/expiry part is covered by the with-confirm case and the unit test |
| AC-198.7 | met | `test_198_release_cmd.py::test_a_second_release_while_the_first_runs_stops_with_an_error_and_changes_nothing_ac_198_7`, `::test_a_release_over_a_hold_whose_process_was_killed_drops_it_and_goes_on_ac_198_7`; `test_198_merge_hold.py::test_a_merge_drops_a_hold_whose_process_is_gone_and_goes_on_ac_198_7`, `::test_a_second_release_is_refused_before_anything_else_ac_198_7`; `test_198_release_hold.py::test_a_hold_whose_process_dies_ends_the_wait_with_the_dropped_line_ac_198_7` | `scripts/cplat/release_hold.py:67-72,109-118,133-142,157-158` | error names version and pid; repo snapshot and hold file unchanged |
| AC-198.8 | met | `tests/cplat/test_198_hold_cmd.py::test_without_a_hold_it_says_so_ac_198_8`, `::test_a_running_hold_is_printed_with_version_since_process_and_state_ac_198_8`, `::test_a_hold_at_a_stop_is_printed_with_its_expiry_ac_198_8`, `::test_json_prints_the_same_as_one_object_or_null_ac_198_8`, `::test_clear_removes_the_hold_and_says_so_ac_198_8`, `::test_a_waiting_merge_continues_when_the_hold_is_cleared_by_hand_ac_198_8` | `scripts/cplat/holdcmd.py:28-47`, `scripts/cplat/cplat.py:95`, `scripts/cplat/release_hold.py:125-130,237-241` | full output strings asserted through `cplat.main` |
| AC-198.9 | met | `test_198_hold_cmd.py::test_status_shows_a_running_release_hold_as_its_second_line_ac_198_9`, `::test_status_shows_a_hold_at_a_stop_with_its_expiry_ac_198_9`, `::test_status_without_a_hold_has_no_line_and_a_null_object_ac_198_9` | `scripts/cplat/dispatch_view.py:175,178-183,191-192`; `scripts/cplat/dispatch.py:139-140` prints that document for `--json` | tests call `status_doc`/`render_status`, the functions `cplat dispatch status` prints |

## Non-goals

No code covers merges outside cplat, release branches, stopping the dispatcher from starting or opening PRs, or holds for
component/system releases: only `platrelease.main` sets a hold. No template layout changes. ✔

## Deviations from the plan

- `scripts/cplat/cplat.py:153-156`: the noun usage no longer prints one `cplat <noun> <verb>` line per verb (only the header
  `(verbs: ...)` list), for every noun. The file is in t4's `files`; the commit says the 12-verb `platform` noun would
  otherwise exceed the usage limit. Acceptable: the verbs are still listed, the CI is green. Still, it changes output
  for every noun, not only `platform`, and the spec does not ask for it. Mention it in the PR.
- AC-198.1 "before the first check": `release-check.py needs-major` (version detection in `platrelease_state.detect`)
  runs before the hold, and the tests leave it out on purpose. Acceptable: the design records it (the hold must record
  the version, which is known only after detection), and it changes nothing in the repo.
- Test files (`tests/cplat/test_198_*.py`, `hold_world_198.py`) are in no task's `files`: they are the acceptance tests from the red commit. Acceptable.
- `docs/CHANGELOG.md` and the removed fragments 750/782/787 come from the main release commit `8c10675d` in the range, not from this feature.
- Every task has `done: true`.

## Contract

Matches `design.md`: file path and JSON shape, `release_hold` API and constants (`HOLD_POLL` 5, `WAIT_LINE_EVERY` 60,
`STOP_TTL` 2 h), every line in the table of lines, `held()` waits outside the lock with `begin += waited`,
`set_release_hold` claims first and then waits for the lock, `platrelease.main` order with `plugin_mismatches` moved into
`_run` after the hold. ✔

## Unresolved test-review findings

None. The review commit `7807bb62` records `findings: 3` but no unresolved lines. Commit `cd8e5b84` resolved them before the freeze.

## Observations (no verdict change)

- `test_198_hold_cmd.py::test_a_usage_error_exits_2_ac_198_8` would also pass without the feature, because an unknown
  `platform` verb already exits 2. It is in the trace, and the other AC-198.8 tests prove the command.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
