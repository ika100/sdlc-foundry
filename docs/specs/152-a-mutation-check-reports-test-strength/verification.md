# Verification — 152 A mutation check reports how strong the acceptance tests are

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-152.1 | `tests/cplat/test_152_mutation.py::test_strong_tests_kill_every_mutant_of_the_changed_line_ac_152_1`, `tests/cplat/test_152_mutation.py::test_a_weak_test_lets_the_boundary_mutant_survive_ac_152_1`, `tests/cplat/test_152_mutation.py::test_only_changed_lines_are_mutated_and_the_count_is_capped_ac_152_1` |
| AC-152.2 | `tests/cplat/test_152_mutation.py::test_write_puts_the_report_into_verification_md_once_ac_152_2` |
| AC-152.3 | `tests/cplat/test_152_mutation.py::test_other_shapes_and_specs_without_tests_are_skipped_ac_152_3`, `tests/cplat/test_152_mutation.py::test_red_tests_before_mutation_are_a_setup_error_ac_152_3`, `tests/cplat/test_152_mutation.py::test_the_build_runs_it_after_the_reviewer_and_never_stops_on_it_ac_152_3` |

In practice: journey 6's API builds reported 16 of 17 and 13 of 20 caught mutants in their `verification.md`; the web build (web-nextjs) was skipped; the two runs took about 2 minutes together.
