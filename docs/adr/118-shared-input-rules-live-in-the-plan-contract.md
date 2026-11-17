# ADR-118: Shared input rules live in the plan contract

**Status:** Proposed (2026-11-17)

## Context

Repos of one product (a provider and its consumers) each implemented the same input limits from prose in the plan, and drifted: a title limit of 200 in the API and 255 in the form. Nothing checked that the repos agree, and the error shape was prose too, so a form could not show a server's message for a field.

## Decision

Shared input rules and the error contract are YAML data in the plan's contract; each repo keeps a copy it checks in CI, and the gitops-app pin PR refuses a stale copy

The rules and the error contract sit as fenced YAML blocks under `### Rules` and `### Errors` of the plan's `## Contract` (format: ADR-011, amendment spec 110).

- Source: the plan's contract, parsed by one parser in the gitops-app template's `scripts/plan.py`; plan-check refuses an invalid block.
- Copy: `cplat spec new --from-plan` writes `contract/<plan_id>.json` (with the gitops-app commit) into each repo that takes part in a rule.
- Repo checks: a service-python provider check (in-process `TestClient`) and a web-nextjs consumer check (jsdom) run inside `devbox run test`, so the repo's CI turns red when the code departs from the copy.
- Pin check: the gitops-app CI job `contract-pins` compares the copy at each pinned commit with the plan and refuses a stale copy.
- Six kinds: `required`, `min_length`, `max_length`, `min_value`, `max_value`, `allowed`.

## Consequences

- Easier: a contract change fails the repos that have not followed it, before it reaches a pin.
- Java and Go providers get no check yet; a later spec adds them.
- Patterns and formats stay prose and are not checked.
- Draft plans are checked at pins too, as the spec names no plan status.
- A later change to the block format must keep `plan.py contract` and the copy's JSON in step.
