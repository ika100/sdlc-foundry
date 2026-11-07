# Verification — 150 The house rules run before the PR

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-150.1 | `tests/cplat/test_150_pr_check.py::test_a_clean_branch_passes_every_rule_ac_150_1`, `tests/cplat/test_150_pr_check.py::test_each_broken_rule_is_one_error_line_ac_150_1` |
| AC-150.2 | `tests/cplat/test_150_pr_check.py::test_a_feat_that_changes_code_needs_a_fragment_ac_150_2`, `tests/cplat/test_150_pr_check.py::test_other_kinds_need_no_fragment_ac_150_2`, `tests/cplat/test_150_pr_check.py::test_a_bad_fragment_is_named_ac_150_2` |
| AC-150.3 | `tests/cplat/test_150_pr_check.py::test_fix_shortens_a_long_title_and_checks_that_one_ac_150_3` |
| AC-150.4 | `tests/cplat/test_150_pr_check.py::test_pr_open_runs_only_the_fragment_and_version_rules_ac_150_4`, `tests/cplat/test_150_pr_check.py::test_pr_open_refuses_before_the_push_ac_150_4` |
| AC-150.5 | `tests/cplat/test_150_pr_check.py::test_outside_the_platform_repo_it_points_to_pr_open_ac_150_5` |
