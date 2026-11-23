---
spec_id: 216-the-system-ship-drives-its-repos-without
title: The system ship drives its repos without a model
status: approved
priority: P1
shape: platform
---

# 216 — The system ship drives its repos without a model

## Problem

`/system:ship` runs as a model session that, after phase `plan`, relays `cplat system ship` one action at a time: `next`, `repo start`, `next --wait` again and again, `repo resume` or `repo hold`, `escalate`, `land`, `phase complete`, `complete`, `finish`. Every rule for these actions is already written down and mechanical, but each relay is a model call that rereads the coordinator's whole context. In journey 23 (platform 5.26.0) the step "One spec for the whole system" took 51 minutes and 24.4 M of the journey's 39.2 M tokens. The coordinator used 8.0 M of them in 78 calls: 31 calls (about 3.4 M) only relayed `cplat`, and 14 more (about 1.4 M) were ad-hoc git and gh checks between actions. Its context grew from 51 k to about 95 k tokens per call. Journey 22 looks the same (coordinator 18.7 M of 42.6 M). Spec 200 moved a component ship into its own process for the same reason. This spec does the same for the mechanical part of the system ship, as one measured wave of the token and time plan: it must move the number or be switched off.

## Stories

As someone shipping a system spec, I want `cplat` to run the repos, the land and the completion of my system ship without a model, and my session only to plan, build the gitops entry, wait and hand over, so that the ship costs my session a few turns and I get the same repo sessions, escalations, dev deploy and final report as today.

As the platform maintainer, I want the driver tested against simulated repos, GitHub and Argo CD, and a switch that brings back today's loop, so that I can trust its decisions before a journey and turn it off if the journey does not show the saving.

**Repos:** sdlc-foundry (the platform: `cplat` and the system plugin; the behaviour reaches every gitops-app repo).

## Acceptance criteria

Starting the driver.

- **AC-216.1** Given a system ship run in phase `publish`, `repos` or `complete` that is neither done nor escalated, when `cplat system ship drive` runs, then it starts one detached process, the driver, in the gitops repo. It records the driver's process id and log path in the system ship state and prints `driver: pid <pid>, log <path>` and `next: cplat system ship wait`. The driver runs the steps of AC-216.2 to AC-216.4 and starts no model session of its own: a test with a fake `claude` that fails when called shows it is never called. Its waiting time counts toward the system ship run. If a driver of the same run is still alive, no second process starts and the existing `driver:` line is printed again. In phase `plan`, with no run, or with a done or escalated run, it exits 1 with one line naming the phase and the step to take, and starts nothing.

What the driver does (the rules `/system:ship` prescribes today, each step's `cplat` output written to the driver's log).

