# ADR-115: A waiting session stops and its wait outlives it

**Status:** Accepted (2026-11-15). Supersedes the blocking of the stop in [ADR-093](093-running-cplat-waits-are-visible-to-the-stop-hook.md); its marks of running waits stay.

## Context

ADR-093 blocked a session's stop while one of its `cplat` waits ran. A blocked session answers every block with a model call, so a
long wait became a loop of model calls without work (#750, 2026-11-14). `claude -p` also ends its background shells when it
exits, so a wait started by a session that stops would die with it.

## Decision

A session may stop while its cplat wait runs; under cplat headless the wait runs detached, headless holds the next session until it ends and a loop guard escalates idle sessions

- Every Stop gate lets the owning session stop while one of its waits runs, answers with one `systemMessage` line and writes no counter.
- With `CPLAT_HEADLESS` set, `cplat` re-runs a wait command as a child in its own process group; the caller streams its output and exits with its code. Outside `cplat headless` nothing is detached.
- A `SessionStart` hook of the shared plugin runs `cplat waits handover` and prints each ended wait's result.
- `cplat headless` polls local files before each session while a detached wait is alive and escalates with cause `environment` after 120 minutes.
- A loop guard reads the session's transcript ([ADR-035](035-token-usage-from-session-transcripts.md)) and escalates a session with cause `platform` after `guard.loop_calls` idle model calls in `guard.loop_minutes` minutes (defaults 10 and 5).
- Pause reaches a running unit through its Stop hook: the session may stop, nothing is counted.

## Consequences

A waiting session costs no model calls, and a wait survives its session. The Stop hook no longer enforces that a session stays
until its wait ends: the run's prompts and `cplat headless` must act on the result at the next session's start. Every new wait
command must be listed in `waitdetach.WAIT_COMMANDS` (a test checks it). The guard needs the transcript; without one (a fake
`claude`) it never trips.
