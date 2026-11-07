# Verification — 151 Prompt changes pass the benchmark before a release

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-151.1 | `tests/cplat/test_151_eval_gate.py::test_no_prompt_change_needs_no_benchmark_ac_151_1` |
| AC-151.2 | `tests/cplat/test_151_eval_gate.py::test_a_prompt_change_without_a_benchmark_fails_with_the_command_ac_151_2`, `tests/cplat/test_151_eval_gate.py::test_a_benchmark_of_these_prompts_passes_and_another_tree_does_not_ac_151_2` |
| AC-151.3 | `tests/cplat/test_151_eval_gate.py::test_a_failed_or_costly_benchmark_fails_the_gate_ac_151_3` |
| AC-151.4 | `tests/cplat/test_151_eval_gate.py::test_the_release_stops_before_its_branch_and_skip_eval_overrides_ac_151_4` |
