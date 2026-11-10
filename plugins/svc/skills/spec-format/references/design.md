# design.md (optional)

The **how**, when the plan alone would not carry it. Write one when the feature adds or changes a public API, an event, a data model or a dependency, or when there is a real choice to make. Skip it for features of three tasks without new interfaces.

```markdown
# Design — 007 Price alerts

## Decisions

- Alerts are evaluated in the tick consumer, not a separate service: one more consumer would double the per-tick latency. ADR: [docs/adr/012-alert-evaluation.md](../../adr/012-alert-evaluation.md).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `alerts/rules.py` | rule model, CRUD | new |
| `alerts/dispatcher.py` | email + webhook delivery with retry | new |
| `pipeline.py` | calls the evaluator per tick | changed |

## Contract

`POST /alerts` → `201 {"id": str, "symbol": str, "threshold": float, "direction": "above"|"below"}`; `422` problem+json on invalid input; `409` when the user has 50 rules (AC-007.6).

Webhook: `POST <url>` body `{"rule_id": str, "symbol": str, "price": float, "at": RFC3339}`; any non-2xx is retried 3× (1 s, 5 s, 25 s) (AC-007.4).

## Data

Table `alert_rule` (id, owner, symbol, threshold, direction, webhook_url, last_state); migration in the plan's t1.
```

## Rules

- **The contract is binding.** Testers write acceptance tests against it before code exists, and other repos may build against it in parallel. Name every field, status code and error format a caller sees. For a larger API, put an OpenAPI file next to it (`contract.openapi.yaml`) and link it.
- Reference criteria ids where a design element exists because of one.
- Decisions that outlive the feature (a new technology, a cross-cutting pattern) also get an ADR in `docs/adr/` (MADR: Status, Context, Decision, Consequences). Feature-local choices stay here.
- Be opinionated: one approach with its reason, not a list of options.
