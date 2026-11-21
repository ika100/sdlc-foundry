# ADR-126: Unit briefings are cut from the build instructions

**Status:** Accepted (2026-11-21)

## Context

A third of the model calls in a unit session were bookkeeping (#869), and the unit-mode reference was read 33 times in journey 21. A
knowledge graph over the instructions gave no gain. Each unit session reads the whole build instructions to find the few sections its
unit needs.

## Decision

A unit session's instructions are cut at print time by heading key from build.md and unit-mode.md through one mapping in code, guarded by tests and the rules check.

No slice is stored, so there is no second copy of any instruction that could drift. The mapping holds heading keys, not text, and no
allowlist excuses a prompt reference that a slice would lose: such a reference is reworded. See
[spec 211](../specs/211-unit-sessions-start-with-their/design.md).

## Consequences

- A renamed or removed phase heading that the mapping names fails the tests and `cplat platform rules check` in CI.
- A new section in build.md or unit-mode.md must be mapped to the units that need it, or the check says so.
- Interactive ship and build runs are unchanged: they keep reading the full instructions.
- The unit's start call prints its briefing, so the session spends no calls on reading the instructions or on bookkeeping.
