---
spec_id: 197-the-journey-13-seams
title: The journey 13 seams
status: done
priority: P1
shape: platform
---

# 197 — The journey 13 seams

## Problem

Journey 13 (2026-11-13, platform 5.21.0) found four places where an agent prompt and the `cplat` code behind it disagree.
The tester's acceptance-test commit is refused by the reviewed step, a deviation naming a task that `cplat plan merge`
folded away marks the run's agent metrics incomplete, the coordinator told the user Grafana needs a port-forward although
it answers through the Gateway, and the web release agent's documented version step fails on its own untracked
changelog. Each one costs a coordinator workaround or a wrong answer in every run that reaches it, and two of them
recurred from journey 11. A fifth finding: one hung acceptance test in the API repo ran until `cplat quiet`'s 9-minute
wall limit, about 9 of the journey's 112.6 minutes on the critical path, because generated repos have no per-test limit.

## Stories

As the build coordinator, I want `cplat component build reviewed` to find the tester's commit as the tester writes it,
so that I never reword a commit to get past the review step.

As the platform maintainer, I want a deviation naming a merged-away task to be counted, so that agent metrics stay
complete after `cplat plan merge`.

As a developer who turned on the dev Grafana stack, I want the command to tell me where Grafana answers, so that the
agent can hand me the link instead of guessing.

As a web repo maintainer, I want the release agent's version step to work as written, so that a release follow-up needs
no improvised fix.

As a coordinator running a generated repo's tests, I want a hung test to fail after a fixed limit and name itself, so
that one stuck test costs minutes, not the whole wall limit.

## Acceptance criteria

- **AC-197.1** Given a feature branch of spec `<NNN>-<slug>` whose acceptance-test commit subject is
  `test(<slug>): acceptance tests for AC-<NNN>.1–AC-<NNN>.<n>` (the tester's documented form, without the spec id), when
  `cplat component build reviewed <spec>` runs, then it writes the `reviewed acceptance tests for <spec id>` commit and
  exits 0; when the branch's only acceptance-test commit names another spec's criteria (`AC-<MMM>.`, `MMM` ≠ `NNN`) or
  neither the spec id nor any `AC-<NNN>.` id, then it exits 1 with the existing "no commit 'acceptance tests for …'" error
  and writes no commit.
- **AC-197.2** Given a run whose plan had task `t1` merged into `t2` by `cplat plan merge` (a `task-merge` event in the run
  record), when `cplat platform runs agent findings --cycle <n> --deviation t1` runs, then one `deviation` finding is
  recorded against `t2` with a note that it was named as `t1` (merged into `t2`), no "agent metric not recorded" warning is
  printed and the run's agent metrics are not marked incomplete; a chain of merges (`t1` into `t2`, `t2` into `t3`)
  resolves to `t3`; an id that is neither a plan task nor a merged-away task still prints the `malformed: deviation`
  warning and marks the metrics incomplete.
- **AC-197.3** Given a gitops-app environment whose host is local (ends in `.localhost`), when
  `cplat system set --env <env> --observability lgtm` runs (also with `--dry-run`), then its output contains a line
  `Grafana: http://grafana.localhost:<port>/` with the local Gateway port the platform already uses for that
  environment's component URLs, and `--json` carries the same URL as `grafana_url`; for a non-local environment the line
  says that Grafana answers only at `grafana.localhost` on that cluster's Gateway, and `grafana_url` is null; for
  `--observability none` or `off` no Grafana line is printed.
- **AC-197.4** Given a system with an environment whose `observability.ui` is `lgtm`, when `cplat system status` runs, then
  that environment's observability entry names the same Grafana location as AC-197.3 (in the table and as `grafana_url`
  in `--json`); environments without `ui: lgtm` show no Grafana location.
- **AC-197.5** Given a web-nextjs repo on a `release/vX.Y.Z` branch whose working tree holds the newly written, not yet
  committed `CHANGELOG.md` (untracked on a first release, modified otherwise), when the release agent's documented
  next-development-version step runs exactly as written, with the pnpm version the web template pins, then it exits 0,
  `package.json` reads `"version": "<NEXT_DEV>"`, and no git tag and no commit are created; a test proves this by running
  the step as documented in a scratch repository, not by matching the prompt's wording.
