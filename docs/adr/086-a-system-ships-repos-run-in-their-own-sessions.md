# ADR-086: A system ship's repos run in their own sessions

**Status:** Accepted (2026-11-08, spec 155)
**Builds on:** [ADR-042](042-product-ship-coordinates-repo-ships.md) (the system ship coordinates repo ships), spec 131 (unit mode), spec 102 (one budget per run tree)

## Context

`/system:ship` shipped every component repo through a subagent of the gitops session, which followed `/component:ship`'s
command file in the repo's clone. A subagent cannot start subagents, so that ship was not the one `/component:ship` runs on
its own: coders of `parallel_safe` tasks ran one after another (#560), unit mode's fresh session per unit (spec 131) did
not apply, and architect, tester and reviewer worked inline in one long context. In journey 6 the step "Plan and ship it to
dev" took 51 of 164 minutes and 54 % of the tokens. The cause is structural: it holds for every system ship with a
component repo, whatever its shape.

## Decision

Each component repo of a system ship runs as its own `cplat headless "/component:ship <repo spec>"` process in its clone.
`cplat system ship repo start` writes and approves the repo spec from the plan (spec 147), commits it on the feature
branch and starts the process detached, linked by `CPLAT_SYSTEM_DIR` (read by `component ship start` as `--system-dir`)
and `CPLAT_RUN_PARENT` (the repo's run is a child of the system ship's run, so one budget covers both and every token is
counted once). The system ship keeps the process (pid, log, starts) in its state. `cplat system ship next --wait` reads
each repo's ship state and whether its process lives: a finished or escalated ship is recorded with `repo result` as
before; a process that ended before its ship did is started once more, then the repo escalates with cause `environment`.
A linked component ship that is done is archived by the system ship, not by its own `ship finish`. The command file has
one path: the coordinator starts no subagent for a component repo.

## Consequences

- A repo inside a system ship is built exactly as on its own: unit mode, the repo's coordinator model. Independent
  repos still run at once up to `--max`. Unit mode runs a repo's tasks one after another; running `parallel_safe` tasks
  at once is spec 157's.
- The gitops session no longer carries the repo ships' context; it waits with `next --wait` and records results.
- Repo ships run on the same machine as the gitops session; a remote session per repo is a later step.
- A plan from before spec 147 (no criteria per repo) is refused at `repo start` with the hint to re-plan, instead of
  falling back to a product-manager inside the system ship.
- The effect is measured with the `system-ship` benchmark (spec 156) on a sample that differs from the journeys.
