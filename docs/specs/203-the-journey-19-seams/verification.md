# Verification — 203 The journey 19 seams

**Result:** pass
**Commit:** 73a60d9b · **Base:** 3797c9b0 · **Trace:** 6/6 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-203.1 | met | `tests/cplat/test_203_context.py::test_the_explicit_context_wins_and_reaches_state_process_and_output_ac_203_1`, `::test_the_calling_sessions_environment_gives_the_context_ac_203_1` (3 cases), `::test_the_settings_files_give_the_context_project_before_user_ac_203_1`, `::test_the_session_environment_goes_before_the_settings_ac_203_1`, `::test_resolve_follows_the_order_of_the_contract_ac_203_1`, `::test_the_local_cluster_of_the_linked_system_is_the_last_source_ac_203_1`, `::test_the_headless_deploy_takes_the_recorded_context_ac_203_1`; `tests/cplat/test_203_context_deploy.py::test_the_recorded_context_makes_deploy_check_argo_and_record_the_smoke_ac_203_1` | `scripts/cplat/shipcontext.py:45` (order: `--context`, recorded, `CPLAT_KUBE_CONTEXT`, `KUBE_CONTEXT`, settings, `k3d-<system>-local` only when listed), `scripts/cplat/ship_handoff.py:179,189,193` (resolve, spawn with `CPLAT_KUBE_CONTEXT`, state), `scripts/cplat/ship_handoff.py:142` (`context:` line right after `headless:`), `scripts/cplat/ship.py:1684-1686` (deploy reads the recorded context) | Tests assert the exact `context: <name> (<source>)` line, the child env, `st["context"]`, Argo `shop-api-dev` checked with `lan`, and `smoke.outcome == "passed"` in state and run record. The deploy test asserts the recorded smoke result, which `ship status` reads, not the `ship status` text itself; accepted as the recorded outcome the criterion states. |
| AC-203.2 | met | `tests/cplat/test_203_context.py::test_a_restart_gets_the_recorded_context_without_being_told_ac_203_2`, `::test_the_resume_after_ended_gets_the_recorded_context_ac_203_2`, `::test_detach_with_an_answer_gets_the_recorded_context_ac_203_2`, `::test_a_restart_with_another_explicit_context_replaces_it_ac_203_2`, `::test_a_live_process_is_reused_and_the_line_still_names_the_context_ac_203_2`, `::test_without_any_context_the_hand_off_starts_and_says_so_ac_203_2`, `::test_an_unknown_explicit_context_exits_with_one_line_and_starts_nothing_ac_203_2` | `scripts/cplat/ship_handoff.py:156-160` (unknown `--context` raises before `ship.start`, recorded context of the same spec), `scripts/cplat/shipcontext.py:50-51,66` (recorded row, the `none` line), `scripts/cplat/ship.py:2217-2219` (`--context needs --detach`) | Restart, resume after `ENDED:` and `--detach --answer` each spawn with `CPLAT_KUBE_CONTEXT=lan`; no source → process starts, exact `none` line, no env var; unknown `nope` → non-zero, one stderr line naming it, no spawn, no state. |
| AC-203.3 | met | `tests/cplat/test_203_reschedule.py::test_a_new_task_runs_before_its_dependants_and_done_units_keep_their_checkpoint_ac_203_3`, `::test_the_build_schedule_shows_the_new_batches_at_once_ac_203_3`, `::test_a_removed_task_leaves_the_units_and_a_second_reschedule_changes_nothing_ac_203_3`, `::test_a_changed_dependency_is_a_change_of_the_plan_ac_203_3`, `::test_an_uncommitted_plan_change_changes_nothing_ac_203_3`, `::test_the_run_goes_on_from_the_changed_plan_and_never_runs_a_done_unit_again_ac_203_3` | `scripts/cplat/units.py:134` (`plan_key`), `:143` (`_ids_from` with kept done units), `:371` (keep), `:404` (`reschedule`), `scripts/cplat/supervisor.py:86-104` (reschedule before each `next_open`, `plan changed:` line, `budget.rescale`) | The supervisor test runs a fake `claude` world: `t0` added after `task:t1`'s session runs once before `t3`, `t1` runs once, run ends with `verification`, `land`, no escalation in units or ship state. The system-ship repo case runs the same `supervisor.drive`; tested through the component world only. |
| AC-203.4 | met | `tests/cplat/test_203_reschedule.py::test_the_plan_key_follows_ids_files_and_dependencies_only_ac_203_4`, `::test_a_repo_without_a_plan_has_no_plan_key_ac_203_4`, `::test_a_batch_that_gained_a_task_is_replaced_by_a_fresh_unit_ac_203_4`, `::test_a_task_merged_into_another_leaves_its_unit_ac_203_4`, `::test_a_change_of_the_text_only_changes_no_unit_ac_203_4`, `::test_a_changed_plan_that_fails_the_check_returns_its_first_error_and_writes_nothing_ac_203_4`, `::test_a_changed_plan_that_fails_its_check_escalates_with_cause_code_and_starts_no_unit_ac_203_4` | `scripts/cplat/units.py:134-140` (key on id, files, depends_on only), `:418-420` (plan check, first error, nothing written), `scripts/cplat/supervisor.py:87-98` (escalate cause `code`, `EXIT_STOPPED`) | New batch `batch:t1,t2,t4` asserted `open/0/0/None`; text-only edit leaves the units byte-equal; bad plan → `{"error": first}`, file unchanged; supervisor stops after `task:t1` with `cause == "code"` and the error (`tX`) in the escalation. |
| AC-203.5 | met | `tests/cplat/test_203_next.py::test_the_limits_are_20_seconds_per_source_and_60_in_total_ac_203_5`, `::test_next_json_returns_within_the_deadline_and_lists_the_silent_source_ac_203_5` (5 sources), `::test_the_screen_names_the_silent_source_and_exits_zero_ac_203_5` (5), `::test_the_sources_that_answered_are_shown_as_usual_ac_203_5`, `::test_a_silent_dispatcher_leaves_the_run_rows_ac_203_5`, `::test_every_source_silent_at_once_still_returns_within_the_total_ac_203_5`, `::test_a_state_lock_another_process_holds_does_not_hold_next_ac_203_5`, `::test_a_run_whose_sources_all_answer_ends_the_ordinary_way_ac_203_5` | `scripts/cplat/nextstate.py:47-48` (20/60), `:280-305` (`_Task`: daemon thread, per-source and total deadline, `no answer within {SOURCE_SECONDS} s`), `:314-391` (group 1 started together, `abandoned`), `scripts/cplat/nextcmd.py:117,141-142` (`hard_exit(0)` after printing) | Constants asserted at 20/60; behaviour asserted with lowered limits (1 s / 2 s, elapsed < 4 s, sources hang 5 s): exit 0, `unavailable` entry with the exact error and kinds, no "Nothing is waiting", "Try again" offered, a held `runs._locked()` lock, `hard_exit` called with 0 only when abandoned. |
| AC-203.6 | met | `tests/cplat/test_203_next.py::test_next_points_its_input_at_devnull_and_turns_prompts_off_ac_203_6`, `::test_next_keeps_an_ssh_command_the_person_set_ac_203_6`, `::test_a_program_that_reads_its_input_does_not_hold_next_ac_203_6` | `scripts/cplat/nextcmd.py:124-134,138` (`_no_input`: fd 0 to `/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GH_PROMPT_DISABLED=1`, `GIT_SSH_COMMAND` default `BatchMode=yes`) | The process test runs the real `cplat next --json` with a pty on stdin nobody types into and a fake `gh` that reads stdin: exits 0 with schema 1 within 30 s (bounded further by AC-203.5's deadlines). |

## Non-goals

- System ship context passing (spec 155) and `cplat system ship start --context`: no change to system ship code. ✔
- No guess from the current kube context: `shipcontext.resolve` (`scripts/cplat/shipcontext.py:59-63`) uses only `k3d-<system>-local` when listed; tested (`unrelated` context gives `(None, None)`). ✔
- Done units never re-run, `cplat plan merge` unchanged (no diff to `planmerge`/`plan` commands). ✔
- `cplat next` stays stateless: no cache, sources not made faster (`needs`, `runlist`, `core.run` unchanged). ✔
- Journey driver stop pattern: not touched. ✔
- No template, header, footer or navigation changes; no prompt, plugin or template edits (A8), so no rules-register entry or version bump needed. ✔

## Deviations from the plan

- `docs/specs/110-*`, `167-*`, `171-*`, `193-*`, `202-*` differ from the base: they come from main PRs #759, #760, #762 merged into the range, not from this build; acceptable.
- `docs/specs/203-the-journey-19-seams/*` (spec, plan, design) belong to the spec workflow, not a task; acceptable.
- Every code file is in a task's `files`; all three tasks are `done: true`. ✔
- `ship_handoff.detach` checks an unknown `--context` before the live-process reuse path, and a missing or failing `kubectl` (`contexts()` returns `None`) refuses any `--context`; both in line with design.md ("before `ship.start` and before any spawn"); acceptable.

## Contract

Matches design.md: `--context` option and the `--context needs --detach` error, resolution rows 1–6 with their source texts, `st["context"] = {name, source}`, `CPLAT_KUBE_CONTEXT` in the child, deploy's `kube context: <name> (recorded at the hand-off)`, `plan_key`, `reschedule` return values, the `plan changed:` line and `summary.log` entry, `SOURCE_SECONDS`/`TOTAL_SECONDS`, `hard_exit`. ✔

## Test changes after the freeze

- `tests/cplat/test_203_next.py` (ff0337d1): the fake `gh` script is wrapped in the shared AC-178.5 prelude (`with_prelude`); assertions unchanged; approved by the user per `cplat spec test-diff`. Still asserts the criterion as written.

## Test review

The reviewed-tests commit (569d1dff) records `findings: 6` and lists no unresolved finding lines (they were resolved in a2cf8298). No unresolved test-review findings.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
