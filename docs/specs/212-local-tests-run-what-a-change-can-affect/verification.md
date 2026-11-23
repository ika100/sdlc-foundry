# Verification — 212 Local tests run what a change can affect

**Result:** pass
**Commit:** 48ad5509 · **Base:** e781d399 · **Trace:** 7/9 criteria named by tests (`tests/cplat/test_212_select.py`); AC-212.8 and AC-212.9 are measurements on the real suite, recorded below and in the pull request

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-212.1 | met | `test_a_changed_module_selects_exactly_the_test_files_that_depend_on_it_and_says_so_ac_212_1`, `test_changed_new_and_previously_red_test_files_are_selected_ac_212_1`, `test_a_file_below_a_subprocess_argument_selects_the_test_that_handed_it_over_ac_212_1`, `test_a_selection_runs_only_its_test_files_and_an_empty_one_passes_with_nothing_run_ac_212_4` | `scripts/testselect.py` (`plan`, `Index`, `message`), `tests/cplat/depsmap.py` (`pytest_ignore_collect`) | Exact selected lists and the message line asserted; the selection runs inside pytest (`--deps-select`). |
| AC-212.2 | met | `test_a_recorded_map_holds_imports_reads_listings_subprocess_arguments_and_cplat_children_ac_212_2`, `test_a_map_recorded_with_workers_holds_the_same_cross_test_dependencies_ac_212_2`, `test_the_real_cplat_records_its_command_module_when_started_from_a_recorded_run_ac_212_2` | `scripts/cplat/depstrace.py`, `scripts/cplat/cplat.py` (child record), `tests/cplat/depsmap.py`, `tests/cplat/shared_render.py` | Static and lazy imports, opens, listings, subprocess trees, cplat child processes, session fixtures and shared renders set up by another test; serial and with 2 workers; autouse patch imports not counted. |
| AC-212.3 | met | `test_without_a_map_the_whole_suite_runs_and_records_one_ac_212_3`, `test_a_change_to_a_shared_file_runs_the_whole_suite_ac_212_3` (6 files), `test_a_module_conftest_imports_at_module_level_is_shared_ac_212_3`, `test_changed_code_no_test_reads_runs_the_whole_suite_and_an_unread_page_runs_nothing_ac_212_3`, `test_a_selection_of_more_than_half_the_test_files_runs_the_whole_suite_ac_212_3`, `test_an_interrupted_or_empty_run_records_no_map_ac_212_3` | `scripts/testselect.py` (`plan`, `shared_files`, `code_like`) | |
| AC-212.4 | met | `test_test_fast_selects_without_arguments_records_with_full_and_runs_given_tests_as_before_ac_212_4`, `test_test_fast_says_why_it_runs_nothing_when_no_test_file_can_see_the_change_ac_212_4`, `test_a_selection_runs_only_its_test_files_and_an_empty_one_passes_with_nothing_run_ac_212_4`; unchanged `test_172_quiet.py` | `devbox.json` (`test-fast`, `test`), `scripts/test-fast.sh` unchanged | The real recipe from devbox.json runs with a fake uv; arguments go to test-fast.sh exactly as before (AC-172.3 tests unchanged and green). |
| AC-212.5 | met | `test_ci_local_selects_unless_full_and_keeps_its_other_steps_ac_212_5` (5 flag orders), `test_ci_local_refuses_an_unknown_flag_ac_212_5` | `scripts/ci-local.sh` | Real ci-local.sh among fakes. |
| AC-212.6 | met | `test_the_change_set_holds_committed_staged_unstaged_untracked_and_recorded_dirty_files_ac_212_6`, `test_the_map_with_the_fewest_changes_is_used_and_bad_or_foreign_maps_are_ignored_ac_212_6`, `test_a_map_recorded_in_one_worktree_serves_another_ac_212_6`, `test_at_most_five_maps_are_kept_and_two_recordings_at_once_leave_readable_maps_ac_212_6` | `scripts/testselect.py` (`changed_files`, `load_maps`), `tests/cplat/depsmap.py` (`write_map`, `prune`) | |
| AC-212.7 | met | `test_a_plain_run_writes_no_map_or_trace_and_adds_no_variable_ac_212_7`, `test_ci_runs_the_whole_suite_without_recording_ac_212_7` | `tests/cplat/depsmap.py` (nothing registered without the option) | |
| AC-212.8 | met | measurement | | Same machine and commit, alternated: recording 469 s and 472 s, plain 449 s and 468 s (+2.6 % on average, limit 15 %). Map of 531 test files: median cplat module is a dependency of 11.8 % of them (limit 20 %). |
| AC-212.9 | met | measurement | | `apilist.main` raises: 42 of 531 selected, 1 newly failing file, selected. `settings.kube_context` raises: reaches 421 of 531 files, so the whole suite runs (26 newly failing files, all run). A checked line of `release.md` changed: 53 selected, 1 newly failing file, selected. No miss. |

## Non-goals

- CI's test jobs and shards unchanged (`.github/workflows/ci.yml` not touched). ✔
- File-level selection only; templates' recipes, `cplat validate`, e2e and site tests untouched; the suite itself not made faster. ✔

## Deviations from the plan

- The selection runs inside pytest (`--deps-select`), not in `test-fast.sh`: the literal suite line stays in `devbox.json` and `ci-local.sh`, where the pin check (spec 127), the timeout check (spec 185) and the suite-command tests (specs 084, 112, 184) read it, so none of them changed. `test-fast.sh` is unchanged.

## Observed while measuring

- During two of the full runs, about 15 test files reached the real `gh`, met this account's GitHub rate limit and slept in `core`'s retry (over 300 s), failing in recording and plain runs alike. A test isolation gap, not part of this change.
