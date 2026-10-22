---
spec_id: 082-sessions-do-not-collide
title: 'Sessions do not collide: claimed issues and specs required'
status: done
priority: P1
tracks: [121, 122]
---

# 082 — Sessions do not collide: claimed issues and specs required

## Problem

Two sessions built #104/#105 at the same time (#107/#108 against #111), and #107/#108 merged without the spec the platform rule asks for. Nothing showed that an issue was taken, and nothing checked the rule.

## Stories

As one of several sessions on the same repos, I want to see that an issue is taken before I start, and the platform to refuse a change without its spec.

## Acceptance criteria

- **AC-082.1** Given `cplat spec new --tracks N` or `cplat ship start` with tracked open issues, when it runs, then each issue gets the `in-progress` label, the user as assignee and a comment naming the branch; an issue already claimed for another branch stops it with who has it, unless `--take-over`; `cplat ship escalate` releases the claim.
- **AC-082.2** Given a pull request in sdlc-foundry that closes an issue and changes `scripts/`, `plugins/` or `templates/`, when CI runs, then it fails unless the diff touches `docs/specs/` or the PR has the `no-spec` label.

## Non-goals

- Claims in /svc:fix-bug or /svc:quick-task (they track no spec).

## Open questions

None.

## Changelog

- 2026-10-22 created from #121, #122
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
