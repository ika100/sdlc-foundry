---
spec_id: 074-ci-runs-once-per-change
title: CI runs once per change
status: approved
priority: P1
tracks: [104]
---

# 074 — CI runs once per change

## Problem

Every template's `ci.yml` runs on `push` to `feature/**`, `fix/**` and the other branch prefixes, and again on `pull_request`. With two self-hosted runners the duplicate push run queues the PR's own jobs (ai-ops#23: `docker` waited behind the push run). Image builds on self-hosted runners are cold unless the runner keeps its Docker data, which `docs/self-hosted-runners.md` does not say.

## Stories

As a founder on GitHub Free with two lan runners, I want each change to run CI once, so that the runners work on the PR instead of a copy of it.

## Acceptance criteria

- **AC-074.1** Given any template's `ci.yml`, when it is read, then `push` triggers only on `main` (and on `v*.*.*` tags where the template builds releases), and branches are covered by `pull_request`; the existing `concurrency` group still cancels superseded PR runs.
- **AC-074.2** Given `docs/self-hosted-runners.md`, when an operator sets up a runner set that builds images, then it recommends a persistent dind `/var/lib/docker` volume per runner set (one runner per volume) as the build cache, and explains why there is no registry cache (it uploads every layer, the uplink cost #95 removed).

## Non-goals

- A registry build cache (dropped in the issue's correction).
- Changing ai-ops's runner set (handed to the ai-ops session).

## Open questions

None.

## References

- Issue #104, PR #95

## Changelog

- 2026-10-22 created from issue #104
- 2026-10-22 approved
