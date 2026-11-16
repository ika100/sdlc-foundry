# ADR-113: An interactive component ship runs in its own headless session

**Status:** Accepted (2026-11-15)

## Context

An interactive `/component:ship` ran every phase in the session the person typed it in. That session carried plan, build, PR, land
and deploy in one context: 5.7 to 8.6 M tokens for "Ship the spec", and in journey 16 (J16-1) a stop on a helper-only CI fix that
nobody could answer. `cplat headless` already runs a ship in one session per unit with checkpoints (ADR-075), but only when the
person starts it by hand.

## Decision

An interactive /component:ship hands its run to its own detached cplat headless process and only waits, relays questions and reports

`cplat component ship start <spec> --detach` starts the process after `start()` ran unchanged; the interactive session runs
`cplat component ship wait`, relays an `ESCALATED:` question to the person (or resumes with suggested answers the person
accepted), and prints the final report from `cplat component ship status`. `--here` keeps the run in the interactive session.
A fix round that only touches a test helper is settled through `cplat spec test-diff` without a stop. Details:
[design.md](../specs/200-a-component-ship-runs-in-its-own-session/design.md).

## Consequences

- The interactive session stays small: it holds no phase context, only the wait results.
- One budget and one run tree cover both sides, so tokens are counted once.
- A headless session never starts another process: `--detach` is ignored under `CPLAT_HEADLESS` or `CPLAT_UNIT`.
- Later changes to the wait outcomes or the report block must keep `ship-handoff.md` and `ship-finish.md` in step.