- **AC-197.6** Given a repo generated from the service-python, library-python or service-java template with one test that
  blocks forever (in its setup, body or teardown) next to passing tests, when `devbox run test-fast` or `devbox run test`
  runs, then the blocked test is reported failed after 120 seconds with its test id and the limit, the other tests still
  run and report, the run exits non-zero, and a suite without such a test reports exactly the same passes and exit code
  as before.
- **AC-197.7** Given a repo generated from the service-go template with one test that blocks forever, when
  `devbox run test-fast` or `devbox run test` runs, then the run of that test's package is stopped after 5 minutes, the
  output names the test that was running, and the run exits non-zero; a suite without such a test passes as before.
- **AC-197.8** Given an existing repo of one of those four templates generated before this spec, when `/platform:update`
  applies the new template version, then the limits of AC-197.6 and AC-197.7 apply to its test runs without the update
  changing any file the template marks as project-owned (such as `pyproject.toml`, `pom.xml`, `go.mod`); a repo that
  already sets its own per-test limit keeps it.

## Non-goals

- Changing the tester agents' commit subject, or the stricter checks of other steps that look for the acceptance-test
  commit (`cplat spec test-diff`, the build unit check).
- Recording deviations for tasks removed by a re-plan (only `cplat plan merge` is covered).
- A public or ingress-backed Grafana for non-local environments, Grafana credentials handling, or adding the URL to the
  gitops repo's `CLAUDE.md`.
- Changing the release agents of the other shapes.
- The web-nextjs template's test limit: its test runner already fails a test that runs past its default per-test timeout.
- Finding or killing stray processes a hung test leaves behind (such as a leftover database server), and sleep checks in
  generated repos' suites.

## Assumptions

- **A1** The reviewed step accepts the acceptance-test commit when its subject contains `acceptance tests for` and names
  either the spec id or a criterion id of this spec (`AC-<NNN>.`), the same rule for every shape's tester (other option:
  change the four tester prompts to put the spec id in the subject; affects AC-197.1).
- **A2** A merged-away task is recorded against the task it was merged into (resolving chains), with the original id kept
  as a note (other option: record it under its own id with the note; affects AC-197.2).
- **A3** The Grafana URL follows the rule the platform already uses for local component URLs (the same port source and
  default), and for non-local environments the output names no URL because the dev stack's route only answers
  `grafana.localhost` (other option: guess `https://grafana.<host suffix>`; affects AC-197.3, AC-197.4).
- **A4** The JSON field is `grafana_url` in both commands (other option: a nested `observability.url`; affects AC-197.3,
  AC-197.4).
- **A5** How the version step is fixed (a pnpm flag such as `--no-git-checks`, or setting the version before writing the
  changelog) is left to the plan; the changed prompt rule gets its rules-register entry and stays within the prompt byte
  budget (spec 168) (other option: move the step into a `cplat` command; affects AC-197.5).
- **A6** The AC-197.5 test runs pnpm the way the platform's web smoke run does and is skipped with a stated reason where
  pnpm cannot be fetched, rather than replaced by a wording check (other option: always run it in CI only; affects
  AC-197.5).
- **A7** The per-test limit for Python and Java is 120 seconds, as spec 185 set for the platform's own suite, and the same in
  `test-fast` and `test` (other option: a longer limit for `test`; affects AC-197.6).
- **A8** Go has no per-test limit in its test runner, so the limit applies per test package at 5 minutes, which stays below
  the 9-minute limit of `cplat quiet` (spec 185) (other option: 120 seconds per package; affects AC-197.7).
- **A9** The limit reaches existing repos through files the platform owns (the generated test commands or platform test
  hooks), because the build files are project-owned and `/platform:update` skips them; a repo's own limit wins (other
  option: tell each repo to edit its build file by hand; affects AC-197.8).
- **A10** This extends past spec 185's non-goal "per-test limits for generated repos" without changing any of its
  criteria, so nothing is replaced (other option: amend spec 185 instead; affects AC-197.6 to AC-197.8).

## Open questions

## Changelog

- 2026-11-13 created
- 2026-11-13 amended: J13-5, a hung test in a generated repo fails after a fixed limit (AC-197.6 to AC-197.8, A7 to A10)
- 2026-11-13 approved
- 2026-11-13 building
- 2026-11-13 done
