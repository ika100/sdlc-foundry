---
spec_id: 072-ship-land-fails-fast-and-heals-stuck-checks
title: Ship land fails fast and heals stuck checks
status: done
priority: P1
tracks: [102]
---

# 072 — Ship land fails fast and heals stuck checks

## Problem

`cplat ship land` reports only once **no** check is pending. In the ai-ops spec 011 run (ika100/ai-ops#23, 2026-10-22) that cost about an hour: a red `security` check was found only after the queued `docker` jobs finished, a `quality` check stayed `in_progress` for 24 min after its workflow run had completed, and in stock-manager-gitops#38 jobs sat queued for 10 min until a cancel and rerun. `ship deploy` waits on the gitops pin PR without looking at its checks at all.

## Stories

As the orchestrator of an unattended ship run, I want a red check reported the moment it concludes and stuck checks healed once on their own, so that a run loses minutes, not an hour, to CI.

## Acceptance criteria

- **AC-072.1** Given a PR where one check concluded `fail` or `cancel` while others are still pending, when `cplat ship land` polls, then it returns RED at once with that check's log tail and merges nothing.
- **AC-072.2** Given a check still `in_progress` whose workflow run is `completed`, when land polls, then it reruns that run once (`gh run rerun <id>`) and says so; if the same run is stale again, then land stops with an error naming the run.
- **AC-072.3** Given a check `queued` for longer than `--queue-timeout` (default 300 s), when land polls, then it cancels and reruns that run once; if it is queued that long again, then land stops with an error that names the run and its runner labels ("picks up no jobs"). A check cancelled by this healing is not reported as red.
- **AC-072.4** Given land is waiting, when a check concludes, then one line per check (`pass`/`fail`/`skipping`, name) is printed as it happens.
- ~~**AC-072.5** Given `cplat ship deploy` waits for an open pin PR in a gitops repo, when a check on it fails or gets stuck, then the deploy fails at once with the log tail, or heals the check, exactly as land does.~~ Withdrawn 2026-10-22: pin PRs carry no checks (pin-dev runs CI inside its own run, #113); replaced by AC-077.1.

## Non-goals

- Required-check configuration: without branch protection every reported check counts.
- Restarting runners or ARC listeners.

## Open questions

None.

## References

- Issue #102
- [Spec 065](../065-merges-wait-for-green-ci-without-branch/spec.md), [Spec 067](../067-ship-an-approved-spec-to-dev/spec.md)

## Changelog

- 2026-10-22 created from issue #102
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
- 2026-10-22 AC-072.5 withdrawn: pin PRs have no checks; spec 077 watches the pin-dev run instead (#113)
