---
spec_id: 091-ship-checks-the-spec-in-dev-with-smoke
title: Ship checks the spec in dev with smoke tests
status: building
priority: P0
---

# 091 — Ship checks the spec in dev with smoke tests

## Problem

`/svc:ship` ends when Argo CD reports `<service>-dev` Synced/Healthy on the merged build (specs 067, 077). Healthy only means the pods answer their probes. Nobody checks whether the feature the spec describes works in dev. The final report says "Next: check the feature in dev", so a human still has to do it by hand. When the user doesn't, a broken build sits in dev unnoticed and is later promoted. This spec lets the platform produce that evidence itself. A spec marks the criteria that can be checked against a running system. Every deployable shape gets a `smoke` recipe that runs those tests against any base URL. Ship runs the recipe against dev and turns a red result into an escalation and a deduplicated issue. Spec 093 (auto-promotion to staging) builds on this.

Depends on 087 (run records) and 088 (the deduplicated-issue convention and helper).

## Stories

As a founder, I want ship to run the spec's smoke tests against dev after Argo reports it healthy, so that "shipped" means the feature works in dev, not only that the pods started.

As a founder, I want a red smoke result in dev to stop the run and land in the service repo as one issue per distinct failure, so that I route it in triage instead of finding it by hand.

As a spec author, I want to mark which criteria are smoke-checkable, so that the build writes tests that can run against a deployed environment.

## Acceptance criteria

- **AC-091.1** Given a spec criterion whose line ends with `(smoke)`, when `cplat spec trace <spec>` runs, then the criterion counts as traced only if at least one test names its id and carries the shape's smoke tag. Otherwise trace exits 1 and names the criterion as `smoke: no smoke-tagged test`. `cplat spec check` accepts the marker on active criteria.
- **AC-091.2** Given a repo of each deployable shape (service-python, service-java, service-go, web-nextjs), whether newly generated or updated with `/shared:update-service`, when `devbox run smoke` runs with `SMOKE_BASE_URL` set, then:
  - it runs only the smoke-tagged tests, sending their requests to that URL;
  - it prints one line per test with its result, plus the passed, failed and skipped counts;
  - it exits 0 only when no test failed;
  - a repo with no smoke-tagged tests exits 0 and prints `0 smoke tests`.
- **AC-091.3** Given `SMOKE_BASE_URL` is unset or empty, when `devbox run smoke` runs, then no test runs and it exits non-zero with a message that names `SMOKE_BASE_URL`.
- **AC-091.4** Given a freshly generated repo of each deployable shape, when `devbox run ci` runs, then it passes; the skeleton contains one example smoke test (the health endpoint, or the root page for web-nextjs); and `devbox run test` and `devbox run ci` never send smoke tests to a deployed environment (without `SMOKE_BASE_URL` they are reported as skipped).
- **AC-091.5** Given a spec with a `(smoke)` criterion, when `/svc:build` (or `/svc:ship`) writes its acceptance tests, then:
  - at least one test naming that id is smoke-tagged;
  - that test reaches the service only through the base URL;
  - it can be repeated against a shared environment: it creates its own data with unique names and never changes or deletes data it did not create.
- **AC-091.6** Given a ship run whose deploy saw `<service>-dev` and every app named by the gitops tasks Synced/Healthy on the merged build, when deploy continues, then:
  - it runs the repo's `smoke` recipe (every smoke-tagged test of the repo, not only the spec's) against the service's dev URL as published by the linked gitops-app;
  - the deploy succeeds only if smoke passes;
  - its output lists each smoke test with its result and, for every `(smoke)` criterion of the spec, `passed` or `failed`.
- **AC-091.7** Given a smoke run in deploy with at least one failing test, when it is the first attempt, then smoke runs once more after 30 seconds and only a second failure counts as red. A pass on the second attempt is reported as `passed on retry` and recorded as a flaky result.
- **AC-091.8** Given a smoke run in deploy that has not finished after 10 minutes, when the limit is reached, then the run is stopped and counts as red with `timed out after 600s`.
- **AC-091.9** Given red smoke in dev, when deploy ends, then:
  - it exits 1;
  - it prints the failing tests and the last 60 lines of their output with secrets redacted;
  - the ship run is escalated with the reason `smoke red in dev: <n> failing (<spec_id>)`;
  - dev keeps running the merged build (nothing is rolled back).
- ~~**AC-091.10**~~ withdrawn 2026-10-23: replaced by AC-091.14, which follows spec 088's issue convention (signature line, `[auto] ` title, labels, closed-issue repeats, cap).
- **AC-091.11** Given a deploy that cannot reach a confirmed dev build, when deploy finishes, then smoke is not run and deploy finishes with a note `smoke not run: <reason>` that lists the spec's `(smoke)` criteria left unchecked. The run is not escalated. This applies when:
  - no kube context was given, so Argo health was not checked;
  - the service has no dev URL (not exposed in dev);
  - the repo is not linked to a gitops-app.
