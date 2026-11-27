# Verification — 220 A docs-only land does not wait for a code PR's catch-up e2e

**Commit:** 707b135c · **Base:** 3246a312 (`c0d3508~1`) · **Trace:** 10/10 criteria named by tests, none missing

Test files: `F` = `tests/cplat/test_220_docs_fast_lane.py` (scenarios driven through `pr._watch` with the fakes in
`tests/cplat/land220_world.py`), `R` = `tests/cplat/test_220_lands_report.py`. Phase 3: test-fast green (5681 passed,
1 skipped), local CI green, `spec test-diff`: no acceptance test changed.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-220.1 | met | `F::test_a_catch_up_behind_only_out_of_scope_commits_keeps_the_green_e2e_ac_220_1`, `F::test_diff_of_docs_commits_is_outside_the_e2e_scope_ac_220_1`, `F::test_e2e_workflows_are_the_ones_that_run_the_scope_script_ac_220_1`, `F::test_an_e2e_ran_only_when_every_check_of_its_workflow_passed_and_none_was_skipped_ac_220_1` | `scripts/cplat/merge_lock.py:394` (e2e head only when the e2e ran), `:400` (range scope), `:358-368` (kept line), `:419` (`skip_workflows`); `scripts/cplat/ship.py:881-886`, `:1029-1039` (skip bound to one head); `scripts/cplat/e2e_gate.py:136-153`; `scripts/e2e-scope.py:183-193` | The test checks one update, the merge on the new head, the exact kept line with 2 commits, and that the e2e of the new head was still pending at the merge (clock < 12.5 min) |
| AC-220.2 | met | `F::test_an_in_scope_commit_in_the_range_waits_for_every_check_and_names_the_path_ac_220_2`, `F::test_an_undecidable_scope_waits_for_every_check_and_says_so_ac_220_2`, `F::test_diff_of_an_e2e_file_is_inside_the_scope_and_names_the_path_ac_220_2`, `F::test_diff_sees_a_release_heading_that_the_range_adds_ac_220_2`, `F::test_diff_of_an_unknown_commit_is_an_error_not_a_decision_ac_220_2`, `F::test_diff_and_base_together_are_an_argument_error_ac_220_2`, `F::test_a_scope_that_cannot_be_read_is_undecidable_and_never_raises_ac_220_2` | `scripts/cplat/merge_lock.py:358-368` (in-scope and undecidable lines); `scripts/cplat/e2e_gate.py:47-49`, `:94-119`; `scripts/e2e-scope.py:183-193`, `:203` | Exact lines asserted (`... is inside the e2e scope (and 1 more)`, `... could not be decided (<error>)`), and the e2e of the new head was waited for (clock >= 25 min, not pending at the merge) |
| AC-220.3 | met | `F::test_the_e2e_run_of_a_kept_head_is_cancelled_after_the_merge_ac_220_3`, `F::test_a_red_non_e2e_check_of_the_new_head_still_stops_a_kept_land_ac_220_3` | `scripts/cplat/land_merge.py:508-510`; `scripts/cplat/ship.py:888-905` | Only the e2e run is cancelled, after the merge event; a red `ci` gives no merge and no cancel |
| AC-220.4 | met | `F::test_a_docs_land_merges_while_a_code_land_waits_on_its_checks_ac_220_4` | `scripts/cplat/merge_lock.py:168-178` (fast lane, asked once), `:212-234` (`Hold.waiting`: claim, flock released); `scripts/cplat/land_merge.py:428-446`; `scripts/cplat/pr.py:93`, `:124` | The test checks the claim contents, that the flock is free during A's wait, the fast-lane line exactly once, B merging first and within 10 min of starting, both merges under the flock, and no claim or lock left over |
| AC-220.5 | met | `F::test_the_code_land_catches_up_again_after_the_fast_lane_merge_ac_220_5` | `scripts/cplat/merge_lock.py:431-440` (base looked at again after a claimed wait); `:159-166` (release hold on retake) | A is updated a second time, merges on that head with `behind == 0`, keeps the round-1 e2e (B's docs commit) and cancels the last head's e2e |
| AC-220.6 | met | `F::test_a_land_in_scope_or_undecidable_waits_for_the_lock_ac_220_6[in scope]`, `[undecidable]` | `scripts/cplat/merge_lock.py:179-190` (a live claim is a queue); `scripts/cplat/land_merge.py:436-438` (undecidable is not `run is False`) | The queue line names A's `who`; B never merges and never starts its own catch-up while A waits |
| AC-220.7 | met | `F::test_a_fast_lane_merge_still_waits_for_a_release_hold_ac_220_7`, `F::test_a_release_mode_land_queues_behind_a_claim_and_takes_no_fast_lane_ac_220_7`, `F::test_a_release_mode_land_behind_main_does_not_catch_up_or_keep_an_e2e_ac_220_7` | `scripts/cplat/merge_lock.py:159-166` (hold checked on every flock take, before the claim check); `scripts/cplat/land_merge.py:431-432` (RELEASE: no predicate); `scripts/cplat/merge_lock.py:398-399` (`Behind`) | The fast-lane merge happens after the hold drops; RELEASE queues, never calls `change_scope`, and behind main raises `BaseMoved` with no update, no range call, no `e2e:`/`fast lane:` line |
| AC-220.8 | met | `F::test_a_land_that_kept_an_e2e_records_its_waits_ac_220_8`, `F::test_the_fast_lane_and_the_catch_up_e2e_are_recorded_for_both_lands_ac_220_8`, `F::test_a_land_that_ends_red_is_recorded_too_ac_220_8`, `R::test_the_report_shows_median_and_p90_lock_wait_for_docs_and_code_lands_ac_220_8`, `R::test_the_report_says_none_when_no_record_holds_a_land_ac_220_8`; key order in `tests/cplat/test_runs_report.py`, `test_runs_report_unclassified.py` | `scripts/cplat/land_merge.py:449-466`; `scripts/cplat/pr.py:125-128`, `scripts/cplat/ship.py:1533-1537` (record in `finally`); `scripts/cplat/merge_lock.py:84-95` (`LandStats`), `:184-190`; `scripts/cplat/runs_report.py:168-199`, `:264`, `:418-429` | Lock wait, catch-up minutes, fast lane and kept e2e asserted per land; report median/p90 per docs and code with exact text. Note: a land that ends in `Busy` before it gets the lock writes no item (record follows `settle`, as design.md says) |
| AC-220.9 | pending (post-release) | `R::test_the_ac_220_9_counts_are_zero_when_no_docs_land_waited_behind_a_catch_up_ac_220_9`, `R::test_the_ac_220_9_counts_find_the_lands_that_the_spec_wants_gone_ac_220_9` | `scripts/cplat/runs_report.py:190-195`, plan `human_steps[0]` | A measurement 7 days after the release, as AC-126.15 and AC-131.18 were. Both counts and their boundaries (5.0 not counted, 6.0 counted; `range_scope == "out"` with `catch_up_e2e`) are tested. Not judged here; it does not block `pass` |
| AC-220.10 | met | all scenario tests in `F` (kept: .1/.3; in scope and undecidable: .2; fast lane and catch-up again: .4/.5; two in-scope lands: .6; hold during fast lane and RELEASE: .7) | `tests/cplat/land220_world.py` (fakes `gh` PR heads, checks with workflow, runs, `update-branch`, `merge`, `run cancel`, and the base history) | No network: `gh` is fully faked; the `--diff` tests use a local git repo only |

## Non-goals

- No batching of e2e across PRs. ✔
- Optimistic release: the in-scope land gives up the flock during its catch-up wait, but its claim keeps every in-scope,
  undecidable and RELEASE land queued (`merge_lock.py:179-190`, AC-220.6), so only out-of-scope lands pass. That is
  assumption A4 and the fast lane itself, not the excluded release of the lock for code PRs. ✔
- `e2e-scope.py` triggers unchanged; `--diff` reuses `triggers` and `_new_headings` (`scripts/e2e-scope.py:183-193`). ✔
- No branch protection or required-check changes. ✔
- No template-owned layout changes. ✔

## Deviations from the plan

- Every changed file is in a task's `files`; all six tasks are `done: true`. ✔
- Contract: the "released" line omits `<new head sha7>`: `  released the merge lock of <slug> while the checks run; ...`
  (`scripts/cplat/merge_lock.py:222`) against design.md's `while the checks of <new head sha7> run`. No criterion or test
  covers it. Acceptable, but fix the line or the design before merge.
- Contract: `e2e-scope.py --diff` prints `ERROR:` on stderr (`scripts/e2e-scope.py:210`), `--base` on stdout. The design
  says "as `--base`". The acceptance test asserts stderr, and `e2e_gate` reads both streams (`e2e_gate.py:107`).
  Acceptable: stdout keeps only `run=`.
- Behaviour: `catch_up` with a `hold` looks at the base again after every round (`merge_lock.py:436-440`), also in repos
  without an e2e workflow, where `land_merge.lock` still yields a `Hold`. Design.md says such repos "behave exactly as
  before". The difference is one more behind check, and a second catch-up if `main` moved by a non-cplat merge.
  Acceptable: stricter, and the existing land tests pass.
- Contract additions: `held(stats=)`, `Hold.waiting(claim=)` and `land_merge.lock(...)` are not in design.md. They are
  internal plumbing. Acceptable.
- The changelog fragment still has the `(#NNN)` placeholder, and it sits in the bold lead, not at the end
  (`docs/changelog.d/220-docs-land-fast-lane.changed.md`). Acceptable until the PR exists; `pr-check` will flag it.
- ADR-089 amended and `docs/dispatch.md` paragraph added as t6 asks. ✔

## Contract

Matches design.md apart from the two line differences above. The printed lines of AC-220.1 to AC-220.4 and AC-220.6, the
claim file, `LandStats`, the `lands` item keys and the report JSON and text are as specified. ✔

SMOKE: none

**Result:** pass

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
