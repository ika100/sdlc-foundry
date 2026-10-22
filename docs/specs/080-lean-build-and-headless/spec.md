---
spec_id: 080-lean-build-and-headless
title: Lean build QA and headless runs that stop when stuck
status: done
priority: P1
tracks: [118, 119]
---

# 080 — Lean build QA and headless runs that stop when stuck

## Problem

- `/svc:build` Phase 3 runs quality, test and security through three agents and then again through `devbox run ci`: every gate twice, and three agent contexts even when all is green (#118).
- `cplat headless` starts up to 6 sessions while a ship run is unfinished, even when a session changed nothing (#119).

## Stories

As the owner of a subscription, I want a build to run each gate once and an unattended run to stop when it makes no progress.

## Acceptance criteria

- **AC-080.1** Given Phase 3, when it starts, then it runs `devbox run lint-fix` and `devbox run ci` first and spawns only the agent of a red gate (at most 2 rounds), plus the tester only when touched internals lack unit tests, plus security only for a changed Dockerfile or findings.
- **AC-080.2** Given `cplat headless`, when two sessions in a row end with the same phase, HEAD, fix rounds and state, then it stops with `no progress`, escalates the ship run with that reason, and exits 1.

## Non-goals

- Changing which agents exist.

## Open questions

None.

## Changelog

- 2026-10-22 created from #118, #119
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
