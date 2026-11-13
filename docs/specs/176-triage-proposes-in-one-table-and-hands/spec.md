---
spec_id: 176-triage-proposes-in-one-table-and-hands
title: Triage proposes in one table and hands off to the dispatcher
status: approved
priority: P1
shape: platform
---

# 176 — Triage proposes in one table and hands off to the dispatcher

## Problem

`/issue:triage` walks the queue one issue at a time: it shows an issue, asks the user up to three questions, moves on, and after confirmation runs `/component:fix` for every bug in the same session, one after the other. A triage of ten issues becomes a session of hours that the user has to watch, although the dispatcher (spec 167) already runs triaged issues unattended. The command also does work the script could do: it searches for duplicates by hand, ignores the route and confidence that engine-filed issues already carry, and cannot tell from `--waiting` whether a reporter answered. Triage records no priority, so an urgent bug waits behind older requests.

## Stories

- As the platform owner, I want triage to show me one table of proposals with the questions collected, and to accept one answer for all of it, so that triage takes minutes instead of a watched session.
- As the platform owner, I want triage to decide and the dispatcher to do the work, so that fixes run unattended in priority order after I confirm.
- As the platform owner, I want duplicates, engine routes and reporter answers found by the script, so that the proposals rest on facts and I check fewer of them.

**Repos:** sdlc-foundry (the platform).

## Acceptance criteria

The proposal (one table, one answer).

- **AC-176.1** Given a queue of issues, when `cplat issue triage batch --json` runs, then it returns every queued issue in one call with its redacted, fenced body and comments, its author's role on the repository (`owner`, `member`, `collaborator`, `contributor` or `none`), the duplicate candidates of AC-176.5, the engine route of AC-176.6, the reply state of AC-176.7 and its status facts (the specs whose `tracks:` name it with their status, a claim with its branch, merged pull requests that reference it, and the open issue it duplicates), using at most one GitHub request per issue for comments and one for the list.
- **AC-176.2** Given a run of `/issue:triage` without an issue number, when the queue is not empty, then before anything is asked or done the user sees one overview, rendered by `cplat` from the batch of AC-176.1 and the triager's proposals, in three groups in this order, each with its count: `Needs your decision` (a row with a question, or marked `check`), `Clear` (a row marked `sure` without a question) and `Already handled` (a row whose status facts say it is in a spec, claimed, fixed by a merged pull request or a duplicate). A row shows the issue number and a one-line summary in the triager's own words of at most 80 characters; a `Clear` row adds class, priority and the planned action in at most three words; `Already handled` rows are folded into one line per status (`in spec <NNN> (<spec status>)`, `being worked on (<branch>)`, `fixed by #<PR>`, `duplicate of #<n>`), in the plain words of spec 192 (no `claim`, `held` or `dispatcher` on screen). The author role is shown only when it is `contributor` or `none`. The status comes only from the status facts of AC-176.1. Issues that the queue skipped are named in one line with their reason. The overview fits 80 columns, is readable without colour, and ends with one line that says how many questions follow.
- **AC-176.3** Given that overview, when the run goes on, then every question is asked as a choice with the recommended answer first (at most four per screen; more follow as a next page that says `<n> of <m>`), and after the last question one confirmation choice shows the plan as one line per action with the choices `OK, do it`, `Change one` and `Cancel`. `Change one` lets the user pick a row and its class or action and shows the confirmation again. A typed answer is accepted in place of a choice (for example "ok", "all ok except 560 feature"). The command applies exactly the confirmed rows, asks again only about rows the answer leaves unclear, and posts, labels or closes nothing for a row the user did not confirm. On request the user sees the exact labels and comment text of a row before confirming.
- **AC-176.4** Given a run that proposes new specs, when the user confirms, then all new specs of the run are written on one `docs/` branch and published as one draft PR, and the summary lists their numbers with the approve command.
- **AC-176.15** Given a finished run, when the summary is printed, then it lists what was done per group and ends with the next step of the delivery process for each kind of result and who takes it (`fix runs on its own`, `approve spec <NNN> (you)`, `reporter answers`, `nothing`), names how to undo each change, and offers the person's own next step as a choice instead of a command to type (the hand-over of spec 192).

Facts from the script.

