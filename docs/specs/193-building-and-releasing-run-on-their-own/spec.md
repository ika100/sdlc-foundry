---
spec_id: 193-building-and-releasing-run-on-their-own
title: Building and releasing run on their own and interrupt only to ask
status: approved
priority: P1
shape: platform
---

# 193 — Building and releasing run on their own and interrupt only to ask

## Problem

Spec 192 leads the person through issue and spec to the point where work is approved, and spec 176 does the same for triage. After approval the
person still has to know the dispatcher: write `.platform/dispatch.yml` from a guide, pick slots, start the loop in a terminal, read
`cplat dispatch status` and `inbox`, decode held reasons and escalation comments, and then find the right release and promote commands. A
stop in the middle shows up as a label, a log path or an exit code, and nobody says what still runs or what is blocked. The person spends
attention watching instead of deciding. This spec makes Build, Release and the deploy steps of `/platform:next` run on their own and speak only
when the person must decide, with every number taken from records.

Related specs: 192 (the entry point `/platform:next`, its screen layout, choices, "Show details", `Undo:` lines, the next step as a choice in
AC-192.8 and the person-minute records of AC-192.10) and 176 (the triage screen). The screen rules of spec 192 (80 columns, `--ascii`, lists
cut at 5, the words never shown, estimates only from at least 3 comparable recorded runs) apply to every screen here and are not repeated.

## Stories

As a person who approved specs and issues, I want to start building them with one choice and see what I will get, how long and how many
tokens it should take, so that I do not have to learn the dispatcher.

As a person whose build stopped, I want to be told what happened, why I am asked and what keeps running, so that I can answer in one step and
the work continues where it stopped.

As a person whose build finished, I want to see what is ready in changelog words and release and promote it with one choice each, so that
delivery ends with nothing waiting for me.

## Acceptance criteria

