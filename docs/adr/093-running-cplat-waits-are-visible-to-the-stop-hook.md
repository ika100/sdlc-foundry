# ADR-093: Running cplat waits are visible to the Stop hook

**Status:** Accepted (2026-11-10, spec 171)
**Builds on:** [ADR-070](070-the-stop-hook-holds-only-the-owning-session-until-it-stops-progressing.md) (the stop gate), [ADR-082](082-a-coordinator-waits-with-a-cplat-wait-never-a-polling-loop.md) (cplat waits)

## Context

The Stop hook of a ship run counts stops without a new commit or phase change and escalates after two (spec 126). A
session that starts a `cplat` wait in the background (`cplat pr wait`, `cplat system ship next --wait`, `cplat
dispatch wait`) and then tries to stop is waiting, not stuck, but the hook could not tell, so the waits were counted
as stops without progress (#626). Background subagents are already visible through Claude Code's subagent files
(#496); `cplat` processes were not visible at all.

## Decision

Every `cplat` wait marks itself as running in the checkout it was started from: `<git dir>/cplat-waits/<pid>.json`
with the process id, the command and the start time, written when the wait starts and removed when it ends
(`waits.running`, used by `waits.record`, `cplat pr wait` and `cplat component ship land`). The Stop hook reads the
marks of its checkout (`waits.live`), ignores and removes those whose process is gone, and, while one runs, blocks
the stop without counting it, naming the wait in the reason (`waiting: <command>; stops without progress: <n>/2`).
A running wait holds the count where it is; it does not reset it.

## Consequences

- A session that only waits is bounded by the wait's own timeouts (ADR-082) and the run's budget, not by the
  no-progress count.
- A new wait is visible to the hook by going through `waits.record` or `waits.running`; nothing else is detected.
- A mark left by a killed process is harmless: its process id is gone, so the next hook removes it.
