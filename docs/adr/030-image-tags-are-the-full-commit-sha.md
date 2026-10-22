# ADR-030 — Image tags are the full commit sha

**Status:** accepted (2026-10-22, spec 078) · **Amends:** [ADR-027](027-dev-follows-main-through-pin-prs.md)

## Context

The service CI pushed `sha-<7>`, and pin-dev, `pin.py` and `/gitops:promote` pinned `sha-<7>`. ai-ops reads a Component's `tagFormat: sha-{commit}` as the full 40-character sha, so it could not pin what the platform built. A 7-character prefix can also collide in a long-lived repository.

## Decision

The pin format is `sha-<40>`, the full commit sha.
- The template CI pushes `sha-<40>` and, for one release, still `sha-<7>`. The pin-dev dispatch sends `sha-<40>`.
- `pin-dev.yml` and `pin.py` accept both formats; the pin branch keeps the short form, `pin/dev-<service>-<7>`.
- `/gitops:promote --sha` pins `sha-<40>`, or `sha-<7>` when only that exists (images built before 4.4.0).

## Consequences

- Every tool that reads or writes a pin agrees on one unambiguous tag.
- Existing short pins stay valid and are replaced by the next build of each service.
- A later release stops pushing `sha-<7>` and drops it from the accepted formats.
