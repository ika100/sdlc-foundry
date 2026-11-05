---
spec_id: 142-no-avoidable-stops-in-the-journey
title: No avoidable stops in the journey
status: approved
priority: P1
shape: platform
---

# 142 — No avoidable stops in the journey

## Problem

The journey runs of 2026-11-05 stopped or needed extra rounds at points where the user's intent was already clear or the
platform could have acted itself:

1. "Make the API reachable from my browser" opened the expose PR and then asked whether to merge it (one extra round).
2. After the system plan declared Postgres, `/system:ship` stopped and asked the user to run
   `KUBE_CONTEXT=… devbox run bootstrap` to install CloudNativePG in the local cluster; the first run did nothing, because
   the local `main` was behind the merged gitops PR, and it had to be run twice.
3. Staging is `promote: after-dev-smoke`, but only a `/component:ship` run promotes it; a fix build and a release build
   that passed their dev smoke each needed a manual `/instance:promote --to staging` (two promotions, two PRs).
4. A promotion that failed half way left a local branch and an uncommitted pin edit on `main`, so the next promotion
   failed until they were cleaned up by hand.

## Stories

- As the owner of a system, I want a request whose intent is clear to finish without a confirmation round.
- As someone running the journey on a local cluster, I want the operators the system needs installed without a manual step.
- As the owner of a system, I want staging to follow every green dev build when it is set to `after-dev-smoke`.

## Acceptance criteria

- **AC-142.1** Given a request to make a component reachable (`/component:set <c> --expose`, or the user asks for it in
  words), when the PR is opened and its CI is green, then it is merged without a further question, as the PRs of
  `/component:add` are; `--no-merge` keeps the old behaviour.
- **AC-142.2** Given a local cluster made with `devbox run cluster-up` (context `k3d-<system>-local`) and a merged gitops
  change that adds an operator under `operators/apps/`, when `/system:ship` (or the command that merged it) continues, then
  it pulls `main` and applies the operators itself (the `bootstrap` recipe), without asking the user; for any other
  context it stops and asks as today.
- **AC-142.3** Given `bootstrap` run on a clone whose `main` is behind `origin/main`, when it starts, then it fast-forwards
  `main` first (or stops naming the commit it is behind), never reporting success with nothing applied.
- **AC-142.4** Given staging set to `promote: after-dev-smoke`, when any build of a component's `main` passes its dev smoke
  (a ship, a fix or a release commit), then staging is promoted to that build as after a ship, and the promotion is printed;
  a release commit that changes only the changelog and version file counts when CI built an image for it (spec 138 decides
  whether such a commit is built).
- **AC-142.5** Given `/instance:promote` failing after it created its branch or edited a pin, when it stops, then it
  restores the clone: the edit is reverted and the local branch deleted (the remote branch, if pushed, is named in the
  error), so that the next run starts clean.

## Non-goals

- No automatic merge of a prod PR: the prod gate is unchanged.
- No operator install on a cluster that is not the local k3d cluster.

## Open questions

1. ~~AC-142.4: should staging follow a release commit that changes only `CHANGELOG.md` and the version file? (Recommended:
      yes, when CI built an image for it; spec 138 decides whether such a commit is built.)~~ Answered: yes, when CI built an image for it (AC-142.4).

## Changelog

- 2026-11-05 created (found in the journey runs of 2026-11-05)
- 2026-11-05 open question answered by the user (recommended answer)
- 2026-11-05 approved
