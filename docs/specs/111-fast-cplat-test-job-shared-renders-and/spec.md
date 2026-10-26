---
spec_id: 111-fast-cplat-test-job-shared-renders-and
title: 'Fast cplat test job: shared renders and sharding'
status: draft
priority: P1
---

# 111 — Fast cplat test job: shared renders and sharding

## Problem

The pull request CI of this repo takes 185 to 246 seconds. Almost all of that is one job, "cplat unit + integration tests", whose pytest step takes about 198 seconds for 2468 tests. Every other ci job finishes in under 30 seconds, except the template smoke jobs, which run in parallel and take up to 140 seconds. More than a third of the suite's test time is fixture setup (479 of 1360 seconds measured locally). Most of that is many tests each rendering the same template from scratch: a render takes about 1.2 seconds, while copying a repo that is already rendered takes about 0.04 seconds. The fleet tests already render once and copy per test. Every build and ship round waits for this job through `cplat pr wait`, so each extra minute is spent again on every pull request and every fix round. The goal is to bring pull request CI to about 2 minutes without dropping a single test or assertion.

## Stories

- As a platform developer, I want the cplat test job to finish in about half the time, so that pull requests and fix rounds wait less for green CI.
- As the platform owner, I want the same tests with the same assertions to run on every pull request, so that a faster CI never means a weaker one.
- As a platform developer, I want to keep running the whole suite locally with one command, as I do today, so that the speed-up in CI does not change how I work.
- As someone who merges pull requests, I want one aggregate result for the whole ci run, so that `cplat pr wait` and the merge rule keep working without change.

## Acceptance criteria

Coverage and isolation

- **AC-111.1** Given the suite before and after this change, when both are collected, then they contain the same test ids, apart from tests added or removed on purpose in the same pull request and named in its description. No test gets a new skip, xfail or deselection, and no assertion is removed or loosened.
- **AC-111.2** Given a test that receives a rendered repo (the gitops-app repo and every other template render used as a test fixture), when it changes, deletes, adds or commits files in that repo, then no other test sees the change: every test gets its own copy, and the shared render stays as rendered.
- **AC-111.3** Given the full suite, when it runs in reverse order, and when each test file runs on its own, then it passes in both cases. A test that passes only because another test ran first fails this criterion.
- **AC-111.4** Given a test whose subject is the render itself (what `cplat new-service` or `cplat new-service --gitops` produces from a template, or its failure modes), then it still renders from the template and does not get a shared copy.
- **AC-111.5** Given a template changed in the working tree, when the suite runs, then the tests see a render of the changed template. A shared render lasts for one test run and is never reused from an earlier run or cached between CI runs.
- **AC-111.6** Given a shared render that fails, when the tests that depend on it run, then each of them errors and shows the render's error message. None of them passes or is skipped.

Speed

- **AC-111.7** Given a full local run of `tests/cplat` with the same command and machine as the baseline, when its fixture setup times are added up, then the total is at most 50% of the baseline (479 seconds measured on 2026-10-26 on a 12-core machine). The before and after numbers are recorded in the pull request.
- **AC-111.8** Given each distinct template render a fixture needs (one template with one set of answers), when the full suite runs, then that render happens at most once per test worker process.
- **AC-111.9** Given pull requests that change code (so the cplat tests run) and do not touch the templates of the smoke jobs, when five of them run after this change ships, then the median wall time of the ci workflow, from its first job starting to `ci-success` finishing, is at most 120 seconds. Pull requests that change a smoke-tested template are bounded by their smoke jobs instead (up to 140 seconds today) and are not part of this target.

Sharding in CI

- **AC-111.10** Given a ci run that needs the cplat tests, when it runs, then the suite is split into 4 parallel jobs. Every collected test runs in exactly one of them, and the union of the shards equals the full suite. This is checked in every ci run that runs the shards, and a run in which a test ran in no shard, or in two, fails.
- **AC-111.11** Given a new test file or test added without any other change, when ci runs, then it lands in a shard automatically. Nobody has to maintain a list of files per shard.
- **AC-111.12** Given the 4 shards of one ci run, then the pytest step of the slowest shard takes at most 1.5 times as long as the average shard, and at most 75 seconds.
- **AC-111.13** Given a failing test in one shard, when ci runs, then the other shards still run to the end (a failure does not cancel them). The failing job's name says which shard it is, and its log names the failing test.
- **AC-111.14** Given any shard that fails or is cancelled, then `ci-success` fails. Given all shards passed, or all were skipped because the change touches no code, then `ci-success` treats the cplat tests as passed, as today. `ci-success` stays the single aggregate result of the ci workflow.

Local use

- **AC-111.15** Given a developer's checkout, when they run the suite as today (`pytest tests/cplat -n auto`, or without `-n` for a serial run), then every test runs in one unsharded run and passes. No new environment variable, flag or setup step is needed.

## Non-goals

- Choosing which tests a change needs, or skipping tests by diff. That belongs to spec 103, which applies only inside the build and ship loop and keeps the pull request's CI running everything (AC-103.8). This spec makes that full run faster and leaves its scope unchanged.
- Changing the templates, the files they render, or the tests of generated repos.
- Speeding up the e2e workflow, the template smoke jobs, CodeQL or the site build.
- Caching renders, dependencies or test results between CI runs.
- Self-hosted or bigger runners.
- Rewriting tests for reasons other than how they get their rendered repos.

## Open questions

- ~~How many parallel shards should the cplat tests use?~~ Answered: 4, see AC-111.10 and AC-111.12.
- ~~Confirm: the target is a median ci wall time of at most 120 seconds over five code pull requests that do not touch the smoke-job templates.~~ Answered: yes; template pull requests stay bounded by the smoke jobs, see AC-111.9.
- ~~Confirm: fixture setup in a full local run drops to at most 50% of the 479-second baseline.~~ Answered: yes, see AC-111.7.
- ~~Should the "every test runs in exactly one shard" check run in every ci run, or only once?~~ Answered: in every ci run, see AC-111.10.

## Changelog

- 2026-10-26 created
- 2026-10-26 amended: folded in the user's answers (4 shards, 120-second median target excluding template pull requests, 50% setup target, shard coverage check in every ci run).
