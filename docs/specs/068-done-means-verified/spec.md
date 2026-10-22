---
spec_id: 068-done-means-verified
title: Done means verified
status: done
priority: P1
---

# 068 — Done means verified

## Problem

`cplat spec set-status <id> done` accepts any building spec. In ai-ops, specs 009 and 010 are `done` without a `verification.md`: the reviewer never checked them against their criteria, and nothing shows it.

## Stories

As a founder, I want a spec to be `done` only when a reviewer found every criterion met, so that `done` in the backlog means proven.

## Acceptance criteria

- **AC-068.1** Given a spec of a component repo (any shape but gitops-app), when it is set to `done`, then `cplat` refuses unless `verification.md` says `**Result:** pass`, and the hint names `/svc:verify <NNN>`; product specs are not affected.
- **AC-068.2** Given an exception, when `--unverified` is passed, then it needs `--reason`, and the reason is recorded in the spec's changelog as `done: unverified: <reason>`.
- **AC-068.3** Given a `done` spec without a passing verification, when the specs are listed, then its next step is `/svc:verify <NNN>`.

## Non-goals

- Failing `cplat spec check` or CI for specs closed before this rule.

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