- **AC-193.1** Given a repo with `.platform/dispatch.yml` and at least one ready issue or spec, when `/platform:next` reaches the Build step, then the screen shows the queue numbered in the order `cplat dispatch plan` gives, each entry with its issue or spec number and one "what you get" line, an estimate per entry and a total only when at least 3 comparable recorded runs exist (an entry without one shows none and the total is left out), the line `Tokens today: <used> of <budget>` plus `this queue needs about <n>` only when the need is known from records, and the choice "Two at a time (recommended) / One at a time / Not now"; "Two" and "One" start the build with 2 and 1 items at once, and "Not now" starts nothing and the queue is shown as a waiting item by the next `/platform:next`.
- **AC-193.2** Given a repo without `.platform/dispatch.yml`, when `/platform:next` reaches the Build step, then instead of a link to a guide it offers "Set up and build (recommended) / Not now", whose "Show details" prints the exact file it will commit (`budget.tokens_per_day` from the 7-day hint of `cplat dispatch plan`, `sources: [issues, specs]`, `gates.approve_specs: human`); "Set up and build" commits the file through a PR that merges only on green CI and then shows the queue of AC-193.1, and "Not now" writes nothing.
- **AC-193.3** Given a build with two items running, when the build screen is shown, then it lists one line per event with the local time (`HH:MM started #<n> <what you get>`, `HH:MM merged #<n> (PR #<m>)`, `HH:MM finished #<n>`) and one line per running item under `Building now`, prints no agent output, and ends with the choice "Keep watching (recommended) / Leave it running / Stop after the running items".
- **AC-193.4** Given an item whose run stopped for a decision, when the build screen is shown, then it prints the lines `What happened:`, `Why I ask:` and `While you think:` (naming each other running item as `keeps running` and what waits for this one), the age when the stop is older than 5 minutes (`asked 2 h 05 min ago`), and a choice with the recommended answer first and "Stop this item (its work stays on branch <branch>)"; an answer is written into the spec as an amendment that quotes the person's answer and the item continues from the phase where it stopped, while "Stop this item" leaves the branch and lists the item as parked. When the amendment only adds the asked point, the person's answer is recorded in the spec's Changelog as its approval and the item continues; an answer that changes any other criterion sends the item back to the Spec step for a normal approval.
- **AC-193.5** Given an item that stopped without a decision to make (it ended twice without finishing, a check stayed red after the automatic rerun, or the day's token budget was reached), when the build screen is shown, then it prints `What happened:`, `Already tried:` (for example `restarted once`, `check rerun once`), the age as in AC-193.4, and the choice "Try again (recommended) / Park it / Show the log", where "Show the log" prints the log path; it never shows only an error line or an exit code. When the stop is the reached daily token budget, the choices are instead "Wait for tomorrow (recommended) / Raise today's budget / Park it": "Raise today's budget" asks for the new number, shows today's use and the queue's known need, and raises the limit for today only after a second confirmation; it prints an `Undo:` line and changes no committed file.
- **AC-193.6** Given a build whose queue is empty and nothing runs, when the end of build is shown, then it prints `Wall time`, `Tokens` and `Questions to you` taken from the run records, the token ledger and the AC-192.10 records (a value that cannot be read is left out), and `Ready to release:` with the sections `Fixed`, `Added` and `Changed`, each line the bold summary of a changelog fragment with its issue numbers, followed by the release step as the next choice (AC-192.8).
- **AC-193.7** Given changes ready to release, when the Release step is shown, then the choice is "Release now (recommended) / Collect more"; "Release now" runs `/platform:release` in the platform repo and `/component:release` in a component repo, whose own confirmation before the tag is still asked, and "Collect more" leaves `Release: <n> changes ready` as a waiting item of the next `/platform:next`; in a deployable repo the steps after the release are "Promote to Staging (recommended) / Not now" and then "Promote to Prod (recommended) / Not now" through `/instance:promote`, which keeps its own production gate.
- **AC-193.8** Given a flow whose last step is done, when `/platform:next` shows the last screen, then it lists the issues closed and the version released, `Your time: <n> min` summed from the AC-192.10 records of the items in this flow, the line `Nothing is waiting for you`, the parked items (or none), and the line `New issues show up here in /platform:next`.

## Non-goals

- The console web UI; follow-up: the same screens as Inbox decisions.
- New scheduling features of the dispatcher (its order, readiness rules and one ship at a time per repo stay as they are).
- Changes to gates, CI, merge rules, release checks or the promote checks.
- The triage screen (spec 176) and the entry point, bar and screen rules themselves (spec 192).
- New notification channels or kinds: a stop while the person is away goes through the existing `notify.yaml` channels and kinds (`escalation`, `stuck`, `budget`) as today.
- Streaming agent output or a live progress bar inside an item.

## Assumptions

- **A1** The choice of AC-193.1 sets the number of items at once with `cplat dispatch slots`, not a commit to the policy file, and the build loop is started detached (or the running one adopted), so closing the session never stops the build (other option: commit `slots` to the policy file; affects AC-193.1, AC-193.3).
- **A2** Specs still build one at a time per repo: with "Two at a time" a second spec shows `starts after #<n>: one spec builds at a time` in the queue instead of a held reason (other option: recommend "One at a time" when only specs are queued; affects AC-193.1).
- **A3** "Comparable" for estimates means the same kind (fix or ship) in the same repo; the queue's token need is the median tokens of those runs times the entries, shown only when every entry has at least 3 (other option: show a partial sum; affects AC-193.1).
- **A4** When the 7-day hint has no usage to base a budget on, the set-up asks the person for the daily budget and recommends no number, since a guessed number is not from records (other option: a fixed starter budget of 20000000; affects AC-193.2).
- **A5** The set-up file goes through a PR that lands on green CI like every other change, and the build starts once it has merged (other option: a direct commit to `main`; affects AC-193.2).
- **A6** The session supplies only the judgement text (`What happened` and `Why I ask` summaries, the "what you get" lines) as input to `cplat`; when it gives none, `cplat` prints the run's stop reason and the spec or issue title, so every screen is printed by `cplat` and identical for the same state (other option: the session writes whole screens; affects AC-193.1, AC-193.3, AC-193.4).
- **A7** "Try again" lifts the item's hold (`cplat dispatch resume <item>`), "Park it" skips it with the reason shown (`cplat dispatch skip`), "Stop after the running items" is `cplat dispatch pause --drain`; each prints its `Undo:` line as in spec 192 (other option: no undo for park; affects AC-193.3, AC-193.4, AC-193.5).
- **A8** The age line appears from 5 minutes after the stop, rounded to minutes, from the time the run record or need carries (other option: always shown; affects AC-193.4, AC-193.5).
- **A9** In a component repo, which has no changelog fragments, `Ready to release` is built from the merged PR titles since the last tag (`fix` to Fixed, `feat` to Added, others to Changed); a merged change without a fragment or a typed title is listed under `Changed` by its PR title (other option: leave it out; affects AC-193.6).
- **A10** In a deployable repo whose staging moves automatically after a green dev smoke (`promote: after-dev-smoke`), the Staging step is shown as done and only Prod is offered (other option: offer Staging anyway; affects AC-193.7).
- **A11** Wall time runs from the first `started` to the last `finished` event of this build; `Questions to you` counts the AC-192.10 questions of the items in this build (other option: count interruptions only; affects AC-193.6).
- **A12** New prompt rules for the session's judgement text get register entries (`docs/rules/README.md`); tests check `cplat` output for a given state, never prompt wording (other option: none; affects all criteria).
- Decided by the user (2026-11-12): an answer on the interruption screen counts as the approval of the amended spec when it only adds the asked point (AC-193.4).
- Decided by the user (2026-11-12): "Try again" on a reached budget may raise today's budget once, after the person confirms the new number; it does not change the committed policy file (AC-193.5).

## Open questions

None.

## Changelog

- 2026-11-12 created
- 2026-11-12 open questions answered by the user: an answer re-approves when it only adds the asked point; a reached budget may be raised for today after confirmation
- 2026-11-12 approved