- **AC-091.12** Given a run escalated on red smoke, when `/svc:ship <spec>` resumes it, then deploy runs only smoke again, without waiting for the pin again, against what dev runs now. A pass finishes the run; a red result follows AC-091.9 and AC-091.14 again.
- ~~**AC-091.13**~~ withdrawn 2026-10-23: replaced by AC-091.15, which uses spec 087's record fields and states that "not run" never counts as passed.
- **AC-091.14** Given red smoke in dev, when the run escalates (escalation cause `code`, so nothing is filed in the platform repo, spec 088), then one issue is filed or +1'd in the service repo following spec 088's convention:
  - the body has exactly one line `Signature: smoke:<16 lowercase hex characters>`, computed from the service repo, the environment `dev` and the sorted ids of the failing tests, with the volatile parts of spec 088 (hashes, numbers, dates) left out;
  - the title is `[auto] Smoke red in dev: ` followed by the failing tests, at most 100 characters;
  - the labels are `triage`, `auto-filed` and `smoke-failure`;
  - the body states the spec id, the image tag, the failing tests, the output tail (at most 60 lines) with secrets redacted, and the run id;
  - an open issue with the same signature gets one counted comment with the new evidence instead of a new issue. A repeat after that issue was closed opens a new issue that links it, unless it was closed as `wontfix`;
  - the cap of spec 088 applies: at most 10 new auto-filed issues per 24 hours per machine;
  - if filing fails (no permission, network), the output says `not filed: <reason>`, the run's outcome does not change, and the filing is retried as spec 088 retries its filings.
- **AC-091.15** Given a finished or escalated ship run whose deploy reached smoke or skipped it, when the final report is printed and the run record is written, then:
  - the report has a `Smoke (dev)` row with `<passed>/<total> passed`, `passed on retry`, `red (<n> failing, issue <url>)` or `not run: <reason>`;
  - the run record (spec 087) carries a `smoke` section with the environment, the outcome (`passed` | `passed-on-retry` | `red` | `timed-out` | `not-run`), the passed, failed and skipped counts, the duration, whether a retry happened, the skip reason, and the signature, issue URL and `new` / `+1` / `suppressed` of a filed issue (as spec 088's `filed` entries);
  - `not-run` never counts as passed, neither in the report nor in the record. A spec with `(smoke)` criteria whose smoke did not run is reported with those criteria as unchecked.
- **AC-091.16** Given a web-nextjs repo, whether newly generated or updated with `/shared:update-service`, when it is checked, then it contains the browser end-to-end scaffold regardless of the former opt-in choice. Its smoke tests are browser tests that load pages at `SMOKE_BASE_URL`, and `devbox run smoke` runs them in the browser runner.

## Non-goals

- Smoke in staging or prod and promotion on green smoke (spec 093).
- Product-wide smoke across several services of a gitops-app (a later follow-up spec).
- Smoke for libraries: they have no deployment.
- Automatic rollback of dev, or an automatic fix of red smoke. The issue goes through `/shared:triage` like any other.
- Scheduled smoke runs against an environment at rest (firing alerts are spec 092).
- Load, performance or security testing against dev.

## Open questions

- ~~Confirm: a criterion is marked smoke-checkable with a trailing `(smoke)` on its line.~~ Answered: yes, see AC-091.1 and AC-091.5.
- ~~Confirm: the base URL is passed as `SMOKE_BASE_URL`.~~ Answered: yes, see AC-091.2, AC-091.3 and AC-091.4.
- ~~How should smoke handle a service that is not exposed through the gateway in dev?~~ Answered: smoke is skipped with a note, no tunnel into the cluster, see AC-091.11.
- ~~Without a kube context, should smoke be skipped?~~ Answered: yes, skipped, see AC-091.11.
- ~~Confirm: one retry after 30 seconds and a 10-minute limit per smoke run.~~ Answered: yes, see AC-091.7 and AC-091.8.
- ~~Every smoke test of the repo or only the spec's?~~ Answered: every smoke-tagged test of the repo, with the spec's criteria reported separately, see AC-091.6.
- ~~Confirm: red smoke never rolls back dev.~~ Answered: yes, see AC-091.9 and the non-goals.
- ~~Confirm: the issue label and the dedupe signature.~~ Answered: spec 088's convention with labels `triage`, `auto-filed` and `smoke-failure`, and kind `smoke` over service repo, environment and sorted failing test ids, see AC-091.14.
- ~~Browser runner or plain HTTP checks for web-nextjs smoke?~~ Answered: always the browser end-to-end runner, and the scaffold becomes standard, see AC-091.16.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended with the user's answers: AC-091.10 and AC-091.13 withdrawn, replaced by AC-091.14 (spec 088's issue convention) and AC-091.15 (spec 087's `smoke` record section; not-run never counts as passed); AC-091.16 added (web smoke always in the browser runner, scaffold standard); AC-091.6 clarified to run every smoke test of the repo
- 2026-10-23 approved
- 2026-10-24 building
