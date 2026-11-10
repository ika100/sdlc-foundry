---
spec_id: 167-a-dispatcher-runs-the-backlog-in
title: A dispatcher runs the backlog in parallel slots
status: done
priority: P1
shape: platform
---

# 167 — A dispatcher runs the backlog in parallel slots

## Problem

Today the user schedules the work between runs. Each round they write issue waves, a progress file and a ship order by hand. Then they start each `cplat headless` ship or fix, wait for it, merge the pull requests one at a time and start the next one. Parallel sessions get in each other's way: they share one checkout, there is one ship slot per clone, and they merge by hand in turn. In the journey measurements of 2026-11-05, about 37 % of the time was waiting and 17 % was the person's own time. The token diagnosis of 2026-10-25 put 42 % of the tokens on coordination.

The pieces for unattended work exist: claims (spec 082), headless unit runs (specs 070, 131), child processes (spec 155), budgets (spec 102), waits (spec 143) and decision points with notifications (spec 122). Nothing uses them to work through the backlog, so the user still has to do that.

This spec adds `cplat dispatch`. It is the level above the orchestrator. It reads the backlog, decides what is ready, starts one orchestrator run (`/component:fix` or `/component:ship` under `cplat headless`) per free slot, merges only on green CI, and records the outcomes. It never designs a fix. It reads only enough to judge whether an item is ready and whether its work can be split. A repo opts in by committing `.platform/dispatch.yml`. Without that file nothing changes, and manual sessions work as before.

## Stories

- As the platform owner, I want approved specs and triaged issues to run on their own in parallel slots, in an order I set once in a policy file, so that I stop being the scheduler between runs.
- As the platform owner, I want to see what the dispatcher would do before it does anything, so that I can turn it on step by step: plan only, then one slot for fixes, then more.
- As the platform owner, I want to hear from it only when a decision is mine (approve, answer, escalation, triage, budget, stuck), plus one daily digest, and to steer it with a few commands, so that it saves my time instead of taking it.
- As a developer in a manual session, I want the dispatcher to leave an issue alone once I claim it or mark it `needs-decision`, and never to merge at the same moment as I do, so that we do not collide.
- As the platform owner, I want the dispatcher to keep to a daily token budget and to continue correctly after a crash, so that unattended work neither overspends nor starts anything twice.

**Repos:** sdlc-foundry (the platform; the dispatcher runs in any component or platform repo that commits a policy file).

## Acceptance criteria

Words used below. A **candidate** is an approved spec, or an open issue with the label `triaged` and without `needs-decision` or `wontfix`, taken from the sources the policy enables. A **unit** is one orchestrator run that the dispatcher started for one candidate. A **slot** can hold one running unit. A **cycle** is one scheduling pass. The dispatcher runs a cycle every 60 seconds and whenever a unit ends, and it reads GitHub at most every 5 minutes. Its state is rebuilt on each start from GitHub, git (branches and worktrees) and the run store. Nothing it relies on lives only in its memory.

The policy and the plan.

- **AC-167.1** Given a repo without `.platform/dispatch.yml`, when `cplat dispatch start` or `cplat dispatch resume` runs, then it exits 1 naming the file and starts nothing. Given a policy without `budget.tokens_per_day` (it has no default), when `cplat dispatch start` or `cplat dispatch resume` runs, then it exits 1 naming that key and starts nothing. Given a policy with an unknown key, or with a value outside the allowed ones, when any `cplat dispatch` command reads it, then it fails naming the key and the allowed values. The keys are `slots`, `budget.tokens_per_day`, `budget.per_unit`, `sources`, `ready`, `priority`, `gates.approve_specs`, `gates.merge` and `serialize`. A `gates.merge` other than `green-ci`, a `gates.approve_specs` other than `human` or `self`, or a `serialize` without `merge`, is refused.
- **AC-167.2** Given any repo, when `cplat dispatch plan [--json]` runs, then it prints the effective policy (the defaults when there is no file, marked as such). When `budget.tokens_per_day` is not set, it shows the key as unset together with the daily token usage of each of the last 7 days as a hint. It then lists every candidate once, in priority order, with its kind (`fix` or `ship`), its verdict (`ready` or `held: <reason>`), its mode (`single` or `team`) and the slot it would take. GitHub (labels, assignees, comments, issue state), branches, worktrees and claims are the same before and after the command.

Readiness and order.

- **AC-167.3** Given a candidate, when a cycle judges it, then it is held, with the reason shown in `plan` and `status`, in each of these cases:
  - `claimed`: it carries `in-progress` without a dispatcher claim, it is claimed for another branch (spec 082), or an open run record of an engine or a manual session serves it.
  - `blocked`: its text says `blocked by #N` or `depends on #N` and #N is open.
  - `duplicate`: an open pull request already closes it, or an approved spec tracks the same issue (the spec runs and the issue is held).
  - `needs-spec`: triage routed it to a spec.

  A held candidate gets no label, comment or claim from the dispatcher.
