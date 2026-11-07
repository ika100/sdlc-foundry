---
spec_id: 153-fewer-waits-after-a-merge
title: Fewer waits after a merge
status: done
priority: P2
shape: platform
---

# 153 — Fewer waits after a merge

## Problem

In journey 5, waiting without any agent working took 74 of 230 minutes; deploys and Argo CD took 25 of them and promotions 16. After a merge to the gitops repo, Argo CD notices the new revision only at its next poll of git, every 3 minutes, unless someone asks for a refresh. Spec 148 made `cplat system wait` ask once; the component ship's own deploy wait (`argo_health`, the `deploy` phase of `/component:ship`) still waits for the poll. While recording the 5.13 round on 2026-11-07, `gh` reported a dropped network as `error connecting to api.github.com … check your internet connection`, wording the retry rule of spec 148 did not know.

## Stories

As someone waiting for a ship to reach dev, I want the platform to tell Argo CD about the merge it just made, so that the wait is the rollout, not the poll.

## Acceptance criteria

- **AC-153.1** Given the deploy wait of `/component:ship` (`argo_health`), when the app still waits for the wanted build or revision, or is missing, 45 seconds into the wait, then it asks Argo CD once for a hard refresh of that app, says so, and keeps waiting; an app that is ready sooner gets no refresh.
- **AC-153.2** Given a `gh` call that fails with `error connecting to api.github.com` or `check your internet connection`, when `core.run` sees it, then it is retried like any call that never reached GitHub (spec 148, AC-148.1).

## Non-goals

- Batching several gitops changes of one request into one PR: it would revise "each operation is one reviewable PR" (`gitops.require_clean`) for about 3 minutes per journey; deferred.
- No Argo CD webhook: a local cluster cannot receive GitHub's webhooks.

## Open questions

- ~~When to refresh?~~ Answered (recommended, self-approved for the 5.13 round on 2026-11-07): once, after 45 seconds, as `system wait` does (spec 148).

## Changelog

- 2026-11-07 created from the strategy after journey 5 (round 3, "fewer round trips"); approved with the recommended answers, as the user asked for this round.
- 2026-11-07 building
- 2026-11-07 done
