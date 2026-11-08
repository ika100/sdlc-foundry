---
spec_id: 158-linked-issues-hear-when-their-spec-pr
title: Linked issues hear when their spec, PR and release land
status: approved
priority: P1
shape: platform
tracks: [568]
---

# 158 — Linked issues hear when their spec, PR and release land

## Problem

The reporter of an issue hears from the platform once, at triage (spec 035). After that the issue is closed by a merge's
`Closes #N` or by `/component:release` with at most a generic "Closed by release" line: no spec link, no summary of the solution,
no version and no way to get the fix (#568). `/component:release` Phase 7 collects every `#NNN` it finds in commits, PR bodies and
the changelog, which can close issues that were only mentioned (#283), and `cplat platform release` does not touch issues at all.
This spec builds on spec 157: the comments reuse its `Changed` and `Why` lines, so 157 ships first.

## Stories

As the reporter of an issue, I want a comment on my issue when a spec for it is written, when it is approved, when the PR that
closes it merges and when a release ships it, so that I can follow my request to the version that contains it without asking.
**Repos:** the platform (`cplat spec publish`, `cplat spec land`, the merges `cplat` performs, `cplat platform release`, the
component release).

As an operator of an unattended ship or a release, I want a comment that cannot be posted to never slow down, fail or change the
command, so that GitHub trouble with one issue costs at most a note in the output.

## Acceptance criteria

- **AC-158.1** Given a spec whose `tracks:` lists issue #N, when `cplat spec publish` opens or updates the spec's draft PR, then #N
  gets one comment that links the spec on the spec branch and the spec PR, gives the planned solution as the spec's first story
  (at most 400 characters) plus `It has <n> acceptance criteria.`, and lists the spec's unstruck open questions (at most 5, then
  `… and <n> more`) under `Open questions you can answer here:`, or says `No open questions.`
- **AC-158.2** Given that spec, when `cplat spec land` merges the approved spec, then #N gets one comment
  `Spec <NNN> approved on <date>` with the link to the spec on the default branch, the planned solution as in AC-158.1 and the line
  `Next: the build; you will hear here when its PR merges.`
- **AC-158.3** Given a PR whose body has a closing reference `Closes #N` (as `cplat pr open` writes it), when `cplat` merges it or
  finds it already merged (`cplat pr wait --merge`, the component ship's land step including a resumed run, or the system ship),
  then #N gets one comment with the PR link, the PR's `Changed` and `Why` lines from spec 157 and the line
  `Ships with the next release; you will hear here when it does.`, whether GitHub has already closed #N or not; a PR merged only by
  hand or in GitHub's UI gets no comment.
- **AC-158.4** Given a release `vX.Y.Z` (by `cplat platform release` or `/component:release`), when it is published, then the issues
  linked to it are the closing references of the PRs merged since the previous tag plus, where the repo has `docs/changelog.d/`, the
  fragments named by an issue number; each gets one comment that starts `Fixed in vX.Y.Z` and gives what shipped: the changelog
  entry that names #N, else the `Changed` line of its closing PR (spec 157), else that PR's title; and how to get it:
  `/plugin marketplace update` then `/platform:update` for the platform, the tag's release page for a component. An open linked
  issue is then closed as completed, a closed one stays closed; an issue only mentioned in a commit or PR body is neither commented
  on nor closed.
- **AC-158.5** Given `/component:release`, when its issue step runs, then it is one `cplat` call that does AC-158.4 and prints the
  same `## Phase 7 complete — …` summary as today; the command file no longer contains hand-written `gh issue close` calls.
- **AC-158.6** Given a milestone comment of AC-158.1 to AC-158.4, when it is posted, then it carries a hidden last line
  `<!-- cplat:milestone <spec-written|spec-approved|pr-merged|released> <spec id|PR number|version> -->`, and an issue that already
  has a comment with that line gets none again; issues only mentioned (not tracked, not a closing reference, not named by a
  fragment), pull requests, and issues of another repository get no comment.
- **AC-158.7** Given `gh` failing, slow, offline or refusing a comment (a locked or deleted issue), when a milestone comment is due,
  then each issue's read-and-post takes at most 20 seconds and the whole comment step of one command at most 120 seconds (the rest
  is skipped), any error is caught per issue, and the command ends with the same exit code and result as without comments, printing
  one line `note: issue comment skipped: #<N> <milestone>: <why>` per skipped issue; running the same command again posts the
  missing comments and no duplicates.
- **AC-158.8** Given the docs, when a user reads `/component:spec`, `/component:ship`, `/component:release`, `/system:ship`, the
  closing notes of the commands and the changelog, then they say that `cplat` posts the milestone comments without asking, the
  closing note names milestone comments next to `platform` escalations as what the platform posts itself, an ADR next to ADR-033
  records why milestone comments need no per-comment OK (#428), and the changelog has an entry for #568.

## Non-goals

- Text written by an agent or a language model: every line comes from a record or a fixed template.
- Comments on issues that are not linked as in AC-158.6, and comments on the platform's own auto-filed, notify or retro issues
  (their closing by the platform stays as it is).
- Editing or deleting earlier milestone comments; each milestone is a new comment (decision 2).
- Changing triage (spec 035): its `Tracked as …` comment and its confirmation before posting stay as they are.
- A switch to turn the comments off.
- Posting under a bot account; comments are posted with the operator's `gh` login, so GitHub does not notify an operator about
  comments on issues they filed themselves.

## Assumptions

- **A4** The "written" milestone is `cplat spec publish` and the "approved" milestone is `cplat spec land`, because both talk to
  GitHub and have links to post (other option: `cplat spec new` and `cplat spec approve`, which may run offline; affects AC-158.1,
  AC-158.2).
- **A5** Only merges `cplat` performs (including a resumed ship that finds the PR merged) post the "PR merged" comment; hand merges
  get none (other option: a CI workflow on merge in every template; affects AC-158.3).
- **A6** The issues linked to a release are the closing references of PRs merged since the previous tag and fragments named by an
  issue number; this narrows `/component:release`'s issue step, which today closes every `#NNN` found in commits, PR bodies and the
  changelog (other option: keep the wide collection; affects AC-158.4, AC-158.5).
- **A7** Milestone comments are deduplicated by a hidden marker line per milestone and key, so a re-run never posts twice and a
  failed post is retried by the next run (other option: a local record of posted comments; affects AC-158.6, AC-158.7).
- **A8** There is no switch to turn the comments off; tests use a faked `gh` (other option: a repo setting to disable them;
  affects AC-158.1 to AC-158.4).
- **A9** Limits: 400 characters for the planned solution, 5 open questions, 20 seconds per issue and 120 seconds per command for
  the comment step (other option: different limits; affects AC-158.1, AC-158.7).

## Open questions

- ~~May the platform post comments on the reporter's issue without asking each time?~~ Answered by the user 2026-11-08: yes, once
  the issue is linked (spec `tracks:`, a PR's `Closes #N`), comments are posted automatically with no per-comment OK. This is a
  platform milestone comment, not a filed issue; the ADR of AC-158.8 reconciles it with #428 / ADR-033.
- ~~One comment edited in place, or one new comment per milestone?~~ Answered by the user 2026-11-08: one new comment per
  milestone, see AC-158.6 and Non-goals.

## Changelog

- 2026-11-08 created (split from spec 157): time limits and per-issue error isolation added (AC-158.7), release text no longer
  depends on changelog fragments (AC-158.4)
- 2026-11-08 approved
