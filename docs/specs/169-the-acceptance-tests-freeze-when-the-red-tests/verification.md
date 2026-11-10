# Verification — 169 The acceptance tests freeze when the red-tests unit ends

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-169.1 | `tests/cplat/test_169_red_freeze.py::test_a_test_commit_inside_the_red_tests_unit_is_frozen_ac_169_1`, `tests/cplat/test_169_red_freeze.py::test_a_later_change_is_still_flagged_against_the_unit_end_ac_169_1` |
| AC-169.2 | `tests/cplat/test_169_red_freeze.py::test_without_a_finished_red_tests_unit_the_given_base_holds_ac_169_2`, `tests/cplat/test_169_red_freeze.py::test_a_unit_commit_off_the_branch_is_ignored_ac_169_2` |
| AC-169.3 | `tests/cplat/test_169_red_freeze.py::test_a_new_test_naming_its_criterion_is_a_tightening_ac_169_3` |
| AC-169.4 | `tests/cplat/test_169_red_freeze.py::test_an_escalation_saved_before_the_session_started_is_the_run_before_ac_169_4` |

Found and fixed during journey 8 (#611).
