---
spec_id: 149-a-spec-decides-by-default
title: A spec decides by default
status: approved
priority: P1
shape: platform
---

# 149 — A spec decides by default

## Problem

The product-manager returns every decision as an open question ([ADR-026](../../adr/026-feature-specs.md)). In journeys 3 to 5 the user answered 56 questions, every one with the suggested answer; journey 5 asked 20 in seven rounds, ten of them for one small API spec. In the run store of the 14 days before 2026-11-07, `decision` is the most frequent escalation cause (31 of 75). Questions whose answer is always the default cost a person's attention, an agent turn per round and, in an unattended run, a stop.

## Stories

As someone who asks for a feature, I want the product-manager to take the sensible defaults itself and show them to me once, at approval, so that I decide on the feature in one step and am asked only what really needs me.

## Acceptance criteria

- **AC-149.1** Given a feature request, when the product-manager writes the spec, then every decision with a sensible default is written into the criteria and listed under `## Assumptions` as `- **A<n>** <decision> (other option: …; affects AC-…)`, and only questions about security or access, money, deleting, migrating or exposing data, or a request too ambiguous to build go under `## Open questions` (product-manager rule 3, the spec format reference, [ADR-084](../../adr/084-a-spec-decides-by-default.md)).
- **AC-149.2** Given `cplat spec new`, when it writes the skeleton, then the skeleton has an `## Assumptions` section before `## Open questions`; a spec with assumptions and no open question passes `cplat spec check` and `cplat spec approve`.
- **AC-149.3** Given a spec with assumptions, when `cplat spec list --json` or the console's spec detail reads it, then it reports the number of active assumptions, the detail lists them, and a struck-through assumption counts as revised, not active.
- **AC-149.4** Given `/component:spec` or `/system:spec`, when the spec has no open question, then the finish block lists the assumptions one per line and one question offers "Approve with these <n> assumptions (Recommended)", "Change an assumption" and "I'll review the file first"; the questions loop asks only open questions.
- **AC-149.5** Given a build PR, when its "How this was built" block is written, then it says how many assumptions were approved with the spec and how many were revised later.
- **AC-149.6** Given journey 6, when its spec steps run, then each asks at most its open questions plus the one approval question, and the number of questions and of revised assumptions is recorded in `docs/PERFORMANCE.md` next to journey 5's 20.

## Non-goals

- No change to `/system:ship`'s unattended answers (D.3 of the component spec command): they stay recorded under `## Decisions taken during the ship`.
- No setting to switch back to asking every question; the approval question offers the review of the file instead.
- Budget stops (`budget exhausted`) stay escalations; raising a budget is a decision about money.

## Open questions

- ~~Should the user still confirm each default one by one?~~ Answered (recommended, self-approved for the 5.13 round on 2026-11-07 as the user asked): no; one approval of the listed assumptions, with the option to change one.
- ~~Is wording that users see a question?~~ Answered: no, an assumption; the approval shows it.

## Changelog

- 2026-11-07 created from the strategy after journey 5 (item B4, "decide by default"); approved with the recommended answers, as the user asked for this round.
