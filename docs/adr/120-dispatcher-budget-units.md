# ADR-120: Dispatcher budget units

**Status:** Accepted (2026-11-18)

## Context

The dispatcher paced work by raw tokens per day (spec 167). A token count is not what the user pays or is limited by:
a subscription user is limited by plan windows (five hours, seven days) in percent, and an API user pays US dollars.
Cached and uncached tokens, and models, cost very differently, so one token figure fits neither.

## Decision

The dispatcher budgets in plan percentages (status line sensor) or USD (price table), never in raw tokens

- `budget.mode: plan` paces by the subscription's windows, read from the status line sensor and estimated from booked
  tokens between readings.
- `budget.mode: cost` caps spending in USD per day and per month, from the price table.
- Tokens stay only as a booking tape that estimates plan usage between readings, and as the deprecated
  `budget.tokens_per_day`, which keeps working with a warning.

## Consequences

- The user states a limit in the unit they pay; `start` in mode cost refuses a policy without a USD daily limit.
- Plan usage is machine-wide state (one subscription serves every repo), while USD ledgers stay per repo.
- A later change must keep one gate (`dispatch_gate`) for every start decision, so `plan`, `status` and the cycle agree.
- Moving off raw tokens means each token source needs a price or an `AGENT_CEILING` fallback; a call never makes usage unknown.
