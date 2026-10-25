# spec.md

The **what** of one feature, in the user's language. No code, no file names, no library choices.

```markdown
---
spec_id: 007-price-alerts          # equals the folder name: <NNN>-<slug>
title: Price alerts
status: draft                      # changed only by `cplat spec approve|set-status`
priority: P1                       # P0 | P1 | P2
shape: service-python              # the repo's shape (omitted in a repo without one)
tracks: [42]                       # optional: GitHub issues this spec answers
parent: acme/shop-gitops:012-checkout   # optional: the product spec this repo's spec is a slice of
---

# 007 — Price alerts

## Problem

Who has the problem, what it costs them today, why now. Two to five sentences.

## Stories

As a trader, I want an alert when a watched symbol crosses my threshold, so that I can react without watching the chart.

## Acceptance criteria

- **AC-007.1** Given a rule "AAPL above 200", when a tick at 200.01 arrives, then one email is sent to the rule's owner within 60 seconds.
- **AC-007.2** Given a rule with a webhook URL, when it fires, then the URL receives a POST with `symbol`, `price` and `rule_id`.
- **AC-007.3** Given a rule that fired, when further ticks stay above the threshold, then no further alert is sent until the price has crossed back.
- **AC-007.4** Given a webhook that answers 5xx, when the alert fires, then delivery is retried 3 times with backoff and the failure is visible in the rule's history.
- ~~**AC-007.5**~~ withdrawn 2026-10-09: SMS moved to spec 009.

## Non-goals

- SMS and push notifications.
- Alerts on derived values (moving averages).

## Open questions

- Should a user be limited in the number of rules? (suggested: 50 per user; affects a new criterion)
- ~~Email provider?~~ Answered: the existing SMTP relay, see AC-007.1.

## Changelog

- 2026-10-08 created
- 2026-10-08 approved
```

## Writing good criteria

- **One observable behaviour each**, in Given / when / then. A tester must be able to write a test from the line alone.
- **Concrete:** numbers, limits, field names the user sees, error responses. "Fast" and "user-friendly" are not criteria.
- **Cover the unhappy paths:** invalid input, missing permission, a dependency down, limits reached. Most defects live there.
- **Behaviour, not implementation:** "the price is stored" is untestable from outside; say what the user or caller can observe.
- **Environment-neutral:** no host ports, local hostnames or machine paths (`:8088`, `todo-web.todo-dev.localhost`, `/Users/...`). Say what is observable wherever the product runs: "the todo list page loads at the web app's root URL".
- **Smoke marker:** end a criterion line with `(smoke)` when its behaviour is observable through the service's public URL; after deploy, `devbox run smoke` checks it in dev against `SMOKE_BASE_URL`. Only for deployable shapes (not libraries), and only for behaviour a test can check using nothing but the base URL.
- **Small features have few criteria.** Three to eight is typical. More than twelve usually means two specs.

## Open questions

- A question is anything the user must decide that changes behaviour: a limit, a permission, a priority between two goals, a wording users see.
- Write each as a question with a **suggested answer** and what it affects, so the user can answer in one word.
- Never answer your own questions by assumption. If a default is obvious and harmless, write it as a criterion and list it under Open questions as "Confirm: …" so the user sees it.
- Answered questions are struck through, with the answer folded into a criterion or a non-goal. `cplat spec approve` refuses while any unstruck question remains.

## Amending

- Add new criteria with the next free number. Change the text of an existing one only to clarify the same behaviour; if behaviour changes, withdraw the old id and add a new one.
- Add a Changelog line for every amendment. The orchestrator moves an approved spec back to `draft`; it needs a new approval and, if criteria changed, a new plan (`spec_hash` drift).
