# Verification — 143 The coordinator waits with cplat, not hand-written loops

**Result:** pass
**Trace:** 11/11 criteria named by tests

Tests: `E` = `tests/cplat/test_143_envwait.py`, `S` = `tests/cplat/test_143_shipwait.py`, `R` = `tests/cplat/test_143_release_wait.py`,
`D` = `tests/cplat/test_143_waits_docs.py` (red at 04b335eb, unchanged since). The spec 129, 138 and 142 doc tests follow the new
texts (`test_platrelease_129_docs.py`, `test_release_target_138.py`: Phase 5 waits with `cplat component release wait`;
`test_142_expose_merge.py`: the step after the merge is now the wait). Full `tests/cplat` suite (CI's pytest command),
`devbox run validate` and `devbox run quality` green locally.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-143.1 | met | `E::test_every_app_ready_exits_0_at_once_with_one_line_per_app_ac_143_1`, `E::test_a_later_commit_that_contains_the_wanted_revision_counts_ac_143_1`, `E::test_named_components_limit_the_wait_to_their_apps_ac_143_1` | `scripts/cplat/envwait.py` `env_targets` (apps of the environment at the wanted revision), `wanted_revision`, `Ancestry`, `Pins`, `judge`, `watch` (`READY:`); `cplat.py` route `system wait` | a later revision's pin is read when the clone knows it |
| AC-143.2 | met | `E::test_one_line_per_state_change_and_exit_0_at_the_last_app_ac_143_2` | `envwait.watch` (a line when an app's text changes), `judge` (line `<app>: <sync>/<health> at <r7>, runs <tag…>`) | |
| AC-143.3 | met | `E::test_a_red_app_at_the_wanted_revision_stops_at_once_ac_143_3` (sync error, failed sync, Degraded), `E::test_a_failed_sync_of_an_older_revision_is_not_red_ac_143_3` | `envwait.judge` (red only at the wanted revision; the operation's revision is checked), `watch` (`RED:` first line, no sleep) | |
| AC-143.4 | met | `E::test_the_timeout_names_what_each_app_waits_for_and_the_refresh_command_ac_143_4`, `E::test_the_timeout_names_the_wanted_image_against_the_running_one_ac_143_4`, `E::test_with_refresh_given_the_timeout_prints_no_refresh_command_ac_143_4` | `envwait.watch` (`TIMEOUT:` block, `missing`, the same command with `--refresh` last), default 540 s in `main` | |
| AC-143.5 | met | `E::test_refresh_asks_once_for_each_app_behind_on_the_revision_ac_143_5` | `envwait.watch` (`argocd.argoproj.io/refresh=hard` on apps behind, one line) | |
| AC-143.6 | met | `E::test_a_current_context_without_the_systems_apps_is_refused_at_once_ac_143_6`, `E::test_a_cluster_that_does_not_answer_or_has_no_argo_cd_is_refused_at_once_ac_143_6` (2 cases), `E::test_the_configured_context_is_used_without_context_ac_143_6` | `envwait.resolve_context`, `list_apps` | exits 1 with `ERROR:` naming the context |
| AC-143.7 | met | `E::test_the_cluster_wait_is_ready_when_the_roots_run_main_ac_143_7`, `…_is_red_on_a_degraded_root_ac_143_7`, `…_times_out_with_the_refresh_command_ac_143_7`, `…_refreshes_the_roots_behind_ac_143_7`, `…_refuses_a_context_without_the_roots_ac_143_7` | `envwait.cluster_wait` (roots `platform-operators`, `platform-systems`), route `cluster wait` | the roots are the two applications that sync the cluster repo itself |
| AC-143.8 | met | `S::test_a_line_per_phase_change_and_exit_0_at_the_phase_ac_143_8`, `S::test_a_later_phase_counts_and_done_is_the_default_ac_143_8`, `S::test_a_run_finished_and_archived_meanwhile_counts_as_done_ac_143_8`, `S::test_an_escalated_run_exits_1_with_the_reason_and_cause_ac_143_8`, `S::test_the_timeout_names_the_phase_and_how_long_the_run_is_in_it_ac_143_8`, `S::test_the_default_timeout_is_540_seconds_ac_143_8`, `S::test_a_clone_without_a_ship_run_exits_at_once_ac_143_8` | `scripts/cplat/shipwait.py` `ship_wait`, `_archived`, `_phase_start`; `ship.py` `wait` subcommand, `_wait_command` | |
| AC-143.9 | met | `S::test_next_wait_blocks_until_the_action_changes_ac_143_9`, `S::test_next_wait_prints_json_like_next_ac_143_9`, `S::test_next_wait_returns_at_once_when_the_action_is_not_wait_ac_143_9`, `S::test_next_wait_times_out_with_the_running_repos_and_phases_ac_143_9` | `shipwait.next_wait` (records a finished repo's result as `repo result` does), `appship.py` `next --wait`, `show_next`, `_next_wait` | design decision 11 |
| AC-143.10 | met | `E::test_the_wait_asks_github_once_for_mains_head_ac_143_10`, `E::test_inside_a_run_the_minutes_count_as_waiting_time_ac_143_10`, `E::test_outside_a_run_the_wait_records_its_own_run_ac_143_10` (3 results), `S::test_the_ship_wait_counts_toward_the_run_it_runs_in_ac_143_10`, `S::test_outside_a_run_the_ship_wait_records_its_own_run_ac_143_10` (3 results), `S::test_next_wait_counts_toward_the_system_ship_run_ac_143_10` | `scripts/cplat/waits.py` `attach`, `record`, `_add_wait`; `envwait.wanted_revision` (one `git fetch`, ancestry and pins read locally) | `ship.gh` fails the env tests on any call |
| AC-143.11 | met | `D::test_the_detector_finds_the_loops_the_coordinators_wrote_ac_143_11`, `D::test_no_command_or_agent_polls_with_a_sleep_loop_ac_143_11` (every command and agent file), `D::test_each_command_names_its_wait_and_what_to_do_on_a_timeout_ac_143_11` (8 commands), `D::test_the_release_waits_for_mains_ci_with_cplat_before_the_tag_ac_143_11`, `D::test_the_waits_are_in_the_cplat_usage_and_agents_md_ac_143_11`, `D::test_the_changelog_fragment_exists_ac_143_11`, `R::` (4 tests) | `plugins/component/commands/{set,add,release}.md`, `plugins/instance/commands/promote.md`, `plugins/system/commands/{set,ship}.md`, `plugins/resource/commands/add.md`, `plugins/cluster/commands/add.md`; `comprelease.ci_wait` (`cplat component release wait`); `docs/AGENTS.md`; ADR-082 | the release's CI wait is a commit's run, not a PR: decision 12 |

## Non-goals

No new slash command. `cplat component ship deploy`, `cplat resource upgrade --wait` and `cplat pr wait` are unchanged (the new
waits reuse `ship.workload_images`, `ship.run_logs` and `ship.say`, not their loops). No `/system:status` column, no smoke test in
the wait, no retry or rollback of a failed sync, no Argo CD webhook. `/component:add` with `--expose` now merges its PR on green
CI as `/component:set` does (spec 142); without an exposure it still leaves the PR for review.

## Plan

Every task `done`. Files outside the tasks: the doc tests of specs 129, 138 and 142 (`tests/cplat/test_platrelease_129_docs.py`,
`tests/cplat/test_release_target_138.py`, `tests/cplat/test_142_expose_merge.py`), which assert the replaced Phase 5 wait and
the step numbers of `/component:set`; acceptable, the behaviour they checked is kept (wait before the tag, merge an exposure
without asking).
