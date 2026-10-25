# Verification — 094 A merge conflict re-plans instead of escalating

**Result:** pass
**Commit:** 6c77ce6 · **Base:** f7b121e (merge base with `origin/main`) · **RED:** 348749c · **Trace:** 15/15 criteria named by tests, none missing

Reviewer run: `pytest tests/cplat/test_replan.py tests/cplat/test_build_replan_docs.py -n auto` → 46 passed. Orchestrator summary: `devbox run ci-local` green, `tests/cplat` 1147 passed, 4 skipped.

All test ids below are in `tests/cplat/test_replan.py` unless they say `test_build_replan_docs.py`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-094.1 | met | `test_a_conflicting_branch_is_aborted_and_set_aside`, `test_merge_refuses_a_dirty_tree_and_changes_nothing`, `test_a_clean_merge_prints_merged_and_exits_0`, `test_merge_refuses_a_done_or_unknown_task`, `test_build_replan_docs.py::test_build_md_drives_phase_2_through_cplat_build` | `scripts/cplat/buildcmd.py:126` (clean tree first), `:142-146` (unmerged paths, `merge --abort`, then a check that HEAD, the tree and `MERGE_HEAD` are back as they were), `:150-153` (exit 3); `plugins/svc/commands/build.md:81` (exit 3 → keep going) | The tests check that HEAD is unchanged, the status is empty, there is no `MERGE_HEAD`, `a.py` has no conflict markers and the branch is kept. |
| AC-094.2 | met | `test_the_rest_of_the_batch_merges_after_a_conflict`, `test_every_conflicting_branch_of_a_batch_is_set_aside` | `buildcmd.py:131-138`, `:150-152`; `build.md:81-88` (steps 2–4 and `task-done` run for each clean merge) | t3 merges after t2 is set aside and becomes `done`. Two conflicting branches both end up pending. |
| AC-094.3 | met | `test_state_gives_the_architect_task_partner_and_paths`, `test_the_partner_is_found_by_the_plan_when_no_merge_names_it`, `test_the_architect_may_change_only_files_depends_on_and_parallel_safe` (title, covers, task removed), `test_a_done_task_and_the_spec_hash_cannot_change`, `test_the_prose_below_the_metadata_may_change`, `test_replan_commit_needs_a_pending_conflict`, `test_build_replan_docs.py::test_architect_has_a_replan_mode` | `scripts/cplat/replan.py:200-249` (`check_amended`), `buildcmd.py:90-110` (partner rules a–d), `buildcmd.py:169-190` (`state`); `build.md:94`; `plugins/svc/agents/architect.md:26-35` | The architect prompt gets `SPEC_DIR` and the `cplat build state` lines: task, the task it collided with, and the paths. |
| AC-094.4 | met | `test_the_amended_plan_is_checked_and_committed_with_the_conflict_in_the_message`, `test_the_schedule_shows_the_replanned_task_after_what_it_depends_on`, `test_schedule_batches_parallel_safe_tasks_with_disjoint_files`, `test_schedule_keeps_gitops_tasks_apart_and_rejects_cycles` | `replan.py:249` (`spec.check`), `replan.py:257-290` (commit message and trailers, only plan.md), `buildcmd.py:43-85` (schedule), `buildcmd.py:229-234` | Two assertions are loose: line 322 (`RE-PLANNED` line) and line 336 (last schedule line) each have a permissive `or`. The criterion is still proven by the strict assertions next to them: commit subject, body, trailers, only plan.md committed, and `\| 2 \| 1 \| t2 (re-planned) \| sequential \|` with levels `[[t3],[t2],[t4]]`. |
| AC-094.5 | met | `test_the_set_aside_branch_survives_until_the_rerun_is_merged_and_green`, `test_resolved_is_a_noop_for_a_task_that_was_not_re_planned`, `test_resolved_refuses_a_replanned_task_that_is_not_done`, `test_the_rerun_prompt_gives_the_old_diff_as_reference` | `replan.py:320-345` (`resolve`: worktree by branch, `remove --force`, `prune`, `branch -D`); `build.md:75` (re-run prompt with `git diff HEAD...<branch>`), `build.md:88` (`resolved` after `task-done`) | |
| AC-094.6 | met | `test_a_task_that_conflicts_again_escalates_with_both_collisions` | `replan.py:156-162` (`decide` → "again"), `replan.py:178-185`, `buildcmd.py:154-157` (exit 4, nothing pending) | The line names the task, both collisions with their paths, and the re-plan commit sha and subject. |
| AC-094.7 | met | `test_a_plan_that_fails_spec_check_is_not_committed`, `test_replan_abort_restores_the_last_valid_plan_and_escalates`, `test_the_prompts_send_errors_once_then_escalate_with_replan_abort` | `buildcmd.py:221-228` (errors, exit 1, no commit), `replan.py:302-317` (`abort`: checkout plus removal of untracked files in SPEC_DIR); `build.md:95-96` (one retry, then `replan-abort` and escalate) | |
| AC-094.8 | met | `test_state_reports_each_replanned_task_with_files_and_outcome`, `test_state_without_replans_prints_one_line`, `test_the_final_report_row_states_the_amended_plan` | `buildcmd.py:182-189`; `build.md:196`, `:202` | `state` prints `re-run pending` or `re-run merged cleanly` for each task, and the report row is built from it. |
| AC-094.9 | met | `test_each_conflict_is_one_event_that_ends_resolved`, `test_a_failed_replan_leaves_the_conflicts_escalated`, `test_a_merge_is_recorded_for_out_of_plan_files` | `buildcmd.py:158-162` (`conflict`, recorded `escalated` first), `replan.py:283-289` (`replan` and `re-planned`), `replan.py:313` (`escalated` on abort), `replan.py:342` (`resolved`) | One commit for two tasks counts `replans == 1` and `merge_conflicts == 2`. The events carry spec, task, partner, paths and the author agent. A second conflict of a re-planned task, or a conflict at the cap, adds its own `escalated` event. A build that stops for an unrelated reason while a re-run is still open leaves that task's event at `re-planned`, which is accurate; the criterion's "escalated when the build stops" is met for every conflict-driven stop. |
| AC-094.10 | met | `test_a_conflict_replans_the_same_without_a_store`, `test_an_unreachable_store_does_not_block_the_replan` | `buildcmd.py:132-135`, `:158-162`, `replan.py:283-289`, `:293-299` (every recording call is wrapped in try/except; `runs_agents` buffers) | |
| AC-094.11 | met | `test_a_resumed_build_schedules_from_the_amended_plan_and_counts_the_replan` | `replan.py:59-83` (history read from git trailers, starting after the `start building` commit) | The local pending file is deleted to simulate a fresh checkout. The `done` tasks stay done, the re-plan is counted, and a second conflict escalates. |
| AC-094.12 | met | `test_the_replan_may_change_nothing_but_the_plan`, `test_a_conflict_leaves_no_markers_anywhere`, `test_the_build_rules_forbid_hand_resolution` | `replan.py:207-213` (any other changed or untracked file is refused), `buildcmd.py:143` (the merge is aborted before control returns); `build.md:81`, `:214` | |
| AC-094.13 | met | `test_a_fourth_replan_escalates_and_lists_the_earlier_commits`, `test_two_replans_still_leave_room_for_a_third` | `replan.py:21`, `:160`, `:188-191` | The message names the cap of 3 and lists each earlier commit as sha plus subject. |
| AC-094.14 | met | `test_an_attended_build_replans_without_asking`, `test_the_final_report_row_states_the_amended_plan` | `build.md:92` ("without asking the user, in an attended build as well as an unattended one"), `build.md:202`; `plugins/svc/commands/ship.md:34` | This is prompt behaviour, so a text test is the right level. |
| AC-094.15 | met | `test_build_replan_docs.py::test_guide_and_build_rules_say_replan_once_then_escalate`, `::test_nothing_still_says_every_conflict_is_escalated`, `::test_ship_docs_no_longer_list_every_conflict_as_an_escalation` | `docs/AGENTS.md:95`, `docs/AGENTS.md:24`; `build.md:214`; `docs/unattended-delivery.md:18`; `ship.md:40`; `scripts/cplat/ship.py:927` | A grep of build.md, AGENTS.md, ship.md and unattended-delivery.md finds no remaining text that says every conflict is escalated. |

