---
spec_id: 096-platform-updates-roll-out-to-every-repo
title: Platform updates roll out to every repo
status: done
priority: P1
---

# 096 — Platform updates roll out to every repo

## Problem

Every platform release has to be pulled into each repo built from it by hand: someone runs `/shared:update-service` in each repo, pushes, opens a PR, waits for CI and merges. Nobody does this regularly, so repos drift. Spec 083 only made the drift visible in `/shared:status` (stock-manager-gitops still had triggers from before #104 and a baseline from before #103). Most updates are routine and should land without anyone involved. A human should only look when the update would discard something the repo changed itself, when it conflicts, or when CI is red. This spec depends on 086, so that repo gates stay intact through an update, and on 087, so that each fleet run is recorded.

## Stories

As the platform owner, I want one command that brings every repo built from the platform up to the current release, so that fixes reach all repos without my doing each one by hand.

As the platform owner, I want routine updates to merge on their own when CI is green, and only the risky ones left for me with the reason stated, so that I look at the exceptions and nothing else.

As a repo owner, I want a fleet update never to merge a change that throws away a local customisation, so that what my repo added survives the autopilot.

## Acceptance criteria

- **AC-096.1** Given the configured repo owners (by default the account `gh` is authenticated as), when `cplat fleet update` (also available as `/shared:fleet`) runs, then it considers every non-archived repo of those owners that has a `.platform-version` stamp and `.copier-answers.yml` pointing at a platform template. Repos without these are not touched and do not appear in the report.
- **AC-096.2** Given a target platform version (by default the installed one, or `--ref <tag>`), when a repo's stamp is equal to or newer than it, then the repo is reported as `up to date` and no branch or PR is created.
- **AC-096.3** Given a repo that is behind, when the fleet update processes it, then the result equals what `/shared:update-service` produces for that repo (same branch naming, same commit, same rules for project-owned and repo-owned files). The branch is pushed and one PR is opened. The PR body contains the update report: from and to version, changed files, kept and replaced `devbox.json` entries, and the changelog range.
- ~~**AC-096.4**~~ withdrawn 2026-10-23: "routine" is now defined by spec 086's list of replaced or dropped customisations, see AC-096.15.
- ~~**AC-096.5**~~ withdrawn 2026-10-23: replaced by AC-096.16, which uses spec 086's list.
- **AC-096.6** Given a PR whose CI ends red (after the transient-failure rerun of spec 079), or that has a merge conflict, or that has no CI check at all, when the fleet update finishes waiting, then the PR is left open with the label `platform-update: needs review` and a comment giving the reason (`red CI: <check>`, `merge conflict` or `no CI checks`). The report shows the repo as `left open` with that reason.
- **AC-096.7** Given an update from one major platform version to the next, when the fleet update processes the repo, then the PR is opened but never merged automatically. Its comment points to the migration notes in the platform CHANGELOG for that major version.
- **AC-096.8** Given a repo that already has an open fleet-update PR from an earlier run, when the fleet update runs again, then it updates that PR to the new target instead of opening a second one. The PR keeps its label if it already had one.
- **AC-096.9** Given a repo where the update itself fails (clone denied, `.copier-answers.yml` unreadable, a template step errors), when the fleet update processes it, then that repo is reported as `failed: <reason>` with the error's first line. The remaining repos are still processed.
- **AC-096.10** Given `cplat fleet update --dry-run`, when it runs, then it lists each repo it would consider with its current and target version and its expected outcome (`up to date`, `would update` or `skipped: <reason>`). It pushes nothing and opens, comments on or merges no PR.
- **AC-096.11** Given a finished fleet update, when it reports, then it prints one row per repo (repo, from version, to version, outcome, PR link) and a count per outcome. It exits 0 when every repo is `up to date` or `merged`, and 1 when any repo is `left open` or `failed`.
- **AC-096.12** Given a fleet update and a configured run store (spec 087), when it finishes, then one run record with `kind` `fleet` holds the target version and each repo's outcome and reason. An unreachable run store does not change the outcome or the exit code.
- **AC-096.13** Given `--only <repo>` (repeatable), when the fleet update runs, then it processes only the named repos. A named repo that is not built from the platform is reported as `skipped: not a platform repo`.
- **AC-096.14** Given a repo update that lists follow-up steps the update cannot do itself (for example a secret to set for the pin-dev workflow, spec 062, or template answers that took their defaults), when the fleet update reports, then it relays those steps under that repo's row, whether or not the PR was merged.
- **AC-096.15** Given a repo that is behind, when its update is routine (spec 086's update report lists no replaced or dropped repo customisations (AC-086.13), the major version is unchanged, the PR has no merge conflict and CI on the PR is green), then the fleet update waits for CI the way `cplat pr wait --merge` does and squash-merges the PR. The report shows the repo as `merged`.
- **AC-096.16** Given an update whose spec-086 report lists at least one replaced or dropped repo customisation, when the fleet update processes it, then it opens the PR but does not merge it. The PR gets the label `platform-update: needs review` and a comment naming each listed customisation. The report shows the repo as `left open: local customisation` with the PR link.
- **AC-096.17** Given several repos to process, when the fleet update runs, then it handles them one at a time in alphabetical order of `owner/name`. It finishes each repo, including its CI wait, before starting the next. There is no overall time limit beyond each PR's own CI wait.

## Non-goals

- Running the fleet update on a schedule or automatically after a platform release. It runs only when someone starts it, and runs unattended once started.
- Filing an issue for a PR left open. The labelled open PR and the report row are the work item.
- The v1 to v2 migration (`--migrate`). A fleet update never deletes `k8s/` and never passes template answer changes (`--data`).
- Resolving merge conflicts or restoring local customisations automatically. Those PRs are left for a human.
- Filing issues for platform failures found during the fleet update. Spec 088 covers that once a run records the failure.
- Deciding which files a repo owns. Spec 086 defines the repo-owned companions, and this spec relies on the update never touching them.
- Updating repos outside the configured owners, or forks.

## Open questions

- ~~Which repos make up the fleet?~~ Answered: every stamped repo of the configured owners, which by default is the authenticated `gh` account; see AC-096.1.
- ~~Should the fleet update run by itself or only on demand?~~ Answered: on demand only, unattended once started; see Non-goals.
- ~~Should a PR left open also file an issue?~~ Answered: no; see Non-goals.
- ~~Confirm: a major-version update is never merged automatically.~~ Answered: yes; see AC-096.7.
- ~~Confirm: a PR with no CI checks is never merged automatically.~~ Answered: yes; see AC-096.6.
- ~~Confirm: the label `platform-update: needs review`, and squash-merge.~~ Answered: yes; see AC-096.6, AC-096.15, AC-096.16.
- ~~Confirm: one repo at a time, alphabetical order, no overall time limit.~~ Answered: yes; see AC-096.17.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended with the user's answers: on demand only and no issue for open PRs; AC-096.4 and AC-096.5 withdrawn for AC-096.15 and AC-096.16 (merge only when spec 086's list of replaced or dropped customisations is empty); one repo at a time (AC-096.17); run record kind `fleet` (AC-096.12).
- 2026-10-23 approved
- 2026-10-24 building
- 2026-10-24 done
