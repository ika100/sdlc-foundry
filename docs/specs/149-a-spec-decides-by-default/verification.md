# Verification — 149 A spec decides by default

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-149.1 | `tests/cplat/test_149_decide_by_default.py::test_the_product_manager_decides_by_default_and_asks_four_kinds_ac_149_1` |
| AC-149.2 | `tests/cplat/test_149_decide_by_default.py::test_the_skeleton_has_an_assumptions_section_before_open_questions_ac_149_2`, `tests/cplat/test_149_decide_by_default.py::test_assumptions_never_block_check_or_approval_ac_149_2` |
| AC-149.3 | `tests/cplat/test_149_decide_by_default.py::test_list_and_detail_count_active_and_revised_assumptions_ac_149_3`, `tests/cplat/test_149_decide_by_default.py::test_a_spec_without_the_section_has_none_ac_149_3` |
| AC-149.4 | `tests/cplat/test_149_decide_by_default.py::test_the_spec_commands_show_assumptions_and_ask_once_ac_149_4` |
| AC-149.5 | `tests/cplat/test_149_decide_by_default.py::test_the_built_block_counts_approved_and_revised_assumptions_ac_149_5` |
| AC-149.6 | Journey 6 (2026-11-07, `ika100-demo/taskboard6-*`): step 3 asked one open question (authentication, a security question) and the approval with 6 assumptions; step 6 only the approval with 9 assumptions; no repo-spec question; 3 questions in the run against 20 in journey 5, no assumption revised; recorded in `docs/PERFORMANCE.md`. |
