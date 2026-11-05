---
spec_id: 137-cplat-waits-out-github-s-rate-limit
title: cplat waits out GitHub's rate limit
status: approved
priority: P1
shape: platform
---

# 137 — cplat waits out GitHub's rate limit

## Problem

GitHub limits API use per user account (REST and GraphQL each 5,000 points an hour, plus short-term secondary limits), shared
by every tool logged in as that user. On 2026-11-04 the limit ran out three times while the demo was recorded (#409): two local
consoles re-read every source every 30 s, whether or not anyone looked, and cplat stopped instead of waiting. `cplat pr wait`
ended at once with `gh pr view … failed: GraphQL: API rate limit already exceeded` (exit 1, three times in a row), and
`cplat spec publish` failed with only `opening the draft pull request failed (gh exit 1)`, which took a `--dry-run` of
`gh pr create` to explain. Every stop needed a person or an agent round to restart the step after the reset.

Tracks #409.

## Stories

- As someone running an unattended ship, I want cplat to wait for GitHub's limit to reset and go on, so that a run does not end
  on a limit that clears by itself.
- As someone reading a failed cplat step, I want GitHub's own error message, so that I see at once that it was the limit.
- As someone with the console open, I want it to read GitHub only while I look at it, so that it does not use up the budget my
  runs need.

## Acceptance criteria

- **AC-137.1** Given a `gh` call made by cplat through `core.run`, when it fails because a GitHub rate limit is exhausted (its
  output names `API rate limit exceeded`, `API rate limit already exceeded` or `secondary rate limit`), then cplat does not fail
  the step: it prints once per wait `GitHub rate limit (<graphql|core|secondary>): waiting until <HH:MM> UTC` to stderr, waits,
  and runs the same call again.
- **AC-137.2** Given such a wait, when GitHub reports the limit's reset time (`gh api rate_limit`, field `reset` of the named
  resource) and it is in the future, then the wait ends 30 s after it; when the reset time cannot be read or is already past (a
  secondary limit, or a limit `rate_limit` under-reports), then the waits back off from 60 s, doubling, to at most 10 min each.
- **AC-137.3** Given waits for one call that add up to more than 65 minutes, when the next attempt still hits the limit, then the
  step fails with a `PlatformError` that names the limit and the total wait, and its hint says to stop other tools that use the
  account (for example a second console).
- **AC-137.4** Given a `gh` call that fails for any other reason (authentication, not found, a red check, a 5xx), when cplat
  reports it, then the behaviour is unchanged: no wait, the same error as before.
- **AC-137.5** Given `cplat spec publish` or `cplat spec review` and a failing `gh` call, when the step reports it, then the
  message contains the last lines of gh's own output, not only `gh exit <n>`.
- **AC-137.6** Given the local console (`cplat platform ui`), when no browser has requested a page or an API route for 10
  minutes, then its background refresh reads no source until the next request, and the next request starts one refresh at once.
- **AC-137.7** Given the platform's tests, when they run, then a fake `gh` that answers a rate limit first and then succeeds
  shows the wait and the retry (with a fake clock, no real sleep), and the console's idle pause is covered without a browser.

## Non-goals

- No new command and no new option: the waiting is automatic.
- No detection or refusal of a second console (a separate change if still needed once the console pauses when idle).
- No change to how often `cplat pr wait` polls CI between its checks; only a rate-limited call waits.
- No counting of GitHub points by cplat itself.

## Open questions

None: these are the behaviours #409 asked for, and the user decided on 2026-11-04 to fix all bugs found while recording the
demo without adding features.

## Changelog

- 2026-11-04 created (tracks #409)
- 2026-11-04 approved
