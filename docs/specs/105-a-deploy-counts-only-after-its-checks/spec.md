---
spec_id: 105-a-deploy-counts-only-after-its-checks
title: A deploy counts only after its checks pass
status: draft
priority: P1
tracks: [155]
---

# 105 — A deploy counts only after its checks pass

## Problem

Issue 155 asks for an enforced post-deploy gate: a deploy must not count as successful, or be promoted, until the running application has passed checks tied to the exact build. Spec 091 already delivers most of it: `cplat ship` deploy runs the smoke tests against dev after Argo reports healthy, retries once, times out after 10 minutes, records the outcome, escalates and files an issue on red, and resumes with smoke only. Spec 093 adds promotion to staging only after a green dev smoke. What remains is narrower. The evidence names the image tag but not the image digest, so a tag that was re-pushed between the check and the promotion is not noticed. The one retry is applied to every failure alike, so a dead gateway and a broken feature are retried the same way and the issue does not say which it was. A run that skipped smoke ("not run") or lost its record can still finish. And nowhere is it written down which parts of the gate are enforced by code and which rest on agent instructions.

## Stories

As the person who promotes a build, I want the smoke evidence to name the image digest that was checked, so that a promotion cannot carry an image that was never checked.

As a founder reading a red result, I want to see whether the failure came from the environment (unreachable, DNS, gateway) or from the application, so that I route it to the right place.

As a maintainer of the platform, I want one place that says which gate steps the code enforces, so that I do not assume the agents enforce what they only recommend.

## Acceptance criteria

- **AC-105.1** Given a deploy that reaches smoke, when the run record's `smoke` section is written, then it also holds the image digest (`sha256:<64 hex>`) of the image the service runs in dev at that moment, read from the cluster. If the digest cannot be read, the outcome is recorded as `not-run` with the reason `image digest unknown`; it does not pass.
- **AC-105.2** Given a staging promotion under spec 093, when the image to pin is chosen, then the digest of that tag in the registry must equal the digest recorded for the green dev smoke. On a mismatch nothing is pinned, and the report says `digest changed since smoke: <recorded> -> <current>`.
- **AC-105.3** Given the evidence summary of `/gitops:promote … staging prod` (spec 093), when it lists a smoke outcome, then it shows the digest that was checked and flags it when the digest `staging` runs differs.
- **AC-105.4** Given a failing smoke test in deploy, when the failure is that the base URL cannot be reached (connection refused, DNS failure, gateway 502, 503 or 504 on every test), then the failure is classed `environment`; any other failing test is classed `application`. The class is in the deploy output, the run record and the filed issue.
- **AC-105.5** Given a failure classed `environment`, when the first attempt fails, then smoke retries up to 3 times in total, 30 seconds apart, inside the 10-minute limit of AC-091.8. Given `application`, then the single retry of AC-091.7 applies, unchanged. If an `environment` failure persists, the run escalates with cause `infra` (not `code`), `smoke red in dev: environment (<url>)`, and no issue is filed in the service repo.
- **AC-105.6** Given a ship run for a deployable service whose pin has been confirmed, when deploy ends as done with a smoke outcome of `not-run`, then the report says `NOT VERIFIED` and the spec's `(smoke)` criteria listed as unchecked, and no staging promotion is started (this restates AC-091.11 and AC-093.3 as one tested rule).
- **AC-105.7** Given a ship run that is resumed or replayed after deploy had finished, when it is asked to finish again or to promote, then smoke runs again unless the record already holds a passed outcome for the same image digest; a passed outcome for a different digest does not count.
- **AC-105.8** Given the documentation of the ship flow, when it is read, then it has one table of the gate's steps (pin confirmed, Argo healthy, smoke, retry, escalation, digest match, promotion) that says for each whether it is enforced by code (and by which check) or only instructed to an agent. A test fails if a step of the table has no automated test that names it.

## Non-goals

- Anything 091 or 093 already do: running smoke in dev, one retry, 10-minute limit, red escalation, deduplicated issues, `smoke not run` notes, resuming with smoke only, staging promotion and the staging smoke.
- Routing an application failure to a coder agent automatically, or repairing it; the issue goes through `/shared:triage` (091 non-goal).
- Rollback of dev or staging on a red result.
- Acceptance suites, preview environments or a new test framework; only the existing smoke tests run.
- Blocking `prod` promotion on missing evidence (093 decided: warn only).

## Open questions

- Is the digest check worth its cost now, or is the tag (`sha-<40>`, built once by CI) enough evidence? (suggested: yes, add it; if no, withdraw AC-105.1 to AC-105.3; affects those)
- Should an `environment` failure ever file an issue? (suggested: no, escalate only; a persistent one is an operator problem; affects AC-105.5)
- Confirm: 3 attempts, 30 seconds apart, for environment failures. (suggested: yes; affects AC-105.5)
- Confirm: the classification by symptom (unreachable URL or gateway errors on every test) is good enough; a smarter classifier is out of scope. (suggested: yes; affects AC-105.4)
- Should AC-105.6 make `not-run` for a service that has dev exposure a failure instead of a "NOT VERIFIED" note? (suggested: no, keep the 091 behaviour; affects AC-105.6)

## Changelog

- 2026-10-25 created