- **AC-216.2** Given a running driver in phase `repos`, when `cplat system ship next` returns an action, then the driver acts as follows. `start`: it runs `cplat system ship repo start <id>` for each listed id. A `preflight failed: <category>: …` line leaves that repo escalated and the others go on. `wait`: it runs `cplat system ship next --wait` again on `WAIT:` (exit 0) and on `TIMEOUT:` (exit 2). After three `TIMEOUT:` results in a row (a `WAIT:` starts the count again) it runs `cplat system ship escalate '<the third TIMEOUT line>' --cause environment` and ends. `answer`: with cause `decision` and a suggested answer for every question, it runs `cplat system ship repo resume <id> --answer '<the suggested answers>'`; otherwise it runs `cplat system ship repo hold <id>`. `escalate`: it runs `cplat system ship escalate '<the repo's reason>'` without `--cause`, so the repo's cause is kept, and ends.
- **AC-216.3** Given a running driver, when the run is in phase `publish`, or `next` returns `land` or `complete`, then the driver acts as follows. In phase `publish` it runs `cplat system ship publish`; on exit 0 it goes on with phase `repos`. `land`: on exit 0 it goes on to `complete`. Exit 1 has already escalated the run, so the driver ends. On exit 2 (`TIMEOUT:`) it runs `land` again, at most twice. A third exit 2 makes it run `cplat system ship escalate '<that TIMEOUT line>' --cause environment` and end. `complete`: it runs `cplat system ship phase complete`, then `cplat system ship complete`, then `cplat system ship finish`, and ends.
- **AC-216.4** Given a rule where `/system:ship` says "stop" without escalating, when the driver meets it, then the driver ends and the run stays unescalated, as today. The two such rules are a publish with a red check (exit 1: no repo starts) and a `repo start` refused because a clone has uncommitted changes (the clone's path). The wait reports it as `STOPPED:` (AC-216.6).

The gitops entry stays with the session.

- **AC-216.5** Given an action `start` that lists the gitops entry (`entry: true`), when the driver handles it, then it runs `repo start` for every listed repo, the entry included. The component repos' own sessions start as today. The driver then records the run as waiting for the entry and ends. This end does not count as an early end (AC-216.6). The wait exits 0 with `ENTRY: <id> in <worktree>`. The session builds the entry in that worktree as the gitops entry reference says (`entry apply`, `entry pr`, `entry land`, or `repo escalate … --cause platform`) and then runs `cplat system ship drive` again. The new driver takes the run from its state. No repo that depends on the entry starts before the entry is merged, or, in a joint run, before its checks have passed.

Waiting on the driver.

- **AC-216.6** Given a run with a recorded driver, when `cplat system ship wait [--timeout T]` (default 540) runs, then it ends no later than T plus 10 seconds after it started and prints one line with the time for each new driver step. It ends with exactly one result. Exit 0: `DONE:` followed by the final report word for word as `cplat system ship complete` printed it and the archive path; `ENTRY:` (AC-216.5); or `WAIT: driver still going, progress in the last <T>s; run the same wait again` when the driver wrote a step or the run state changed during the call. Exit 1: `ESCALATED:` followed by the reason, the cause, each escalated repo's questions with their suggested answers, the repo table, the log path and `resume it with /system:ship <spec>`; `STOPPED:` followed by the line of the rule that stopped it (AC-216.4); or `ENDED: driver ended in phase <phase>; log <path>` when the driver process ended while the run is neither done, escalated, stopped nor waiting for the entry. After the first `ENDED:`, `cplat system ship drive` starts the driver again from the state; a second early end in the same run escalates the run with cause `environment`, naming the log. Exit 2: `TIMEOUT:` with the phase, the time since the driver's last step and the log path, when nothing changed during the call. A run without a recorded driver makes the wait exit 1 at once with one line saying so and naming `cplat system ship drive`.

The session, the Stop hook and resuming.

- **AC-216.7** Given the `/system:ship` instructions with the driver on, when the session ships a spec, then it runs `cplat shape`, `cplat system ship start …` and phase `plan` as today, then `cplat system ship phase publish`, `cplat system ship drive` and `cplat system ship wait`. It runs the same wait again on `WAIT:` and on `TIMEOUT:`. After three `TIMEOUT:` results in a row (a `WAIT:` starts the count again) it runs `cplat system ship escalate '<the TIMEOUT line>' --cause environment`. It builds the entry on `ENTRY:` and runs `drive` again on the first `ENDED:`. On `DONE:` it prints the report and on `ESCALATED:` or `STOPPED:` it prints the result, each followed by the hand-over (`cplat next --json`). The session itself runs no `next`, `repo start`, `repo resume`, `repo hold`, `land`, `phase complete`, `complete` or `finish`. The changed rules have rules-register entries (spec 168), and the instructions read at the start are shorter than their recorded size before this change.
- **AC-216.8** Given a running driver and the session that owns the run, when that session tries to stop outside a wait, then `cplat system ship gate` holds it with the next step `cplat system ship wait`. A running `cplat system ship wait` lets the stop through, as AC-202.1 says. The driver's steps, a repo's state change and a commit in a running repo's clone count as progress. Two stops without progress escalate the run as today. The driver never claims the run, and a session that does not own the run is not held.
- **AC-216.9** Given a run state written by today's flow (phase `repos` or `complete`, repos running in their own sessions, finished, escalated or held, and no driver recorded), when `/system:ship <spec>` resumes it with the driver on, then `cplat system ship drive` takes the run from that state. It restarts no repo session that is still alive, records each repo that finished meanwhile as `repo result` does, and goes on with the action `next` returns. An escalated run that is resumed (`cplat system ship start`) goes on the same way.

The switch, the simulation and the measure.

- **AC-216.10** Given `CPLAT_SYSTEM_DRIVER=0` in the session's environment, when `cplat system ship drive` runs, then it starts no process, prints `driver: off (CPLAT_SYSTEM_DRIVER=0); run phase repos in this session`, and exits 0. The session then runs phases `publish`, `repos` and `complete` with today's rules, the same verbs and the same order as before this change. A run that a driver started goes on in the session from its state. Without the variable, or with any other value, the driver is on.
- **AC-216.11** Given fakes of `gh`, of the repo sessions and of Argo CD with injected delays and failures, when the driver runs a simulated system ship, then the `cplat system ship` steps it takes equal, in order, the sequence the `/system:ship` rules prescribe. The scenarios are: two dependent repos to `DONE:`; a repo escalating with cause `decision` and a suggested answer for every question (resume); a repo escalating without a suggested answer (hold, then `escalate` once nothing runs, with the repo's cause); three `TIMEOUT:` in a row (escalate with cause `environment`), and two `TIMEOUT:` around a `WAIT:` (no escalation); `land` exiting 2 twice and then 0 (`complete`), and three times (escalate with cause `environment`); a `preflight failed` repo next to one that goes on; the gitops entry (`ENTRY:`); and a driver killed mid-run (`ENDED:`, restart, then a second end escalating). The suite runs without network or cluster in under 60 seconds.
- **AC-216.12** Given the first journey measured with this change (`cplat platform runs journey measure`) that runs a system ship, when its step "One spec for the whole system" is read, then the coordinator made at most 40 model calls in it (journey 23: 78) and used at most 4.0 M tokens (journey 23: 8.0 M). The step also has no more escalations and no more stops than journey 23. If any of these fails, `CPLAT_SYSTEM_DRIVER=0` becomes the default in the next release and the change is reverted. The result is recorded in the journey's performance rows.

## Non-goals

- Changing how repo sessions build or ship (the waves on unit sessions and building), the component ship, or `cplat system ship next --wait` itself (spec 194).
- Changing phase `plan` or the planner.
- Moving the gitops entry into the driver (a possible follow-up spec, see the Notes).
- Any web console work: the user reworks the UI.
- A merge queue.
- New escalation causes, texts or answer rules: the driver applies today's.

## Assumptions

- **A1** The driver is started by a new verb `cplat system ship drive` and waited on with a new verb `cplat system ship wait`, so that `start` keeps its refusals and `next --wait` keeps its contract (other option: `cplat system ship start --detach` and a changed `next --wait`; affects AC-216.1, AC-216.6, AC-216.7).
- **A2** The driver is a detached process, as in spec 200, because a foreground loop would outlast the 10-minute tool limit. Its log goes to the gitops repo's headless log folder, and its process id and log path are in the system ship state (other option: a foreground `cplat` call run again by the session; affects AC-216.1, AC-216.6).
- **A3** At the gitops entry the driver runs `repo start` for it, then ends with the run marked as waiting for the entry. The session builds the entry and runs `drive` again, so two processes never write the run at once (other option: the driver keeps running while the session builds the entry; affects AC-216.5).
- **A4** The two "stop" rules of today (a red publish check, a clone with uncommitted changes) end the driver with `STOPPED:` and leave the run unescalated, as today (other option: escalate them with a cause; affects AC-216.4, AC-216.6).
- **A5** The driver runs `finish` after `complete`, and the wait prints the final report from the archived run (other option: the session runs `finish`; affects AC-216.3, AC-216.6).
- **A6** The suggested answers go to `repo resume` in question order, each as `<question>: <suggested answer>`, joined by `; ` (other option: only the answers, one per line; affects AC-216.2).
- **A7** Progress for `system ship wait` is a new driver step or a change of the run state. While the driver lives it ends a step at least every `next --wait` timeout, so three `TIMEOUT:` results in a row (about 27 minutes of silence) mean a hung driver, and the session escalates with cause `environment`. The driver keeps its own three-`TIMEOUT:` rule for the repos (other option: the wait never times out while the driver process lives; affects AC-216.6, AC-216.7).
- **A8** A driver that ends early is started once more, and a second early end escalates the run with cause `environment`, as AC-200.4 does for a component ship (other option: escalate at the first end; affects AC-216.6).
- **A9** The switch is a new environment variable `CPLAT_SYSTEM_DRIVER`, on by default, `0` for off. Today's loop rules stay in a reference that the session reads only when `drive` reports the driver off, so that the instructions read at the start shrink (other option: reuse `CPLAT_HEADLESS_LEAN`, which already switches the headless context trim; affects AC-216.7, AC-216.10, AC-216.12).
- **A10** The gitops entry stays with the session, as the request says, although its steps are `cplat` calls. Only its PR title needs a summary (other option: move it into the driver now; affects AC-216.5).
- **A11** The measure is read from the first journey after release that runs a system ship. Escalations and stops are counted as `cplat platform runs journey measure` reports them for that step (other option: average two journeys; affects AC-216.12).

## Notes for the architect

- An ADR may be needed: "a system ship's mechanical loop runs in `cplat`", amending ADR-082 (who decides on a `TIMEOUT:`) and ADR-086.
- AC-186.2 and AC-194.4 name the `/system:ship` instructions as the side that resumes, holds and counts `TIMEOUT:` results. They stay true through the switch-off path of AC-216.10. If that path is ever removed, a follow-up must supersede them.
- The entry's steps are already `cplat` calls (`entry apply`, `entry pr --title`, `entry land`). A title built from the spec's title would let a follow-up move the entry into the driver too and save the `ENTRY:` round trip.
- The driver can reuse the component ship's detach seams (spawn, alive) so that the simulation replaces them.

## Open questions

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-21 created
- 2026-11-21 priority P1 proposed: P1: normal bug or feature
- 2026-11-23 approved