## Harness fix after RED (commit 6c77ce6)

`git diff 348749c 6c77ce6 -- tests/cplat/test_replan.py` touches only helpers and one call. It does not change what any criterion means.

- `edit_plan` falls back to `_flow_tasks` only when the literal it looks for is missing. That happens because the existing `cplat spec task-done` (not changed by this build) rewrites `tasks` as block YAML. `_flow_tasks` re-renders the same parsed tasks in the fixture's flow style and keeps the metadata head and the prose. The plan's YAML content is unchanged, and `replan-commit` compares parsed YAML, so the style has no effect on any verdict. Before the fix the affected tests failed on the helper's own `assert old in text`, not on product behaviour. This was a harness bug.
- `cplat.main(["spec", "check", "007", "--repo", …])` became `cplat.main(["spec", "--repo", …, "check", "007"])`. `--repo` belongs before the `spec` subcommand, and the old order raised argparse `SystemExit` instead of reaching the assertion. The assertion is the same.
- No assertion, criterion id, test name or expected value changed. `cplat spec test-diff 6c77ce6` exits 0 (orchestrator). Against 348749c, `test-diff` reports exactly this helper change in `test_replan.py` and nothing else.

## Non-goals

- Nothing resolves conflicts automatically: `cplat build merge` only aborts, and `replan-commit` refuses any change outside plan.md. ✔
- Nothing covers conflicts outside Phase 2. The PR, land and gitops paths are untouched; `ship.py` changes one gate string only. ✔
- Re-plans happen only for a merge conflict: `replan-commit` needs a pending conflict (`replan.py:203-204`). ✔
- A re-plan cannot change the spec: `spec_hash` and all metadata must stay equal, and only plan.md may change. ✔
- No plan-accuracy metric or report was added. This build only emits events through the existing `runs_agents` calls. ✔

