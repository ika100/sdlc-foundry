---
spec_id: 196-triage-proposes-a-priority-the-user
title: Triage proposes a priority the user confirms
status: approved
priority: P1
shape: platform
---

# 196 — Triage proposes a priority the user confirms

## Problem

`/issue:triage` classifies an issue and routes it, but it records no priority: an issue gets no priority label and a feature becomes a spec with the default priority of `cplat spec new`. The dispatcher (spec 167) orders its work by labels such as `p1` and by a spec's priority, so today that ordering runs on defaults nobody chose and an urgent bug waits behind older requests. Spec 176 already shows a priority in its overview and adds "the confirmed priority label", but says nowhere how the priority is proposed, changed or carried into a spec. This spec settles that: triage proposes a default priority with a reason, the user approves or changes it in the same confirmation, and only then is it written.

Relation to spec 176 (approved, not built): 176 owns the layout of the overview, the questions and the confirmation; this spec owns the priority shown in it and what is written for it. The criteria below hold for the confirmation step of today's triage and for the one of spec 176, whichever is built first. AC-196.8 replaces AC-176.10 because the labels follow the spec priorities `P0`/`P1`/`P2`.

## Stories

- As the platform owner, I want triage to propose a priority for each issue it routes, with the reason, so that I only correct the few that are wrong instead of choosing each one.
- As the platform owner, I want the priority I confirmed to reach the issue and the spec, so that the dispatcher works on urgent things first without my pinning them.

**Repos:** sdlc-foundry (the platform).

## Acceptance criteria

Priority levels of an incoming issue, decided by the user on 2026-11-13; triage proposes by these definitions:

- `P0`: an outage, data loss, a security problem, or something that blocks all other work.
- `P1`: a normal bug or feature; the fallback when nothing signals urgency.
- `P2`: cosmetic, a convenience, or something with an easy workaround.

- **AC-196.1** Given a triage run that classifies an issue as `bug`, `small-change` or `feature`, when the confirmation is shown, then that issue's row shows exactly one proposed priority (`P0`, `P1` or `P2`) and a reason of at most 60 characters; an issue classified `question`, `duplicate`, `wontfix`, `needs-exploring` or `needs-info` shows no priority.
- **AC-196.2** Given an issue without a priority label, when triage proposes its priority, then it proposes the level whose definition above the issue matches, and the reason names that definition (for example `P0: data loss`, `P2: easy workaround`); given an issue in which nothing signals `P0` or `P2`, then it proposes `P1` with the reason `P1: normal bug or feature`.
- **AC-196.3** Given an issue that already carries the label `p0`, `p1` or `p2`, when triage proposes its priority, then the proposal is that priority with the reason `set on the issue`, whatever the text suggests; given an issue with more than one of these labels, then the most urgent is proposed and the row is marked as needing the user's decision.
- **AC-196.4** Given the confirmation, when the user changes the priority of a row (by the change choice, or typed, for example `560 p0`), then the confirmation is shown again with the new priority and the reason `changed by you`; given a run that ends without the user's confirmation (cancelled, or an unattended or scheduled run), then no priority label is added or removed on any issue and no spec is created.
- **AC-196.5** Given a confirmed priority for an issue that carries a different priority label, when the command acts, then afterwards the issue carries exactly the confirmed one of `p0`, `p1`, `p2`; given an apply call that adds two priority labels at once, then it is refused with an error naming both and the issue is left unchanged; given an issue confirmed with a class that gets no priority, then its existing priority label is left as it is.
- **AC-196.6** Given a confirmed `feature` that becomes a new spec, when the command acts, then the new spec's `priority` equals the confirmed priority and the issue carries the matching label.
- **AC-196.7** Given a confirmed `feature` added to the `tracks:` of an existing spec whose priority differs from the confirmed one, when the command acts, then the issue carries the confirmed label, the spec's priority is unchanged, and the run's summary names both (for example `#560 p1, spec 123 P2`) and how to change the spec's priority.
- **AC-196.8** Given the label set, when `setup-labels` runs, then `p0`, `p1` and `p2` exist and existing labels are left as they are; and given two ready triaged bugs, the older labelled `p2` and the newer labelled `p1` by a triage run, when the dispatcher orders them with the documented default priority rules, then the `p1` bug comes first, and a spec created by triage at `P1` comes before an older-numbered spec at `P2`. (replaces AC-176.10)
- **AC-196.9** Given ready candidates, when a cycle orders them, then it applies the policy's `priority` rules in order and moves to the next rule only to break a tie, and the documented default rules are `label:p0`, `label:bug`, `label:p1`, `spec-order`, `oldest`: under them a ready `p0` item (an issue labelled `p0` or a spec at `P0`) comes before an older `label:bug` item and before `p1` and `p2` items, while a repo whose dispatch policy sets its own `priority` rules is ordered by those unchanged. Given `cplat dispatch prioritize <item>`, then that item comes first until it starts. Given `cplat dispatch skip <item> --reason <text>`, then it is held as `skipped: <text>` until `cplat dispatch resume <item>`. Both survive a restart of the dispatcher. (replaces AC-167.5)

