# Verification — 159 Unit mode runs independent tasks at once

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-159.1 | `tests/cplat/test_159_batch_units.py::test_independent_tasks_share_a_batch_unit_and_a_dependent_one_follows_ac_159_1_ac_159_5`, `tests/cplat/test_159_batch_units.py::test_a_batch_holds_at_most_parallel_tasks_ac_159_1`, `tests/cplat/test_159_batch_units.py::test_tasks_sharing_a_file_never_share_a_batch_ac_159_1`, `tests/cplat/test_159_batch_units.py::test_headless_passes_parallel_to_units_and_sessions_ac_159_1` |
| AC-159.2 | `tests/cplat/test_159_batch_units.py::test_a_batch_is_done_only_when_all_its_tasks_are_ac_159_2`, `tests/cplat/test_159_batch_units.py::test_the_next_step_of_a_batch_names_its_tasks_and_the_merge_ac_159_2`, `tests/cplat/test_159_batch_units.py::test_the_batch_unit_runs_build_phase_2s_parallel_batch_ac_159_2_ac_159_3_ac_159_7` |
| AC-159.3 | `tests/cplat/test_159_batch_units.py::test_a_batch_session_without_progress_stalls_as_any_unit_ac_159_4`, `tests/cplat/test_159_batch_units.py::test_the_batch_unit_runs_build_phase_2s_parallel_batch_ac_159_2_ac_159_3_ac_159_7` |
| AC-159.4 | `tests/cplat/test_159_batch_units.py::test_a_partly_done_batch_runs_again_for_the_rest_and_is_no_stall_ac_159_4`, `tests/cplat/test_159_batch_units.py::test_a_batch_session_without_progress_stalls_as_any_unit_ac_159_4` |
| AC-159.5 | `tests/cplat/test_159_batch_units.py::test_independent_tasks_share_a_batch_unit_and_a_dependent_one_follows_ac_159_1_ac_159_5`, `tests/cplat/test_159_batch_units.py::test_a_task_not_parallel_safe_is_a_unit_of_its_own_ac_159_5` |
| AC-159.6 | `tests/cplat/test_159_batch_units.py::test_a_ship_runs_one_session_for_the_batch_ac_159_1_ac_159_6` |
| AC-159.7 | `tests/cplat/test_159_batch_units.py::test_a_batch_session_without_progress_stalls_as_any_unit_ac_159_4`, `tests/cplat/test_159_batch_units.py::test_the_batch_unit_runs_build_phase_2s_parallel_batch_ac_159_2_ac_159_3_ac_159_7` |
| AC-159.8 | `tests/cplat/test_159_batch_units.py::test_parallel_1_keeps_one_unit_per_task_ac_159_8` |