## Deviations from the plan

- `docs/specs/094-…/plan.md` changed outside every task's `files` (the `done: true` flags from `cplat spec task-done`). This is expected bookkeeping and acceptable.
- `tests/cplat/test_replan.py` changed after RED (6c77ce6). This is the harness fix described above and is acceptable.
- All tasks t1–t4 are `done`. No source file changed outside the tasks' `files`.
- The branch is behind `origin/main`: specs 088 and 095 merged after the merge base f7b121e. `git diff origin/main..HEAD` therefore shows their files as removed. The branch's own change (`git diff f7b121e..HEAD`) is limited to the 15 files of this spec. Rebase onto `origin/main` before the PR; `docs/CHANGELOG.md` `[Unreleased]` will likely need a merge of the new bullet. This does not affect the verdicts.

## Contract

The implementation matches `design.md` (subcommands, exit codes 0/1/3/4, trailer format, pending file, recording order). There are small wording differences, none of them load-bearing:

- The "again" escalation ends with `A task is re-planned once. Conflicts are never resolved by hand.`; the contract has `…once; conflicts are never…`. Acceptable: the tests and the criterion need only the facts the line names.
- `resolved` prints `branch <b> was already gone` when the branch no longer exists, and it also drops a leftover pending entry. These are additive and acceptable.
- `build.md:81` says `cplat build merge` records the conflict before it aborts the merge. The code aborts first and then records (`buildcmd.py:143` then `:159`), as the design's step order says. This is prompt wording kept for an 089 test (commit 43b7af7). Acceptable, but the prompt line is factually inverted.
