# ADR-116: A days budget raise lives in local state

**Status:** Accepted (2026-11-17)

## Context

[Spec 193](../specs/193-building-and-releasing-run-on-their-own/spec.md) (AC-193.5) lets the person raise the run queue's
token budget from `/platform:next` when a build stops at the limit. The limit comes from `tokens_per_day` in the committed
`.platform/dispatch.yml`. The user decided on 2026-11-12 that a raise is for one day only: writing it into the policy
file would need a pull request, would outlive the day it was meant for and would change what every clone of the repo
believes the budget is.

## Decision

A raise of the run queue's daily token budget holds for the local day in the dispatcher state and never changes the committed policy file.

The raise is `steering.budget_today = {"day", "tokens", "at"}` in the local dispatcher state. Every reader of the limit
goes through `dispatch_budget.limit_of(policy, slug)`, which returns the raise only while its `day` is the local day and
the policy's value otherwise.

## Consequences

- Nothing committed changes: the policy file, the repo and other clones keep their budget.
- A raise ends at midnight (local time) without anyone removing it; an older raise is ignored by every reader.
- `cplat dispatch budget --reset-today` takes a raise back at once.
- A later change that reads the daily limit must call `limit_of`, never `tokens_per_day` directly, or it ignores the raise.
