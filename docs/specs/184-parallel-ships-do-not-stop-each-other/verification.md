# Verification — 184 Parallel ships do not stop each other

**Commit:** fd869d45 (second pass) · **Base:** c5777d8b · **Trace:** 10/10 criteria named by tests (`cplat spec trace`, unchanged); `cplat quiet test-fast` 9899 passed, 12 skipped; `cplat quiet ci` OK on the first pass

Scope: only the commits whose message names 184 and the 184 files (the range also holds the merged work of specs 178–183, which this review does not judge).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-184.1 | met | `tests/cplat/test_184_pause.py::test_a_reset_time_pauses_the_unit_until_one_minute_after_it_and_starts_the_same_unit_again_ac_184_1`, `::test_the_legacy_loop_pauses_and_starts_the_same_prompt_again_ac_184_1`; `tests/cplat/test_184_usagelimit.py::test_the_unix_reset_after_the_bar_is_read_as_local_time_ac_184_1`, `::test_the_resets_form_is_the_first_such_moment_at_or_after_the_end_ac_184_1`, `::test_only_the_last_non_empty_line_is_read_for_the_message_ac_184_1` | `scripts/cplat/usagelimit.py:87` (detect), `:111` (pause, reset + 60 s), `scripts/cplat/supervisor.py:139-176`, `scripts/cplat/headless.py:547-566` | The tests check the exact line, a sleep of reset + 60 s with no session started in between (`T.log`), the same unit or prompt started again, exit 0 and `shipped`, and no escalation. Both reset forms (`\|<unix>` and `resets …`, with a zone and with an unknown zone) are covered. |
| AC-184.2 | met | `test_184_pause.py::test_silent_sessions_pause_5_then_10_minutes_and_the_run_goes_on_ac_184_2`, `::test_the_limit_message_without_a_time_pauses_5_minutes_ac_184_2`, `::test_pauses_beyond_360_minutes_stop_the_run_as_an_environment_pause_and_the_same_command_continues_ac_184_2`, `::test_a_reset_time_beyond_the_cap_stops_at_once_naming_the_reset_ac_184_2`, `::test_the_legacy_loop_stops_as_an_environment_pause_beyond_the_cap_ac_184_2`; `test_184_usagelimit.py::test_without_a_time_the_waits_are_5_10_20_40_then_60_minutes_ac_184_2`, `::test_the_pauses_of_one_run_stop_at_360_minutes_in_total_ac_184_2`, `::test_a_session_with_no_output_that_ends_within_60_seconds_is_a_hit_without_a_time_ac_184_2` | `scripts/cplat/usagelimit.py:111-126`, `scripts/cplat/headless.py:449` (cause `environment`), `:472` (stop_of), `scripts/cplat/supervisor.py:169-170` | The tests cover the 5/10/20/40/60/60 schedule, the 360-minute cap with and without a reset time, exit 1 with the exact `environment pause:` line, the record `{reason, cause: environment}` and the dispatch result. Neither the ship nor the units file is escalated, and running the same command again ships. |
| AC-184.3 | met | `test_184_pause.py::test_the_paused_session_is_no_invocation_ac_184_3`, `::test_the_pause_is_not_counted_against_the_minutes_of_the_budget_or_of_max_minutes_ac_184_3`, `::test_two_empty_sessions_then_a_checkpoint_continue_to_the_next_unit_without_a_stall_ac_184_3`, `::test_a_pause_after_a_stall_adds_none_and_the_checkpoint_after_it_resets_the_count_ac_184_3`, `::test_the_legacy_loop_pauses_and_starts_the_same_prompt_again_ac_184_1` (invocations), `::test_a_paused_session_does_not_count_as_no_progress_in_the_legacy_loop_ac_184_3`, `::test_the_legacy_pause_is_no_time_of_max_minutes_or_the_budget_ac_184_3`; `test_184_usagelimit.py` budget tests; `test_budget_pause.py`; regression `tests/cplat/test_184_review_fixes.py::test_a_legacy_pause_that_stops_the_run_carries_no_invocation_ac_184_3` | `scripts/cplat/budget.py:318`, `:344`, `:465`; `scripts/cplat/units.py:405`; `scripts/cplat/supervisor.py:165`; `scripts/cplat/headless.py:554-559` | First pass: partial, because the legacy-loop session whose limit stopped the run kept its invocation. Fixed in fd869d45: `budget.count_invocation(rid, -1)` now runs at `headless.py:554`, before `pauser.pause` and the `pause.stop` return. This matches unit mode and the design contract. The regression test drives the legacy loop with a reset 7 h ahead (beyond the cap). It expects exit 1 and an `environment pause` line, and asserts `invocations() == 0`. |
| AC-184.4 | met | `tests/cplat/test_184_allowlist.py` (all, e.g. `::test_the_dry_run_of_a_ship_shows_the_log_folder_and_the_view_rules_ac_184_4`, `::test_no_other_gh_run_or_gh_api_command_is_allowed_ac_184_4`, `::test_every_session_of_a_ship_is_granted_them_ac_184_4`) | `scripts/cplat/preflight.py:40-73`, `scripts/cplat/headless.py:376-380` | The tests check that the log folder is the one `quiet._log_path` writes, that the three `gh run view … --log-failed` forms are allowed and rerun, cancel, delete, watch, `--log`, `--web` and `gh api` are not, that `refused_rules` is unchanged, that a build gets none of the new rules, and that they appear in the dry run and in every session's `--allowedTools` and `CPLAT_RUN_ALLOWLIST`. |
| AC-184.5 | met | `tests/cplat/test_184_template_lint.py` (parsers for each tool including Checkstyle `ConstantName`, `--changed` on a temporary repo, ci-local order, ci.yml wiring, devbox tools) | `scripts/template-lint.py:135-233`, `scripts/ci-local.sh:55-56` (`set -euo pipefail`, `:7`), `.github/workflows/ci.yml:56,263,439,603`, `devbox.json` | A branch with no template change renders nothing. A changed template is rendered with defaults and smoke data, and a violation exits 1 with `<template>: <file>:<line>: <rule>: <message>`. Deviation (in design.md): the service-go smoke job keeps `golangci-lint-action` instead of the script, so its lines are golangci-lint's own `file:line:col: msg (linter)`. They name the file, line and rule but are not the script's uniform line. Acceptable, see Contract. |
| AC-184.6 | met | `tests/cplat/test_184_land_adr.py` (union, one and two clashes with exact `renumbered ADR-004 to ADR-005 (3 references)` lines, references only in branch files, row removed, refusals, the shared limit of 3), both entries `ship` and `pr` | `scripts/cplat/land_resolve.py:136-195`, `scripts/cplat/land_merge.py:347-395` | The tests check a signed merge of `main`, a push without force (ancestor check) and the new head's checks judged before the merge (`assert_landed_by_a_signed_merge_of_main`). The next number comes from `adr.next_number` (`land_merge.py`, Context `next_adr`). |
| AC-184.7 | met | `tests/cplat/test_184_land_rules.py` (R3→R4 renumbered with word-bounded references only in branch files, `rulescheck` passes on the result; header, both-changed entry, `register.yml` baseline and other-file conflicts stop clean; the three kinds of round share the limit of 3; a result the rules check refuses stops) | `scripts/cplat/land_resolve.py:203-280`, `scripts/cplat/land_merge.py:357`, `:374`, `:383-386` | Merge aborted on refusal (`assert_stopped_clean`: no MERGE_HEAD, clean status, nothing pushed). |
| AC-184.8 | met | `tests/cplat/test_184_slots.py` (wait line naming the holder, start after the holder ends with `POLL_SECONDS` ≤ 60, `--no-wait` exit 1 with no record or ledger, stale line, `slots: 2`, worktree and clone share, nested run, dry run takes none, waiting is no budget time) | `scripts/cplat/run_slot.py:76-164`, `scripts/cplat/headless.py:325-330` (SlotBusy → exit 1), `:393` (slot after the dry-run return, before the run record) | Real second process as the holder; flock freed by the kernel. |
| AC-184.9 | met | `tests/cplat/test_184_dispatch_slots.py` (no unit while a manual run holds the only slot; plan/status JSON and text `held by /component:ship 182 (manual)`; fake slot-taking headless shows peak overlap ≤ `slots` and no busy refusal) | `scripts/cplat/dispatch_cycle.py:109-111,152,302`, `scripts/cplat/dispatch_view.py:92-107,157,216` | |
| AC-184.10 | met | `tests/cplat/test_184_envprefix.py` (candidates, allowed forms, another program, `;` `&&` `\|\|` `\|` `$(` backticks and newline, lowercase names, every refused name and prefix, committed files only, dry-run block with `not allowed:` lines, every unit session granted, a command added by the plan unit announced once before the next unit's run line); regression `tests/cplat/test_184_review_fixes.py::test_a_background_or_redirected_command_is_not_allowed_ac_184_10` (`&`, `>`, `<`) | `scripts/cplat/envprefix.py:22`, `:36-58`; `scripts/cplat/headless.py:381-384`, `:421-436` | First pass: partial, because a single `&` passed. Fixed in fd869d45: `_CHAINING` (`envprefix.py:22`) now holds `&`, `>` and `<`. It is checked by substring before parsing (`:38-40`), so background lists and redirections are refused. The allowed-form tests still pass, since none uses these characters. A value that contains `&`, `<` or `>` is now refused as well. That is stricter than the criterion and safe. |

## Non-goals

- No scheduler across repos or machines: the slots are local flock files keyed by the repo slug (`run_slot.py:49-54`). ✔
- No prediction of the usage limit and no machine-wide session counting. ✔
- No resolution of hand-written files: any path other than `GENERATED`, `docs/adr/README.md` or `docs/rules/**.yml` still stops (`land_merge.py:357-360`). No rebase and no force push. ✔
- No renumbering of spec numbers on land. ✔
- No process or memory limits on test runs. ✔
- No prompt changes in the 184 commits, so the prompt byte baseline is untouched. ✔
- Only `NAME=value … devbox run <script>` commands are allowed, verbatim (`envprefix.py:56`). ✔
- No template files changed, so no template-owned layout changed. ✔

## Deviations from the plan

- `tests/cplat/conftest.py`: an autouse fixture `silent_sessions_are_not_pauses` sets `usagelimit.QUICK_SECONDS = 0` for every test file except `test_184_*`. The fakes of older tests now print a line (`test_headless*.py`, `test_budget.py`, `test_ship_escalate_rules.py`, `test_supervisor_131.py`, `test_159_batch_units.py`, `test_167_policy_plan.py`, `test_dispatch_view.py`, `test_ci_templates.py`, `test_headless_131.py`). These files are in no task's `files`. Acceptable: they follow from AC-184.2 and are recorded in design.md ("Decisions taken during the ship"), and the 184 tests still see the real threshold.
- `devbox.lock` changed with `devbox.json` (t7). Acceptable.
- `docs/adr/102-…md` and `docs/adr/README.md` were added but are in no task's `files`. Acceptable: design.md asks for the ADR.
- `scripts/ci-local.sh` and `devbox.json` also gained a `check-test-sleeps.py` step. It comes from spec 178's merged work, not 184. Not judged.
- `tests/cplat/test_184_review_fixes.py` (fd869d45) is in no task's `files`. Acceptable: it holds the regression tests for the first review's findings, and on purpose it adds no criterion tags to the frozen acceptance tests.
- Every task t1–t12 is `done: true`.

## Contract

Matches `design.md`, with these differences:

- `headless.stop_of` returns `("escalated", "escalated")` for `environment pause:`, while design.md says `("environment", "escalated")` (`headless.py:472`). The acceptance test expects `stop_reason == "escalated"` with `cause == "environment"` in the record and the dispatch result. Acceptable: the cause carries `environment` as the criterion asks.
- First pass: the legacy loop skipped `count_invocation(rid, -1)` on a stopping pause. Fixed in fd869d45 (`headless.py:554`), so the legacy loop now follows the contract's order.
- The service-go smoke job keeps `golangci-lint-action`, a choice design.md documents. The criterion's "the CI smoke jobs print the same lines" holds in substance (file, line and linter are printed) but not in the script's uniform format. Acceptable as a documented design decision. The orchestrator may want the spec text to say "file, line and rule" instead of "the same lines".
- Unit mode and the legacy loop exempt a silent short session that moved the feature head, reached a checkpoint or changed the ship state (`supervisor.py:142-143`, `headless.py:549-550`). This is recorded in design.md, and acceptable.

## Tightened acceptance tests

none (`TIGHTENED: none`). The tests changed after the red commit (44bee45a: `test_184_land_rules.py`, `test_184_pause.py`, `test_184_land_adr.py`) only fix setups that contradicted the contract:

- `untouched.md` is now a file of `main`, not of the branch.
- The ADR whose number clashes is now last in the table, so every move of `main` conflicts.
- The escalation record is compared on `reason` and `cause`.

None of them loosens the criterion as written. They were approved and recorded in design.md.

## Suppressions in acceptance tests

none (`SUPPRESSIONS: none`).

**Result:** pass

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
