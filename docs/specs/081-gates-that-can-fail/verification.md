# Verification — 081 Gates that can fail: pinned tools and a doctor check

**Result:** pass
**Base:** b1fb9a6 · **Trace:** 3/3 criteria named by tests · `scripts/ci-local.sh` green: 657 passed, 4 skipped (`pytest -n auto`)

| Criterion | Verdict | Tests |
|---|---|---|
| AC-081.1 | met | `tests/cplat/test_gates.py::test_every_gate_tool_in_the_templates_is_pinned`, `tests/cplat/test_gates.py::test_bump_raises_gate_pins_within_their_line` |
| AC-081.2 | met | `tests/cplat/test_gates.py::test_doctor_passes_real_gates`, `tests/cplat/test_gates.py::test_doctor_flags_gates_that_cannot_fail`, `tests/cplat/test_gates.py::test_doctor_runs_the_gate_checks` |
| AC-081.3 | met | `tests/cplat/test_gates.py::test_adopt_reports_missing_ci_gates` |

## Notes

Python, Java and web gates run from lockfiles (uv, pom, package.json); their devbox binaries are pinned for consistency.

## Deviations from the plan

None; specs 077–084 were implemented in one change with the plans written alongside (all tasks done).
