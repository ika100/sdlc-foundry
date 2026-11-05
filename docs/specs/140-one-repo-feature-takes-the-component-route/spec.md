---
spec_id: 140-one-repo-feature-takes-the-component-route
title: A one-repo feature takes the component route
status: approved
priority: P1
shape: platform
---

# 140 — A one-repo feature takes the component route

## Problem

In the journey runs of 2026-11-05 the first feature ("create and list tasks", one service) went through the system route:
`/system:spec` → `/system:plan` → `/system:ship`, which adds a plan PR, a second spec for the repo (written from the plan),
a sub-agent and more CI rounds. Even "For taskboard2-api: I want to …" took that route, because Claude ran next to the
gitops repo and `/system:new` points every first feature at `/system:spec`. The same feature through `/component:spec`
and `/component:ship` took 17 minutes on 2026-11-03; through the system route it took about 70 minutes of working time
(journey 1, including stops) and stopped on questions the repo spec raised again.

## Stories

- As the owner of a system, I want a feature that changes one component to be specified and shipped in that component's
  repo, so that it needs one spec, one PR and one ship.
- As the owner of a system, I want the system route for features that span several repos or change the gitops repo, so
  that their contract and order are planned.

## Acceptance criteria

- **AC-140.1** Given `/system:spec <description>` in a gitops-app repo, when the description names exactly one component
  of `system.yaml` and asks for no resource, exposure or environment change, then the command says that one repo is
  enough, recommends `/component:spec` in that repo with the same description, and asks the user once, with the component
  route as the recommended answer, before writing a system spec (also when the match is unambiguous).
- **AC-140.2** Given the user picks the component route in AC-140.1, when the command continues, then it runs the component
  spec flow in that component's clone (the path `system.yaml` and the local checkout give) and the next step it prints is
  `/component:ship <id>` there; no system spec, plan or plan PR is created.
- **AC-140.3** Given a description that names two or more components, or asks for a resource, exposure or environment
  change, when `/system:spec` runs, then it writes a system spec as today, without the extra question.
- **AC-140.4** Given `/system:new` or `/component:new` finished, when they print the next steps, then the first-feature
  step recommends `/component:spec` in the component's repo for a feature of one component and `/system:spec` for one
  that spans repos, instead of `/system:spec` for every first feature.

## Non-goals

- No change to the system route itself (plan, ship, contracts).
- No new command.

## Open questions

1. ~~Should the component route be taken without asking when the match is unambiguous (one component named, nothing else)?
      (Recommended: ask once, with the component route as the recommended answer.)~~ Answered: ask once, component route recommended (AC-140.1).

## Changelog

- 2026-11-05 created (found in the journey runs of 2026-11-05)
- 2026-11-05 open question answered by the user (recommended answer)
- 2026-11-05 approved
