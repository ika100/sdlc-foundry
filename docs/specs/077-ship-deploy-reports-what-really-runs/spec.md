---
spec_id: 077-ship-deploy-reports-what-really-runs
title: Ship deploy reports what really runs
status: done
priority: P0
tracks: [113, 114, 115]
---

# 077 — Ship deploy reports what really runs

## Problem

`cplat ship deploy` can be wrong in three ways (2026-10-22 review):
- It never sees a red pin CI. Pin PRs carry no checks, because `pin-dev.yml` runs CI inside its own run (#113).
- Right after a pin merges, Argo still reports the old revision as Synced/Healthy, so deploy says done while dev runs the old image (#114).
- A missing `GITOPS_TOKEN` only prints a notice. Main stays green, nothing is pinned, and deploy waits 30 min before it hints at the token (#115).

## Stories

As the orchestrator of a ship run, I want deploy to succeed only when dev runs the merged build, and to fail at once with the reason otherwise.

## Acceptance criteria

- **AC-077.1** Given the gitops-app's pin-dev run for the merge commit, when it fails or its jobs stay queued, then `ship deploy` fails at once with its log tail, or reruns it once, like land does (spec 072). `pin-dev.yml` names its run `pin-dev <service> <tag>` so that it can be found.
- **AC-077.2** Given the service's own CI run on main for the merge commit, when it fails, then deploy fails at once naming it; when it succeeded and no pin-dev run exists after the grace period, then deploy fails naming the `GITOPS_TOKEN` step.
- **AC-077.3** Given Argo still reports the old image, when deploy checks `<service>-dev`, then it waits until `status.summary.images` contains the merged build's tag, and only then judges health; other apps wait until `status.sync.revision` is at or after the last merged gitops commit.
- **AC-077.4** Given a repo whose `.platform-app.yml` links a gitops-app and no `GITOPS_TOKEN` secret, when `cplat ship start` or `cplat doctor` runs, then start refuses and doctor fails the check, both with the one-line fix; the template's pin-dev job warns (`::warning::`) instead of a notice.

## Non-goals

- Restarting Argo or forcing a refresh (a kubectl write the unattended allowlist does not have).

## Open questions

None.

## Changelog

- 2026-10-22 created from #113, #114, #115
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
