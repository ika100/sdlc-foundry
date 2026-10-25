---
spec_id: 093-green-dev-smoke-promotes-to-staging
title: Green dev smoke promotes to staging
status: building
priority: P1
---

# 093 — Green dev smoke promotes to staging

## Problem

Every merge reaches `dev` by itself (spec 062, ADR-027), and with spec 091 `cplat ship` also checks the shipped spec in `dev` with smoke tests. `staging` still moves only when someone runs `/gitops:promote <service> dev staging` and merges the PR by hand. Staging therefore lags behind `dev` by however long it takes a human to notice. The evidence that a build works (green CI, healthy in dev, green smoke) already exists, but nobody acts on it. At `prod` time the person deciding sees a tag and nothing else: the PR says nothing about whether that build ran in staging or passed its smoke tests there. The round brief (decision 6) asks to replace this human step with the platform's own evidence for staging, while `prod` stays a human decision made with that evidence in front of the person deciding.

Depends on 091: its `devbox run smoke` recipe with `SMOKE_BASE_URL`, the smoke outcome in the run record, and red-smoke issues. It also uses 087 (run records), the deduplicated-issue convention of 088, and the `alert` label of 092. It amends ADR-027 decision 4 for `staging`.

## Stories

As a developer, I want a build that passed its smoke tests in `dev` to reach `staging` without me doing anything, so that `staging` always runs the newest build that is known to work.

As the person who promotes to `prod`, I want `/gitops:promote … staging prod` to show me what the platform knows about the release (did its build run in staging, did its smoke tests pass there, are issues open), so that I accept the risk knowingly and don't have to dig through CI runs.

As an operator, I want to switch automatic promotion off for one service or a whole app, so that I can hold `staging` still while someone is testing there.

## Acceptance criteria

- **AC-093.1** Given a `cplat ship` run of a service in a gitops-app with automatic staging promotion on, where the service is already in `staging`, when the `dev` smoke outcome (spec 091) is passed or passed on retry, then ship gets a PR into the gitops-app that pins that service's `staging` to the same image tag `dev` runs (`sha-<40>`). The PR merges itself once the gitops-app CI passes, and `staging` runs that image within 15 minutes of the green smoke result, with no manual command.
- ~~**AC-093.2**~~ withdrawn 2026-10-23: the default is no longer "off everywhere"; replaced by AC-093.15.
- **AC-093.3** Given a ship run whose `dev` smoke outcome is red, or "not run" for any reason (spec 091), when deploy ends, then no staging PR is opened, `staging` keeps its image, and the report names the reason ("dev smoke red" or "dev smoke not run: <reason>"). A build merged outside `cplat ship` has no `dev` smoke outcome and is therefore never promoted automatically.
- **AC-093.4** Given a service that is not yet in `staging`, when its `dev` smoke passes, then no staging PR is opened, and the report names the manual first step: `/gitops:promote <service> dev staging`.
- **AC-093.5** Given `staging` already runs a later commit of the service's main than the build that passed `dev` smoke, when promotion would start, then nothing is pinned and the report says that `staging` is already newer. Given an open automatic staging PR for an older build of the same service, when a newer build is promoted, then the older PR is closed with a comment naming the newer one.
- **AC-093.6** Given an automatic staging PR whose gitops-app CI fails, when it does not merge, then the PR stays open with a comment linking the failed run, `staging` keeps its previous image, and the ship run escalates with that reason.
- **AC-093.7** Given an automatic staging PR, when someone reads it, then its title and body say it was opened automatically under spec 093 and name the service, the new tag, the tag `staging` ran before, and the green `dev` smoke result with a link to its run record. Reverting the merged PR puts `staging` back on the previous image.
- **AC-093.8** Given a build that `staging` now runs, with the service healthy in Argo CD on that tag, when ship continues, then it runs `devbox run smoke` with `SMOKE_BASE_URL` set to the service's staging URL as published by the gitops-app, using the same retry and time limit as in `dev` (AC-091.7, AC-091.8). The staging smoke outcome (passed / passed on retry / red / not run, with counts, time and issue link) is recorded in the run record's smoke section next to the `dev` outcome. The final report has a `Smoke (staging)` row in the format of AC-091.13.
- **AC-093.9** Given a red staging smoke outcome, when the run escalates, then an issue labelled `smoke-failure` is filed in the service repo following spec 091 and the 088 convention: a title starting with `[auto] `, labels `triage` and `auto-filed`, one `Signature: smoke:<16 hex>` line computed over service repo + environment `staging` + the sorted failing test ids, and secrets redacted. An open issue with the same signature gets a comment instead of a new issue. `staging` stays on the build (no automatic rollback), and the ship run escalates with `smoke red in staging: <n> failing (<spec_id>)`.
- **AC-093.10** Given a service with no URL in `staging` (not exposed there, or the app defines no staging host), when the staging smoke would run, then the outcome is "not run: no staging URL for <service>". It is never counted as passed, and the run is not escalated.
- **AC-093.11** Given `/gitops:promote <service...> staging prod` (including `--dry-run`), when it runs, then before opening the PR it shows an evidence summary for each service. The summary gives:
  - the release version and its commit;
  - the commit `staging` runs;
  - the `dev` and staging smoke outcomes for the release's commit from the run records (passed / passed on retry / red / not run / no record, each with time and link);
  - the number of open issues in the service repo labelled `smoke-failure` or `alert` (spec 092), with their links.

  The same summary goes into the PR body.