## Non-goals

- A priority per acceptance criterion (no MoSCoW on requirements).
- Further changes to the dispatcher's ordering beyond naming `label:p0` first in the default rules (AC-196.9): no new rule kinds, no change to how rules break ties, no change to a `priority` policy a repo set itself.
- Triage changing the priority of an existing spec, or re-prioritising issues and specs outside a triage run.
- Priority buttons in the console; the Inbox keeps pointing to `/issue:triage`.
- A deadline, severity or effort field beside the priority.

## Assumptions

- **A1** The priority labels are `p0`, `p1`, `p2`, the lower-case spec priorities, so that an issue and a spec share one scale (other option: spec 176's `p1`/`p2`/`p3`; affects AC-196.8, replaces AC-176.10).
- **A2** A priority label already on the issue is kept as the proposal; several are resolved to the most urgent and put to the user (other option: the triager's own proposal wins; affects AC-196.3).
- **A3** Only `bug`, `small-change` and `feature` get a priority; for the other classes an existing priority label is left untouched (other option: remove it on `wontfix` and `duplicate`; affects AC-196.1, AC-196.5).
- **A4** The reason is at most 60 characters and starts with the level and the matched definition (`P0: data loss`); the fixed reasons are `set on the issue` and `changed by you` (other option: free wording; affects AC-196.1, AC-196.2, AC-196.3, AC-196.4).
- **A5** Folding a feature into an existing spec never changes the spec's priority; the summary names the difference. Under the default rules a tracked issue's `p1` label already lifts its spec, because a spec matches the labels of the issues it tracks (other option: raise the spec to the issue's priority; affects AC-196.7).
- **A6** One apply call with two priority labels is refused instead of keeping the last (other option: last one wins; affects AC-196.5).

## Notes for the architect

- The prompt of `/issue:triage` may not grow past the recorded size and every new rule sentence needs a register entry with a reason (spec 168). Keeping the existing-label rule, the `P1` fallback and the one-label replacement in `cplat` keeps the prompt small; only matching the issue to a definition (AC-196.2) needs the triager.
- The levels here describe an incoming issue. `docs/backlog.md` describes the platform's own specs differently ("P0 blocks a usable platform, P1 completes it, P2 is optional"); that line stays unchanged. The two scales meet when triage creates a spec at the issue's level (AC-196.6), so the user guide that explains triage should say that a triaged spec's priority follows the issue definitions; reconciling the backlog line is left to a later decision.
- If spec 176 is built first, the proposed priority and its reason fit into its batch facts and its confirmation lines; if this spec is built first, today's confirm table gets a priority column with the reason.
- A spec with `priority: P0` already matches `label:p0`; until now the default rules did not name it, so it sorted with `P2` specs. With AC-196.9 it sorts first, so existing `P0` specs move ahead of bugs (accepted by the user). The dispatcher guide and the design of spec 167 still show the old default and need the new one.

## Open questions

- ~~Under the default rules `label:bug, label:p1, spec-order, oldest`, an item at `p0` sorts no earlier than one at `p2`. Should the default rules name `label:p0`? (suggested: yes, `label:p0` first; affects AC-196.8)~~ Answered 2026-11-13: yes, `label:p0` first; existing `P0` specs move ahead too; see AC-196.9.

## Changelog

- 2026-11-13 created
- 2026-11-13 priority level definitions decided by the user (P0/P1/P2, P1 fallback); assumptions on P0 triggers and class fallbacks removed
- 2026-11-13 amended: open question answered (`label:p0` first in the default dispatcher rules); new AC-196.9 replaces AC-167.5; non-goal on ordering narrowed
- 2026-11-13 approved
