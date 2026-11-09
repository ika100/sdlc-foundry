# Verification — 156 A system ship benchmark

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-156.1 | `tests/cplat/test_156_system_benchmark.py::test_usage_registrations_of_several_project_dirs_are_all_kept_ac_156_1`, `tests/cplat/test_156_system_benchmark.py::test_the_benchmark_command_dispatches_system_ship_ac_156_1`, `tests/cplat/test_156_system_benchmark.py::test_the_task_pins_a_gitops_repo_and_three_components_with_their_revisions_ac_156_1_ac_156_2`, `tests/cplat/test_156_system_benchmark.py::test_the_entry_pr_needs_no_body_file_ac_156_1` |
| AC-156.2 | `tests/cplat/test_156_system_benchmark.py::test_the_task_pins_a_gitops_repo_and_three_components_with_their_revisions_ac_156_1_ac_156_2`, `tests/cplat/test_156_system_benchmark.py::test_the_pinned_plan_has_independent_repos_and_an_ordering_ac_156_2` |
| AC-156.3 | `tests/cplat/test_156_system_benchmark.py::test_until_repos_needs_no_kube_context_ac_156_3`, `tests/cplat/test_156_system_benchmark.py::test_until_repos_ends_done_after_the_repos_and_lands_nothing_ac_156_3`, `tests/cplat/test_156_system_benchmark.py::test_a_resumed_run_keeps_until_ac_156_3`, `tests/cplat/test_156_system_benchmark.py::test_an_unknown_until_is_refused_ac_156_3` |
| AC-156.4 | `tests/cplat/test_156_system_benchmark.py::test_without_until_the_run_still_lands_ac_156_3`, `tests/cplat/test_156_system_benchmark.py::test_repo_numbers_count_wall_agent_tokens_sessions_and_parallel_subagents_ac_156_4`, `tests/cplat/test_156_system_benchmark.py::test_overlap_is_the_components_wall_clock_over_the_runs_ac_156_4`, `tests/cplat/test_156_system_benchmark.py::test_the_report_names_every_repo_and_the_spread_ac_156_4` |
| AC-156.5 | `tests/cplat/test_156_system_benchmark.py::test_a_difference_inside_the_spread_is_no_gain_ac_156_5`, `tests/cplat/test_156_system_benchmark.py::test_a_difference_beyond_the_spread_is_reported_ac_156_5`, `tests/cplat/test_156_system_benchmark.py::test_one_run_per_side_is_never_a_result_ac_156_5`, `tests/cplat/test_156_system_benchmark.py::test_the_stored_report_groups_by_plugins_tree_and_compares_the_last_two_ac_156_5` |
| AC-156.6 | `tests/cplat/test_156_system_benchmark.py::test_the_sample_differs_from_the_journey_system_ac_156_6` |
| AC-156.7 | `tests/cplat/test_156_system_benchmark.py::test_the_eval_gate_does_not_require_the_system_benchmark_ac_156_7` |
