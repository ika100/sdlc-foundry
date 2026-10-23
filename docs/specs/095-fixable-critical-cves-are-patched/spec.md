---
spec_id: 095-fixable-critical-cves-are-patched
title: Fixable critical CVEs are patched without asking
status: draft
priority: P1
---

# 095 — Fixable critical CVEs are patched without asking

## Problem

Today a CRITICAL dependency finding stops `/svc:build` and `/svc:ship` and waits for the user (build Phase 3, the security agent's "CRITICAL findings block release"), even when the advisory names a fixed version. The fix is then almost always the same mechanical step: bump the package, re-run the gates. The user has decided this step needs no human (round decision 6). The unattended run should take it itself and stop only where there is a real decision: no fix exists, or the fix breaks the code. It depends on spec 087 for recording what was patched.

## Stories

As a maintainer shipping a spec unattended, I want a CRITICAL CVE with a released fix to be patched inside the run, so that the run reaches dev without waiting for me on a mechanical bump.

As a maintainer reading the PR, I want every automatic bump listed with its advisory and versions, so that I can see what changed and why without reading the diff.

As the platform owner, I want each automatic patch recorded, so that the weekly retro (spec 090) can see how often runs patch, what fails and which packages recur.

## Acceptance criteria

- **AC-095.1** Given a `/svc:build` or `/svc:ship` run of a service-python, library-python, service-java, service-go or web-nextjs repo whose security gate is red because of a CRITICAL dependency finding whose advisory names a fixed version, when the run handles the red gate, then it bumps that dependency to the lowest fixed version through the repo's devbox recipe, runs the full CI gate (`devbox run ci`) again and continues without asking the user.
- **AC-095.2** Given the vulnerable package is only a transitive dependency, when it is patched, then the resolved version in the lock file moves to the fixed version, and the repo's declared dependencies change only where the shape cannot force the version otherwise (an override or constraint for that one package).
- **AC-095.3** Given every template named in AC-095.1, when a repo is generated from it, then it has a devbox recipe that bumps one named dependency to a given version and updates the lock file; given a package the repo does not depend on, the recipe exits non-zero naming the package and changes no file.
- **AC-095.4** Given a patch that leaves the CI gate green, when the run continues, then the bump is its own commit `fix(deps): bump <package> <from> -> <to> (<advisory id>)` on the run's branch, and the PR body and the run's final report list each bump as package, from version, to version, advisory id and severity.
- **AC-095.5** Given a CRITICAL finding whose advisory names no fixed version, when the run handles the red gate, then no dependency file changes and the run escalates (`cplat ship escalate` in a ship run) with a reason naming the package, the installed version, the advisory id and "no fix released".
- **AC-095.6** Given a bump after which any gate (quality, tests, security) is red, when the run handles it, then the bump is reverted so the dependency files equal their state before the bump, no acceptance test is edited, and the run escalates naming the package, the attempted version and the failing gate with its failing test names or log tail.
- **AC-095.7** Given a patch that made the security gate green for that package but a further fixable CRITICAL finding appears, when the run handles it, then it patches again, at most 2 patch rounds per run in total; a third round needed → the run escalates listing the findings still open.
- **AC-095.8** Given a ship run in phase `land` whose PR security check turns red on a fixable CRITICAL finding (an advisory published after the build), when the run handles the red check, then it patches as in AC-095.1, pushes and waits again, and the round counts toward the existing limit of 3 red CI rounds.
- **AC-095.9** Given a finding reported by a scanner that prints no severity, when the run classifies it, then it counts as CRITICAL when its advisory has a CVSS base score of 9.0 or higher or is rated critical; a finding whose severity cannot be determined is not patched automatically and is handled as today.
- **AC-095.10** Given HIGH findings, base-image OS package findings, or a gitops-app repo, when the security gate runs, then the behaviour is unchanged: HIGH documented, unfixed base-image findings summarised (spec 059), gitops-app repos never bump anything.
- **AC-095.11** Given a run record store is configured (spec 087), when the run attempts a patch, then the run's record holds one patch event per package with package, from version, attempted version, advisory id, severity and outcome (`patched`, `no-fix`, `reverted`); without a store the patch proceeds and nothing blocks (spec 087's rule).

## Non-goals

- Repos at rest: no scheduled or fleet-wide audit that opens patch PRs outside a run (see open questions; proposed as a follow-up spec).
- Changing or bumping base images to fix OS package findings (spec 059 keeps them tracked, not fixed).
- `/svc:release` and `/shared:check-quality`: release still stops on a red security gate; check-quality stays read-only.
- Secrets findings and bandit findings: they keep stopping the run as today.
- Upgrading dependencies that have no finding.

## Open questions

- Should fixable HIGH findings be patched the same way? Every template's security gate already turns red on them (pip-audit on any finding, `pnpm audit --audit-level high`, OWASP at CVSS 7, trivy at HIGH), so today they stop the run just like CRITICAL. (suggested: yes, every fixable finding that turns the gate red, same limits; affects AC-095.1, AC-095.9, AC-095.10)
- May an automatic bump cross a major version when the lowest fixed version is in a new major? (suggested: yes when every gate stays green, and the PR body and report mark it "major bump"; affects AC-095.1, AC-095.4)
- Should repos at rest also be patched, by a weekly scheduled audit on the self-hosted runner that opens a patch PR per repo (or as part of the fleet update in spec 096)? (suggested: not in this spec; a follow-up spec after 096; affects Non-goals)
- Confirm: CRITICAL for scanners without a severity means CVSS base score 9.0 or higher, unknown severity is not patched (AC-095.9).
- Confirm: at most 2 patch rounds per run before escalating (AC-095.7).
- Confirm: the commit message format `fix(deps): bump <package> <from> -> <to> (<advisory id>)` (AC-095.4).

## Changelog

- 2026-10-23 created
