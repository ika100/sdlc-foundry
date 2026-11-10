---
spec_id: 170-release-wait-names-a-commit-of-another-repo
title: Release wait names a commit of another repo
status: approved
priority: P2
shape: platform
tracks: [614]
---

# 170 — Release wait names a commit of another repo

## Problem

In journey 8 a session released two component repos with parallel Bash calls, and one `cplat component release wait --commit <web sha>` ran in the api clone. It waited 120 s for a `ci` run that cannot exist there, then reported `NO RUN … (a commit that changes only Markdown builds no image)`, which sent the session looking for the wrong cause (#614).

## Stories

As a session releasing several repos, I want a commit of the wrong repo named as such at once, so that I rerun the wait in the right clone instead of debugging CI.

## Acceptance criteria

- **AC-170.1** Given a commit GitHub does not know in the clone's repo (No commit found, HTTP 404 or 422), when `cplat component release wait --commit` finds no `ci` run at its first poll, then it exits 1 at once with `NO COMMIT: <sha> is not a commit of <repo>`, without waiting.
- **AC-170.2** Given the commit check itself fails on the network, when the wait runs, then it keeps waiting as before and asks again on the next poll.

## Non-goals

- Running each Bash call of a session in its own directory: the session's shell is Claude Code's.

## Assumptions

None.

## Open questions

None.

## Changelog

- 2026-11-10 created from #614 (journey 8); self-approved under the standing order to fix what a journey finds.
