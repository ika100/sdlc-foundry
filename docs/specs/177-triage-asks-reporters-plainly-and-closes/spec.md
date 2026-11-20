---
spec_id: 177-triage-asks-reporters-plainly-and-closes
title: Triage asks reporters plainly and closes what needs no work
status: approved
priority: P2
shape: platform
---

# 177 — Triage asks reporters plainly and closes what needs no work

## Problem

When an issue from another person is unclear, `/issue:triage` asks the user up to three questions about it. The user usually cannot answer them, because the user was not there, and the reporter comment that follows is drafted in the platform's internal terms (labels, spec numbers, commands). Nothing tells the reporter what happens if they do not answer, and a silent issue stays open for good. Answered questions, duplicates and refusals are never closed either, because the command's hard rule forbids closing, so the open list fills with issues that need no work. This spec builds on spec 176, which gives triage the author's role on the repository and the reply state of `needs-info` issues.

## Stories

- As someone who files an issue without a clear description, I want a plain, specific request for what is missing and a clear statement of what happens if I do not answer, so that I know how to get my issue looked at.
- As the platform owner, I want to be asked only what I can know about an unclear issue, so that questions I cannot answer go to the reporter directly.
- As the platform owner, I want issues that need no further work closed after I confirm, so that the open list shows only real work.

**Repos:** sdlc-foundry (the platform).

## Acceptance criteria

Unclear issues from other people.

- **AC-177.1** Given an issue filed through a form that leaves required fields empty, or filed without a form, when the issue is proposed as `needs-info`, then the row names the missing fields of the matching form (bug report or feature request), the questions to the user are limited to what the user may know (such as who the reporter is or whether the problem is known), and every other question goes into the drafted reporter comment.
- **AC-177.2** Given a drafted comment to a reporter whose role is not `owner`, `member` or `collaborator`, when it is shown to the user, then it thanks the reporter, asks for each missing item in plain words, names no spec numbers, labels or internal commands other than public ones (`/platform:doctor`, `/issue:report`), and states the number of days after which a silent issue is closed and that a comment reopens the review.

Closing what needs no work.

- **AC-177.3** Given a confirmed `duplicate`, `question` (answered) or `wontfix`, when the command acts, then it posts the confirmed comment and closes the issue as `not planned` (a duplicate: with the link to the original). An unconfirmed row is never closed.
- **AC-177.4** Given a `needs-info` issue silent for at least the configured number of days (default 14), when triage runs, then it proposes closing it with a final comment that invites the reporter to comment to reopen, and closes it only after the user confirms. A reporter comment on a closed `needs-info` issue puts it back in the queue on the next `list`.

## Non-goals

- Closing without the user's confirmation, including silent `needs-info` issues: triage only proposes.
- Hiding a reporter comment that contains a secret: triage may suggest it, the user does it on GitHub.
- The one-table proposal, the script facts and the dispatcher hand-off: spec 176.

## Assumptions

- **A1** The hard rule "never close an issue" becomes "never close an issue without the user's confirmation" (other option: keep issues open; affects AC-177.3, AC-177.4).
- **A2** A silent `needs-info` issue is proposed for closing after 14 days, configurable per repository (other option: 30 days; affects AC-177.4).
- **A3** The plain-language rules apply to reporters outside the repository only; comments to `owner`, `member` or `collaborator` may use internal terms (other option: plain language for everyone; affects AC-177.2).

## Open questions

## Changelog

- 2026-11-10 created (split from spec 176, AC-176.11 to AC-176.14)
- 2026-11-10 approved
