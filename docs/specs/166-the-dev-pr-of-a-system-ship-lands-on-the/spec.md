---
spec_id: 166-the-dev-pr-of-a-system-ship-lands-on-the
title: The dev PR of a system ship lands on the current main
status: approved
priority: P1
shape: platform
tracks: [597]
---

# 166 — The dev PR of a system ship lands on the current main

## Problem

A system ship pins every build of its spec on one branch, `compose/<spec>`, and lands that PR after the last component merged (spec 144). The branch stays open for the whole run. In journey 7 three gitops PRs merged on main meanwhile (hosts, observability, the database backups), the dev PR conflicted with them, and `cplat system ship land` failed until the session merged main by hand. The final report then named web `sha-88a8d36` while dev ran `sha-e55ef6a`, a later build that pin-dev had put on main (#597).

## Stories

As someone shipping a system unattended, I want the dev PR to land on whatever main has become, so that gitops changes merged during the run neither stop it nor get lost, and the report names what dev runs.

## Acceptance criteria

- **AC-166.1** Given a dev PR whose branch is behind main, when `cplat system ship land` runs, then it merges main into `compose/<spec>` and pushes it before merging the PR, so every commit main got meanwhile stays on main, and it says so.
- **AC-166.2** Given that merge conflicts only in files `render.py` writes (`applications/<system>/applicationset.yaml`, `overlays/`, `addons/`, `policies/`, `autonomy.json`, `operators/`, `bootstrap/`), when land resolves it, then it takes main's files, pins every build of the run again in dev and renders again, and the dev PR lands with the run's pins.
- **AC-166.3** Given main pins a later build of a component than the run's (GitHub's compare says main's build is ahead), when land refreshes the branch, then dev keeps main's build, the run's state records it as that component's pin, and the report and the dev smoke name the build dev runs.
- **AC-166.4** Given the merge conflicts in any other file (`system.yaml`, scripts, docs), when land runs, then the merge is aborted, nothing is merged, and the run escalates naming the files.

## Non-goals

- Resolving a conflict in `system.yaml`: two changes to the system model need a person or a re-plan.
- Rebasing instead of merging: a merge keeps the PR's history and needs no force-push.

## Assumptions

- **A1** A later build is one GitHub's compare reports as `ahead` of the run's build; when it cannot tell, the run's own build is pinned again (affects AC-166.3).

## Open questions

None.

## Changelog

- 2026-11-09 created from #597 (journey 7); approved as the user asked ("go on, I follow your proposals").
