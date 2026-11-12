# ADR-106: A release reuses the green ci run of its commit

**Status:** Proposed (2026-11-12)

## Context

<!-- why a decision is needed: the forces and constraints -->

## Decision

/component:release skips its local gates when main's ci run on the tagged commit passed every gate within 7 days

## Consequences

<!-- what becomes easier or harder, what a later change must keep -->
