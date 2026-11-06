---
spec_id: 147-the-system-plan-writes-the-repo-specs
title: The system plan writes the repo specs
status: approved
priority: P1
shape: platform
---

# 147 — The system plan writes the repo specs

## Problem

A system spec goes through four writing rounds before any code exists: the system spec, the system plan, then a repo spec and a repo plan for every component repo. In journey 4 (2026-11-06, [docs/PERFORMANCE.md](../../PERFORMANCE.md)) the step "Plan and ship it to dev" took 65 of 164 working minutes and 38 of 77 M tokens. Inside it, a product-manager agent wrote each repo spec again from the system criteria, with its own open questions, and the ship then amended it with the suggested answers. The repo specs came out at 19 and 23 criteria for a task list. The decisions were already made: the user answered them on the system spec and approved its plan (spec 141). Writing them a second time per repo costs a full agent round per repo, grows the criteria (and with them the tests, code and review), and adds questions nobody needs to answer.

## Stories

As someone shipping a feature across several repos, I want the approved system spec and its plan to be all the specification there is, so that the ship goes straight from the plan to building each repo.

As someone reading a repo spec, I want a small set of criteria that each name the system criterion they serve, so that I can see why every test exists.

## Acceptance criteria

- **AC-147.1** Given an approved system spec, when the system planner writes the plan, then every component repo's slice lists that repo's own criteria (Given / when / then, each ending with the system criterion it serves, `(system AC-<NNN>.<n>)`), between 3 and 8 per repo unless the slice says why more are needed.
- **AC-147.2** Given a plan that lists repo criteria, when its plan check (`devbox run plan-check`) runs, then it refuses a component repo slice without criteria, a criterion that names no system criterion or one outside its slice, and a system criterion of a slice that none of its criteria serves; the gitops-app repo's own slice needs no criteria.
- **AC-147.3** Given a plan whose slice has criteria, when `cplat spec new --from-plan <plan> <repo>` runs, then the repo spec holds those criteria as its own acceptance criteria (numbered in the repo spec), the System context section and no open questions, and `cplat spec check` passes on it without any edit.
- **AC-147.4** Given `/system:ship` and a plan whose slices have criteria, when a repo's ship starts, then its repo spec is created and approved without a product-manager agent and without questions, and the ship continues with the repo plan.
- **AC-147.5** Given a plan written before this spec (a slice without criteria), when the repo's ship starts, then the repo spec is written as before (product-manager, the suggested answers taken under `/system:ship`).
- **AC-147.6** Given a spec with more than 12 active criteria, when `cplat spec check` runs, then it passes with a warning that names the count and suggests splitting the spec; the product-manager and planner guidance aims at 3 to 8 criteria per spec or slice.
- **AC-147.7** Given journey 5, when its step "Plan and ship it to dev" runs, then no product-manager agent runs for a repo spec and no repo-spec question is asked, and the step's time, tokens and criteria count are recorded in `docs/PERFORMANCE.md` next to journey 4's.

## Non-goals

- The component route (`/component:spec` for a feature of one repo) is unchanged.
- Each repo is still planned by its own architect (`/component:plan`); the system plan does not replace the repo plan.
- No change to budgets, gates, reviews or the order of the ship.
- Existing plans are not rewritten; they keep the old flow (AC-147.5).

## Open questions

- ~~Who writes a repo's criteria: the system planner in the plan, or a product-manager per repo?~~ Answered (the recommended option, self-approved for this round on 2026-11-06 while the user is away): the system planner, in the plan; it already knows the contract and the system criteria.
- ~~How many criteria per repo?~~ Answered: 3 to 8 as guidance; `cplat spec check` warns above 12 and never fails on the count (AC-147.6).
- ~~Should a product-manager still review the repo spec's wording?~~ Answered: no; the reviewer checks the build against the criteria as before.

## Changelog

- 2026-11-06 created after the journey 4 analysis (strategy item 3); open questions answered with the recommended options, as the user asked for this round.
- 2026-11-06 approved
- 2026-11-06 AC-147.2 clarified: the check applies to a plan that lists repo criteria (older plans keep AC-147.5); the check is the gitops repo's plan check.
