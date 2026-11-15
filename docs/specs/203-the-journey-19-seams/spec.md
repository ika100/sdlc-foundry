---
spec_id: 203-the-journey-19-seams
title: The journey 19 seams
status: building
priority: P1
shape: platform
---

# 203 — The journey 19 seams

## Problem

Journey 19 (2026-11-15, platform 5.23.1) found three platform defects. First (J19-1), the hand-off of spec 200 starts the
headless ship without the kube context the shipping session uses, so the detached run's deploy step could neither check
dev nor run the dev smoke; the interactive session checked the cluster and ran the smoke by hand, which records nothing.
Second (J19-2), an escalation in the API repo of a system ship was answered with its suggested answer, which added a plan
task before the acceptance tests; the build went on with the units derived from the old plan, could not continue, and the
coordinator stopped the run with the API half built. Third (J19-3), `cplat next`, the hand-over at the end of
`/component:ship` and `/system:ship`, hung twice in journey 19 and once in journey 17 until the coordinator stopped it.
Each one costs a hand-run step, a stopped run or a stuck session in every journey that meets it.

## Stories

As someone shipping a spec from an interactive session, I want the handed-off run to deploy and smoke-test dev with the
same cluster my session would use, so that the dev smoke is recorded in the run and I run nothing by hand.

As a coordinator whose run changed its plan after an answer, I want the build to go on from the changed plan, so that an
answered question never leaves a repo half built.

As someone at the end of a ship, I want `cplat next` to answer within a minute, so that the hand-over never holds my
session.

**Repos:** sdlc-foundry (the platform: `cplat` and the component and system plugins; the behaviour reaches every
component and gitops-app repo).

## Acceptance criteria

The handed-off run has the shipping session's kube context (J19-1).

- **AC-203.1** Given `cplat component ship start <spec> --detach` in a component repo, when it starts the headless
  process, then it resolves one kube context in this order: its own `--context C`; `CPLAT_KUBE_CONTEXT`, then
  `KUBE_CONTEXT` of the calling session; `kube_context:` in the settings files; the context `k3d-<system>-local` when the
  kubeconfig has it. It records the context in the ship state, prints `context: <name> (<where it came from>)` after the
  `headless:` line, and the headless run's `cplat component ship deploy` without `--context` uses it: it checks Argo CD
  health of `<service>-dev`, runs the dev smoke and records its result in that run, so `cplat component ship status` of
  the run shows the smoke as passed or failed, never "not run" for a missing context.
- **AC-203.2** Given a run handed off with a recorded context, when it is started again (a second `--detach`, the resume
  after `ENDED:`, or `--detach --answer`), then the new process gets the same context unless `--context` names another.
  Given no context from any source of AC-203.1, the hand-off still starts the process, prints
  `context: none (dev is not checked; pass --context <kube-context>)`, and deploy records "not run" as today. Given a
  `--context C` that the kubeconfig does not have, `ship start --detach` exits non-zero with one line naming `C`, and no
  process starts.

A changed plan reschedules the build (J19-2).

- **AC-203.3** Given a unit-mode build (a component ship, or a repo of a system ship) whose plan's task list changes in the
  committed tree after the build started (a task added, as by an answered escalation, merged by `cplat plan merge`,
  removed, or with changed dependencies), when the next unit is chosen, then the units are derived again from the committed
  plan before that unit starts: in the journey's case the new task `t0` runs before every not-done task that depends on it,
  each done unit keeps its checkpoint and is not run again, and the run neither escalates nor stops because of the change.
  `cplat component build schedule` prints the new batches at once.
- **AC-203.4** Given the same rescheduling, when a not-done unit's set of tasks changed (a `batch:` unit that lost or gained
  a task, a `task:` unit whose task was merged into another), then that unit is replaced by the new one, which starts fresh
  with no sessions or stalls counted. A change to the plan's text that changes no task id, files or dependency changes no
  unit. A changed plan that fails the plan check starts no unit and escalates the run with cause `code`, naming the check's
  first error.

`cplat next` always returns (J19-3).

- **AC-203.5** Given a source of `cplat next` that does not answer (a GitHub call that never returns, a state file whose
  lock another process holds, or a run state that cannot be read), when `cplat next` or `cplat next --json` runs, then it
  exits 0 within 60 seconds in total and within 20 seconds per source. The sources that answered are shown as usual, the
  silent one is named as AC-192.4 says, and `--json` lists it under `unavailable` with the error `no answer within 20 s`.
- **AC-203.6** Given `cplat next` run with an open terminal on its input that nobody types into, or with no input at all,
  when it reads its sources, then it never waits for input, a password or a confirmation from any program it calls, and
  returns as in AC-203.5; the hand-over at the end of `/component:ship` and `/system:ship` therefore ends within the same
  60 seconds.

## Non-goals

- Changing which cluster a system ship passes to its repo sessions (spec 155) or how `cplat system ship start --context`
  resolves its context.
- Guessing a context from the current kube context alone: a context that is neither given, configured nor the system's
  local one is not used.
- Re-running done units after a plan change, or changing what `cplat plan merge` allows (spec 186).
- Making the sources of `cplat next` faster, or caching them between calls (`cplat next` stays stateless, AC-192.1).
- The journey driver's stop pattern ("what you decide"), which lives in the journey tooling, not in the platform.

## Assumptions

- **A1** The context order is `--context`, `CPLAT_KUBE_CONTEXT`, `KUBE_CONTEXT`, the settings' `kube_context:`, then
  `k3d-<system>-local` when present, matching how deploy and the local port lookup (spec 199) already find the cluster
  (other option: the current kube context when it lists the component's Argo CD application, as the system ship does;
  affects AC-203.1).
- **A2** The context reaches the headless process through its environment and the ship state, so a resumed process gets it
  without the session passing it again (other option: only a `--context` argument each time; affects AC-203.1, AC-203.2).
- **A3** Without any context the hand-off still starts and says so, because a ship without a cluster (a library-like
  component, CI-only checks) must keep working (other option: refuse the hand-off; affects AC-203.2).
- **A4** The schedule follows the plan in the committed tree of the feature head, as units already do (spec 131); a plan
  change not yet committed changes nothing (other option: the working tree; affects AC-203.3).
- **A5** Only a task's id, files and dependencies decide whether a unit changed; title and description edits never restart
  a unit (other option: any change to a task's block; affects AC-203.4).
- **A6** A plan that fails the plan check after a change escalates with cause `code`, because the run wrote it (other
  option: cause `decision`; affects AC-203.4).
- **A7** The limits are 20 seconds per source and 60 seconds in total, well under the 10-minute Bash limit; the plan finds
  the call that blocked in journeys 17 and 19 and names it in its first task (other option: 30 and 120 seconds; affects
  AC-203.5, AC-203.6).
- **A8** The fixes live in `cplat`; if the plan changes an agent or command prompt, each rule gets a rules-register entry
  (spec 168) and the prompts stay within their recorded size; tests check behaviour with faked `kubectl`, `gh` and
  `claude`, not prompt sentences (spec 180) (other option: none; a build note, affects AC-203.1 to AC-203.6).

## Open questions

## Changelog

- 2026-11-15 created
- 2026-11-15 approved
- 2026-11-15 building
