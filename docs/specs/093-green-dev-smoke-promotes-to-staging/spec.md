---
spec_id: 093-green-dev-smoke-promotes-to-staging
title: Green dev smoke promotes to staging
status: draft
priority: P1
---

# 093 — Green dev smoke promotes to staging

## Problem

Every merge reaches `dev` by itself (spec 062, ADR-027), and with spec 091 the platform also checks the shipped spec in `dev` with smoke tests. `staging` still moves only when someone runs `/gitops:promote <service> dev staging` and merges the PR by hand. Staging therefore lags behind `dev` by however long it takes a human to notice. The evidence that a build works (green CI, healthy in dev, green smoke) already exists, but nobody acts on it. At `prod` time the person deciding sees a tag and nothing else: the PR says nothing about whether that build ran in staging or passed its smoke tests there. The round brief (decision 6) asks to replace this human step with the platform's own evidence for staging, while `prod` stays a human decision made with that evidence in front of the person deciding.

Depends on 091 (smoke tests and the `dev` smoke result). It uses 087 (run records) to record results and the issue deduplication of 088/091 to report red staging smoke.

## Stories

As a developer, I want a build that passed its smoke tests in `dev` to reach `staging` without me doing anything, so that `staging` always runs the newest build that is known to work.

As the person who promotes to `prod`, I want `/gitops:promote … staging prod` to show me what the platform knows about the release (did its build run in staging, did its smoke tests pass there, are issues open), so that I accept the risk knowingly and don't have to dig through CI runs.

As an operator, I want to switch automatic promotion off for one service or a whole app, so that I can hold `staging` still while someone is testing there.

## Acceptance criteria

- **AC-093.1** Given a service in a gitops-app with automatic staging promotion on, that is already in `staging`, when the `dev` smoke tests (spec 091) pass for the build `dev` runs, then the gitops-app gets a PR that pins that service's `staging` to the same image tag `dev` runs (`sha-<40>`). The PR merges itself once the gitops-app CI passes, and `staging` runs that image within 15 minutes of the green smoke result, with no manual command.
- **AC-093.2** Given a gitops-app, when its settings are read, then automatic staging promotion is set once for the whole app and can be overridden per service. With no setting at either level it is off. A service whose effective setting is off gets no automatic staging PR, and the run's report says "automatic promotion to staging is off for <service>".
- **AC-093.3** Given a build whose `dev` smoke tests failed, or did not run for any reason, when the run ends, then no staging PR is opened, `staging` keeps its image, and the report names the reason ("dev smoke failed" or "dev smoke not run: <reason>").
- **AC-093.4** Given a service that is not yet in `staging`, when its `dev` smoke passes, then no staging PR is opened, and the report names the manual first step: `/gitops:promote <service> dev staging`.
- **AC-093.5** Given `staging` already runs a later commit of the service's main than the build that passed `dev` smoke, when promotion would start, then nothing is pinned and the report says that `staging` is already newer. Given an open automatic staging PR for an older build of the same service, when a newer build is promoted, then the older PR is closed with a comment naming the newer one.
- **AC-093.6** Given an automatic staging PR whose gitops-app CI fails, when it does not merge, then the PR stays open with a comment linking the failed run, `staging` keeps its previous image, and a run that waits for staging (AC-093.8) escalates with that reason.
- **AC-093.7** Given an automatic staging PR, when someone reads it, then its title and body say it was opened automatically under spec 093 and name the service, the new tag, the tag `staging` ran before, and the green `dev` smoke result with a link to where it was recorded. Reverting the merged PR puts `staging` back on the previous image.
- **AC-093.8** Given a build that `staging` now runs, with the service healthy in Argo CD on that tag, when the platform checks it, then the same smoke tests as in `dev` run against the service's staging URL. Their result (passed / failed / not run, the time and a link) is recorded in the run record (spec 087). When the build was shipped with `cplat ship`, the run's final report also states the staging promotion and the staging smoke result.
- **AC-093.9** Given staging smoke tests that fail, when the result is recorded, then one deduplicated issue is filed (or an existing open one is updated) in the service's repo, following the same convention as red `dev` smoke in spec 091. It names the environment `staging`, the build and the failing tests, with secrets redacted. `staging` stays on the build, and a `cplat ship` run waiting for it escalates.
- **AC-093.10** Given a service with no URL in `staging` (not exposed there, or the app defines no staging host), when the staging smoke would run, then its result is "not run: no staging URL for <service>", which is never counted as passed.
- **AC-093.11** Given `/gitops:promote <service...> staging prod` (including `--dry-run`), when it runs, then before opening the PR it shows an evidence summary for each service. The summary gives the release version and its commit, the commit `staging` runs, the `dev` and staging smoke results for the release's commit (passed / failed / not run / no record, each with time and link), and the number and links of open issues filed for the service by smoke tests (091, this spec) or alerts (spec 092). The same summary goes into the PR body.
- **AC-093.12** Given a release whose commit has no green staging smoke result (failed, not run, no record, or `staging` runs a different commit), when the prod evidence summary is shown, then it starts with a warning line that says why. The prod PR is still opened, so the decision stays with the person.
- **AC-093.13** Given any setting, when a gitops-app is validated, then a value that would promote `prod` automatically is rejected with a message that `prod` is promoted only by `/gitops:promote`. No platform step ever merges a prod promotion PR.
- **AC-093.14** Given the docs (USER-JOURNEY, HOW-IT-WORKS, the gitops-app CLAUDE.md), the `/gitops:promote` command and the agents, when they describe how `staging` and `prod` move, then they describe the mechanism of this spec, including how to turn automatic promotion off.

