---
spec_id: 157-prs-and-issues-get-short-summaries-for
title: PRs and issues get short summaries for reviewers and reporters
status: draft
priority: P1
shape: platform
tracks: [568]
---

# 157 — PRs and issues get short summaries for reviewers and reporters

## Problem

A reviewer of a build or ship PR gets the orchestrator's text and, at the end, spec 133's collapsed "How this was built" block: a
complete run record, but no short answer to "what changed, why, how did the review go, what is left". PRs opened by `/system:ship`
get no generated section at all. The reporter of an issue hears from the platform once, at triage (spec 035); after that the issue is
closed by a merge's `Closes #N` or by `/component:release` with at most a generic "Closed by release" line: no spec link, no summary
of the solution, no version and no way to get the fix (#568). Both summaries can be built from records the platform already keeps
(the spec, the PR, `verification.md`, the changelog fragment and the run records), so they cost no agent time and read the same in
every repo.

## Stories

As a reviewer of a build or ship PR, I want five lines at the top of the PR body saying what changed and why, how the review went
and what risks or follow-ups remain, so that I know what I am reviewing before I open the diff or the "How this was built" block.
**Repos:** the platform (`cplat pr open`, the component ship, the system ship).

As the reporter of an issue, I want a comment on my issue when a spec for it is written, when it is approved, when the PR that
closes it merges and when a release ships it, so that I can follow my request to the version that contains it without asking.
**Repos:** the platform (`cplat spec publish`, `cplat spec land`, the merges `cplat` performs, `cplat platform release`, the
component release).

As a platform maintainer, I want all of this text rendered by `cplat` from records, so that it cannot be embellished by an agent
and is the same in every repo.

## Acceptance criteria

- **AC-157.1** Given a PR body that `cplat pr open` sends (component build, ship or fix, with or without a current run), when the
  PR is opened or updated, then the body starts with the line `<!-- cplat:summary -->`, then the line `**Summary**`, then exactly
  four bullet lines that begin `- **Changed:**`, `- **Why:**`, `- **Review:**` and `- **Risks and follow-ups:**`, then the line
  `<!-- /cplat:summary -->`, followed by the body as it was; spec 133's "How this was built" block stays at the end of the body with
  unchanged content, and a body that already has a summary block gets it replaced, never a second one.
- **AC-157.2** Given the branch's changelog fragment, its spec (`--spec`) and the PR's closing references, when the summary is
  rendered, then `Changed` is the fragment's first sentence without Markdown emphasis (else the PR title), followed by
  `(<n> criteria of spec <NNN>, <m> files)` when there is a spec (else `(<m> files)`), `<m>` counted against the base branch; and
  `Why` is the first sentence of the spec's `## Problem`, else `Closes #<N>: <issue title>` for each closing reference (at most 3),
  else `not recorded`.
- **AC-157.3** Given the current run's records and the spec's `verification.md`, when the summary is rendered, then `Review` reads
  `verification <pass|fail|not yet>; <f> reviewer findings (<severity counts>), <x> fixed in fix rounds, <d> accepted as deviations`
  using the findings and fix rounds of spec 133 (AC-133.6) and the accepted deviations of AC-133.7, or
  `verification <…>; findings not recorded` without a run; and `Risks and follow-ups` lists the first sentence of each accepted
  deviation and of each top-level item of a `## Follow-ups` section in `verification.md`, at most 3 then `… and <n> more`, else
  `none recorded`.
- **AC-157.4** Given any value placed in the summary or in an issue comment of this spec, when it is rendered, then it has passed
  the run records' redaction (as AC-133.8), contains no prompts, no diffs and no agent-written text, and each summary line is at most
  300 characters (cut with `…`); when building the summary fails, the body is left unchanged, the PR still opens and the output has
  one extra line `note: summary skipped: <why>`.
- **AC-157.5** Given a `/system:ship` run, when it opens or updates a PR in a component repo or in the gitops repo, then that PR's
  body starts with the AC-157.1 block rendered for that repo's spec and branch (a gitops PR without its own spec uses the system
  spec); the "How this was built" block is not added there (spec 133 non-goal stays).
- **AC-157.6** Given a spec whose `tracks:` lists issue #N, when `cplat spec publish` opens or updates the spec's draft PR, then #N
  gets one comment that links the spec on the spec branch and the spec PR, gives the planned solution as the spec's first story
  (at most 400 characters) plus `It has <n> acceptance criteria.`, and lists the spec's unstruck open questions (at most 5, then
  `… and <n> more`) under `Open questions you can answer here:`, or says `No open questions.`
- **AC-157.7** Given that spec, when `cplat spec land` merges the approved spec, then #N gets one comment
  `Spec <NNN> approved on <date>` with the link to the spec on the default branch, the planned solution as in AC-157.6 and the line
  `Next: the build; you will hear here when its PR merges.`
- **AC-157.8** Given a PR whose body has a closing reference `Closes #N` (as `cplat pr open` writes it), when `cplat` merges it
  (`cplat pr wait --merge`, the component ship or the system ship), then #N gets one comment with the PR link, the PR's `Changed` and
  `Why` lines from AC-157.2 and the line `This ships with the next release.`; a PR merged by hand or by GitHub's UI gets no comment.
