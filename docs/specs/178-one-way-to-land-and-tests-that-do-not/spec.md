---
spec_id: 178-one-way-to-land-and-tests-that-do-not
title: One way to land and tests that do not race
status: done
priority: P1
shape: platform
tracks: [648]
---

# 178 — One way to land and tests that do not race

## Problem

The platform's defects sit in the seams between its layers (orchestrator, headless session, coder session, `cplat`, git and GitHub, parallel sessions). Each layer is tested alone against fakes, so a seam is first exercised in a journey, where a failure costs a person's time and a long retry. Three recent examples: during the 5.17.0 release `main` moved, and `cplat platform release --confirm merge` went through the land path of spec 171. That path merged `main` into `release/5.17.0`, so its changelog section and benchmarked plugin tree no longer matched what was released. It then called the merge at once, before the new head's required check had finished, and GitHub refused (#648). Merging is done by five commands, and only some of them share the landing rules of ADR-092, so a fix in one does not reach the others. And the dispatcher's land and unit acceptance tests (spec 167) failed on the slower CI runner because they wait for processes and threads with fixed sleeps. This round adds no feature: it leaves one way to merge and makes the tests deterministic. It also adds one test that runs a whole ship across the layers in CI.

## Stories

As the platform maintainer, I want every merge into `main` to go through one landing path with the mode its command states, so that a landing fix reaches every command and a release is never changed behind my back.

As the platform maintainer, I want the suite to pass or fail the same way on my machine, under `-n auto` and on the slower CI runner, and one test to run a ship through every layer, so that a seam breaks in CI and not in a journey.

**Repos:** sdlc-foundry (the platform; the landing path reaches every component and system repo through `cplat`).

## Acceptance criteria

Landing.

- **AC-178.1** Given an open release PR whose branch is behind `main` (`main` moved after the release branch was cut), when `cplat platform release --confirm merge` runs, then it pushes nothing to the release branch, merges nothing, and exits 1. Its first line is `main moved: start the release again`, and a `fix:` line names the steps: close the release PR, delete the release branch, run `cplat platform release`. The same holds when `main` moves while the release waits for its checks.
- **AC-178.2** Given a land that updated the PR's branch itself (it merged `main` into it, regenerated a generated file per AC-171.6, or pushed local commits per AC-171.5), when it reaches the merge, then it makes no merge call until every required check of the new head has finished green. A red check stops the land as a red check does today. A test with a fake GitHub shows no merge call while any required check of the new head is pending.
- **AC-178.3** Given a merge that GitHub refuses because a required check is pending or the head moved, when the land handles the refusal, then it does not exit with an error. It goes back to waiting for the checks of the PR's current head and merges when they are green, inside the merge lock (AC-167.7). After 3 refused merges in one land, it exits 1 with `merge refused 3 times: <GitHub's last reason>`.
- **AC-178.4** Given the five commands that merge into `main` (`cplat component ship land`, `cplat pr wait --merge`, the dispatcher's land of a unit, `cplat platform release --confirm merge` and `cplat spec land`), when each one merges, then it goes through the one landing path of ADR-092 with its stated mode. Release does not allow catch-up; the other four do. A parametrised test runs the same scenarios against all five and shows the same outcome in each: a head that moved before the merge (AC-171.4), a merge accepted followed by a failed local step (AC-171.3), a refused merge (AC-178.3) and a branch behind `main`. The only difference is the branch behind `main`: release stops as in AC-178.1, and the other four catch up as in AC-178.2.

Tests that do not race.

- **AC-178.5** Given the tests that start processes or threads (among them the acceptance and unit tests of specs 131, 167 and 171), when the whole `cplat` suite runs 10 times in a row under `-n auto` and once with every spawned fake process slowed by 2 seconds, then every run passes. No test waits for a process or thread by a fixed sleep: each one waits for an event or a file with a timeout, and time-dependent behaviour runs on a fake clock.
- **AC-178.6** Given a test in the `cplat` suite that waits for a process, a thread or a time limit with a real sleep, when the repository checks run (`devbox run quality` and CI), then they fail with one line per occurrence naming the test file, the line and the fix (wait for an event or a file, or use the fake clock). A sleep inside a fake program that stands in for a slow process is allowed only with a marker on that line giving the reason.

The seam test.

- **AC-178.7** Given a temporary clone with a bare origin, a fake `claude` program that follows a script, a fake `gh` program backed by that origin, and no network, when the integration test runs `cplat headless "/component:ship <spec>"` from preflight to land, then the run exits 0, its run record is `done`, and the unit's commits are on the origin's `main`. The script issues the unit's real `cplat` and git commands, and the fake `claude` calls the configured hooks the way Claude Code does. The test runs in the platform's CI on every pull request and takes at most 120 seconds.
- **AC-178.8** Given the seam test of AC-178.7, when each of these seams is broken, then a variant of the test fails naming it:
  - a `CPLAT_*` variable of the outer run reaches the test command the unit runs;
  - the repo's committed allowlist lacks a rule the preflight requires: the run must exit 1 with `preflight failed: no-repo-allowlist:` and start no session (AC-171.1);
  - a session ends after a local commit and the ship is resumed: the commit must be pushed before checks are judged (AC-171.5);
  - the session stops while its `cplat pr wait` runs: the Stop hook must block the stop without counting it as a stop without progress (AC-171.8).

## Non-goals

- Any new user-visible feature, or a change of the landing rules of ADR-092 beyond the release mode and the waits of AC-178.2 and AC-178.3.
- Rebuilding a release branch on top of a moved `main` automatically, rebasing or force-pushing any branch.
- A seam test with a real model, real GitHub or the network, and replacing the journeys: they still run.
- Making every test in the repository deterministic. This spec covers the `cplat` tests that start processes or threads or depend on time; the e2e cluster test is out.
- A merge lock across machines (spec 167 Non-goals).

## Assumptions

- **A1** A release whose branch is behind `main` stops and tells the person to close the PR, delete the branch and start again, without rebuilding the branch itself (other option: the rerun cuts a new release branch from `main` and replaces the old one automatically; affects AC-178.1).
- **A2** Release is the only command that does not allow catch-up. `cplat spec land` and the dispatcher's land catch up like `ship land` and `pr wait --merge` (other option: `spec land` refuses catch-up as well; affects AC-178.4).
- **A3** At most 3 refused merges per land before it stops, the same bound as the regeneration rounds of AC-171.6 (other option: bounded only by the wait timeouts; affects AC-178.3).
- **A4** The stress gate is 10 consecutive `-n auto` runs plus one run with fake processes slowed by 2 s. It is run while building this spec, not on every pull request; the repository check of AC-178.6 keeps the result (other option: a nightly stress job in CI; affects AC-178.5).
- **A5** Fixed sleeps are found by a repository check, with a marked exemption only inside fake programs that stand in for slow processes (other option: review only, no check; affects AC-178.6).
- **A6** The seam test uses a fake `gh` backed by the bare origin (PRs, checks and merges are simulated locally) and a fake `claude` that runs the configured hooks, so it needs no network and no token (other option: a recorded GitHub API; affects AC-178.7, AC-178.8).
- **A7** The seam test runs in the regular pytest job on every pull request, within 120 seconds (other option: a separate CI job, or only on the e2e runner; affects AC-178.7).

## Open questions

None.

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
- 2026-11-10 building
- 2026-11-11 done
