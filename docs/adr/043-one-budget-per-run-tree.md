# ADR-043 — One budget per run tree, kept in a local ledger and checked at safe points

**Status:** accepted (2026-10-25, spec 102)

## Context

Runs nest: `cplat headless` starts sessions that run `cplat ship`, which runs a build and CI waits; `cplat app-ship`
runs one ship per repo. Each had its own limits (`--max-runs`, `--max-minutes`, 3 fix rounds), so limits added up
instead of holding, and an unmetered round of ten specs cost about $105. Run records (ADR-032) are written once at the
end and a resumed run is a new record, so they cannot hold a running total across a resume.

## Decision

- The outermost run (no `parent`) owns one budget of four limits (minutes, agent invocations, CI reruns, estimated
  cost). Every run below it counts against that budget; none starts with fresh limits.
- The budget is a local ledger keyed by the work (repo and spec or prompt), not by run id, so a resumed run of the
  same work continues it. A tree that ends `done` closes the ledger.
- Limits are checked only at safe points the code already passes (before a session, a subagent, a CI rerun, at a
  phase end, before a product ship starts a repo ship). A stop never kills running work; it escalates with cause
  `decision` and leaves the run resumable.
- Defaults are on: 180 min, 60 invocations, 6 reruns, $15 per ship, multiplied by the ships a root covers; any limit
  can be set or turned `off`.

## Consequences

- Subagent starts are counted and refused by a `PreToolUse` hook of the shared plugin, the only point Claude Code
  offers before a subagent runs.
- Cost is an estimate from local transcripts (ADR-035); when it is `unknown` the cost limit cannot be enforced and the
  other three still are.
- The ledger is local to the machine, like the active run records; a run continued on another machine starts a new
  ledger.
