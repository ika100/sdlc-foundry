# verification.md

The reviewer's evidence that the build meets the spec. Written after QA, before the PR; the PR links it.

```markdown
# Verification — 007 Price alerts

**Result:** pass            <!-- pass | fail -->
**Commit:** 1a2b3c4 · **Base:** 9f8e7d6 · **Trace:** 4/4 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-007.1 | met | `tests/test_alerts.py::test_alert_email_on_cross` | `src/app/alerts/dispatcher.py:41` | |
| AC-007.2 | met | `tests/test_alerts.py::test_webhook_payload` | `src/app/alerts/dispatcher.py:63` | |
| AC-007.3 | not met | `tests/test_alerts.py::test_no_repeat` | `src/app/pipeline.py:88` | the test checks one extra tick only; a second crossing re-arms wrongly |
| AC-007.4 | met | `tests/test_alerts.py::test_retry_backoff` | `src/app/alerts/dispatcher.py:72` | |

## Non-goals

No SMS or push code was added. ✔

## Deviations from the plan

- `src/app/config.py` changed but is in no task's `files` (new `ALERT_RETRY` setting); acceptable, documented in `docs/env-vars.md`.

## Contract

Matches `design.md`. ✔

## Suppressions in acceptance tests

| File | Line | Rule | False positive |
|---|---|---|---|
| `tests/test_alerts.py` | 41 | `noqa: S105` | yes: a test password, not a secret |
```

Include the suppressions section when the build suppressed a lint finding in an acceptance test, so that the reviewer judges each one (spec 160).

## Rules

- **Verdicts:** `met` (a test proves the behaviour and the code implements it as specified), `not met` (missing, wrong, or the test does not actually prove the criterion), `partial` (say which part). Any `not met` or `partial` makes the result `fail`.
- **Evidence is concrete:** test id and code `file:line`. "Looks fine" is not evidence.
- **Judge the test, not just its existence:** a test named after the criterion that does not assert the stated outcome counts as `not met`.
- Non-goals: flag code that implements something the spec excluded.
- Deviations: files changed outside every task's `files`, tasks not done, contract differences. Deviations are not automatically failures; say whether each is acceptable.
