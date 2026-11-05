---
spec_id: 141-an-approved-plan-asks-no-new-questions
title: An approved system plan asks no new questions
status: approved
priority: P1
shape: platform
---

# 141 — An approved system plan asks no new questions

## Problem

`/system:ship` writes each repo's spec from the approved system plan (`/component:spec --from-plan`, D.3). When the
product-manager raises open questions there, the ship stops: "report the questions verbatim; never answer them yourself".
In the journey of 2026-11-05 this stopped the unattended ship twice before any code was written: task-api's spec asked 3
edge-case questions after 14 minutes (Unicode length, whitespace-only titles, an empty `due_date`), and the web UI's spec
asked one wording question (form labels). Every question had a suggested answer, and the user took each of them. The user
had approved the system spec and its plan; the stop cost a round and up to 15 minutes each.

## Stories

- As someone who approved a system spec and its plan, I want the repo specs to be written without stopping, so that the
  ship builds while I am away.
- As that person, I want to see which decisions were taken for me, so that I can correct one later.

## Acceptance criteria

- **AC-141.1** Given `/system:ship` writes a repo spec from an approved system plan, when the product-manager names open
  questions that each have a suggested answer, then the ship does not stop: the suggested answers are folded into the
  repo spec's criteria and listed in a `## Decisions taken during the ship` section of that spec, and the spec is approved
  (as D.3 approves a spec without questions).
- **AC-141.2** Given an open question without a suggested answer, or one that would change a criterion of the system spec
  or the plan's contract, when the ship writes the repo spec, then the ship stops and reports it as today.
- **AC-141.3** Given a ship that took decisions under AC-141.1, when it ends (done or escalated), then its final report
  lists each decision with its repo and spec, and the run record carries their count.
- **AC-141.4** Given the product-manager writing a repo spec from a plan, when it drafts open questions, then its
  instructions say to prefer the system spec's answers and conventions (lengths, formats, error codes) over a new question,
  so that a question is raised only for a decision the system spec does not cover.
- **AC-141.5** Given a repo PR opened by a ship that took decisions under AC-141.1, when the PR is opened, then one comment
  on it lists those decisions, so a reviewer sees them where the code is.

## Non-goals

- No change to `/component:spec` run by hand: there the questions loop stays.
- No change to the questions of the system spec itself.

## Open questions

1. ~~Should decisions taken for the user also be posted as a comment on the repo's PR? (Recommended: yes, one comment listing
      them, so a reviewer sees them where the code is.)~~ Answered: yes, one PR comment listing them (AC-141.5).

## Changelog

- 2026-11-05 created (found in the journey runs of 2026-11-05)
- 2026-11-05 open question answered by the user (recommended answer)
- 2026-11-05 approved
