# Verification — 160 A lint suppression in an acceptance test is not a changed test

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-160.1 | `tests/cplat/test_160_lint_suppressions.py::test_a_rule_named_line_suppression_is_accepted_ac_160_1`, `tests/cplat/test_160_lint_suppressions.py::test_python_suppressions_are_named_too_ac_160_1`, `tests/cplat/test_160_lint_suppressions.py::test_an_existing_suppression_kept_and_one_added_is_accepted_ac_160_1`, `tests/cplat/test_160_lint_suppressions.py::test_test_diff_names_the_suppression_and_refuses_a_rule_less_one_ac_160_1_ac_160_2` |
| AC-160.2 | `tests/cplat/test_160_lint_suppressions.py::test_a_code_change_a_rule_less_or_file_wide_suppression_is_refused_ac_160_2`, `tests/cplat/test_160_lint_suppressions.py::test_a_removed_suppression_is_not_suppression_only_ac_160_2`, `tests/cplat/test_160_lint_suppressions.py::test_test_diff_names_the_suppression_and_refuses_a_rule_less_one_ac_160_1_ac_160_2` |
| AC-160.3 | `tests/cplat/test_160_lint_suppressions.py::test_a_comment_that_is_no_suppression_stays_formatting_in_python_ac_160_1`, `tests/cplat/test_160_lint_suppressions.py::test_every_coder_may_suppress_a_false_positive_by_rule_ac_160_3` |
| AC-160.4 | `tests/cplat/test_160_lint_suppressions.py::test_a_comment_that_is_no_suppression_stays_formatting_in_python_ac_160_1`, `tests/cplat/test_160_lint_suppressions.py::test_the_reviewer_lists_each_suppression_in_verification_ac_160_4` |
