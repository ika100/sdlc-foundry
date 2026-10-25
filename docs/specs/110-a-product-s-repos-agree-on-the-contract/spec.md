---
spec_id: 110-a-product-s-repos-agree-on-the-contract
title: A product's repos agree on the contract between them
status: draft
priority: P2
tracks: [143]
---

# 110 — A product's repos agree on the contract between them

## Problem

In a product, the web front end and the API often both validate the same input on purpose: the front end for fast feedback, the API as the authority. In the todo sample (issue 143) nothing proves that the two agree. If one side changes a limit (the maximum title length, the allowed values of a field) or the error response (status code, error body shape), each repo's own tests stay green, and the mismatch only shows up as an unexpected 422 or a generic error in a running environment. A product plan already states the contract between repos in its `## Contract` section (ADR-011, spec 053), and each repo's spec gets it through `/svc:spec --from-plan`, but it is prose: no repo checks its behaviour against it, and nothing notices when a repo drifts from it later. Spec 104 covers only the template-owned fixes from issue 143; this spec covers the agreement between repos.

## Stories

As a product developer, I want the shared input rules and the error response of a product to be written once, in the plan's contract, so that the front end and the API implement the same thing.

As a developer of one repo, I want my repo's CI to fail when my code no longer matches the contract, so that I find the drift in my pull request and not as a 422 in dev.

As a product owner, I want a repo that runs with an outdated copy of the contract to be caught before it is pinned, so that the repos of one product never run against different limits.

## Acceptance criteria

- **AC-110.1** Given a product plan with two or more repos, when `devbox run plan-check` runs, then the `## Contract` section must contain a `### Rules` part next to `### Errors` and `### Timeouts`: one entry per shared input rule with a rule id, the endpoint and field, the kind of rule (required, minimum and maximum length, minimum and maximum value, allowed values), its concrete value, the repo that provides it and the repos that consume it. A plan with no shared rules says so in one line with a reason. A missing `### Rules`, a rule without a concrete value, an unknown kind or a repo that is not in the plan is refused, naming the rule.
- **AC-110.2** Given the same plan, when `plan-check` runs, then `### Errors` must state, in the same machine-readable form, the status code a rule violation returns and the fields of the error body (at least which field failed, which rule, and a message), and plan-check refuses a rule whose violation has no stated status code.
- **AC-110.3** Given a finished plan (`completed` or `abandoned`) written before this spec, when `plan-check` runs, then a missing `### Rules` is a warning, not an error (as spec 061 treats specs 045 and 053).
- **AC-110.4** Given `/svc:spec --from-plan <plan> <repo-id>` for a repo that provides or consumes a rule, when the repo's spec is written, then the repo gets a machine-readable copy of the rules and the error contract that concern it, marked with the plan id and the gitops-app commit it was taken from, and the repo's spec lists them in its Product context.
- **AC-110.5** Given a `service-python` repo that provides a rule, when its CI runs, then a contract check derived from the copy (not from hand-written values) sends, for each rule, a value at the limit (accepted), a value just past it (rejected), every allowed value (accepted) and one value outside the allowed set (rejected), and asserts that every rejection has the status code and error body fields of AC-110.2. A difference fails the check, naming the rule id, the field, the expected and the actual result.
- **AC-110.6** Given a `web-nextjs` repo that consumes a rule, when its CI runs, then a contract check derived from the copy runs the front end's own validation with the same boundary values as AC-110.5 and fails, naming the rule id, the field, the expected and the actual result, when the front end accepts what the contract rejects or rejects what it accepts.
- **AC-110.7** Given the same `web-nextjs` repo, when its contract check feeds it an API response with the status code and error body of AC-110.2, then the front end shows the message at the field named in the body (not a generic error); given a status code the contract does not list, then it follows what `### Errors` says for unlisted responses. A different outcome fails the check.
- **AC-110.8** Given a repo whose contract check fails, when that repo's pull request runs CI, then the pull request is red in that repo; the other repos of the product are not needed to run the check (no running API, no network call to another repo).
- **AC-110.9** Given a pin PR in the gitops-app repo for a service (spec 062), when the pinned commit's copy of the rules or the error contract differs from the plan's current contract, then gitops-app CI fails, naming the service, the rule id and both values. A repo with no copy whose plan assigns it a rule fails the same way; a repo that takes part in no rule is not checked.
- **AC-110.10** Given a plan whose contract changes after the repos built (for example the maximum title length goes from 200 to 120), when `/svc:spec --from-plan` is run again in a repo, then its copy is updated to the new values and its contract check fails until the code follows them.
- **AC-110.11** Given the planner agent text and the plan format docs, when they describe the contract, then they show the `### Rules` part, the machine-readable error contract and one worked example (a title with a maximum length and a status field with allowed values).

## Non-goals

- A contract-testing framework such as Pact, a broker or a schema registry service.
- Removing the duplicate validation: both sides keep validating; this spec only proves they agree.
- Changes to the sample product (`ika100/todo`, `todo-api`, `todo-web`); adopting this there belongs to specs in those repos.
- Rules between two back-end services, events and queues, and response shapes beyond the error contract.
- `service-java`, `service-go` and `library-python` contract checks (see the open questions).
- Generating front-end or API code from the contract.

## Open questions

- Where is the single source of the rules? (suggested: the plan's `### Rules`, as above, because every product already has a plan contract and it works for any shape; alternatives: the API's published OpenAPI document as the source, which FastAPI already serves and which carries lengths and allowed values, with the front end checked against it, or both, with the provider's OpenAPI document checked against the plan; affects AC-110.1, AC-110.4 to AC-110.6)
- How is a repo's copy kept honest? (suggested: the gitops-app pin PR check of AC-110.9; alternative: each repo's CI reads the plan from the gitops-app repo on every run, which needs a read token and fails when that repo is unreachable; affects AC-110.8, AC-110.9)
- Is `### Rules` mandatory for every plan with two or more repos, or only when a `web-nextjs` repo and a service share an endpoint? (suggested: mandatory, with the one-line "no shared rules" escape; affects AC-110.1)
- Confirm: the rule kinds are required, minimum and maximum length, minimum and maximum value, and allowed values; anything else (patterns, formats) is prose and not checked. (affects AC-110.1, AC-110.5, AC-110.6)
- Should `service-java` and `service-go` providers get the contract check of AC-110.5 in this spec? (suggested: no, a follow-up spec once the Python and Next.js checks have proven themselves; affects a new criterion)
- Should the provider's OpenAPI document also be checked against the rules, so that API clients see the same limits? (suggested: no, not in this spec; affects a new criterion)

## Changelog

- 2026-10-25 created
