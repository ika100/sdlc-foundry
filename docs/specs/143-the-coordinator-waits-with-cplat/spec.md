---
spec_id: 143-the-coordinator-waits-with-cplat
title: The coordinator waits with cplat, not hand-written loops
status: done
priority: P1
shape: platform
tracks: [475]
---

# 143 — The coordinator waits with cplat, not hand-written loops

## Problem

In the two journeys of 2026-11-05 the coordinator wrote its own polling loops whenever a command left it to wait: on
`cplat component ship status` of two clones, on `kubectl get applications` until every app read `Synced Healthy`, on a
deployment's image until a new pin rolled out, on `curl` until a newly exposed host answered, and on `gh pr view` until a
pin PR merged. Spec 136 ranks these waits fifth among the cost drivers, about 10 minutes per journey. The loops are slow
(fixed sleeps of 10–15 s, a new loop after every 10-minute tool limit), they see only part of the state (`Synced Healthy`
on the old revision counts as done), and one of them never polled at all. When Argo CD has not picked up a merge yet,
nothing says so (#264, item 3): the app stays on the old revision for up to three minutes and it looks as if nothing
happens. `cplat pr wait` (spec 079) solved the same problem for CI; the environment and the ship run have no such wait.

## Stories

- As the coordinator, I want one command that blocks until an environment runs what `main` of the gitops repo says, so
  that I never write a polling loop on Argo CD.
- As the coordinator, I want one command that blocks until a ship run in another clone reaches a phase or ends, so that I
  never poll `ship status`.
- As the owner of a system, I want a wait that runs out of time to say which app is behind and on what, so that I see at
  once whether Argo CD has not picked up the merge or the new build does not start.

## Acceptance criteria

**The environment wait.** `cplat system wait --env <env> [<component>…] [--revision <sha>] [--refresh] [--timeout S]
[--context C]` runs in a gitops-app repo. It waits for the Argo CD applications of that environment: one per component
that has an instance there and one per resource there; naming components limits it to their apps. An app is in its wanted
state when it is synced to the wanted revision of the gitops repo (default: the head of `main` on GitHub when the wait
starts; a later commit that contains it also counts), it is `Synced` and `Healthy`, and, for a component, it runs the
image tag that revision pins for it in that environment (the image rule of `cplat component ship deploy`, spec 077). The
default timeout is 540 s, so one wait fits in one tool call.

- **AC-143.1** Given every app of the environment in its wanted state, when `cplat system wait --env dev` runs, then it
  exits 0 at once and prints one line per app with the revision and the image tag it runs.
- **AC-143.2** Given apps that reach their wanted state one after another, when the wait runs, then it prints one line each
  time an app's state changes (for example `todo-api-dev: Synced/Progressing at 4f2a91c, runs sha-4f2a91c…`) and nothing
  while no state changes, and it exits 0 once the last app is in its wanted state.
- **AC-143.3** Given an app at the wanted revision with a sync error, a failed sync operation or health `Degraded`, when
  the wait sees it, then it stops at once with exit 1 and a first line starting with `RED:` that names the app, the
  revision and Argo CD's message; it does not wait out the timeout.
- **AC-143.4** Given an app that is still behind when the timeout ends, then the wait exits 2 with a first line starting
  with `TIMEOUT:` and one line per app that is behind, naming what it waits for against what it has: the wanted revision
  against the revision Argo CD has synced (`waiting for revision 4f2a91c, Argo CD is at 9b07c3e`), the wanted image tag
  against the images it runs, or its sync and health status. An app that does not exist is listed as `missing`. When an
  app is behind on the revision and `--refresh` was not given, the last line is the same command with `--refresh` added.
- **AC-143.5** Given `--refresh`, when the wait starts, then it asks Argo CD once for a hard refresh of each app it waits
  for that is not yet at the wanted revision, and prints one line saying so; apps already at the revision are left alone.
- **AC-143.6** Given no `--context` and a current kube context that is not the system's cluster, a cluster that does not
  answer, or no Argo CD in it, when the wait starts, then it exits non-zero at once naming the problem and the context it
  tried, without waiting.
- **AC-143.7** Given a cluster repo (spec 125), when `cplat cluster wait [--refresh] [--timeout S] [--context C]` runs,
  then it waits in the same way for the cluster's root application to be synced to the head of the cluster repo's `main`
  and to be `Synced` and `Healthy`, with the output, exit codes and `--refresh` of AC-143.1–AC-143.6.

**The ship wait.**

- **AC-143.8** Given a ship run in a clone, when `cplat component ship wait [--repo DIR] [--phase P] [--timeout S]` runs,
  then it prints one line with the time each time the run's phase changes, and exits 0 when the run reaches phase `P` or a
  later one (in the order plan, build, pr, land, deploy, done), or `done` when no phase is given. It exits 1 with a first
  line starting with `ESCALATED:`, the reason and the cause when the run is escalated, and 2 with `TIMEOUT:`, the phase and
  how long the run has been in it when the timeout (default 540 s) ends first. A clone without a ship run makes it exit
  non-zero at once, saying so.
- **AC-143.9** Given a system ship run whose `cplat system ship next` says `action: wait`, when
  `cplat system ship next --wait [--timeout S]` runs, then it blocks until the action is another one and prints it as
  `next` would (`--json` included), with a line each time a running repo's phase changes; it exits 2 with `TIMEOUT:` and
  the running repos and their phases when the timeout (default 540 s) ends first.

**Both waits.**

- **AC-143.10** Given a wait inside an unfinished ship or system ship run, when it ends, then its minutes count toward that
  run's record as waiting time, as with `cplat pr wait` (spec 087); outside a run it records its own run with why it ended
  (`reached`, `red`, `timeout`, `escalated`). A wait asks GitHub at most once for the head of `main`; everything else it
  reads from the cluster and the run state.

**The commands use them.**

- **AC-143.11** Given the command files and agents that today leave the coordinator to wait for an environment, a ship run
  or a PR (at least `/component:set` and `/component:add` with an exposure, `/instance:promote`, `/system:set`,
  `/resource:add`, `/cluster:add`, `/system:ship` at `action: wait`, and the CI waits of `/component:release`), then each
  names the wait to run at that point (`cplat system wait`, `cplat cluster wait`, `cplat component ship wait`,
  `cplat system ship next --wait` or `cplat pr wait`), passes `--refresh` right after a merge it made, says to run the same
  wait again on exit 2, at most twice, and then to escalate with cause `environment`, and says never to write a polling
  loop. A test fails when a command file or agent contains a shell loop with `sleep` that polls `kubectl`, `gh` or `cplat`.

## Non-goals

- No new slash command and no user-facing feature beyond the waits: they are `cplat` commands that the commands and
  agents call.
- No change to what `cplat component ship deploy`, `cplat resource upgrade --wait` or `cplat pr wait` wait for; they may
  share code with the new waits, with the same behaviour.
- No new column in `/system:status` for the synced revision against `main` (#264 suggested it); the wait's output names
  it. It can follow once the platform is stable.
- No wait for a background subagent's files or commits (`plan.md` appears, a commit names a task): subagents run in the
  foreground, as the commands already say; a loop on their files is a defect of the command that started them.
- No smoke test inside the environment wait; reachability stays with `/instance:verify` and `devbox run smoke`.
- No automatic retry or rollback of a failed sync; a red wait reports, the command decides.
- No Argo CD webhook from GitHub for instant pick-up of a merge; `--refresh` covers the local cluster.
- #264 item 4 (merges without CI) stays open there.

## Open questions

- ~~Name of the environment wait: `cplat system wait --env <env>` or `cplat instance wait <env>`?~~ Answered:
  `cplat system wait --env`, since it also waits for the resources' apps, which are not instances; see the environment
  wait and AC-143.1.
- ~~Should the wait hard-refresh an app by itself when it is still behind after Argo CD's polling interval, without
  `--refresh`?~~ Answered: no; the command that merged passes `--refresh`, and the timeout message prints the command with
  it; see AC-143.4, AC-143.5, AC-143.11.
- ~~Confirm: a default timeout of 540 s for every wait; exit 2 means "run it again"; the commands escalate after the third
  timeout in a row.~~ Answered: yes; see the environment wait, AC-143.4, AC-143.8, AC-143.9, AC-143.11.
- ~~Confirm: `cplat cluster wait` belongs in this spec.~~ Answered: yes; see AC-143.7.
- ~~Confirm: `cplat system ship next --wait` belongs in this spec.~~ Answered: yes; see AC-143.9.

## Changelog

- 2026-11-05 created
- 2026-11-05 approved by the user
- 2026-11-05 building
- 2026-11-05 done
