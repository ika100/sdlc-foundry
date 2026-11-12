# ADR-102: Parallel unattended runs share repo slots and pause at the usage limit

**Status:** Proposed (2026-11-11)

## Context

Parallel unattended ships in one repo stop each other: a session that hits the usage limit counts as a stall or a spent invocation, runs compete for the same machine and merge lock, and two branches that each take the next ADR or rule number conflict in the index files. Spec 184 (AC-184.1 to AC-184.10) asks for runs that wait instead of failing.

## Decision

Every non-dry-run cplat headless holds one of the repo's machine-wide slots (dispatcher slots, else 1), shared with the dispatcher; a usage-limit session is an environment pause (wait for the reset, at most 360 min in total) that counts as neither a stop, an invocation nor budget minutes; a land settles ADR-index and rule-register conflicts by renumbering the branch's side

## Consequences

Runs wait for a slot or the usage-limit reset without spending budget; the pool size is the dispatcher's `slots`, so the dispatcher and direct runs share one limit. Pause time is subtracted from the ledger, not a stopped clock. A land renumbers only the branch's side and shares the 3-round limit with spec 171. Details: `docs/specs/184-parallel-ships-do-not-stop-each-other/design.md`.
