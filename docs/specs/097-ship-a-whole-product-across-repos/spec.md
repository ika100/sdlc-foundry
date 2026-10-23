---
spec_id: 097-ship-a-whole-product-across-repos
title: Ship a whole product across repos
status: draft
priority: P1
tracks: [110]
---

# 097 — Ship a whole product across repos

## Problem

A single-repo spec ships unattended from approval to `dev` (`/svc:ship`, specs 067 and 076), but a product spec does not: `/app:build` stops at open PRs in every wave, the user merges each one, checks that the gitops entry landed first, and starts the next wave by hand. The approval of the product spec is the human decision; the waves, merges and waits after it are routine. A second gap makes an unattended product run risky: gitops CI checks Components only against the public schema catalog and skips unknown kinds, so a Component written for a CRD that the service branch changes is never checked against that CRD. This broke `ai-ops-config` during ai-ops spec 011 (`namespaces "ai-ops-build" not found`; issue #110).

Depends on 087 (run records) and 091 (dev smoke tests).

## Stories

As a founder, I want one command that takes an approved product spec through every repo's spec, plan, build, PR, green CI, merge and `dev` deployment in plan order, so that the only human step is approving the product spec.
**Repos:** the gitops-app repo and every component repo the product plan lists.

As a founder, I want gitops CI to check a Component against the CRD from the service branch it belongs to, so that a gitops change and its service change cannot land in a broken combination.
**Repos:** the gitops-app repo; the service repo that ships the CRD.

## Acceptance criteria

- **AC-097.1** Given `/app:ship <spec>` in a repo whose shape is not `gitops-app`, or a product spec that is not approved, when it starts, then it refuses with a hint (`/svc:ship` for a component repo; approve the spec first) and changes nothing.
- **AC-097.2** Given an approved product spec without a product plan, when `/app:ship` starts, then it plans it unattended and continues only when the plan passes `plan-check`; architect blockers or a failing check end the run escalated with the reason.
- **AC-097.3** Given a product spec or plan that is missing on the default branch or differs from it, when the run starts, then it opens a PR with them, merges it after all checks are green, and only then starts any repo; a red check starts no repo and escalates.
- **AC-097.4** Given a running product ship, when it is started again, then it resumes from its recorded state (which is never committed): repos already deployed are not touched again, a repo in progress resumes at its own ship phase; while the run is neither done nor escalated, the session is not allowed to end.
- **AC-097.5** Given the product plan, when the run schedules repos, then a repo starts only when every repo in its `depends_on` is deployed in `dev` with green smoke tests (spec 091), and repos whose dependencies are met run at the same time, at most `--max` at once (default 3).
- **AC-097.6** Given a component repo that starts, when its slice is created from the plan, then its repo spec carries `parent:` and is approved by the run if it has no open questions; if it has any, that repo escalates with the questions verbatim and none is answered by the run.
- **AC-097.7** Given an approved repo slice, when its ship runs, then it goes through the same phases, limits and escalation rules as `/svc:ship` (plan, build, PR, land after green checks with at most 3 red rounds, deploy to `dev`) in that repo's own clone; a clone with uncommitted changes is refused with its path, and nothing is ever pushed to a repo's default branch directly.
- **AC-097.8** Given a plan entry for the gitops-app repo itself, when it is ready, then the run builds it as `/app:build` does (spec 045), merges its PR after all checks are green, and no repo that depends on it starts before that merge; a red check escalates with the failed checks.
- **AC-097.9** Given several open gitops PRs of one product run (the gitops entry and the gitops tasks of repo ships, spec 076), when they are merged, then they merge one at a time in plan order; a PR that no longer merges cleanly after another one merged stops that repo with an escalation naming both PRs, and nothing is force-pushed.
- **AC-097.10** Given a repo whose ship escalates, when the run continues, then no repo that depends on it starts, repos already in progress finish their current ship, and the run ends escalated with a table of every repo and its state; resuming continues at the escalated repo.
- **AC-097.11** Given every repo of the plan deployed in `dev`, when the run finishes, then the product spec is `done` and the plan completed (both on the default branch through a PR merged on green), and the report shows one row per repo (repo spec, PR, CI rounds, `dev` image and Argo state, smoke result), the plans' `human_steps` as a checklist, and the `/gitops:promote` commands for staging; nothing is promoted beyond `dev` by this run.
- **AC-097.12** Given a product ship, when it starts, escalates or finishes, then it appends one product run record (spec 087) with the product spec, outcome, escalation reason and time per repo, linked to the run record of each repo ship.
- **AC-097.13** Given a gitops PR opened by `cplat ship gitops pr`, when it is opened, then its body names the service repo and branch the change belongs to in a marker that gitops CI reads.
- **AC-097.14** Given a gitops PR with that marker, when gitops CI validates it, then every changed Component whose kind is defined by a CRD shipped in that service branch's chart is validated against that CRD before the catalog, and an invalid Component fails the check with the file, the kind, the offending field and the `<repo>@<branch>` it was checked against.
- **AC-097.15** Given a marker whose branch no longer exists (merged or deleted), when gitops CI validates the PR, then it validates against the service repo's default branch and says so in the check log; given a service repo it cannot read, then the check fails with a hint naming the missing access, never skipping the validation silently.
- **AC-097.16** Given a marker naming a repo that the gitops-app does not link, when gitops CI validates the PR, then the check fails naming the repo and fetches nothing from it.
- **AC-097.17** Given a gitops PR or push without the marker (a hand-written PR, a pin PR, a push to the default branch), when gitops CI runs, then it validates exactly as before this spec.

## Non-goals

- Promoting to staging or prod (staging on green smoke is spec 093; prod stays `/gitops:promote`).
- Re-planning a repo after a merge conflict between its task branches (spec 094); here such a conflict escalates as in `/svc:ship`.
- Changing `/app:build`: it stays the attended flow that stops at open PRs.
- Validating anything other than Components against CRDs from a service branch (Helm values, chart templates).
- A product-level smoke test across repos beyond each repo's own `dev` smoke tests (spec 091).

## Open questions

- Should `/app:ship` plan a product spec that has no plan yet, instead of refusing with a hint to `/app:plan`? (suggested: yes, as `/svc:ship` does for a repo spec; affects AC-097.2)
- When the product spec or plan is not on the default branch, may the run open and merge that PR itself? (suggested: yes, merged only after green checks; affects AC-097.3, AC-097.11)
- Is "deployed in `dev` with green smoke tests" the gate before a dependent repo starts, or is "PR merged" enough? (suggested: deployed with green smoke, so a dependent repo builds against a running dependency; affects AC-097.5)
- Confirm: repos of the same wave run in parallel, at most 3 by default, as in `/app:build`. (suggested: yes; affects AC-097.5)
- Gitops CI needs read access to private service repos to fetch their CRDs. Where does it come from? (suggested: one read-only token secret in the gitops-app repo, reported by `cplat doctor` as a warning when missing; without it a PR with a marker fails with a hint, a PR without a marker is unaffected; affects AC-097.15, new criterion for doctor)
- Confirm: when the marker's branch is gone, CI validates against the service repo's default branch instead of failing. (suggested: yes, since `after-release` gitops PRs merge after the service branch is merged and deleted; affects AC-097.15)
- Confirm: `/app:build` stays as the attended flow next to `/app:ship`. (suggested: yes; affects Non-goals)

## Changelog

- 2026-10-23 created