- **AC-093.12** Given a release whose commit has no green staging smoke outcome (red, not run, no record, or `staging` runs a different commit), when the prod evidence summary is shown, then it starts with a warning line that says why. The prod PR is still opened, so the decision stays with the person.
- **AC-093.13** Given any setting, when a gitops-app is validated, then a value that would promote `prod` automatically is rejected with a message that `prod` is promoted only by `/gitops:promote`. No platform step ever merges a prod promotion PR.
- **AC-093.14** Given the docs (USER-JOURNEY, HOW-IT-WORKS, the gitops-app CLAUDE.md), the `/gitops:promote` command and the agents, when they describe how `staging` and `prod` move, then they describe the mechanism of this spec, including how to turn automatic promotion off. None of them still says that `staging` promotions are never auto-merged.
- **AC-093.15** Given a gitops-app, when its settings are read, then automatic staging promotion is set once app-wide in its app settings and can be overridden per service in its service registry. A newly generated gitops-app has it switched on app-wide. An existing gitops-app that sets nothing at either level, including after `/shared:update-service`, has it off. A service whose effective setting is off gets no automatic staging PR, and the run's report says "automatic promotion to staging is off for <service>".
- **AC-093.16** Given the platform's decision records, when this spec ships, then a new ADR, listed in the ADR index, records that `staging` follows a green `dev` smoke through a self-merging pin PR while `prod` stays a manual, reviewed promotion with an evidence summary. The ADR amends ADR-027 decision 4, and ADR-027 links to it.

## Non-goals

- Automatic promotion to `prod`, in any form.
- Automatic rollback of `staging` when staging smoke fails. Rollback is a revert of the promotion PR (AC-093.7).
- Promoting builds merged outside `cplat ship`, or running smoke from a scheduled or runner-side job (spec 091 runs smoke only in ship).
- Blocking a prod promotion on missing or red staging evidence; the summary only warns (AC-093.12).
- Promoting several services of a product together as one unit, or ordering their promotions by dependency (spec 097 covers cross-repo shipping).
- Adding a service to `staging` for the first time; that stays `/gitops:promote <service> dev staging` (AC-093.4).
- Load, soak or manual exploratory testing in staging; only the spec 091 smoke tests run.
- A time window or schedule for promotions (for example, "only on weekdays").

## Open questions

- ~~Should automatic staging promotion be on or off when a gitops-app sets nothing?~~ Answered: off for existing gitops-apps, on for newly generated ones (AC-093.15).
- ~~Confirm: the setting is app-wide with a per-service override.~~ Answered: yes (AC-093.15).
- ~~Which builds get promoted?~~ Answered: every build with a green `dev` smoke outcome; builds merged by hand have none and are not promoted (AC-093.3).
- ~~Who runs the promotion and the staging smoke when nobody is in a `cplat ship` session?~~ Answered: the place that ran the `dev` smoke, which under spec 091 is `cplat ship` deploy (AC-093.1, AC-093.8; non-goal).
- ~~When staging smoke fails, should `staging` be put back on its previous image automatically?~~ Answered: no; file the deduplicated issue and keep the build (AC-093.9).
- ~~Should a missing or red staging result block the prod promotion, or only warn?~~ Answered: warn only (AC-093.12).
- ~~Confirm: `staging` runs the promoted build within 15 minutes of the green `dev` smoke result.~~ Answered: yes (AC-093.1).
- ~~Confirm: only services already in `staging` are promoted automatically.~~ Answered: yes, the first entry stays manual (AC-093.4).

## Changelog

- 2026-10-23 created
- 2026-10-23 amended: open questions answered. AC-093.2 withdrawn and replaced by AC-093.15 (off for existing gitops-apps, on for new ones). AC-093.1, AC-093.3, AC-093.6, AC-093.8, AC-093.9, AC-093.11 and AC-093.14 clarified to match spec 091 (promotion and staging smoke run in `cplat ship`; `devbox run smoke` with `SMOKE_BASE_URL`; smoke outcome and `smoke-failure` issue convention) and spec 092 (`alert` label). AC-093.16 added: a new ADR amends ADR-027 for staging.
- 2026-10-23 approved
- 2026-10-25 building
