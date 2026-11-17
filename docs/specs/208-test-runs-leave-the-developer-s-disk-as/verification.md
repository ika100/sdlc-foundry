# Verification — 208 Test runs leave the developer's disk as they found it

**Result:** fail
**Commit:** 4dc057df · **Base:** e642dd43 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-208.1 | met | `tests/cplat/test_208_runtemp.py::test_inline_script_envs_lie_in_the_runs_own_cache_ac_208_1` (serial/xdist x passing/failing), `::test_the_developers_cache_location_of_any_kind_is_protected_ac_208_1`, `::test_the_conftest_loads_the_plugin_so_every_entry_point_is_protected_ac_208_1` | `tests/cplat/runtemp.py:143-159` (run's `UV_CACHE_DIR`/`PYTEST_DEBUG_TEMPROOT`), `:282-285` + `:249-251` (workers), `tests/cplat/conftest.py:12` | Asserts the developer cache snapshot is unchanged (entries, size, mtime), one run-owned cache for all workers, inherited by subprocesses. Every entry point (`devbox.json:32`, `scripts/test-fast.sh`, `scripts/ci-local.sh:59`, `ci.yml:193`) runs `pytest tests/cplat…`, so the conftest loads the plugin. |
| AC-208.2 | met | `tests/cplat/test_208_e2e_uv_cache.py::test_a_script_that_fails_early_leaves_the_developers_cache_and_removes_its_own_ac_208_2` (run/cluster/upgrade), `::test_each_script_sources_the_lib_and_ends_the_cache_in_cleanup_ac_208_2`, `::test_the_lib_*` | `tests/e2e/lib/uv-cache.sh:10-20`, `tests/e2e/run.sh:79-81,114`, `cluster.sh` / `upgrade.sh` (same pattern) | Only the failing path runs the scripts end to end. The passing path goes through the same `cleanup` trap, and the structure test shows the end call sits outside the `E2E_KEEP` block and before `exit $rc`. |
| AC-208.3 | met | `test_208_runtemp.py::test_a_passing_run_leaves_nothing_under_the_temp_root_ac_208_3` (nested pytest + shared-renders), `::test_a_passing_run_leaves_earlier_runs_untouched_ac_208_3`, `::test_a_run_without_tests_passes_and_leaves_nothing_ac_208_3` | `runtemp.py:184-185`, `:199-202`, `:87-125` | |
| AC-208.4 | met | `failed_run` fixture (serial + xdist) with `::test_a_failing_run_leaves_only_failed_and_its_bookkeeping_ac_208_4`, `::test_the_failed_tests_of_every_phase_keep_their_directories_ac_208_4`, `::test_the_directories_of_passed_tests_are_gone_ac_208_4`, `::test_a_failing_run_says_where_it_kept_the_files_ac_208_4`, `::test_an_interrupted_run_counts_as_failing_…_ac_208_4`, `::test_a_collection_error_leaves_an_empty_failed_directory_ac_208_4` | `runtemp.py:209-238` (`failed/<slug>/`, slug per design), `:262-273` (manifest), `:299-301` | Setup, call, teardown and timeout failures each keep exactly their marker. The uv cache, tmp, temproot, manifest and shared-renders are gone. |
| AC-208.5 | met | `::test_the_oldest_of_four_failing_runs_is_removed_ac_208_5`, `::test_there_are_never_leftovers_of_more_than_three_runs_ac_208_5`, `::test_passing_runs_do_not_push_failing_leftovers_out_ac_208_5`, `::test_an_orphan_is_settled_and_counts_as_a_failing_run_ac_208_5` | `runtemp.py:87-125`, `KEEP_FAILING_RUNS` at `:29` | |
| AC-208.6 | met | `::test_a_run_that_ends_leaves_an_overlapping_run_alone_ac_208_6`, `::test_a_live_run_is_never_touched_by_cleanup_or_retention_ac_208_6`, `::test_a_live_failed_looking_run_does_not_count_toward_removal_ac_208_6`, `::test_concurrent_runs_get_their_own_directory_and_cache_ac_208_6` | `runtemp.py:165-177` (flock, staging rename), `:96-99` and `:119-123` (live skip) | The overlapping run's own assertions pass after the others' cleanup (result same as alone). |
| AC-208.7 | not met | `::test_the_plugin_adds_no_per_test_work_beyond_listing_a_directory_ac_208_7` | `runtemp.py:262-273` | TEST LOOSER: the test checks a proxy (two manifest lines per test, no extra files), not wall time. The criterion needs both full-run wall times measured and recorded in the PR, at most 10 % apart. Commit 4dc057df says the timing "could not be measured", and the phase-3 full run was cut at 47 %. No numbers exist. |

## Non-goals

No change to `scripts/cplat` (cplat's own `uv run` is unchanged), to templates, or to size limits for the general uv cache. Leftovers from before the change are not removed: retention globs only `cplat-run-*` (`runtemp.py:90`). No caching between runs. No template-owned layout touched. ✔

## Deviations from the plan

- None in files. Every changed file is in a task's `files` (t1: `runtemp.py`, `conftest.py`; t2: `runtemp.py`, `CONTRIBUTING.md`, changelog fragment; t3: e2e lib + 3 scripts). The test files are the acceptance tests. All tasks are `done: true`.
- t2's "Done when" asks for both AC-208.7 timings in the PR body. They are not measured yet (see AC-208.7). Not acceptable until recorded.
- Observation, not a failure: `pytest_plugins` in `tests/cplat/conftest.py` is only allowed while that conftest is an initial conftest. A run of `pytest tests` from the repo root (not one of AC-208.1's entry points) would stop with pytest's "non-top-level conftest" error.

## Contract

Matches `design.md`: paths, `run.json`, manifest format, pass/fail rules, slug, stderr line, retention order, explicit `--basetemp`, and the e2e lib functions. ✔
