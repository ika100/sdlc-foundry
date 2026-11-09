# ADR-088: A dispatcher schedules orchestrator runs from a policy file

**Status:** Accepted (2026-11-09, spec 167)
**Builds on:** [ADR-086](086-a-system-ships-repos-run-in-their-own-sessions.md) (runs as their own `cplat headless` processes), [ADR-082](082-a-coordinator-waits-with-a-cplat-wait-never-a-polling-loop.md) (waits), [ADR-051](051-run-state-is-per-worktree.md) (state per checkout), spec 082 (claims), spec 102 (budgets), spec 131 (unit runs), spec 122 (needs and notifications)

## Context

The pieces for unattended work exist: claims, headless unit runs, child processes, budgets, waits and decision points
with notifications. The user still schedules between runs: issue waves, a progress file, a ship order, starting each
`cplat headless` run, merging one pull request at a time. In the journey measurements of 2026-11-05 about 37 % of the
time was waiting and 17 % the person's own time; the token diagnosis of 2026-10-25 put 42 % of the tokens on
coordination. An agent that coordinates would spend tokens on exactly that.

## Decision

A level above the orchestrator, `cplat dispatch`, works through the backlog. It is deterministic code: readiness, order,
slots, claims, merges and the token budget are Python with tests. It calls a model only for two short questions about
an item that is about to start: does the issue's premise still hold on `main`, and can a spec's work be split (only
when no valid plan answers it). It never designs, triages or reviews; it starts the existing `/component:fix` and
`/component:ship` runs, one per slot, each in its own git worktree on its own branch, and lands fix units itself.

- A repo opts in by committing `.platform/dispatch.yml` (slots, daily token budget, per-unit budget, sources, readiness
  labels, priority rules, gates, serialization). Without it nothing runs; `cplat dispatch plan` shows the defaults.
- A unit is a worktree with a unit file in its git dir. The dispatcher's state is rebuilt on every start from the
  worktrees, the unit files, the processes that live, the claim comments on GitHub and the run store; the local state
  file holds only steering, the token ledger, caches and history. Units run detached, so the loop can die and be
  started again without starting anything twice.
- GitHub is read at most every 5 minutes; a cycle runs every 60 seconds and when a unit ends.
- The user hears from it only for a decision of theirs (`approve`, `answer`, `escalation`, `triage`, `budget`, `stuck`)
  and in one daily digest.

## Consequences

- Scheduling between runs is code; the user sets the order once and steers with `pause`, `resume`, `slots`,
  `prioritize` and `skip`.
- Every unit is an ordinary orchestrator run: the run store, budgets, escalations and the console see it as before.
- One ship unit at a time and one machine: a central spec-number reservation and a ship slot per worktree are a
  follow-up spec; a merge lock across machines is out of scope.
- `cplat needs` gains a repo scope, so a repo outside any system (the platform repo) has an inbox too.
- New labels are part of the platform's vocabulary: `triaged` (set by triage), `needs-decision`, `stale-premise`.
