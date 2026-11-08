---
spec_id: 157-prs-and-issues-get-short-summaries-for
title: Build and ship PRs start with a short summary
status: approved
priority: P1
shape: platform
tracks: [568]
---

# 157 — Build and ship PRs start with a short summary

## Problem

A reviewer of a build or ship PR gets the orchestrator's text and, at the end, spec 133's collapsed "How this was built" block: a
complete run record, but no short answer to "what changed, why, how did the review go, what is left". PRs opened by `/system:ship`
get no generated section at all (#568). The answer can be built from records the platform already keeps (the spec, the changelog
fragment where the repo has one, `verification.md` and the run records), so it costs no agent time and reads the same in every repo.
Telling the issue's reporter about the spec, the merge and the release is spec 158, which builds on this one.

## Stories

As a reviewer of a build or ship PR, I want five lines at the top of the PR body saying what changed and why, how the review went
and what risks or follow-ups remain, so that I know what I am reviewing before I open the diff or the "How this was built" block.
**Repos:** the platform (`cplat pr open`, the component ship, the system ship).

As a platform maintainer, I want that text rendered by `cplat` from records, so that it cannot be embellished by an agent and is the
same in every repo, including component repos that have no changelog fragments.

## Acceptance criteria

- **AC-157.1** Given a PR body that `cplat pr open` sends (component build, ship or fix, with or without a current run), when the
  PR is opened or updated, then the body starts with the line `<!-- cplat:summary -->`, then the line `**Summary**`, then exactly
  four bullet lines that begin `- **Changed:**`, `- **Why:**`, `- **Review:**` and `- **Risks and follow-ups:**`, then the line
  `<!-- /cplat:summary -->`, followed by the body as it was; spec 133's "How this was built" block stays at the end of the body with
  unchanged content, and a body that already has a summary block gets it replaced, never a second one.
- **AC-157.2** Given the PR's spec (`--spec`), the branch's changelog fragment (a file under `docs/changelog.d/`, where the repo has
  that folder) and the PR's closing references, when `Changed` is rendered, then it is the spec's `title`, else the fragment's first
  sentence without Markdown emphasis, else the PR title; followed by `(<n> criteria of spec <NNN>, <m> files)` when there is a spec
  (else `(<m> files)`), `<m>` counted against the base branch. A component repo without `docs/changelog.d/` gets the spec title,
  never a fallback to the PR title while a spec is given.
- **AC-157.3** Given the same inputs, when `Why` is rendered, then it is the `so that …` clause of the spec's first story (from
  `so that` to the end of that sentence), else `Closes #<N>: <issue title>` for each closing reference (at most 3, then
  `… and <n> more`), else `not recorded`; the spec's `## Problem` is not quoted.
- **AC-157.4** Given the current run's records and the spec's `verification.md`, when `Review` and `Risks and follow-ups` are
  rendered, then `Review` reads `verification <pass|fail|not yet>; <f> reviewer findings (<severity counts>), <x> fixed in fix
  rounds, <d> accepted as deviations` using the findings and fix rounds of spec 133 (AC-133.6) and the accepted deviations of
  AC-133.7, or `verification <…>; findings not recorded` without a run; and `Risks and follow-ups` lists the first sentence of each
  accepted deviation and of each top-level item of a `## Follow-ups` section in `verification.md`, at most 3 then `… and <n> more`,
  else `none recorded`.
- **AC-157.5** Given any value placed in the summary, when it is rendered, then it has passed the run records' redaction (as
  AC-133.8), contains no prompts, no diffs and no agent-written text, and each line is at most 300 characters (cut with `…`); when
  building the summary fails for any reason, the body is left unchanged, the PR still opens with the same exit code, and the output
  has one extra line `note: summary skipped: <why>`.
- **AC-157.6** Given a `/system:ship` run, when it opens or updates a PR in a component repo or in the gitops repo, then that PR's
  body starts with the AC-157.1 block rendered for that repo's spec and branch (a gitops PR without its own spec uses the system
  spec); the "How this was built" block is not added there (spec 133 non-goal stays).
- **AC-157.7** Given the docs, when a user reads `/component:build`, `/component:ship`, `/system:ship` and the changelog, then the
  commands say that `cplat` adds the summary at the top of the PR body and the orchestrator does not write one, and the changelog has
  an entry for #568.

## Non-goals

- Text written by an agent or a language model: every line comes from a record or a fixed template (decision 3).
- Comments on issues; that is spec 158.
- Any change to the content of spec 133's "How this was built" block, or to the orchestrator's own text in the PR body.
- A summary for PRs that `cplat` does not open (release, upgrade, fleet and cluster-repo PRs).
- Adding changelog fragments to component templates.

## Assumptions

- **A1** The summary is four labelled bullets under a `**Summary**` line, between hidden markers, at the very top of the body
  (other option: a `## Summary` heading after the orchestrator's text; affects AC-157.1).
- ~~**A2** `Changed` comes from the changelog fragment's first sentence, `Why` from the spec's Problem.~~ Revised 2026-11-08:
  component repos have no fragments and a Problem section opens with background, so see A2b.
- **A2b** `Changed` comes from the spec title first (then fragment, then PR title) and `Why` from the first story's `so that`
  clause (then the closing references), so the summary is useful in component repos (other option: fragment first; affects
  AC-157.2, AC-157.3).
- **A3** Risks and follow-ups are the accepted deviations plus an optional `## Follow-ups` section in `verification.md`; no new
  record is introduced (other option: a new run record for follow-ups; affects AC-157.4).
- **A9** Limits: 300 characters per line, 3 risk items (other option: different limits; affects AC-157.4, AC-157.5).

## Open questions

- ~~May an agent write or polish the PR summary?~~ Answered by the user 2026-11-08: no, `cplat` renders it purely from records,
  see AC-157.5 and Non-goals.

## Changelog

- 2026-11-08 created
- 2026-11-08 split: the issue comments moved to spec 158; `Changed`/`Why` sources revised for component repos (A2b)
- 2026-11-08 approved
