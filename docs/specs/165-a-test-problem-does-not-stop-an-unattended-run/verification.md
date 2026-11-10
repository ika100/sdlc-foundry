# Verification — 165 A test problem does not stop an unattended run

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-165.1 | `tests/cplat/test_165_test_problems.py::test_a_stricter_test_is_a_tightening_ac_165_1`, `tests/cplat/test_165_test_problems.py::test_a_weakened_test_is_refused_with_the_reason_ac_165_1`, `tests/cplat/test_165_test_problems.py::test_a_new_skip_is_refused_in_every_language_ac_165_1` |
| AC-165.2 | `tests/cplat/test_165_test_problems.py::test_a_later_change_to_a_tightened_test_is_checked_again_ac_165_2`, `tests/cplat/test_165_test_problems.py::test_the_cli_needs_a_reason_and_exits_1_on_a_refusal_ac_165_2` |
| AC-165.3 | `tests/cplat/test_165_test_problems.py::test_the_pr_block_names_a_tightened_test_apart_from_an_approval_ac_165_3`, `tests/cplat/test_165_test_problems.py::test_the_cli_records_the_tightening_in_the_run_record_ac_165_3` |
| AC-165.4 | `tests/cplat/test_165_test_problems.py::test_the_build_tightens_a_looser_test_and_the_reviewer_marks_and_lists_it_ac_165_4` |
| AC-165.5 | `tests/cplat/test_165_test_problems.py::test_phase_1_runs_the_e2e_acceptance_tests_once_before_freezing_them_ac_165_5` |
| AC-165.6 | `tests/cplat/test_165_test_problems.py::test_the_web_tester_never_starts_the_app_inside_a_test_ac_165_6` |
| AC-165.7 | `tests/cplat/test_165_test_problems.py::test_a_test_that_passes_alone_is_flaky_and_the_run_goes_on_ac_165_7`, `tests/cplat/test_165_test_problems.py::test_a_failing_rerun_keeps_the_first_result_ac_165_7`, `tests/cplat/test_165_test_problems.py::test_other_scripts_and_other_failures_are_never_rerun_ac_165_7` |

Journey 8 (v5.15.0) used the tighten path once; it refused a valid tightening (two new tests naming their criterion), fixed by spec 169 (AC-169.3, #611).
