---
spec_id: 091-ship-checks-the-spec-in-dev-with-smoke
title: Ship checks the spec in dev with smoke tests
status: draft
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
  - it runs the repo's `smoke` recipe against the service's dev URL as published by the linked gitops-app;
  - the deploy succeeds only if smoke passes;
  - its output lists each smoke test with its result and, for every `(smoke)` criterion of the spec, `passed` or `failed`.
- **AC-091.7** Given a smoke run in deploy with at least one failing test, when it is the first attempt, then smoke runs once more after 30 seconds and only a second failure counts as red. A pass on the second attempt is reported as `passed on retry` and recorded as a flaky result.
- **AC-091.8** Given a smoke run in deploy that has not finished after 10 minutes, when the limit is reached, then the run is stopped and counts as red with `timed out after 600s`.
- **AC-091.9** Given red smoke in dev, when deploy ends, then:
  - it exits 1;
  - it prints the failing tests and the last 60 lines of their output with secrets redacted;
  - the ship run is escalated with the reason `smoke red in dev: <n> failing (<spec_id>)`;
  - dev keeps running the merged build (nothing is rolled back).
- **AC-091.10** Given red smoke in dev, when the run escalates, then an issue labelled `smoke-failure` is filed in the service repo. Its title names the failing tests; its body states the spec id, the image tag, the failing tests, the redacted output tail and a link to the run record.
  - If an open issue with the same signature (service repo, environment `dev`, sorted failing test ids) already exists, a comment with the new evidence is added to it instead of a new issue.
  - If filing fails (no permission, network), a warning is printed and the run's outcome does not change.
- **AC-091.11** Given a deploy that cannot reach a confirmed dev build, when deploy finishes, then smoke is not run and deploy finishes with a note `smoke not run: <reason>` that lists the spec's `(smoke)` criteria left unchecked. The run is not escalated. This applies when:
  - no kube context was given, so Argo health was not checked;
  - the service has no dev URL (not exposed in dev);
  - the repo is not linked to a gitops-app.
- **AC-091.12** Given a run escalated on red smoke, when `/svc:ship <spec>` resumes it, then deploy runs only smoke again, without waiting for the pin again, against what dev runs now. A pass finishes the run; a red result follows AC-091.9 and AC-091.10 again.
- **AC-091.13** Given a finished or escalated ship run, when the final report is printed, then:
  - it has a `Smoke (dev)` row with `<passed>/<total> passed`, `passed on retry`, `red (<n> failing, issue <url>)` or `not run: <reason>`;
  - the run record (spec 087) holds the smoke outcome, the counts, the duration, whether a retry happened, the skip reason and the issue link.

## Non-goals

- Smoke in staging or prod and promotion on green smoke (spec 093).
- Product-wide smoke across several services of a gitops-app (spec 097).
- Smoke for libraries: they have no deployment.
- Automatic rollback of dev, or an automatic fix of red smoke. The issue goes through `/shared:triage` like any other.
- Scheduled smoke runs against an environment at rest (firing alerts are spec 092).
- Load, performance or security testing against dev.

## Open questions

- Confirm: a criterion is marked smoke-checkable with a trailing `(smoke)` on its line. (suggested: yes; affects AC-091.1, AC-091.5)
- Confirm: the base URL is passed as `SMOKE_BASE_URL`. (suggested: yes; affects AC-091.2, AC-091.3, AC-091.4)
- A service that is not exposed through the gateway in dev has no URL ship can reach. Should smoke be skipped with a note, or should ship reach the service through a temporary tunnel into the cluster? (suggested: skip with a note, because a tunnel needs cluster access the unattended allowlist does not grant; affects AC-091.11)
- Without a kube context, Argo health is not confirmed. Should smoke be skipped, or run as soon as the pin PR is merged, at the risk of testing the old image? (suggested: skip; affects AC-091.11)
- Confirm: one retry after 30 seconds and a 10-minute limit per smoke run. (suggested: yes; affects AC-091.7, AC-091.8)
- Should smoke in deploy run every smoke-tagged test of the repo (catches regressions) or only the tests of the spec being shipped? (suggested: every smoke test of the repo, with the spec's criteria reported separately; affects AC-091.6)
- Confirm: red smoke escalates and files an issue but never rolls back dev. (suggested: yes, because rollback is a prod-style decision and dev is allowed to be broken; affects AC-091.9)
- Confirm: the issue label is `smoke-failure` and the dedupe signature is service repo + environment + sorted failing test ids. (suggested: yes, following spec 088's convention; affects AC-091.10)
- web-nextjs repos created without the end-to-end scaffold have no browser test runner. Should web smoke tests always use the browser runner, which would make the scaffold part of every web repo, or run as plain HTTP checks in the unit runner? (suggested: always ship the browser runner and make the scaffold standard, because smoke for a web app should load real pages; affects AC-091.2, AC-091.4)

## Changelog

- 2026-10-23 created
