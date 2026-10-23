---
spec_id: 097-ship-a-whole-product-across-repos
title: Ship a whole product across repos
status: approved
priority: P1
---

# 097 — Ship a whole product across repos

## Problem

A single-repo spec ships unattended from approval to `dev` (`/svc:ship`, specs 067 and 076), but a product spec does not. `/app:build` stops at open PRs in every wave: the user merges each one, checks that the gitops entry landed first, and starts the next wave by hand. The approval of the product spec is the human decision; the waves, merges and waits after it are routine work.

Depends on 087 (run records), 091 (dev smoke tests) and 098 (gitops CI checks Components against the CRD from the service branch; it ships before this spec so that an unattended product run cannot merge a gitops change that breaks against its service's new CRD).

## Stories

As a founder, I want one command that takes an approved product spec through every repo's spec, plan, build, PR, green CI, merge and `dev` deployment with green smoke tests, in plan order, so that the only human step is approving the product spec.
**Repos:** the gitops-app repo and every component repo the product plan lists.

## Acceptance criteria

- **AC-097.1** Given `/app:ship <spec>` in a repo whose shape is not `gitops-app`, or a product spec that is not approved, when it starts, then it refuses with a hint (`/svc:ship` for a component repo; approve the spec first) and changes nothing.
- **AC-097.2** Given an approved product spec without a product plan, when `/app:ship` starts, then it plans it unattended and continues only when the plan passes `plan-check`; architect blockers or a failing check end the run escalated with the reason.
- **AC-097.3** Given a product spec or plan that is missing on the default branch or differs from it, when the run starts, then it opens a PR with them, merges it after all checks are green, and only then starts any repo; a red check starts no repo and escalates.
- **AC-097.4** Given an escalated or interrupted product ship, when `/app:ship <spec>` is started again, then it resumes from its recorded state (which is never committed): repos already deployed are not touched again and a repo in progress resumes at its own ship phase. While the run is neither done nor escalated, the session is not allowed to end.
- ~~**AC-097.5**~~ withdrawn 2026-10-23: replaced by AC-097.19 (fallback gates for libraries and services not exposed in `dev`).
- **AC-097.6** Given a component repo that starts, when its slice is created from the plan, then its repo spec carries `parent:` and is approved by the run if it has no open questions; if it has any, that repo escalates with the questions verbatim and none is answered by the run.
- **AC-097.7** Given an approved repo slice, when its ship runs, then it goes through the same phases, limits and escalation rules as `/svc:ship` (plan, build, PR, land after green checks with at most 3 red rounds, deploy to `dev` with smoke) in that repo's own clone; a clone with uncommitted changes is refused with its path, and nothing is ever pushed to a repo's default branch directly.
- **AC-097.8** Given a plan entry for the gitops-app repo itself, when it is ready, then the run builds it as `/app:build` does (spec 045), merges its PR after all checks are green, and no repo that depends on it starts before that merge; a red check escalates with the failed checks.
- **AC-097.9** Given several open gitops PRs of one product run (the gitops entry and the gitops tasks of repo ships, spec 076), when they are merged, then they merge one at a time in plan order; a PR that no longer merges cleanly after another one merged stops that repo with an escalation naming both PRs, and nothing is force-pushed.
- **AC-097.10** Given a repo whose ship escalates (including red smoke in `dev`, which files its issue as spec 091 describes), when the run continues, then no repo that depends on it starts, repos already in progress finish their current ship, and the run ends escalated with a table of every repo and its state; resuming continues at the escalated repo.
- ~~**AC-097.11**~~ withdrawn 2026-10-23: replaced by AC-097.20 (completion follows the gates of AC-097.19).
- **AC-097.12** Given a product ship, when it finishes, escalates or is taken over, then exactly one run record (spec 087) is written at that run end (none at its start) with `kind` `product-ship`, `repo` the gitops-app repo, `spec` the product spec, `outcome` `done`, `escalated` or `abandoned`, the escalation with its `cause` (spec 088) taken from the repo that escalated, and a list of the `run_id`s of the repo ship records it drove. A resumed product ship is a new run whose record names the escalated run in `resumes`.
- ~~**AC-097.13**~~ withdrawn 2026-10-23: moved to spec 098 (issue #110).
- ~~**AC-097.14**~~ withdrawn 2026-10-23: moved to spec 098 (issue #110).
- ~~**AC-097.15**~~ withdrawn 2026-10-23: moved to spec 098 (issue #110).
- ~~**AC-097.16**~~ withdrawn 2026-10-23: moved to spec 098 (issue #110).
- ~~**AC-097.17**~~ withdrawn 2026-10-23: moved to spec 098 (issue #110).
- **AC-097.18** Given `/app:ship <spec>` without a kube context for the product's cluster, when it starts, then it refuses with a hint to name or select that context and changes nothing.
- **AC-097.19** Given the product plan, when the run schedules repos, then a repo starts only when every repo in its `depends_on` has passed its gate, and repos whose dependencies passed run at the same time, at most `--max` at once (default 3). The gates are:
  - a deployable service exposed in `dev`: its ship finished with the merged build Synced/Healthy in `dev` and smoke `passed` or `passed on retry` (spec 091); smoke `not run` or red never passes the gate;
  - a service not exposed in `dev`: Argo reports its merged build Synced/Healthy in `dev`;
  - a library: its PR is merged.
- **AC-097.20** Given every repo of the plan past its gate (AC-097.19), when the run finishes, then the product spec is `done` and the plan completed (both on the default branch through a PR merged on green). The report shows one row per repo (repo spec, PR, CI rounds, `dev` image and Argo state, and the `Smoke (dev)` result as spec 091 words it, `not run: <reason>` for a service not exposed in `dev` or a library), the plans' `human_steps` as a checklist, and the `/gitops:promote` commands for staging; this run promotes nothing beyond `dev`.

## Non-goals

- Promoting to staging or prod (staging on green smoke is spec 093; prod stays `/gitops:promote`).
- Re-planning a repo after a merge conflict between its task branches (spec 094); here such a conflict escalates as in `/svc:ship`.
- Changing `/app:build`: it stays the attended flow that stops at open PRs.
- Gitops CI validating Components against the CRD from the service branch (spec 098).
- A product-wide smoke test across several services after the last repo is deployed (a follow-up spec); each repo runs only its own `dev` smoke (spec 091).

## Open questions

- ~~Should `/app:ship` plan a product spec that has no plan yet, instead of refusing with a hint to `/app:plan`?~~ Answered: yes, unattended, see AC-097.2.
- ~~When the product spec or plan is not on the default branch, may the run open and merge that PR itself?~~ Answered: yes, merged only after green checks, see AC-097.3 and AC-097.11.
- ~~Is "deployed in `dev` with green smoke tests" the gate before a dependent repo starts, or is "PR merged" enough?~~ Answered: deployed in `dev` with green smoke, see AC-097.5.
- ~~Confirm: repos of the same wave run in parallel, at most 3 by default, as in `/app:build`.~~ Answered: yes, see AC-097.5.
- ~~Gitops CI needs read access to private service repos to fetch their CRDs. Where does it come from?~~ Moved to spec 098.
- ~~Confirm: when the marker's branch is gone, CI validates against the service repo's default branch instead of failing.~~ Moved to spec 098.
- ~~Confirm: `/app:build` stays as the attended flow next to `/app:ship`.~~ Answered: yes, see Non-goals.
- ~~Smoke `not run` never counts as passed (spec 091), so under AC-097.5 a dependency whose smoke cannot run would block its dependents. What should gate the dependents then?~~ Answered: no start without a kube context (AC-097.18); a library gates on its merged PR, a service not exposed in `dev` on Argo Synced/Healthy for the merged build, reported as `not run: <reason>` (AC-097.19, AC-097.20).
- ~~Should 097 also run a product-level smoke after the last repo is deployed?~~ Answered: no, a follow-up spec, see Non-goals.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended: open questions answered (unattended product planning, spec/plan PR merged on green, dependents wait for `dev` with green smoke, wave parallelism 3, `/app:build` kept); the gitops CI CRD validation (AC-097.13 to AC-097.17, issue #110) withdrawn and moved to spec 098, which this spec now depends on; the run record aligned with specs 087 and 088.
- 2026-10-23 amended: no start without a kube context (AC-097.18); AC-097.5 and AC-097.11 withdrawn and replaced by AC-097.19 and AC-097.20 with fallback gates for libraries and services not exposed in `dev`; product-wide smoke added to Non-goals; AC-097.12 clarified to one record at run end only.
- 2026-10-23 approved