## Non-goals

- Automatic promotion to `prod`, in any form.
- Automatic rollback of `staging` when staging smoke fails (see the open question; the default is to stay on the build and file an issue).
- Promoting several services of a product together as one unit, or ordering their promotions by dependency (spec 097 covers cross-repo shipping).
- Adding a service to `staging` for the first time; that stays `/gitops:promote <service> dev staging` (AC-093.4).
- Load, soak or manual exploratory testing in staging; only the spec 091 smoke tests run.
- A time window or schedule for promotions (for example, "only on weekdays").

## Open questions

- Should automatic staging promotion be on or off when a gitops-app sets nothing? (suggested: off for existing gitops-apps, which have no setting until they add one; newly generated gitops-apps have it switched on in their app-wide settings, so new products get the autonomy and existing ones opt in with one line; affects AC-093.2)
- Confirm: the setting is app-wide with a per-service override, read from the gitops-app's app settings and its service registry. (suggested: yes; affects AC-093.2)
- Which builds get promoted: only builds shipped through `cplat ship` (where 091 runs the `dev` smoke tests), or every merge that reaches `dev`, even one merged by hand? (suggested: every build with a green `dev` smoke result, wherever that smoke ran. A build merged by hand gets no `dev` smoke under 091, so it is not promoted. That gives one rule and no second smoke runner. Affects AC-093.1, AC-093.3)
- Who runs the promotion and the staging smoke when nobody is in a `cplat ship` session? (suggested: the same place that ran the `dev` smoke. Inside `cplat ship` the run waits for staging and reports it (AC-093.8). The runner-side variant follows 091's answer; affects AC-093.1, AC-093.8)
- When staging smoke fails, should `staging` be put back on its previous image automatically? (suggested: no. File the deduplicated issue and keep the build in `staging` so it can be investigated; the prod summary shows the red result. A rollback is a revert of the promotion PR. Affects AC-093.9 and a possible new criterion)
- Should a missing or red staging result block the prod promotion, or only warn? (suggested: warn only, since prod is where a human accepts risk; affects AC-093.12)
- Confirm: `staging` runs the promoted build within 15 minutes of the green `dev` smoke result. (suggested: yes, same order as spec 062's 10 minutes plus one gitops CI run; affects AC-093.1)
- Confirm: only services already in `staging` are promoted automatically, and the first entry into `staging` stays manual. (suggested: yes, because the first entry needs staging-specific settings such as hosts, secrets and replicas; affects AC-093.4)

## Changelog

- 2026-10-23 created
