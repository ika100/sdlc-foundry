---
spec_id: 095-fixable-critical-cves-are-patched
title: Fixable dependency CVEs are patched without asking
status: draft
priority: P1
---

# 095 — Fixable dependency CVEs are patched without asking

## Problem

Today, when a dependency finding turns the security gate red, `/svc:build` and `/svc:ship` stop and wait for the user (build Phase 3, the security agent's "CRITICAL findings block release"). That happens even when the advisory names a fixed version. Every template's gate turns red on HIGH findings as well as CRITICAL ones (pip-audit on any finding, `pnpm audit --audit-level high`, OWASP at CVSS 7, trivy at HIGH). The fix is then almost always the same mechanical step: bump the package and re-run the gates. The user has decided this step needs no human (round decision 6, widened on 2026-10-23 to every fixable finding that turns the gate red). The unattended run should take this step itself. It should stop only where there is a real decision: no fix exists, or the fix breaks the code. This spec depends on spec 087 to record what was patched.

## Stories

As a maintainer shipping a spec unattended, I want a dependency CVE with a released fix to be patched inside the run, so that the run reaches dev without waiting for me on a mechanical bump.

As a maintainer reading the PR, I want every automatic bump listed with its advisory, its versions and whether it crosses a major version, so that I can see what changed and why without reading the diff.

As the platform owner, I want each automatic patch recorded, so that the weekly retro (spec 090) can see how often runs patch, what fails and which packages recur.

## Acceptance criteria

- ~~**AC-095.1**~~ withdrawn 2026-10-23: limited to CRITICAL findings; replaced by AC-095.12 (every finding that turns the gate red).
- **AC-095.2** Given the vulnerable package is only a transitive dependency, when it is patched, then the resolved version in the lock file moves to the fixed version, and the repo's declared dependencies change only where the shape cannot force the version otherwise (an override or constraint for that one package).
- **AC-095.3** Given every template named in AC-095.12, when a repo is generated from it, then it has a devbox recipe that bumps one named dependency to a given version and updates the lock file; given a package the repo does not depend on, the recipe exits non-zero naming the package and changes no file.
- **AC-095.4** Given a patch that leaves the CI gate green, when the run continues, then the bump is its own commit `fix(deps): bump <package> <from> -> <to> (<advisory id>)` on the run's branch, and the PR body and the run's final report list each bump as package, from version, to version, advisory id and severity.
- ~~**AC-095.5**~~ withdrawn 2026-10-23: limited to CRITICAL findings; replaced by AC-095.13.
- **AC-095.6** Given a bump after which any gate (quality, tests, security) is red, when the run handles it, then the bump is reverted so the dependency files equal their state before the bump, no acceptance test is edited, and the run escalates naming the package, the attempted version and the failing gate with its failing test names or log tail.
- ~~**AC-095.7**~~ withdrawn 2026-10-23: limited to CRITICAL findings; replaced by AC-095.14.
- ~~**AC-095.8**~~ withdrawn 2026-10-23: limited to CRITICAL findings; replaced by AC-095.15.
- ~~**AC-095.9**~~ withdrawn 2026-10-23: severity no longer selects what is patched; the gate's own threshold does (AC-095.12).
- ~~**AC-095.10**~~ withdrawn 2026-10-23: HIGH findings are now patched; replaced by AC-095.16.
- **AC-095.11** Given a run record store is configured (spec 087), when the run attempts a patch, then the run record's `patches` section holds one entry per package with package, from version, attempted version, advisory id, severity, whether it is a major bump, and outcome (`patched`, `no-fix`, `reverted`); without a store the patch proceeds and nothing blocks (spec 087's rule).
- **AC-095.12** Given a `/svc:build` or `/svc:ship` run of a service-python, library-python, service-java, service-go or web-nextjs repo, when the security gate is red because of a dependency finding whose advisory names a fixed version (of any severity the gate fails on, HIGH and CRITICAL included), the run handles the red gate as follows. It bumps that dependency to the lowest fixed version through the repo's devbox recipe, runs the full CI gate (`devbox run ci`) again and continues without asking the user.
- **AC-095.13** Given a dependency finding that turns the security gate red and whose advisory names no fixed version, when the run handles the red gate, then no dependency file changes and the run escalates (`cplat ship escalate` in a ship run) with a reason naming the package, the installed version, the advisory id and "no fix released".
- **AC-095.14** Given a patch made the security gate green for one package but another fixable finding still keeps the gate red, when the run handles it, then it patches again. A run makes at most 2 patch rounds in total. If a third round would be needed, the run escalates listing the findings still open.
- **AC-095.15** Given a ship run in phase `land`, when its PR security check turns red on a fixable dependency finding (an advisory published after the build), then the run patches as in AC-095.12, pushes and waits again. The round counts toward the existing limit of 3 red CI rounds.
- **AC-095.16** Given findings that do not turn the security gate red (the image scan report, findings below the gate's threshold), or base-image OS package findings, or a gitops-app repo, when the security gate runs, then nothing is bumped and the reporting is unchanged: unfixed base-image findings are summarised (spec 059), and gitops-app repos never bump anything.
- **AC-095.17** Given the lowest fixed version is in a higher major version than the installed one, when the bump leaves every gate green, then the run keeps it and continues. The PR body and the final report mark that bump "major bump". If any gate turns red, AC-095.6 applies.

## Non-goals

- Repos at rest: no scheduled or fleet-wide audit that opens patch PRs outside a run. This is a follow-up spec, to come after spec 096.
- Changing or bumping base images to fix OS package findings (spec 059 keeps them tracked, not fixed).
- `/svc:release` and `/shared:check-quality`: release still stops on a red security gate, and check-quality stays read-only.
- Secrets findings and bandit findings: they keep stopping the run as today.
- Upgrading dependencies that have no finding.

## Open questions

- ~~Should fixable HIGH findings be patched the same way?~~ Answered: yes, every fixable finding that turns the gate red, same limits; see AC-095.12 to AC-095.16.
- ~~May an automatic bump cross a major version?~~ Answered: yes when every gate stays green, marked "major bump"; see AC-095.17 and AC-095.11.
- ~~Should repos at rest also be patched?~~ Answered: a follow-up spec, not here; see Non-goals.
- ~~Confirm: CRITICAL for scanners without a severity means CVSS 9.0 or higher.~~ Answered: accepted, then made moot by patching every gate-red finding; AC-095.9 withdrawn.
- ~~Confirm: at most 2 patch rounds per run.~~ Answered: yes; see AC-095.14.
- ~~Confirm: the commit message format.~~ Answered: yes; see AC-095.4.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended with the user's answers: scope widened from CRITICAL to every fixable finding that turns the security gate red (title updated; AC-095.1, .5, .7, .8, .9, .10 withdrawn; AC-095.12 to .16 added); major bumps allowed and marked (AC-095.17); patches recorded in the run record's `patches` section (AC-095.11 clarified); repos at rest moved to a follow-up spec.
