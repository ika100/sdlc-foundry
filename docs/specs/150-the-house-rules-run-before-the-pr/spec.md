---
spec_id: 150-the-house-rules-run-before-the-pr
title: The house rules run before the PR
status: done
priority: P2
shape: platform
---

# 150 — The house rules run before the PR

## Problem

In the 14 days before 2026-11-07, 31 runs of `cplat pr wait` in this repo came back red on a house rule rather than on the change: `pr-title` 18 times, `spec-required` 13, plus `validate` (plugin version mismatch) 8 and `release-check` 3. Each one costs a CI round of 10 to 20 minutes and a fix commit. The rules are cheap and known before the push: CI's own scripts (`check-pr-title.py`, `check-spec-required.py`, the `dco` job, the version loop of `quality`, `check-links.py`, the fragment names) can run locally, and some of them can fix themselves.

## Stories

As someone (or an agent) opening a PR in the platform repo, I want one command to check every house rule CI will check and to fix what it can, so that the first CI round tests the change, not its paperwork.

## Acceptance criteria

- **AC-150.1** Given the platform repo and a branch, when `cplat platform pr-check --title T [--body-file F] [--label L]` runs, then it checks the PR title, the spec rule, the changelog fragment, the plugin manifests and versions, the DCO sign-off of every commit since the base and the Markdown links with the same functions or scripts CI runs, prints one `ERROR:` line per problem with what to do, and exits 1, or prints `OK:` and exits 0.
- **AC-150.2** Given a `feat`, `fix` or `perf` title and a branch that changes `scripts/`, `plugins/` or `templates/`, when no fragment under `docs/changelog.d/` is added, then pr-check names the missing fragment and its file name format; an added fragment with a bad name or no text is named too.
- **AC-150.3** Given `--fix` and a valid title longer than 72 characters, when pr-check runs, then it prints `TITLE: <the title shortened to 72 characters>` and checks that one.
- **AC-150.4** Given `cplat pr open` in the platform repo, when the fragment or the plugin versions break a house rule, then it refuses before the push with the problems and the pr-check command; title and spec rules stay as spec 126 defines them (a caller's title is refused, never shortened).
- **AC-150.5** Given pr-check outside the platform repo, when it runs, then it stops with an error that points to `cplat pr open`.

## Non-goals

- No automatic version bump: plugins are bumped in one PR before a release, as `CONTRIBUTING.md` describes.
- No change to CI; pr-check only runs the same rules earlier.

## Open questions

- ~~Should pr-check fix the title by itself?~~ Answered (recommended, self-approved for the 5.13 round on 2026-11-07): only with `--fix`, and `cplat pr open` keeps refusing a caller's bad title (spec 126, AC-126.11).

## Changelog

- 2026-11-07 created from the strategy after journey 5 (item A2, "cplat applies the house rules"); approved with the recommended answers, as the user asked for this round.
- 2026-11-07 building
- 2026-11-07 done
