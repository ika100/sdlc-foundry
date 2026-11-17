# Verification — 191 Upgrades are tested fast, across skipped versions, and the database drill leaves the release gate

**Commit:** 6eb3241 (cycle 2) · **Base:** 5e9d19b · **Trace:** 8/8 criteria named by tests

Phase 3: `devbox run test-fast` 11222 passed; `devbox run ci` green; no acceptance test changed since the red commit except the AC-191.4
tightening (6eb3241, below; the file's 41 tests pass). Since cycle 1 (29d0cb0) only `tests/cplat/test_upgrade_191_render_check.py` changed,
and no code. The cluster jobs (AC-191.5 to AC-191.7) have not run yet: the branch is not pushed.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-191.1 | met | `tests/cplat/test_upgrade_191_render_check.py::test_a_change_kubernetes_refuses_is_reported_as_one_breaking_line_ac_191_1` (14 cases), `::test_an_object_that_holds_data_and_is_gone_is_reported_as_loses_data_ac_191_1` (5), `::test_a_renamed_claim_counts_as_removed_ac_191_1`, `::test_a_generated_secret_that_the_credentials_plan_no_longer_names_is_reported_ac_191_1`, `::test_the_namespace_comes_from_..._ac_191_1`, `::test_findings_are_sorted_by_environment_then_object_and_counted_ac_191_1` | `scripts/upgrade-render-check.py:191-231` (rules, removals, rendered Secrets `:128-145`), `:281-285` (line format, FAILED line, exit 1) | Every field and removal the criterion lists has a case. Each case asserts the exact `BREAKING` line (old/new values, reason, accept hint) and the exact `FAILED: n ..., <tag> -> candidate` line. |
| AC-191.2 | met | `::test_harmless_differences_pass_with_the_ok_line_and_no_container_runtime_ac_191_2`, `::test_a_side_that_does_not_render_exits_2_naming_the_side_and_the_error_ac_191_2` (2) | `scripts/upgrade-render-check.py:70-74` (render error per side), `:286-289` (OK line), `:389-393` (exit 2) | The test covers a new object, an image change, a label/annotation change, a larger size, a set clusterIP and a removed Deployment/Service, and asserts the exact OK line with 9 objects. Fake docker/podman/k3d/kubectl prove that no runtime is called. Exit 2 is asserted with the exact `from-release <tag>` and `candidate` lines. |
| AC-191.3 | met | `::test_a_matching_upgrade_step_line_accepts_the_finding_ac_191_3` (fragment, unreleased, released after tag), `::test_a_line_in_a_release_not_after_the_from_release_does_not_accept_ac_191_3`, `::test_an_unaccepted_finding_fails_and_ends_with_the_accept_hint_ac_191_3`, `::test_a_step_accepts_its_kind_and_field_for_every_object_and_environment_ac_191_3` | `scripts/upgrade-render-check.py:239-263` (changelog range, `STEP` regex `:44`), `:275-282` | Asserted: the exact ACCEPTED line, exit 0 with `(1 accepted)`, the range bound (a line in the from-release's own section does not accept) and the hint ending. |
| AC-191.4 | met | `test_upgrade_191_render_check.py::test_run_mode_prints_one_section_per_from_release_and_ends_ok_ac_191_4`, `::test_run_mode_fails_when_either_section_fails_ac_191_4` (2), `::test_run_mode_a_section_that_does_not_render_exits_2_ac_191_4` (2), `::test_run_mode_compares_once_when_previous_and_oldest_are_the_same_tag_ac_191_4`, `::test_run_mode_says_so_and_passes_when_there_is_no_oldest_release_ac_191_4`, `::test_run_mode_from_options_name_the_sections_ac_191_4`; `test_upgrade_191_release_ci.py::test_the_render_job_runs_the_comparison_within_five_minutes_ac_191_4`, `::test_the_workflow_triggers_cover_the_template_and_the_check_itself_ac_191_4`, `::test_the_render_check_runs_for_the_files_it_reads_ac_191_4` (7), `::test_the_render_check_runs_for_a_new_release_heading_ac_191_4`, `::test_the_render_check_does_not_run_for_a_docs_only_change_ac_191_4`, `::test_nothing_changed_prints_three_false_lines_with_run_last_ac_191_4` | `scripts/upgrade-render-check.py:306-327` (section with `from <tag>:` header, exit 2 per side), `:338-372` (tag list, `compared once` line, final OK/FAILED line, 2 over 1), `scripts/release-check.py:230-243` (`render=`), `.github/workflows/e2e-upgrade.yml:71-84` (job `upgrade render check`, timeout 5, `uv run scripts/upgrade-render-check.py`) | Cycle 2: the run mode is now asserted as behaviour. A copy of the script runs with a stub builder and a stub `release-check.py`. The tests assert exactly two headers, `from v5.3.0:` and `from v5.0.2:`, each with its exact OK line. A break in either section gives exit 1, with the exact BREAKING and FAILED lines in that section only and `upgrade render check: FAILED (from v5.3.0: exit .., from v5.0.2: exit ..)`. A render error gives exit 2. The same tag gives one section and the exact `compared once` line. The job, timeout, triggers and nightly run are asserted as in cycle 1. |
| AC-191.5 | met | `test_upgrade_191_release_ci.py::test_from_tag_previous_is_the_newest_release_tag_not_at_head_ac_191_5`, `::test_from_tag_previous_without_a_tag_fails_naming_the_series_ac_191_5`, `::test_from_tag_oldest_is_the_newest_patch_of_the_first_minor_of_the_major_ac_191_5`, `::test_from_tag_oldest_skips_when_the_major_has_no_first_minor_release_ac_191_5`, `::test_from_tag_oldest_skips_when_it_is_the_previous_release_ac_191_5`, `::test_the_candidate_major_is_the_one_of_a_newer_release_heading_ac_191_5`, `::test_the_oldest_release_job_runs_nightly_and_on_dispatch_only_and_skips_cleanly_ac_191_5`, `::test_the_release_gate_names_neither_the_oldest_nor_the_drill_job_ac_191_5` | `scripts/release-check.py:182-221`, `.github/workflows/e2e-upgrade.yml` job `upgrade-oldest` | The tag rules are asserted as behaviour (v5.0.3 among unsorted tags, both `skipped:` lines, exit 0). The job is asserted from the workflow's structure; the nightly/dispatch run proves the cluster run. |
| AC-191.6 | met | `test_upgrade_191_release_ci.py::test_the_gate_passes_with_both_green_and_ignores_the_oldest_and_drill_jobs_ac_191_6`, `::test_the_gate_refuses_a_tag_missing_either_check_ac_191_6` (4), `::test_the_gate_takes_both_checks_from_the_pull_requests_head_with_the_same_tree_ac_191_6`, `::test_the_gate_refuses_a_head_that_lacks_either_check_ac_191_6` (3), `::test_the_previous_release_job_is_the_platform_update_part_with_a_45_minute_limit_ac_191_6`, `::test_the_builder_creates_and_updates_the_system_without_a_cluster_ac_191_6`, `::test_the_update_script_runs_the_update_part_and_sources_the_builder_ac_191_6`; adapted spec 121 script tests in `test_upgrade_121_ops.py`; `tests/e2e/upgrade.sh` | `scripts/release-check.py:270-301` (gate on two checks), `tests/e2e/upgrade.sh:167-177,567-655,664-702`, `tests/e2e/lib/upgrade-system.sh:58-143` | The gate is asserted as behaviour with exact OK/ERROR lines per check, including a same-tree head. The cluster half is structural here (no backups, no `--to 17`, final checks present), as for AC-121.24. The `e2e upgrade (previous release → candidate)` run on the pull request proves it (plan t6 done-when). |
| AC-191.7 | met | `::test_the_drill_runs_for_the_resource_upgrade_and_backup_code_and_its_own_steps_ac_191_7` (5), `::test_a_change_to_the_drill_steps_alone_does_not_run_the_update_part_ac_191_7`, `::test_the_drill_runs_for_a_changed_database_row_and_not_for_another_row_ac_191_7`, `::test_the_drill_workflow_has_the_designed_triggers_and_permissions_ac_191_7`, `::test_the_drill_job_runs_the_drill_after_a_decide_job_with_a_75_minute_limit_ac_191_7`, `::test_no_job_of_the_upgrade_workflow_is_the_drill_ac_191_7`, `::test_the_drill_script_holds_the_guard_and_the_major_steps_ac_191_7`; `tests/e2e/upgrade-drill.sh` | `scripts/release-check.py:225-241` (`drill=`, database rows), `.github/workflows/e2e-upgrade-drill.yml`, `tests/e2e/upgrade-drill.sh:32-179`, `tests/e2e/upgrade.sh:659-662` | The decisions are asserted as behaviour: a postgres or cnpg row triggers the drill, a keda row does not, and a drill-only change does not run the update part. The cluster steps are structural here; the drill run on the pull request (it touches `upgrade-drill.sh`) proves them. |
| AC-191.8 | met (see Departures) | `::test_contributing_names_the_four_jobs_the_gate_and_how_to_run_them_ac_191_8`, `::test_an_adr_records_the_split_and_amends_adr_069_ac_191_8`, `::test_a_changelog_fragment_lists_the_change_ac_191_8` | `CONTRIBUTING.md:118-125`, `docs/adr/116-upgrade-tests-split-a-fast-release-gate-from-nightly-runs.md`, `docs/adr/069-...md:4`, `docs/changelog.d/191-upgrade-render-check.changed.md` | The guide names the four jobs, when each runs, the two the gate requires, the `Upgrade step:` acceptance and the local commands. The duration is still to be recorded (below). |

## Duration of `e2e upgrade (previous release → candidate)` (AC-191.8)

| Run | Duration | Source |
|---|---|---|
| before (spec 121, after #401/#483) | 22–25 min | spec 191, Problem |
| pull request shipping spec 191 | **pending**: fill in from the job's `Total:` line once CI has run | design.md, Verification note |

Target: at most 15 minutes (recorded, not asserted).

## Departures

- AC-191.8 is judged `met` although the PR duration is pending. The criterion asks for a number from the pull request that ships this file, so it cannot be measured before that PR exists. The ship step must fill in the row above.
- AC-191.5 to AC-191.7 are judged `met` on structural tests of the cluster scripts and workflows. Their outcome needs a k3d cluster (15–40 minutes per run); the CI jobs on the pull request are the behavioural proof.

## Non-goals

No Argo CD in the test (`WITH_ARGO=0` kept), no Java/Go/web components, no downgrade testing, no faster cluster setup. The existing checks were moved into `upgrade-drill.sh` and `final_checks`, not changed. No template-owned layout changed. ✔

## Deviations from the plan

- `docs/adr/116-upgrade-tests-split-a-fast-release-gate-from-nightly-runs.md` is in no task's `files`. t7's notes create it with `cplat adr add`. Acceptable.
- `tests/cplat/test_154_journey_6_findings.py` is in no task's `files`. The AC-154.1 retry test now feeds a green render check and expects 3 `gh` calls (one dropped call, one read per required check) instead of 2. Its retry assertion is unchanged, so this follows the two-check gate. Acceptable.
- `tests/cplat/test_upgrade_121_ops.py`: the spec 121 tests were adapted as t1/t5/t6 planned (render check in the green fixtures, the 45-minute timeout, the three e2e files read together, the new header needles). The tag rule's needles (`v5.0.*`, `versions.py`) left the script and are now covered by the AC-191.5 tests. Acceptable.
- Run mode: the real `from-tag oldest` returns `skipped: <tag> is the previous release` for an equal tag, so the `previous and oldest supported release are both <tag>: compared once` branch (`upgrade-render-check.py:350-351`) is unreachable in the default mode with the real `release-check.py`. The new AC-191.4 test reaches it through a stub that returns the tag. In production the run still compares once and says so, through the `skipped:` line. Acceptable. The two design lines overlap.
- `CONTRIBUTING.md:118` still says before `git tag` the gate "needs a green upgrade e2e … on that commit". The new text after it says both checks. This is a stale half-sentence; acceptable, but worth aligning.
- The fragment's `Upgrade step: ExternalSecret object: …` line accepts every removed ExternalSecret from every from-release before it, for as long as the line is in range. That is always the case for the oldest-release run within major 5, so a real ExternalSecret removal that loses data would pass silently. The removed target Secret is still reported unless a `plan.json` names it. This is the spec's kind-and-field acceptance (AC-191.3, A4); the risk is noted. This read-only review did not re-run `uv run scripts/upgrade-render-check.py` to check that it exits 0 on this branch (t7 done-when).
- `tests/e2e/upgrade.sh:168`: when `from-tag previous` exits 1, `set -e` stops the script at the assignment. The `fail "no previous release tag found"` on line 169 never runs, and the `ERROR:` line is swallowed into `$FROM`. This affects diagnostics only; acceptable.
- `scripts/release-check.py:47`: `E2E_PATHS =(` is missing a space (cosmetic).

## Contract

Matches `design.md`: the compare and run lines, exit codes 0/1/2, the `from-tag` lines, the three decide lines with `run=` last, the gate's per-check lines, and the job names, triggers, timeouts (2/5/45/60, drill 2/75), permissions and concurrency. One exception is the overlapping "compared once" line noted above. ✔

## Tightened acceptance tests

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_upgrade_191_render_check.py` (6eb3241) | AC-191.4's run mode was only regex-matched against the script source (cycle 1: TEST LOOSER). Six run-mode tests (9 cases) now run a copy of the script with a stub builder and a stub `release-check.py`. | Yes: one `from <tag>:` section per from-release, failure when either fails (exit 1, or 2 for a render error), one section and the `compared once` line for the same tag, and the exact last line. The older source-regex test stays but is redundant. |

## Unresolved test-review findings

None (6 findings, all resolved).

## Not met

None.

**Result:** pass

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
