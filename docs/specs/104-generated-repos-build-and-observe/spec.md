---
spec_id: 104-generated-repos-build-and-observe
title: Generated repos build and observe reliably
status: building
priority: P1
tracks: [143, 965]
---

# 104 — Generated repos build and observe reliably

## Problem

A static review of the todo sample (issue 143) found reliability gaps that a generated repo inherits from its template. The container build of `service-python` (and of `web-nextjs`) falls back to an install that ignores the lockfile when the locked install fails, so an outdated lockfile builds quietly and the image holds dependencies nobody reviewed. The `service-python` template declares request count, latency and error metrics, but only the `/ping` example records the count, by hand; every real endpoint a team adds is invisible in `/metrics`, and the latency and error metrics never receive a value. Nothing in the platform's own checks generates a repo and proves these two properties. Since ADR-125 a repo may also depend on a private library from GitHub Packages, read with the secret `PACKAGES_READ_TOKEN` (issue 965); CI and local installs can pass it, but the image build has no way to read it, and nothing tells a team that the secret is missing. Database deadlines (a `todo-api` finding) and the sample's web bundle check are not template behaviour and stay with the sample repos.

## Stories

As a developer, I want the image build to fail when the lockfile is out of date, so that what runs in dev is exactly what I locked and reviewed.

As an operator, I want every HTTP endpoint of a generated Python service to show up in `/metrics` with count, latency and status, so that dashboards and alerts work for endpoints added later without extra code.

As a developer whose repo uses a private library, I want the image build to read that library with the packages token, and to be told when the token secret is missing, so that the image builds the same dependencies as CI without a token in the image.

As a platform maintainer, I want the platform's own tests to generate a repo and check both properties, so that a template change cannot silently undo them.

## Acceptance criteria

- **AC-104.1** Given a newly generated `service-python` repo whose lockfile does not satisfy its declared dependencies, when its container image is built, then the build fails with the install error and produces no image. A build with a matching lockfile succeeds.
- **AC-104.2** Given a newly generated `web-nextjs` or `service-typescript` repo whose lockfile does not satisfy its declared dependencies, when its container image is built, then the build fails with the install error and produces no image. The install stays the one strict install (`pnpm install --frozen-lockfile`, no fallback); it may carry the secret mount of AC-104.11.
- **AC-104.3** Given a repo of either shape updated with `/shared:update-service`, when the update is applied, then it gets the same strict install as AC-104.1 and AC-104.2 (the container build file is template-owned, not project-owned).
- **AC-104.4** Given a newly generated `service-python` repo with observability on, when any endpoint is called (including one the team added after generation and an unknown path answered with 404), then `/metrics` shows for it a request count and a request duration, labelled by method, route and status code. (smoke)
- **AC-104.5** Given the same service, when a request is made to a path with a variable part (for example `/items/123` and `/items/456`), then both requests count under the one route pattern (`/items/{id}`), and unknown paths count under one shared label, so the number of label values does not grow with the paths callers send.
- **AC-104.6** Given the same service, when a handler raises an unhandled error, then the response is 500, the request is counted with status code 500, and `application_errors_total` increases by one for that error type.
- **AC-104.7** Given the same service, when `/metrics` itself is scraped, then the scrape does not add to the request metrics.
- **AC-104.8** Given a newly generated `service-python` repo, when it is checked, then no metric is declared that nothing records, and the `/ping` example no longer records its own count (the common recording of AC-104.4 does).
- **AC-104.9** Given a `service-python` repo generated with observability off, when it is built and run, then it starts and answers `/health` with no metrics code or dependency present.
- **AC-104.10** Given the platform's own test suite, when it runs, then it generates a `service-python` repo and a `web-nextjs` repo, builds nothing it cannot build in CI, and fails if the strict install of AC-104.1 and AC-104.2 is missing or the recording of AC-104.4 to AC-104.6 does not happen. It adds no more than 2 minutes to the existing CI run.
- **AC-104.11** Given a newly generated `web-nextjs` or `service-typescript` repo that depends on a private package of its owner on GitHub Packages, when its image is built with `PACKAGES_READ_TOKEN` passed as a build secret (CI passes it when the repository secret is set), then the install reads the package, and the token appears in no image layer, build argument or image history. Without the secret, a repo with only public dependencies builds unchanged, and a repo with a private dependency fails at the install with the registry's authentication error.
- **AC-104.12** Given a repo whose `.npmrc` points its owner's scope at `npm.pkg.github.com` (or whose Python dependencies read release-asset wheels of a private repo), when `/platform:doctor` runs and the repository has no `PACKAGES_READ_TOKEN` secret, then it reports the missing secret with the command that sets it; a repo without private dependencies gets no such line.

## Non-goals

- Database statement, lock and pool deadlines: application behaviour of the sample (`ika100/todo-api`), not template behaviour. They belong to a spec in that repo.
- The sample's frontend bundle and secret check (`ika100/todo-web`). Whether the `web-nextjs` template should ship one is a separate spec, once the sample's check has proven itself.
- `service-java` and `service-go` build and metrics behaviour; issue 143 covers only the Python sample.
- New observability stacks, tracing changes, new dashboards or alert rules.
- Rewriting existing generated repos' own application code; only template-owned files change.
- Private packages from registries other than GitHub Packages, and creating or rotating the token itself.

## Open questions

- ~~Do `service-java` and `service-go` have the same lockfile fallback or unrecorded metrics, and should this spec cover them?~~ Answered: no, they are checked in a follow-up spec (non-goal).
- ~~Should `web-nextjs` ship a CI check that fails when a secret or a server-only value appears in the production bundle?~~ Answered: not now; a separate spec once the sample's check has proven itself (non-goal).
- ~~Confirm: the metric label for unmatched paths is one shared value, and the route pattern replaces the concrete path.~~ Answered: yes, see AC-104.5.
- ~~Confirm: the added CI time of the generated-repo checks is capped at 2 minutes.~~ Answered: yes, see AC-104.10.

- ~~Should `/component:new` also warn at creation time, or is `/platform:doctor` enough?~~ Answered: doctor only, since a new repo has no private dependency yet (AC-104.12).
- ~~Does AC-104.11 need a real private-package build in the platform's CI?~~ Answered: no; the rendered-Dockerfile check plus a build without the secret is enough (no test package to publish).

## Changelog

- 2026-10-25 created
- 2026-10-25 amended: folded in the user's answers (Java/Go and the bundle check stay out of scope).
- 2026-10-25 approved
- 2026-10-28 building
- 2026-10-28 done
- 2026-11-27 draft: amend: private package token in image builds and missing-secret message (#965)
- 2026-11-27 amended: private packages in image builds and the missing-secret message (issue 965); needs a new approval and a new plan.
- 2026-11-27 amended: the user answered both open questions as suggested.
- 2026-11-27 approved; the old plan is plan.v1.md
- 2026-11-27 building
