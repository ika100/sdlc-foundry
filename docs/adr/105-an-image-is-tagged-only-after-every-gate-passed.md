# ADR-105: An image is tagged only after every gate passed

**Status:** Proposed (2026-11-12)

## Context

<!-- why a decision is needed: the forces and constraints -->

## Decision

Component CI builds and pushes images by digest alongside the gates; tags and the dev pin follow only after every gate passed

## Consequences

<!-- what becomes easier or harder, what a later change must keep -->
