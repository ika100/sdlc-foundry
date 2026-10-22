---
spec_id: 084-platform-ci-in-minutes
title: Platform CI in minutes
status: done
priority: P2
tracks: [124, 127]
---

# 084 — Platform CI in minutes

## Problem

- `pytest tests/cplat` takes about 3 min: 616 tests at about 0.3 s each, mostly subprocess calls (#127).
- One transient Maven failure cancelled two healthy smoke-test jobs, so the rerun repeated three (#124).

## Stories

As a contributor, I want the platform's own CI and local checks to take a minute, and a flaky download to cost one job.

## Acceptance criteria

- **AC-084.1** Given `scripts/ci-local.sh` and the repo's CI, when the cplat tests run, then they run in parallel (`pytest -n auto`) and pass.
- **AC-084.2** Given the template smoke-test matrices, when one job fails, then the others run to the end (`fail-fast: false`), and the Java smoke jobs retry downloads (`-Daether.connector.http.retryHandler.count=3`).

## Non-goals

- Splitting the suite into separate jobs.

## Open questions

None.

## Changelog

- 2026-10-22 created from #124, #127
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
