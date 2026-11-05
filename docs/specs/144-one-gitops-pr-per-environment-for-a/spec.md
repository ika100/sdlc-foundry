---
spec_id: 144-one-gitops-pr-per-environment-for-a
title: One gitops PR per environment for a system ship
status: done
priority: P1
shape: platform
---

# 144 — One gitops PR per environment for a system ship

## Problem

A system ship (`/system:ship`, spec 097) lands its changes to dev in one gitops PR per repo. In the journey of 2026-11-05
(journey 2, `ika100-demo/taskboard2-gitops`), the part 2 system spec 002 (Postgres for the API, the web UI wired to it)
gave dev three PRs besides the spec, plan and done PRs: #12 the compose entry (the database and the web wiring), then #13
and #14, one `pin-dev` PR per component. Each is a push, a CI run, a merge and an Argo sync, one after another, and the
component ships wait for their own pin before their dev smoke. Spec 136 measured the CI waits as the largest share of the
journey's waiting time (47 of ≈ 100 minutes), made of many rounds rather than slow runs, and named fewer rounds as one of
the two levers. Its criterion AC-136.11 was moved here on 2026-11-05.

Where the extra PRs come from today:

1. The scheduler of the system ship starts the gitops entry first (plan order), and `cplat system ship entry land` merges
   it before the component repos run, so the resources exist when a component's dev smoke runs.
2. Every merge to a component's `main` makes its CI dispatch `pin-dev` to the gitops-app; the gitops-app's `pin-dev.yml`
   opens and merges one PR per component. The component ship's deploy phase finds that run by name (spec 077), waits for
   Argo and runs the dev smoke.
3. With staging set to `promote: after-dev-smoke`, each green dev smoke promotes staging on its own (spec 142, AC-142.4),
   so the same system spec can give one staging PR per component.

## Stories

- As someone shipping a system spec across several repos, I want dev to change in one gitops PR, so that the ship waits
  for one CI round and one sync instead of one per repo.
- As the owner of a system, I want the database, the configuration and the new images of one spec to reach dev together,
  so that dev never runs a new component against a resource that is not there yet, or an old one against a changed config.
- As the platform owner, I want the journey's PR count to drop measurably (spec 136's report), so that the change shows
  in the numbers.

## Acceptance criteria

- **AC-144.1** Given a system ship whose plan has a gitops entry and component repos, when the component repos have
  merged, then dev gets exactly one gitops PR for the spec that holds the entry's changes (resources, configuration,
  exposure) and the dev pin of every component the plan builds; no separate `pin-dev` PR is opened for those builds.
- **AC-144.2** Given that PR, when its checks are green, then it is merged once, after the last component of the plan has
  merged and its image exists, and Argo syncs dev once for the whole spec; a component's own dev pin does not land before
  it.
- **AC-144.3** Given a component ship that runs inside a system ship, when its PR has merged and its image is built, then
  its deploy phase ends at "pinned in the system ship's dev PR" instead of waiting for a `pin-dev` run, and the component
  ship counts as delivered for the system ship's scheduler.
- **AC-144.4** Given the joint dev PR merged and dev synced, when the system ship continues, then it runs the dev smoke of
  every component of the plan (as `cplat instance verify dev` records it, spec 142) and reports each result; a red smoke
  escalates the system ship naming the component, as a red component ship does today.
- **AC-144.5** Given a component of the plan whose build fails or escalates, when the others have merged, then the joint
  dev PR is not merged and the system ship escalates naming that component; dev keeps running the builds it ran before the
  ship, so dev never gets a partial spec.
- **AC-144.6** Given a merge to a component's `main` that is not part of a running system ship (a fix, a release commit,
  a component ship of its own), then `pin-dev` behaves as today: one PR per build, merged on green CI.
- **AC-144.7** Given staging set to `promote: after-dev-smoke` and a system ship whose dev smokes all pass, then staging is
  promoted in one gitops PR for all components of the spec, not one per component.
- **AC-144.8** Given the part 2 journey of spec 136 (one system spec across the gitops repo and two component repos),
  when it is recorded with `cplat platform runs journey`, then the gitops repo gets one dev PR for the system spec besides
  its spec, plan and done PRs (2026-11-05: three), and the stages `2.pr-ci` and `2.deploy-dev` show it.

## Non-goals

- The part 3 environment settings (hosts, policy, observability, backups in one PR, #427): a command for observability
  and backups is its own change, and `system set` across several settings is out of scope here.
- The spec, plan and done PRs of a system spec; spec 136's later criteria and #410 cover them.
- Promotions to prod: the prod PR and its gate stay as they are (`/instance:promote`, spec 093).
- Merging component PRs into one: each component repo keeps its own PR and CI.
- Shortening a single gitops CI run (spec 136's later AC on gitops CI time).
- Changing a component ship that is not inside a system ship.

## Open questions

- ~~How does a component's build reach the joint PR?~~ Answered by the user (2026-11-05): the system ship pins each component itself with `pin.py` on its `compose/<spec>` branch after the component ship has merged and its `sha-<40>` image exists; `pin-dev.yml` reads a `ship/<spec>` marker and skips its own PR for that commit (AC-144.1).
- ~~Must the resources land before the components that use them?~~ Answered: no; they land together and Argo's sync waves order them, the joint PR adds the waves where they are missing (AC-144.2).
- ~~A component fails while the others are green?~~ Answered: keep the joint PR open and escalate; landing a partial spec is the user's decision (AC-144.5).
- ~~Does the system ship's dev smoke replace the component ship's?~~ Answered: yes (AC-144.3, AC-144.4).
- ~~Gitops-apps rendered before this spec?~~ Answered: the system ship keeps one PR per component, with one line saying so, until `/platform:update` brings the new `pin-dev.yml`.
- ~~Staging too (AC-144.7) or strictly dev?~~ Answered: dev and staging; AC-144.7 stays.

## Changelog

- 2026-11-05 created from spec 136's AC-136.11 (moved here by the user's decision) and its measurement of journey 2
- 2026-11-05 open questions answered by the user as recommended; AC-144.7 (staging) kept
- 2026-11-05 approved
- 2026-11-05 building
- 2026-11-05 done
