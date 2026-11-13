# ADR-005: Node version policy — pin current LTS, bump via `copier update`

**Status:** Accepted
**Date:** 2026-05-22

## Context

How does the `web-nextjs` template handle Node versioning? Options: pin one LTS, follow latest LTS automatically (no pin), or pin Active LTS while CI-matrixing N and N-1.

## Decision

The template **pins one Node major version** (the current Active LTS at template release time) in:
- `package.json` `engines.node`
- `devbox.json` package list (`nodejs@<major>`)
- Dockerfile base image (build stages `node:<major>-slim`, runtime `gcr.io/distroless/nodejs<major>-debian13`, spec 189)
- CI workflow `actions/setup-node` `node-version` input

Bumps happen as platform PRs that change these four locations together; consumers pull bumps via `copier update`.

## Rationale

- Reproducibility parity with how we handle Python (`python_version` is a Copier-pinned value).
- Auto-following latest LTS produces "works on my laptop" drift between devs, CI, and prod.
- N + N-1 matrix doubles CI cost for negligible benefit — we don't ship libraries consumed by external Node-N-1 users.

## Consequences

- One source of truth for the Node version (the Copier answer file); single-line bumps when LTS rolls.
- Consumers who reject a bump can `copier update --skip-answered` selectively.
- The template's `tests/` includes a smoke test that asserts `process.versions.node` matches the pinned major, so accidental local overrides surface immediately.

## References

- [platform-vision.md §11.4](../requirements/platform-vision.md)
