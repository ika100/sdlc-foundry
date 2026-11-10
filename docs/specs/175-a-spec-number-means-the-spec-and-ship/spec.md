---
spec_id: 175-a-spec-number-means-the-spec-and-ship
title: A spec number means the spec and ship PRs close their issues
status: done
priority: P1
shape: platform
tracks: [638, 645]
---

# 175 — A spec number means the spec and ship PRs close their issues

## Problem

Two small gaps cost the platform owner silent mistakes. First, the dispatcher guide says that a steering item can be a spec number (`<NNN>`), but `cplat dispatch skip 154` (and `prioritize`, `resume <item>`) reads a bare number as issue #154. The command reports success, the spec the owner meant keeps running, and an unrelated issue gets held (#638). Second, `cplat component ship pr --body-file` sends the build PR template's `{{CLOSES}}` placeholder to GitHub unchanged. PRs #634 and #635 merged without closing references, so their tracked issues stayed open and the linked-issue comments (spec 158) never went out (#645). `cplat pr open` already fills the placeholder; the ship path does not.

## Stories

- As the platform owner steering the dispatcher, I want a spec number to name the spec, an explicit issue form to name the issue, and an ambiguous number to be refused, and I want each command to tell me what it acted on, so that I never hold the wrong item without noticing.
- As the platform owner, I want every PR that a ship run opens to close the issues its spec tracks, so that merging the PR closes them and their reporters hear about it.

**Repos:** sdlc-foundry (the platform).

## Acceptance criteria

The dispatcher's steering items (`cplat dispatch skip <item> --reason <text>`, `prioritize <item>`, `resume <item>`).

- **AC-175.1** Given a repo with spec `154-<slug>` and no open issue #154, when `cplat dispatch skip 154 --reason r` runs, then the spec is held as `skipped: r`, no issue is held, and the command prints `skipped: spec 154-<slug> (reason: r)`. `prioritize 154` prints `prioritized: spec 154-<slug>` and `resume 154` prints `resumed: spec 154-<slug>`, each acting on the spec. A zero-padded number (`054`) always names spec 054 and never an issue, and a bare number matches a spec by its value (`54` matches spec 054).
- **AC-175.2** Given a repo with spec `154-<slug>` and an open issue #154, when an item is written `#154` or `issue-154`, then it always names the issue and the command prints `<verb>: issue #154`. When it is written `spec-154` or `154-<slug>`, then it always names the spec. Given a bare number that matches no spec but an open issue (`638` with an open #638 and no spec 638), then it names the issue and prints `<verb>: issue #638`. The dispatcher guide's item line states this rule and these forms.
- **AC-175.3** Given a bare number that matches both a spec and an open issue, when any of the three steering commands runs, then it exits 2 with `ERROR: 154 is both spec 154-<slug> and open issue #154: write spec-154 or #154`, and the dispatcher's state (pins, skips, holds) is the same as before. The same exit and unchanged state hold for a bare number that matches neither a spec nor an open issue, for a `spec-<N>` or zero-padded number with no such spec, and for a bare number that matches a spec while the open issues cannot be read (no GitHub snapshot and GitHub unreachable); each message names the item and the explicit forms to write.

The ship PR body.

- **AC-175.4** Given a ship run of a spec with `tracks: [30, 12]`, a feature branch whose commits contain `Closes #44`, open issues #30 and #44, a closed issue #12, and a body file containing `{{CLOSES}}`, when `cplat component ship pr --title T --body-file F` opens the PR, then the PR body has `Closes #30` and `Closes #44` on their own lines in place of the placeholder, ascending, without #12. These are the same lines `cplat pr open --spec <spec id>` writes for that branch. When none of the issues is open, the placeholder becomes `N/A`. Without a ship run's spec, the lines come from the branch's commits only.
- **AC-175.5** Given `cplat component ship pr` whose body would still contain `{{CLOSES}}` after filling, including when the ship run's spec cannot be read, when it runs, then it exits 2 with `ERROR: PR body still contains {{CLOSES}}` and the reason, before `devbox run ci` and before anything is pushed, and it opens or edits no PR.

## Non-goals

- Changing how other commands read items, such as `cplat component ship <spec>` or `/component:fix #N`.
- Correcting the bodies of PRs #634 and #635 or closing the issues they missed. That is a one-off manual step.
- Other commands that open PRs (`cplat component ship gitops pr`, `cplat system ship entry pr`). A follow-up covers them if they show the same gap.
- Rewriting the body of a PR that is already open when `ship pr` reuses it (AC-126.12 keeps retitling only).

## Assumptions

- **A1** A bare number resolves to whatever exists: a spec, or an open issue. When it is both, or neither, it is refused. A zero-padded number is always a spec (other option: a bare number is always a spec, as the guide's `<NNN>` reads, and an issue needs `#`; affects AC-175.1, AC-175.2, AC-175.3).
- **A2** `issue-<N>` is accepted next to `#<N>` as the issue form, because `#` needs quoting in some shells (other option: only `#<N>`; affects AC-175.2).
- **A3** Open issues are taken from the dispatcher's GitHub snapshot (at most 5 minutes old, spec 167), or from a fresh read when there is no snapshot. If neither is available, a bare number that matches a spec is refused rather than guessed (other option: treat it as the spec; affects AC-175.3).
- **A4** Each steering command prints one line `<skipped|prioritized|resumed>: <spec <spec id>|issue #N>`, plus `(reason: <text>)` for skip (other option: also print the issue title; affects AC-175.1, AC-175.2).
- **A5** A refused item exits 2, the exit code `cplat` uses for "fix the input and call again" (other option: exit 1; affects AC-175.3, AC-175.5).
- **A6** `ship pr` fills the placeholder exactly as `cplat pr open` does: only open issues, ascending, PR references skipped, `N/A` when none (other option: write every tracked issue without checking its state; affects AC-175.4).
- **A7** The placeholder check runs after filling and before `devbox run ci`, next to the title and spec-rule checks of AC-126.9, so a bad body costs no CI run (other option: check only before the push; affects AC-175.5).

## Open questions

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
- 2026-11-10 building
- 2026-11-10 done