- **AC-176.5** Given an open issue whose `Signature:` line equals that of another open or recently closed issue, or whose title shares its significant words with another open issue's title above a fixed threshold, when the batch or `show` runs, then that issue lists the other one as a duplicate candidate with the reason (`same signature` or `similar title`). An issue never lists itself, and a candidate is a hint for the proposal, never a decision.
- **AC-176.6** Given an engine-filed issue (label `signal`) whose body has a `## Triage` section, when the batch runs, then its row carries the engine's route, confidence and suspected files, and the command proposes that route as the class, marked `check` when the confidence is below 0.7.
- **AC-176.7** Given an issue labelled `needs-info`, when `list --waiting` or the batch runs, then it shows whether the last comment after the triage question came from the reporter (`answered <age>`) or not (`silent <age>`). An answered issue is proposed for triage again, considering only the comments since the triage question.

The hand-off.

- **AC-176.8** Given a confirmed `bug` or `small-change` in any repo shape, the platform repo included, when the command acts, then it adds `triaged` and the confirmed priority label, posts a comment that begins `Triage:` and holds the task in the triager's words (summary, the user's answers, the expected result), and starts no fix in the session. This holds whatever the author's role: the user's confirmation is the gate for an issue from outside the repository too. The summary points to `cplat dispatch status` and the console Board.
- **AC-176.9** Given a triaged issue with a `Triage:` comment, when the dispatcher starts its fix run, then the run's task is the newest `Triage:` comment written by a user with write access, and the reporter's text reaches the run only fenced as untrusted data. A `Triage:` comment by someone without write access is ignored.
- ~~**AC-176.10**~~ superseded by AC-196.8 on 2026-11-13: Given the label set, when `setup-labels` runs, then `p1`, `p2` and `p3` exist, and a dispatcher policy with the documented default priority rules orders a `p1` issue before an older `p2` issue.

Moved to spec 177 (unclear issues from other people, closing what needs no work).

- ~~**AC-176.11**~~ withdrawn 2026-11-10: moved to spec 177 (split).
- ~~**AC-176.12**~~ withdrawn 2026-11-10: moved to spec 177 (split).
- ~~**AC-176.13**~~ withdrawn 2026-11-10: moved to spec 177 (split).
- ~~**AC-176.14**~~ withdrawn 2026-11-10: moved to spec 177 (split).

## Non-goals

- An unattended triage that labels or closes without the user's confirmation: triage stays a proposal until the user answers.
- Changes to how the dispatcher runs a fix once it has started, or to its slots and budget.
- The console's own triage actions (buttons to confirm rows): the Inbox keeps pointing to `/issue:triage`; a follow-up may add them.
- Model-based duplicate detection: the script compares signatures and titles only.
- Questions to outside reporters and closing issues: spec 177.

## Assumptions

- **A1** One answer message confirms the whole plan; rows can still be changed one by one (other option: per-issue confirmation only; affects AC-176.3).
- **A2** All new specs of one run go into one docs PR (other option: one PR per spec; affects AC-176.4).
- **A3** The engine confidence threshold for `sure` is 0.7 (other option: always `check` for engine issues; affects AC-176.6).
- ~~**A4** Priority labels are `p1`/`p2`/`p3`, matching the dispatcher's documented `label:p1` rule (other option: `urgent` only; affects AC-176.10).~~ Revised 2026-11-13: `p0`/`p1`/`p2`, the spec priorities; spec 196, AC-196.8.
- ~~**A5** The hard rule "never close an issue" becomes "never close an issue without the user's confirmation" (other option: keep issues open; affects AC-176.13, AC-176.14).~~ Moved to spec 177.
- ~~**A6** A silent `needs-info` issue is proposed for closing after 14 days, configurable per repository (other option: 30 days; affects AC-176.14).~~ Moved to spec 177.

## Open questions

- ~~Should a triaged issue from an author outside the repository (`contributor` or `none`) reach the dispatcher like any other, or wait for a second confirmation before an unattended fix starts? (suggested: like any other, because the task is the triager's `Triage:` comment and the reporter's text stays fenced; affects AC-176.8, AC-176.9)~~ Answered 2026-11-10: like any other; see AC-176.8.

## Changelog

- 2026-11-10 created
- 2026-11-10 split: AC-176.11 to AC-176.14 moved to spec 177; open question answered (outside authors like any other)
- 2026-11-10 approved
- 2026-11-12 amended: the table adds a one-line summary, a status from the batch's status facts and the next step in the delivery process (AC-176.1, AC-176.2)
- 2026-11-12 amended: the table becomes a grouped overview (needs your decision, clear, already handled) with questions as choices, one confirmation and a closing next step (AC-176.2, AC-176.3, new AC-176.15); replaces the columns added earlier today
- 2026-11-12 approved again by the user with today's amendments (grouped overview, choices, closing next step)
- 2026-11-13 AC-176.10 superseded by AC-196.8 (priority labels `p0`/`p1`/`p2`); A4 revised
