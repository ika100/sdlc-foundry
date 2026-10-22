---
spec_id: 065-merges-wait-for-green-ci-without-branch
title: Merges wait for green CI without branch protection
status: done
priority: P0
---

# 065 — Merges wait for green CI without branch protection

## Problem

ika100's repositories are private on GitHub Free, which has neither branch protection nor auto-merge for private repositories. Two things in the platform depend on them: the gitops-app's `pin-dev` workflow turns on auto-merge (`gh pr merge --auto`) and relies on required checks to hold the merge (ADR-027), and spec 054 protects `main` of new repos. On the free plan the auto-merge call fails, so `dev` never follows `main`, and nothing makes a merge wait for CI. ai-ops recorded this as R2 ("no branch protection, Free plan") and worked around it by pushing images from a laptop and pinning by hand.

## Stories

- As a founder on GitHub Free, I want pin PRs to merge themselves only after their CI passed, so that `dev` follows `main` without a paid plan.
- As a founder, I want every automated merge to wait for green checks, so that an unprotected `main` still only receives tested changes.

## Acceptance criteria

- **AC-065.1** Given a dispatched pin, when `pin-dev` has opened the pin PR, then it runs the gitops-app CI (`ci.yml`, as a reusable workflow on the pin branch) and merges the PR itself only when that CI succeeded, without branch protection or auto-merge; two concurrent pins never share a CI concurrency group.
- **AC-065.2** Given a pin whose CI fails or is cancelled, when the workflow ends, then the PR stays open with a comment linking the failed run, the workflow fails, and `dev` keeps the previous image.
- **AC-065.3** Given a repository whose branch protection requires checks from the PR itself, when the direct merge is refused, then the workflow starts CI on the PR and turns on auto-merge instead.
- **AC-065.4** Given `/shared:new-service` on a plan without branch protection or auto-merge, when it sets the repository up, then it says that merges still wait for green CI (pin-dev and `/svc:ship`), and only the setting pin-dev cannot work without (Actions may open pull requests) is a warning with the exact command.
- **AC-065.5** Given a feature PR, when `cplat ship land` decides, then it merges only when at least one check was reported and none is pending, failed or cancelled; otherwise it does not merge.

## Non-goals

- Preventing a human with write access from pushing to `main` (the free plan cannot; agents are kept off it by the permission allowlist).
- Rulesets or a merge queue.

## Open questions

None.

## References

- [Review of stock-manager, stock-manager-gitops and ai-ops](../../e2e/2026-10-22-review-unattended-delivery.md)
- [ADR-028](../../adr/028-unattended-delivery-without-branch-protection.md)

## Changelog

- 2026-10-22 created from the review of the three lan repos
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
