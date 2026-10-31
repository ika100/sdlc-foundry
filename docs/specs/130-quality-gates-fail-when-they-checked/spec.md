---
spec_id: 130-quality-gates-fail-when-they-checked
title: Quality gates fail when they checked nothing
status: draft
priority: P1
shape: platform
tracks: [285]
---

# 130 — Quality gates fail when they checked nothing

## Problem

A quality gate that ran but checked nothing reports green, and everyone downstream (CI, `/component:build`, `/component:ship`, the reviewer) reads that green as "verified". It happened in cluster-gitops: `validate` passed while kubeconform checked 0 resources (#260, #266), which #278 fixed for that one recipe only. The same hole exists across the templates: test runners that collect or run 0 tests, kustomize/kubeconform loops over an empty build in gitops-app, render checks that compare no files, and secrets scans whose file list is empty. Every generated repo inherits the hole, so it has to be closed in every template at once and kept closed by a platform test (#285).

## Stories

As a developer in a generated repo, I want `devbox run test` to turn red when no test ran, so that a green gate always means something was checked.

As a platform operator, I want the gitops `validate` and render checks to fail on an empty build, so that a broken overlay cannot pass as valid manifests.

As a platform maintainer, I want a platform test that runs every covered gate of every template against empty input, so that a new template or a changed recipe cannot reintroduce a silent pass.

## Acceptance criteria

- **AC-130.1** Given any covered gate (`test`, `test-fast`, `validate`, `render-check`, `secrets-scan`) in any of the 7 templates, when it checked nothing, then it exits non-zero and prints one line to stderr of the form `<gate>: checked nothing: <what was empty> - <how to fix>`, where `<what was empty>` is one of `0 tests ran`, `0 resources`, `0 files compared`, `0 files to scan`.
- **AC-130.2** Given a service-python or library-python repo whose tests directory collects 0 tests, when `devbox run test` or `devbox run test-fast` runs, then the recipe exits non-zero (pytest's "no tests collected" status is passed through, not swallowed) and prints the AC-130.1 line with `0 tests ran` and the fix "add at least one test".
- **AC-130.3** Given a service-go repo whose packages contain no test functions (with or without `_test` files), when `devbox run test` or `devbox run test-fast` runs, then the recipe exits non-zero with the AC-130.1 line `0 tests ran`.
- **AC-130.4** Given a service-java repo with no test classes, or test classes without test methods, when `devbox run test` or `devbox run test-fast` runs, then the build fails with the AC-130.1 line `0 tests ran`; neither recipe passes `-DskipTests` or otherwise skips the test phase.
- **AC-130.5** Given a web-nextjs repo with no test files, when `devbox run test` or `devbox run test-fast` runs, then the recipe exits non-zero with the AC-130.1 line `0 tests ran`, and neither the test scripts nor the test runner configuration shipped by the template contain `--passWithNoTests` or its config equivalent.
- **AC-130.6** Given any test-running template (service-python, library-python, service-go, service-java, web-nextjs) where every collected test was skipped, when `devbox run test` or `devbox run test-fast` runs, then it fails like AC-130.2 to AC-130.5: skipped tests do not count as tests that ran.
- **AC-130.7** Given a gitops-app repo whose kustomize builds and kubeconform checks together cover 0 resources (no overlay or addon builds anything, or every matched file is empty), when `devbox run validate` (and therefore `devbox run test`) runs, then it exits non-zero with the AC-130.1 line `0 resources` and the fix "run `devbox run render` and check that the system has components".
- **AC-130.8** Given a cluster-gitops repo whose cluster build is empty, when `devbox run validate` (and therefore `devbox run test`) runs, then it keeps failing as since #278 (non-zero exit, kubeconform's summary still printed) and also prints the AC-130.1 line with `0 resources`.
- **AC-130.9** Given a gitops-app or cluster-gitops repo, when `devbox run render-check` (and the `test-fast` recipe that runs it) compares 0 rendered files, then it exits non-zero with the AC-130.1 line `0 files compared` instead of "OK: up to date".
- **AC-130.10** Given any of the 7 templates where the file list handed to the secrets scanner is empty (after the template's exclusions), when `devbox run secrets-scan` (and therefore `security`) runs, then it exits non-zero with the AC-130.1 line `0 files to scan`.
- **AC-130.11** Given a covered gate that fails because it checked nothing, when the composite recipes `ci`, `quality` or `security` run it, then they exit non-zero too.
- **AC-130.12** Given a covered gate in any template, when its input is non-empty and valid, then it passes as before; a freshly rendered template with default answers passes its own `test`, `test-fast`, `validate`, `render-check` and `secrets-scan` (each template ships at least one test and non-empty files to scan and render).
- **AC-130.13** Given no setting, environment variable or recipe argument, when a covered gate checked nothing, then there is no way to make it pass (no opt-out).
- **AC-130.14** Given the platform test suite, when it runs, then for each of the 7 templates it renders the template, runs each covered gate of that template against empty input with stub tools on the path, and asserts a non-zero exit and the AC-130.1 line; a template in the shape registry without this coverage makes the suite fail.
- **AC-130.15** Given the contributing guide and the template authoring guide, when a contributor reads them, then each contains the rule "a gate that checked nothing fails" with a pointer to the platform test of AC-130.14.
- **AC-130.16** Given the 5.5.0 release, when a repo generated from an earlier release with 0 tests (or an empty build or file list) runs `/platform:update`, then its covered gate turns red with the AC-130.1 line, and the platform changelog lists the change under 5.5.0 as a behaviour change that names the symptom and the fix (add at least one test / make the build non-empty); the release is a minor, not a major.

## Non-goals

- Changing `lint`, `typecheck` or `audit`; they keep their current behaviour on empty input.
- An opt-out setting for repos that deliberately have no tests.
- Changing which tests a generated repo has, or adding tests to existing repos during `/platform:update`.
- Minimum test counts or coverage thresholds beyond "at least one test ran".

## Open questions

- ~~Confirm: the message line is `<gate>: checked nothing: <what was empty> - <how to fix>` on stderr, with the four "what was empty" phrases of AC-130.1.~~ Answered: yes, see AC-130.1.
- ~~Confirm: a run in which every collected test was skipped counts as "0 tests ran" and fails.~~ Answered: yes, see AC-130.6.
- ~~Confirm: `test-fast` follows the same rule as `test` in every template, including gitops-app and cluster-gitops where it is the render check.~~ Answered: yes, see AC-130.2 to AC-130.6 and AC-130.9.

## Changelog

- 2026-10-31 created
- 2026-10-31 amended: the three confirmations (message format, skip-only runs fail, `test-fast` follows `test`) answered yes and struck; AC-130.8 clarified so the cluster-gitops recipe keeps its #278 behaviour and kubeconform summary and adds the AC-130.1 line
