---
spec_id: 176-triage-proposes-in-one-table-and-hands
title: Triage proposes in one table and hands off to the dispatcher
status: draft
priority: P1
shape: platform
---

# 176 — Triage proposes in one table and hands off to the dispatcher

## Problem

`/issue:triage` walks the queue one issue at a time: it shows an issue, asks the user up to three questions, moves on, and after confirmation runs `/component:fix` for every bug in the same session, one after the other. A triage of ten issues becomes a session of hours that the user has to watch, although the dispatcher (spec 167) already runs triaged issues unattended. The command also does work the script could do: it searches for duplicates by hand, ignores the route and confidence that engine-filed issues already carry, and cannot tell from `--waiting` whether a reporter answered. Questions about an unclear issue from another person go to the user, who usually cannot answer them, and the drafted reporter comment uses internal terms. Answered questions, duplicates and refusals are never closed, so the open list fills with noise. Triage records no priority, so an urgent bug waits behind older requests.

## Stories

- As the platform owner, I want triage to show me one table of proposals with the questions collected, and to accept one answer for all of it, so that triage takes minutes instead of a watched session.
- As the platform owner, I want triage to decide and the dispatcher to do the work, so that fixes run unattended in priority order after I confirm.
- As the platform owner, I want duplicates, engine routes and reporter answers found by the script, so that the proposals rest on facts and I check fewer of them.
- As someone who files an issue without a clear description, I want a plain, specific request for what is missing and a clear statement of what happens if I do not answer, so that I know how to get my issue looked at.
- As the platform owner, I want issues that need no further work closed after I confirm, so that the open list shows only real work.

**Repos:** sdlc-foundry (the platform).

## Acceptance criteria

The proposal (one table, one answer).

- **AC-176.1** Given a queue of issues, when `cplat issue triage batch --json` runs, then it returns every queued issue in one call with its redacted, fenced body and comments, its author's role on the repository (`owner`, `member`, `collaborator`, `contributor` or `none`), the duplicate candidates of AC-176.5, the engine route of AC-176.6 and the reply state of AC-176.7, using at most one GitHub request per issue for comments and one for the list.
- **AC-176.2** Given a run of `/issue:triage` without an issue number, when the queue is not empty, then before anything is asked or done the user sees one table with one row per queued issue (number, title, author role, proposed class, proposed priority, planned action, and a mark `sure` or `check`) followed by every question of the run, numbered and naming its issue. Issues that the queue skipped are named in one line with their reason.
- **AC-176.3** Given that table, when the user answers in one message (for example "ok", "all ok except 560 feature", "560 split, Q2 new spec"), then the command applies exactly the confirmed rows, asks again only about rows the answer leaves unclear, and posts, labels or closes nothing for a row the user did not confirm.
- **AC-176.4** Given a run that proposes new specs, when the user confirms, then all new specs of the run are written on one `docs/` branch and published as one draft PR, and the summary lists their numbers with the approve command.

Facts from the script.

- **AC-176.5** Given an open issue whose `Signature:` line equals that of another open or recently closed issue, or whose title shares its significant words with another open issue's title above a fixed threshold, when the batch or `show` runs, then that issue lists the other one as a duplicate candidate with the reason (`same signature` or `similar title`). An issue never lists itself, and a candidate is a hint for the proposal, never a decision.
- **AC-176.6** Given an engine-filed issue (label `signal`) whose body has a `## Triage` section, when the batch runs, then its row carries the engine's route, confidence and suspected files, and the command proposes that route as the class, marked `check` when the confidence is below 0.7.
- **AC-176.7** Given an issue labelled `needs-info`, when `list --waiting` or the batch runs, then it shows whether the last comment after the triage question came from the reporter (`answered <age>`) or not (`silent <age>`). An answered issue is proposed for triage again, considering only the comments since the triage question.

The hand-off.

- **AC-176.8** Given a confirmed `bug` or `small-change` in any repo shape, the platform repo included, when the command acts, then it adds `triaged` and the confirmed priority label, posts a comment that begins `Triage:` and holds the task in the triager's words (summary, the user's answers, the expected result), and starts no fix in the session. The summary points to `cplat dispatch status` and the console Board.
- **AC-176.9** Given a triaged issue with a `Triage:` comment, when the dispatcher starts its fix run, then the run's task is the newest `Triage:` comment written by a user with write access, and the reporter's text reaches the run only fenced as untrusted data. A `Triage:` comment by someone without write access is ignored.
- **AC-176.10** Given the label set, when `setup-labels` runs, then `p1`, `p2` and `p3` exist, and a dispatcher policy with the documented default priority rules orders a `p1` issue before an older `p2` issue.

Unclear issues from other people.

- **AC-176.11** Given an issue filed through a form that leaves required fields empty, or filed without a form, when the issue is proposed as `needs-info`, then the row names the missing fields of the matching form (bug report or feature request), the questions to the user are limited to what the user may know (such as who the reporter is or whether the problem is known), and every other question goes into the drafted reporter comment.
- **AC-176.12** Given a drafted comment to a reporter whose role is not `owner`, `member` or `collaborator`, when it is shown to the user, then it thanks the reporter, asks for each missing item in plain words, names no spec numbers, labels or internal commands other than public ones (`/platform:doctor`, `/issue:report`), and states the number of days after which a silent issue is closed and that a comment reopens the review.

Closing what needs no work.

- **AC-176.13** Given a confirmed `duplicate`, `question` (answered) or `wontfix`, when the command acts, then it posts the confirmed comment and closes the issue as `not planned` (a duplicate: with the link to the original). An unconfirmed row is never closed.
- **AC-176.14** Given a `needs-info` issue silent for at least the configured number of days (default 14), when triage runs, then it proposes closing it with a final comment that invites the reporter to comment to reopen, and closes it only after the user confirms. A reporter comment on a closed `needs-info` issue puts it back in the queue on the next `list`.

## Non-goals

- An unattended triage that labels or closes without the user's confirmation: triage stays a proposal until the user answers.
- Changes to how the dispatcher runs a fix once it has started, or to its slots and budget.
- The console's own triage actions (buttons to confirm rows): the Inbox keeps pointing to `/issue:triage`; a follow-up may add them.
- Model-based duplicate detection: the script compares signatures and titles only.

## Assumptions

- **A1** One answer message confirms the whole table; rows can still be confirmed one by one (other option: per-issue confirmation only; affects AC-176.3).
- **A2** All new specs of one run go into one docs PR (other option: one PR per spec; affects AC-176.4).
- **A3** The engine confidence threshold for `sure` is 0.7 (other option: always `check` for engine issues; affects AC-176.6).
- **A4** Priority labels are `p1`/`p2`/`p3`, matching the dispatcher's documented `label:p1` rule (other option: `urgent` only; affects AC-176.10).
- **A5** The hard rule "never close an issue" becomes "never close an issue without the user's confirmation" (other option: keep issues open; affects AC-176.13, AC-176.14).
- **A6** A silent `needs-info` issue is proposed for closing after 14 days, configurable per repository (other option: 30 days; affects AC-176.14).

## Open questions

- Should a triaged issue from an author outside the repository (`contributor` or `none`) reach the dispatcher like any other, or wait for a second confirmation before an unattended fix starts? (suggested: like any other, because the task is the triager's `Triage:` comment and the reporter's text stays fenced; affects AC-176.8, AC-176.9)

## Changelog

- 2026-11-10 created
