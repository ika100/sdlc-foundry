---
spec_id: 223-change-quality-fix-causes-and-attempts
title: 'Change quality: fix causes and attempts to done'
status: draft
priority: P1
shape: platform
tracks: [1099]
---

# 223 — Change quality: fix causes and attempts to done

## Problem

The platform maintainer cannot say how often a release breaks something or how many tries a delivery takes (#1099). The 90-day run store shows 37% of unattended ships done, 59% of the spend in escalated or failed runs, and about $10 per delivered ship against a $0.69 median ship run; 38% of commits are fixes and 10 of 24 minor releases since 5.7 needed a patch. But no fix names the change that caused it, so there is no change-failure rate per release and no blast radius: patch releases, stopped journeys and downstream repos that ran the broken version. And `cplat platform runs report` counts runs one by one, so it never shows that one spec took four runs and three escalations before it was done, or what the whole chain cost compared with the one run that succeeded. Without these two numbers, a change that makes delivery more reliable cannot be told apart from one that only moves the cost.

## Stories

- As the platform maintainer, I want every fix entry to name what caused it, so that `cplat` can report which releases broke something and how far the damage reached.
- As the platform maintainer, I want the runs report to group the runs of one spec or issue into a chain and show the attempts and the cost of the whole chain, so that I can see what a delivered item really costs.

**Repos:** sdlc-foundry (the platform repo; its changelog, its journeys and the run store it reports on).

## Acceptance criteria

Words used below. A **fix entry** is a changelog entry in a `fixed` fragment or under `### Fixed` in a released section of `docs/CHANGELOG.md`. Its **cause line** is its last line, `Caused by: <cause>`, where `<cause>` is one or more PR numbers (`#812` or `#812, #815`), a released version (`v5.23.0`), `none` (the defect is not from a platform change, for example an upstream tool) or `unknown`. A release **caused** a fix entry when the entry names that version, or names a PR whose merge commit is first contained in that release's tag. A **chain** is the set of run records of kinds `ship`, `product-ship`, `build` and `fix` with the same repo and the same spec, or the same issue when the record has no spec; an **attempt** is a record of a chain whose `parent` is not another record of the same chain.

Fix causes.

- **AC-223.1** Given a branch that adds a `fixed` fragment without a cause line, or with a cause line whose `<cause>` is not of the forms above, when `cplat platform pr-check` or the CI fragment check runs, then it fails with one `ERROR:` line naming the fragment and the expected form `Caused by: #<PR> | v<X.Y.Z> | none | unknown`; an `added` or `changed` fragment needs no cause line, and fragments already released are never checked.
- **AC-223.2** Given a `fixed` fragment whose cause line names `#812`, when pr-check runs and GitHub is reachable, then it fails with an `ERROR:` line if #812 is not a merged PR of the platform repo; given `v9.9.9`, then it fails if no tag `v9.9.9` exists; given GitHub unreachable, then it prints one `WARNING:` line that the PR was not checked and does not fail for it.
- **AC-223.3** Given a fixed fragment ending in `Caused by: #812`, when `cplat platform release` assembles it, then the released entry under `### Fixed` keeps the cause line unchanged, so the cause stays readable after the fragment is deleted.
- **AC-223.4** Given released sections 5.30.0, 5.30.1 and 5.31.0 where two fix entries of 5.30.1 name PRs released in 5.30.0, one fix entry of 5.31.0 names a PR merged after 5.30.1 and before 5.31.0, and one names no cause line, when `cplat platform change-quality --since v5.30.0` runs, then it prints one row per release with the fix entries it caused and the releases that carried them (5.30.0: 2, carried by 5.30.1), counts the fix whose cause PR was in the same release as `caught before release` (not a failure of any release), counts the entry without a cause line or with `unknown` as `unattributed: 1`, and prints `change-failure rate: 1 of 3 releases (33%)` plus the same rate over minor and major releases only; `none` causes are listed apart and count for no release.
- **AC-223.5** Given a release that caused fix entries, when change-quality reports it, then its row also shows the blast radius: the patch releases that carried those fixes, the journeys in `docs/PERFORMANCE.md` marked stopped whose linked issue or PR is one of those entries' numbers (`(#NNN)` or the fragment id), and the downstream repos of the fleet (the repos `cplat fleet update` considers) whose `.platform-version` stamp held a version from that release up to, not including, the first release carrying the fix; when the fleet cannot be read, the repo count is `unknown`, never 0.
- **AC-223.6** Given `cplat platform change-quality --json`, then the same results are printed as one JSON document with the keys `window`, `releases` (each with `version`, `caused`, `carried_by`, `stopped_journeys`, `affected_repos`), `caught_before_release`, `unattributed`, `none`, `change_failure_rate` and `change_failure_rate_minor`, and nothing else on standard output; outside the platform repo the command stops with an error that names the platform repo.

Attempts until done.

- **AC-223.7** Given run records of one repo's spec 131 in the report window: an escalated ship costing $4.00, an abandoned ship costing $1.50 and a done ship costing $2.00, in that order, when `cplat platform runs report` runs, then its `Chains:` section shows that chain with 3 attempts, 1 escalation, 1 abandon, 0 failed, `attempts to done: 3`, chain cost $7.50, successful run $2.00 and `spent outside the successful run: 73%`; a child record whose `parent` is in the chain adds its cost once and is no attempt.
- **AC-223.8** Given chains in the window, when the runs report runs, then the `Chains:` section also shows the number of chains done and not done, the median attempts to done, the chain cost per delivered item (the summed cost of the done chains divided by their number) next to the median cost of a successful run, and the spend of chains not done; with `--json` these are under the key `chains` (`items`, `done`, `open`, `median_attempts_to_done`, `cost_per_delivered`, `median_successful_cost`, `open_spend`), and the existing keys are unchanged.
- **AC-223.9** Given a chain with an attempt whose cost cannot be read, then its chain cost is shown as at least the known sum with `+unknown` and is left out of `cost_per_delivered`, never counted as $0; given a chain whose first record started before the window, then it is marked `partial`; given records of these kinds with neither spec nor issue, then they are counted as `unchained: <n>` and are in no chain.

## Non-goals

- Cause lines in generated (component) repos' changelogs or in issues; this spec covers the platform's own changelog.
- Backfilling causes for entries already released; a cause line added by hand to a released entry counts from then on (A4).
- Showing chains or change-failure rate in the weekly retro or its public issue: a follow-up once the numbers have been read for a few weeks.
- Reverting, blocking or holding a release because of its change-failure rate.
- Classifying why a fix was needed (missing test, environment, upstream); only the cause link is recorded.

## Assumptions

- **A1** The cause lives as the last line of the fix entry's text, `Caused by: …`, and so appears in the public changelog (other option: a hidden comment or a separate cause file the release deletes; affects AC-223.1, AC-223.3).
- **A2** Only `fixed` fragments need a cause line, and `unknown` is allowed so that the check never blocks a fix whose cause nobody found (other option: refuse `unknown`; affects AC-223.1, AC-223.4).
- **A3** pr-check verifies the named PR or tag only when GitHub is reachable, else it warns; the CI fragment check checks the form only (other option: fail when unreachable; affects AC-223.2).
- **A4** change-quality reads causes from `docs/CHANGELOG.md` and the fragments, so past entries count as `unattributed` until someone adds their cause line by hand (other option: a one-off backfill from commit messages; affects AC-223.4).
- **A5** The change-failure rate counts every release in the window and is also shown for minor and major releases only; a fix whose cause PR is in the same release is `caught before release`, not a failure (other option: count only minor releases; affects AC-223.4).
- **A6** The command is `cplat platform change-quality [--since v<X.Y.Z>] [--json]`, defaulting to the releases of the last 90 days (other option: a section of `runs report`; affects AC-223.4, AC-223.6).
- **A7** Affected downstream repos come from the history of each fleet repo's `.platform-version` stamp, read with the same owners and `gh` login as `cplat fleet update`; no new access (other option: only the current stamp; affects AC-223.5).
- **A8** A chain is keyed by repo plus spec, or repo plus issue when the record has no spec, like the person time per delivered item (spec 192); `headless`, `dispatch` and `pr-wait` records are not attempts because the ship records they drive already count (other option: count them as attempts; affects AC-223.7, AC-223.9).
- **A9** A chain belongs to the window when any of its records does; a chain begun before the window is `partial` and its earlier records are not fetched (other option: extend the window back to the chain's start; affects AC-223.9).
- **A10** Costs are the estimates of spec 099 per record; `unknown` stays `unknown` as in AC-102.5 (other option: none; affects AC-223.7 to AC-223.9).

## Open questions

## Changelog

- 2026-11-27 created
- 2026-11-27 priority P1 proposed: P1: normal bug or feature
