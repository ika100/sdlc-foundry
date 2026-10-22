---
spec_id: 083-platform-drift-in-status
title: Platform drift in /shared:status
status: done
priority: P2
tracks: [125]
---

# 083 — Platform drift in /shared:status

## Problem

Repos fall behind the platform silently. stock-manager-gitops still had triggers from before #104 and a baseline from before #103, and was found only by looking.

## Stories

As a product owner, I want to see which repos run an old platform version.

## Acceptance criteria

- **AC-083.1** Given `/shared:status` in a gitops-app, when it runs, then each service row shows the service repo's `.platform-version` and whether it is behind the platform version installed; a repo without the file shows `none`.

## Non-goals

- A table in the weekly bump PR (it does not know the repos).

## Open questions

None.

## Changelog

- 2026-10-22 created from #125
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
