---
spec_id: 075-devbox-run-ci-is-the-ci-gate
title: devbox run ci is the CI gate, locally
status: approved
priority: P1
tracks: [105]
---

# 075 — devbox run ci is the CI gate, locally

## Problem

`/svc:build` Phase 3 runs quality, tests and security through three agents, but not exactly what CI runs, in CI's order, on the final tree. In ai-ops#23 everything was green locally and CI's `security` job still failed, which cost a 15-minute CI round on the lan runners.

## Stories

As the orchestrator of a build, I want one local command that runs exactly the gates CI runs, so that nothing red is ever pushed.

## Acceptance criteria

- **AC-075.1** Given any template, when `devbox run ci` runs, then it runs the same `devbox run` gates as the jobs of the template's `ci.yml`, in job order, and fails on the first red one; `cplat shape check` requires the recipe.
- **AC-075.2** Given a ship run with a `ci` recipe, when `cplat ship pr` is called, then it runs `devbox run ci` first and on red refuses to push, printing the tail of the output.
- **AC-075.3** Given `/svc:build` and `/svc:ship`, when the build reaches the end of Phase 3, then they run `devbox run ci` once on the final tree and send a red result back to the coder before anything is pushed.

## Non-goals

- Image builds in `devbox run ci` (Phase 5 builds and smoke-starts the image).
- Pinning every devbox package (see spec 073).

## Open questions

None.

## References

- Issue #105, [Spec 073](../073-secrets-scan-agrees-locally-and-in-ci/spec.md)

## Changelog

- 2026-10-22 created from issue #105
- 2026-10-22 approved