- **AC-167.4** Given a ready issue about to take a slot, when the short premise check finds it already resolved on `main`, then `start` comments on the issue with the commit or pull request that resolved it, labels it `stale-premise`, closes it and starts no unit. `plan` only shows `held: stale`. An issue that was reopened after such a close is never closed as stale again.
- **AC-167.5** Given ready candidates, when a cycle orders them, then it applies the policy's `priority` rules in order and moves to the next rule only to break a tie. The default order is `label:bug`, `label:p1`, `spec-order`, `oldest`. Given `cplat dispatch prioritize <item>`, then that item comes first until it starts. Given `cplat dispatch skip <item> --reason <text>`, then it is held as `skipped: <text>` until `cplat dispatch resume <item>`. Both survive a restart of the dispatcher.

Running units.

- **AC-167.6** Given `slots: 2`, three ready issues and enough daily budget, when `cplat dispatch start` runs, then for each of the first two issues it claims the issue as in AC-082.1 (the comment names `cplat dispatch` and the branch), creates the issue's own worktree on its own branch, and starts `cplat headless "/component:fix #N"` there as a separate process with the per-unit budget of AC-131.13. It records the process and the log path. A test with a fake headless shows the two units overlapping and the third issue waiting until a slot frees. A ready approved spec starts `cplat headless "/component:ship <spec>"` the same way, with `--parallel 3` in mode `team` and `--parallel 1` in mode `single`. While a ship unit runs, a second ship candidate is held as `ship-busy`. A draft spec never starts while `gates.approve_specs` is `human` (the default). Only when the policy sets `gates.approve_specs: self` explicitly does a cycle approve a draft spec itself, and only one with no unstruck open question and a passing `cplat spec check`; the approval is recorded as made by `cplat dispatch`, and any other draft stays held as `needs-approval`.
- **AC-167.7** Given two units, or a unit and a manual session's `cplat pr wait --merge` in the same repo, whose pull requests are ready to merge at the same time, when they land, then they merge one at a time. The second waits for the lock, and if its branch is now behind `main`, its CI runs again on top of the first merge before it merges. No pull request merges unless every check is green. With `e2e` in `serialize`, the lock covers the whole land phase (pull request CI through merge), so only one unit runs its land phase at a time. After a unit's merge, its claim is released, its outcome (`done`, the pull request, tokens used) is recorded and its slot is refilled in the next cycle.
- **AC-167.8** Given a unit that escalates, when the dispatcher sees it, then it releases the claim and labels the issue (or the spec's tracked issue) `needs-decision`, with a comment giving the reason. `cplat needs` gets an `escalation` entry, and the slot is refilled. Once the user removes `needs-decision`, the item is judged again in the next cycle. Given a unit whose process ended while its run is neither done nor escalated, then it is started once more from its saved state. A second such end escalates it with cause `environment`, and `cplat needs` gets an entry of the new kind `stuck` naming the log path.
- **AC-167.9** Given a dispatcher with two running units that is killed, when `cplat dispatch start` runs again, then it adopts the unit processes that still live and treats dead ones as in AC-167.8. No unit is started twice, and no issue gets a second claim or comment. It does not need any file the killed process kept in memory only.

Budget, steering and seeing it.

- **AC-167.10** Given `budget.tokens_per_day` (required to start, AC-167.1), when a cycle runs, then it adds up the tokens of every unit and of the dispatcher's own agent calls since local midnight. Once the limit is reached, no unit starts and no agent call is made. Running units continue within their own budgets (spec 102). `cplat needs` gets one `budget` entry per day, and starts continue after midnight on their own. While a running or finished unit's usage is unknown, no new unit starts, and `status` names that unit.
- **AC-167.11** Steering takes effect within one cycle and is recorded in the dispatcher's state, so it survives a restart:
  - `cplat dispatch pause`: no unit starts, and running units stop at their next checkpoint (spec 131), ready to resume.
  - `pause --drain`: no unit starts, and running units finish.
  - `cplat dispatch resume`: starts are allowed again.
  - `cplat dispatch slots <N>`: the slot count changes. A lower N never stops a running unit; it lets units finish until N is reached.

  `cplat dispatch status [--json]` lists the slots (unit, kind, phase, since, tokens used), the queue in order, the held items with reasons, pause state and today's tokens of the limit. `cplat dispatch wait [--timeout S]` (default 540 s, ADR-082) exits 0 when no unit runs and nothing ready is queued, 1 with a first line `ESCALATED:` or `RED:` when a unit escalates or a merge check fails, and 2 with `TIMEOUT:` and the running units. `cplat dispatch report [--since D]` lists per day what was delivered, escalated and held, and the tokens used.
- **AC-167.12** Given the new kinds `budget` and `stuck`, when they occur, then `cplat needs --json` lists them with the object, the reason and the command that resolves them, and the console Inbox shows them. `cplat dispatch inbox` lists the open needs of the kinds `approve`, `answer`, `escalation`, `triage`, `budget` and `stuck`. Instant notifications (AC-122.22) go out only for those kinds, and quiet hours are kept. A daily digest lists the units delivered, the escalations, the held items, the queue and the tokens used since the last digest. An empty digest is not sent.

## Non-goals

- Designing, triaging or reviewing work. The dispatcher starts the existing `/component:fix` and `/component:ship` runs, and their internals do not change. Untriaged issues stay with `/issue:triage` and the `triage` decision of spec 122.
- Writing draft specs for issues routed to `spec`, and running more than one ship unit at a time. Both need the follow-up spec on a central spec-number reservation for every `cplat spec new` and a ship slot per worktree instead of per clone.
- A merge lock across machines. The lock of AC-167.7 holds for the clones of a repo on one machine.
- Filing issues. The autonomy engine (spec 124) and the automatic issues of specs 088, 091 and 092 file them. The dispatcher only starts work, and AC-167.3 keeps it from starting work a run already serves.
- System (gitops-app) repos and `/system:ship`.
- Raising agent quality, or the limits set by machine resources (kind clusters, ports), CI capacity (one self-hosted runner, GitHub Free) and human review.

## Assumptions

- **A1** `cplat dispatch plan` works without a policy file and shows the defaults, so trying it needs no commit. Only `start` and `resume` need the file (other option: every command refuses without the file; affects AC-167.1, AC-167.2).
- **A2** The defaults follow the rollout: `slots: 1`, sources are issues only (approved specs off), `gates.approve_specs: human`, `gates.merge: green-ci`, `serialize: [merge]`. Turning on more slots and ship units is an edit to the policy (other option: specs on by default; affects AC-167.1, AC-167.6).
- **A3** The two short agent calls (does the premise still hold on `main`; single or team) run only for candidates that are about to take a free slot, in `plan` as well. The other candidates show `premise: unchecked` (other option: check every candidate; affects AC-167.2, AC-167.4).
- **A4** Fix units always run in mode `single`. A ship unit runs in mode `team` (`--parallel 3`, spec 159) when the divisibility check judges its work splittable, and in mode `single` (`--parallel 1`) otherwise (other option: always `--parallel 3` and let the plan decide; affects AC-167.6).
- **A5** `blocked` is read from `blocked by #N` and `depends on #N` in the item's text. A spec and an issue it tracks count as one candidate, and the spec runs (other option: GitHub's issue relations; affects AC-167.3).
- **A6** A stale close carries the label `stale-premise` and the evidence. If the user reopens the issue, that overrides the check for good (other option: a stale issue is only commented on and left open; affects AC-167.4).
- **A7** A dispatcher claim differs from a manual one by its claim comment naming `cplat dispatch`. The `in-progress` label without that comment counts as a manual claim (other option: a separate `dispatch` label; affects AC-167.3, AC-167.6).
- **A8** A cycle runs every 60 s and on every unit end, and GitHub is read at most every 5 minutes (other option: 30 s and 1 minute; affects AC-167.3, AC-167.11).
- **A9** `pause` without `--drain` stops running units at their next checkpoint, and `--drain` lets them finish (other option: the reverse; affects AC-167.11).
- **A10** The daily budget counts from local midnight. A unit with unknown usage holds new starts instead of counting as 0 (other option: count it at its per-unit limit; affects AC-167.10).
- **A11** The digest goes out daily at 09:00 local through the channels of `notify.yaml` that are set to `digest` (other option: weekdays only, as in AC-122.25; affects AC-167.12).
- **A12** With `e2e` in `serialize`, the whole land phase is serialized, because the e2e job runs on the single self-hosted runner. Without it, only the merge is serialized (other option: serialize only the e2e job; affects AC-167.7).
- **A13** A draft spec the dispatcher may not approve (gate `human`, an open question, or a failing `cplat spec check`) is held as `needs-approval` in `plan` and `status`, and gets no label or comment (other option: hide drafts from the candidate list; affects AC-167.6).

## Open questions

- ~~Does `budget.tokens_per_day` have a default, or must the policy state it?~~ Answered 2026-11-09: no default; `start` and `resume` refuse without it, `plan` shows the daily usage of the last 7 days as a hint, see AC-167.1, AC-167.2, AC-167.10.
- ~~May the dispatcher approve specs itself when `gates.approve_specs: self` is set?~~ Answered 2026-11-09: yes, only when set explicitly, only for a draft with no open questions and a passing `cplat spec check`, recorded as approved by `cplat dispatch`, see AC-167.1, AC-167.6.

## Changelog

- 2026-11-09 created
- 2026-11-09 amended: both open questions answered; `budget.tokens_per_day` is required to start or resume and `plan` shows a 7-day usage hint (AC-167.1, AC-167.2, AC-167.10); `gates.approve_specs: self` lets the dispatcher approve clean drafts (AC-167.1, AC-167.6)
- 2026-11-09 approved
- 2026-11-10 building
- 2026-11-10 done