- **AC-157.9** Given a release `vX.Y.Z` (by `cplat platform release` or `/component:release`), when it is published, then every issue
  linked to it (a closing reference of a PR merged since the previous tag, or a changelog fragment named by that issue's number)
  gets one comment that starts `Fixed in vX.Y.Z`, quotes the first sentence of the release's changelog entry that names #N (else
  `no changelog entry names #N`) and says how to get it: `/plugin marketplace update` then `/platform:update` for the platform, the
  tag's release page for a component; an open linked issue is then closed as completed, a closed one stays closed.
- **AC-157.10** Given a milestone comment of AC-157.6 to AC-157.9, when it is posted, then it carries a hidden last line
  `<!-- cplat:milestone <spec-written|spec-approved|pr-merged|released> <spec id|PR number|version> -->`, and an issue that already
  has a comment with that line gets none again; issues only mentioned (not tracked, not a closing reference, not named by a
  fragment), pull requests, and issues of another repository get no comment.
- **AC-157.11** Given `gh` failing, offline or refusing a comment (a locked or deleted issue), when a milestone comment is due, then
  the command that triggered it ends with the same exit code and result as without comments and prints one line
  `note: issue comment skipped: #<N> <milestone>: <why>` per skipped issue; running the same command again posts the missing
  comments and no duplicates.
- **AC-157.12** Given the docs, when a user reads `/component:build`, `/component:ship`, `/component:release`, `/system:ship`, the
  closing notes of the commands and the changelog, then the commands say that `cplat` adds the summary and posts the milestone
  comments, `/component:release` runs the issue step through `cplat` instead of hand-written `gh issue close` calls, the closing
  note names milestone comments next to `platform` escalations as what the platform posts itself (ADR-033, #428), an ADR records
  the decision, and the changelog has an entry for #568.

## Non-goals

- Text written by an agent or a language model: every line comes from a record or a fixed template (decision 3).
- Comments on issues that are not linked as in AC-157.10, and comments on the platform's own auto-filed, notify or retro issues
  (their closing by the platform stays as it is).
- Any change to the content of spec 133's "How this was built" block, or to the orchestrator's own text in the PR body.
- Editing or deleting earlier milestone comments; each milestone is a new comment (decision 2).
- Changing triage (spec 035): its `Tracked as …` comment and its confirmation before posting stay as they are.
- A summary for PRs that `cplat` does not open (release, upgrade, fleet and cluster-repo PRs).

## Assumptions

- **A1** The summary is four labelled bullets under a `**Summary**` line, between hidden markers, at the very top of the body
  (other option: a `## Summary` heading after the orchestrator's text; affects AC-157.1).
- **A2** `Changed` comes from the changelog fragment's first sentence, `Why` from the spec's Problem (other option: from the PR
  title and the first story; affects AC-157.2).
- **A3** Risks and follow-ups are the accepted deviations plus an optional `## Follow-ups` section in `verification.md`; no new
  record is introduced (other option: a new run record for follow-ups; affects AC-157.3).
- **A4** The "written" milestone is `cplat spec publish` and the "approved" milestone is `cplat spec land`, because both talk to
  GitHub and have links to post (other option: `cplat spec new` and `cplat spec approve`, which may run offline; affects AC-157.6,
  AC-157.7).
- **A5** Only merges `cplat` performs post the "PR merged" comment; hand merges get none (other option: a CI workflow on merge in
  every template; affects AC-157.8).
- **A6** The issues linked to a release are the closing references of PRs merged since the previous tag and fragments named by an
  issue number; this narrows `/component:release`'s issue step, which today closes every `#NNN` found in commits, PR bodies and the
  changelog (other option: keep the wide collection; affects AC-157.9).
- **A7** Milestone comments are deduplicated by a hidden marker line per milestone and key, so a re-run never posts twice and a
  failed post is retried by the next run (other option: a local record of posted comments; affects AC-157.10, AC-157.11).
- **A8** There is no switch to turn the comments off; tests use a faked `gh` (other option: a repo setting to disable them;
  affects AC-157.6 to AC-157.9).
- **A9** Limits: 300 characters per summary line, 400 for the planned solution, 3 risk items, 5 open questions (other option:
  different limits; affects AC-157.3, AC-157.4, AC-157.6).

## Open questions

- ~~May the platform post comments on the reporter's issue without asking each time?~~ Answered by the user 2026-11-08: yes, once
  the issue is linked (spec `tracks:`, a PR's `Closes #N`), comments are posted automatically with no per-comment OK. This is a
  platform milestone comment, not a filed issue; the commands' closing note is reconciled with #428 / ADR-033, see AC-157.12.
- ~~One comment edited in place, or one new comment per milestone?~~ Answered by the user 2026-11-08: one new comment per
  milestone, see AC-157.10 and Non-goals.
- ~~May an agent write or polish the PR summary?~~ Answered by the user 2026-11-08: no, `cplat` renders it purely from records,
  see AC-157.4 and Non-goals.

## Changelog

- 2026-11-08 created
