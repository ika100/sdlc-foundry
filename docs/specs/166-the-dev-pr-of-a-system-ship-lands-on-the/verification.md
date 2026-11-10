# Verification — 166 The dev PR of a system ship lands on the current main

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-166.1 | `tests/cplat/test_166_joint_pr_refresh.py::test_main_merged_meanwhile_is_kept_when_the_dev_pr_lands_ac_166_1` |
| AC-166.2 | `tests/cplat/test_166_joint_pr_refresh.py::test_a_conflict_in_a_rendered_pin_takes_main_and_pins_the_run_again_ac_166_2` |
| AC-166.3 | `tests/cplat/test_166_joint_pr_refresh.py::test_a_later_build_on_main_is_kept_and_reported_as_what_dev_runs_ac_166_3` |
| AC-166.4 | `tests/cplat/test_166_joint_pr_refresh.py::test_a_conflict_in_system_yaml_escalates_without_merging_ac_166_4` |

Journey 8 (v5.15.0): the system ship's dev PR (#9) landed through `cplat system ship land` without a hand merge.
