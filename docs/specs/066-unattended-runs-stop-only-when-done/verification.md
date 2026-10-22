# Verification — 066 Unattended runs stop only when done or blocked

**Result:** pass
**Base:** decbfbc · **Trace:** 3/3 criteria named by tests · `pytest tests/cplat`: 563 passed, 3 skipped

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-066.1 | met | `tests/cplat/test_ship.py::test_an_unfinished_run_blocks_with_the_next_step, ::test_the_build_phase_reports_what_is_still_red, ::test_gate_cli_reads_the_hook_input` | `scripts/cplat/ship.py gate(), build_status()` | hook output format follows Claude Code's Stop hook contract (decision/reason); not exercised in a live session here |
| AC-066.2 | met | `tests/cplat/test_ship.py::test_escalation_finish_and_the_block_cap_let_the_session_stop` | `scripts/cplat/ship.py gate(), start()` |  |
| AC-066.3 | met | `tests/cplat/test_ship.py::test_no_run_never_blocks, ::test_the_stop_hook_only_starts_cplat_when_a_run_exists` | `plugins/shared/hooks/hooks.json (Stop)` |  |

## Non-goals

No SubagentStop hook. ✔

## Deviations from the plan

None; the specs were implemented in one change with the plan written alongside (all tasks done).
