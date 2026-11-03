# Verification — 134 A pull request runs only the e2e it needs, and that e2e runs in parallel parts

**Result:** pass (AC-134.7 measured on this pull request's own e2e run, see below)
**Trace:** 9/9 criteria named by tests

Tests: `S` = `tests/cplat/test_e2e_scope_134.py`, `P` = `tests/cplat/test_e2e_parts_134.py`, `W` = `tests/cplat/test_e2e_workflows_134.py`,
`D` = `tests/cplat/test_e2e_docs_134.py`. The cluster run itself happens only in the e2e workflow (GitHub-hosted runners); `actionlint`
and `scripts/pin-actions.py --check` pass on both workflows.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-134.1 | met | `W::test_the_e2e_workflow_has_no_pr_path_filter_and_a_decide_job_ac_134_1`, `W::test_every_cluster_job_needs_decide_and_runs_on_true_or_a_schedule_ac_134_1` | `.github/workflows/e2e.yml:8-14` (no `paths`), `:25-40` (decide), `:45`, `:71` (`if`) | The `needs` step runs only on `pull_request`; on schedule and dispatch the `if` of the jobs does not read it |
| AC-134.2 | met | `S::test_a_path_the_e2e_exercises_triggers_it_ac_134_2` (20 paths), `S::test_a_path_the_e2e_does_not_exercise_does_not_trigger_it_ac_134_2` (17 paths), `S::test_a_new_release_heading_is_the_release_pull_request_ac_134_2`, `S::test_the_cli_decides_on_the_diff_against_base_ac_134_2`, `S::test_the_cli_runs_for_a_release_heading_ac_134_2`, `S::test_an_unknown_base_is_one_error_line_not_a_traceback_ac_134_2` | `scripts/e2e-scope.py:24-25`, `:104-135` (rule), `:138-144` (heading), `:161-168` (diff against `--base`), `:171-190` (CLI) | Data files and non-package directories of `scripts/cplat` (`assets/`, `prices.json`) trigger: the safe side |
| AC-134.3 | met | `S::test_the_exercised_set_holds_the_modules_the_e2e_scripts_call_and_import_ac_134_3`, `S::test_the_exercised_set_follows_imports_inside_functions_ac_134_3`, `S::test_modules_the_e2e_never_reaches_are_not_in_the_set_ac_134_3`, `S::test_the_set_is_computed_from_the_scripts_at_head_not_a_list_ac_134_3`, `S::test_list_prints_the_set_one_name_per_line_ac_134_3` | `scripts/e2e-scope.py:32-101` (`NOUNS`/`PLUMBING` read with `ast.literal_eval`, `ast.walk` over every member) | 64 of 103 modules and packages today (`--list`); memoised per file stat, so the 40-PR test computes it once |
| AC-134.4 | met | `W::test_the_upgrade_e2e_decides_on_the_pull_requests_base_ac_134_4`; the existing `tests/cplat/test_upgrade_121_ops.py` workflow and `needs-upgrade-e2e` tests still pass | `.github/workflows/e2e-upgrade.yml:57-60` (`${BASE:+--base "$BASE"}`) | On the last 40 commits of main, deciding on each commit's own diff runs the upgrade e2e for 8, deciding against the latest tag for 21 |
| AC-134.5 | met | `P::test_an_unknown_part_fails_before_the_cluster_starts_ac_134_5`, `P::test_in_part_selects_a_block_for_all_or_a_listed_part_ac_134_5`, `P::test_the_shared_setup_runs_in_every_part_ac_134_5`, `P::test_each_scenario_runs_in_its_parts_ac_134_5` (14 scenario prefixes), `P::test_every_step_runs_in_at_least_one_part_ac_134_5` | `tests/e2e/run.sh:55-67` (check and `in_part`), guards `:200`, `:510`, `:947`, `:1373`, `:2024`, `:2099`, each closed by `fi  # end part` | `all` runs the old sequence; the one added line (`:1955`) commits a dirty tree before the broker removal and is a no-op after the scaling steps, which end on a clean tree |
| AC-134.6 | met | `W::test_the_e2e_job_is_three_parts_on_a_pr_and_all_otherwise_ac_134_6`, `W::test_the_cluster_job_is_unchanged_but_for_decide_ac_134_6` | `.github/workflows/e2e.yml:42-66` | |
| AC-134.7 | met | `P::test_the_two_longest_scenarios_run_in_different_parts_and_not_in_core_ac_134_7` (the structure); run 41673840772 of this pull request (below) | `.github/workflows/e2e.yml:42-66`; the guards in `tests/e2e/run.sh` | decide 11 s + longest part 1478 s = 1489 s ≤ 1620 s; first start to last end 1711 s, of which 253 s waiting for a runner |
| AC-134.8 | met | `S::test_fewer_of_the_last_40_pull_requests_start_the_cluster_e2e_ac_134_8` (fixture `tests/cplat/fixtures/e2e_scope_134_prs.json`) | `scripts/e2e-scope.py:121-135` | 19 of 40 start it under the new rule against 23 under the old path filter; 3 of the 19 are release pull requests, which did not run it before |
| AC-134.9 | met | `D::test_contributing_states_the_e2e_rules_ac_134_9`, `D::test_adr_080_is_written_and_indexed_ac_134_9`, `D::test_the_changelog_lists_the_change_ac_134_9` | `CONTRIBUTING.md:46`, `:97`, `:101`; `docs/adr/080-a-pull-request-runs-only-the-e2e-it-needs.md`; `docs/CHANGELOG.md` `[Unreleased]` | |

## AC-134.7: timings

Before (10 runs each, 2026-11-03): the e2e workflow ran one job, median 2458 s (41 min, min 2351, max 2561); the job started within
5 s of the workflow.

After, run 41673840772 of this pull request (all jobs green):

| Job | Queued for a runner | Ran | Sum of its `==>` steps |
|---|---|---|---|
| does this change need the cluster e2e | 12 s | 11 s | |
| e2e cluster (two systems, one operator) | 62 s | 130 s | |
| e2e core | 120 s | 1321 s (22.0 min) | 1282 s |
| e2e scaling | 253 s | 1447 s (24.1 min) | 1435 s |
| e2e backups | 85 s | 1478 s (24.6 min) | 1464 s |

The longest part ran 1478 s against 2458 s before (-40 %). From the first job's start to the last job's end: 1711 s (28.5 min), of
which 253 s the scaling part waited for a runner while other pull requests' jobs held the account's concurrent runners; without that
wait the run takes decide 11 s + 1478 s = about 1490 s. Largest steps per part: core: cluster up 271 s, promote to staging 179 s,
images 128 s; scaling: the scale-down wait 345 s, cluster up 239 s; backups: cluster up 242 s, backup apply 210 s, database switch
153 s, environment restore 152 s.
