---
spec_id: 156-a-system-ship-benchmark
title: A system ship benchmark
status: done
priority: P1
shape: platform
tracks: [560]
---

# 156 — A system ship benchmark

## Problem

The benchmarks (spec 099, ADR-035, the eval gate of spec 151) cover one repo: quick-task, build, ship and fix-rounds on `ika100/todo-api`. Nothing measures a system ship across several repos, the step that took a third of journey 6. Journeys are the only multi-repo measurement, and they are a poor instrument for this:

- one journey takes about three hours and varies by about 30 minutes per part (network, CI, model), so a gain of 10 minutes cannot be told from noise in one run;
- every journey ships the same kind of system (a Python API and a Next.js web UI, one after the other), so tuning against journeys risks fitting the platform to that one scenario.

## Stories

As the platform maintainer, I want to measure a system ship on a fixed sample that differs from the journey system, as often as a change needs, so that I can tell whether a change makes system ships faster or cheaper in general, and by how much, before running a journey.

## Acceptance criteria

- **AC-156.1** Given `cplat platform runs benchmark system-ship [--plugins DIR] [--reset-first] [--repeat N]`, when it runs, then it ships a fixed system spec with `/system:ship` through `cplat headless` on a fixed sample system: a gitops repo and three components of different shapes or languages. Each run is recorded as a run of kind `benchmark` with its usage, and every sample repo is reset to its fixed revision afterwards (open PRs closed, branches and tags created by the run removed), as the single-repo benchmarks do.
- **AC-156.2** Given the sample system spec, when it is planned, then its plan has at least one pair of repos that do not depend on each other and at least one repo that depends on another. The benchmark therefore measures both concurrency and ordering. The spec and the plan are pinned in the benchmark's task file, so every run builds the same work.
- **AC-156.3** Given a benchmark system ship, when it runs, then it stops after every component repo's PR has merged on green checks and before `land` (no cluster needed). It does this through `cplat system ship start --until repos`, which ends the run done at that point.
- **AC-156.4** Given a finished benchmark run, when it is reported, then the record and the output give, per repo: wall clock, agent time, tokens, sessions, criteria and coders run concurrently. For the whole run they give: wall clock, total tokens, cost and an overlap figure (the sum of the repos' wall clocks divided by the run's wall clock; 1.0 means fully sequential).
- **AC-156.5** Given `--repeat N` with N > 1, or earlier records for the same task version, when the report prints, then it shows the median and the spread (lowest to highest) of wall clock and tokens per plugins tree. A comparison between two trees says "within the spread" when their medians differ by less than the larger spread. One run is never presented as a gain.
- **AC-156.6** Given the sample system and its spec, when they are chosen, then they differ from the journey's system in domain, in component shapes, and in the order of the repos in the plan. The benchmark's README states that changes are judged on this benchmark and the single-repo ones, and that a journey only confirms a result.
- **AC-156.7** Given the eval gate (spec 151), when this benchmark exists, then the gate does not require it: it is report-only, run on demand and before a journey, because one run costs about an hour. The release checklist names it for a release that changes the system ship.

## Non-goals

- Measuring `land`, deploys, promotions or anything on a cluster: they wait on CI, Argo CD and the cluster, not on agents, and the journey covers them.
- A required release gate for system ships (AC-156.7).
- Replacing the journeys: they stay the end-to-end check of the person's experience.

## Open questions

- ~~Where should the sample system live?~~ Answered (recommended, approved 2026-11-08): four new private repos under `ika100`: `bench-sys-gitops`, `bench-sys-api` (Python service), `bench-sys-worker` (Go service) and `bench-sys-web` (Next.js), created once with `/system:new` from a manifest kept in `scripts/cplat/benchmark/`. Creating the repos is the one outward-facing step, and it is done once.
- ~~What should the sample spec be?~~ Answered (recommended, approved 2026-11-08): a small feature in a domain unlike the journey's task board, for example "labels on stored files". The API adds the label model and endpoints. The worker and the web UI each consume the API contract and do not depend on each other. About 3 to 6 criteria per repo.
- ~~How many runs to judge a change?~~ Answered (recommended, approved 2026-11-08): `--repeat 3` for a round's before and after, `--repeat 1` for a quick check; the report's spread rule (AC-156.5) decides.

## Changelog

- 2026-11-08 drafted with spec 155, so that its effect can be measured without fitting to the journey; approved as recommended on 2026-11-08.
- 2026-11-09 building
- 2026-11-09 done
