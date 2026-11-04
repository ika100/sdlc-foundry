---
spec_id: 138-release-tags-the-staging-build
title: A component release tags the build staging tested
status: draft
priority: P1
shape: platform
---

# 138 — A component release tags the build staging tested

## Problem

A prod promotion (spec 106) takes the release image `X.Y.Z`, and a `v*.*.*` tag never rebuilds: the CI gives the `sha-<40>`
image of the tagged commit its `X.Y.Z` tags. Prod is refused unless that digest equals the one staging runs. But
`/component:release` writes the version bump and the CHANGELOG entry in a release PR, merges it and tags the merge commit:
a new commit that dev may run but staging never tested. So the release flow as written can never reach prod.

In the demo of 2026-11-04 (#426), Claude worked around this: it tagged the commit staging ran directly (`v0.1.0`; the repos
already declared 0.1.0) and skipped the release PR, so neither repo got a CHANGELOG entry.

Tracks #426.

## Stories

- As the owner of a component, I want `/component:release` to tag the build staging tested, so that the release can be
  promoted to prod without a digest mismatch.
- As a reader of a component's history, I want every release to have its CHANGELOG entry and version, so that I can see what
  each version contains.

## Acceptance criteria

- **AC-138.1** Given a component whose staging runs `sha-<S>`, when `/component:release` tags a release, then the tag is on
  commit `S` (or the command stops before tagging and says why), never on a commit staging did not run.
- **AC-138.2** Given a release, when it is tagged, then the CHANGELOG entry and the version file for `vX.Y.Z` are on `main`,
  either in the tagged commit or in a commit after it, as decided in the open question.
- **AC-138.3** Given a release whose tagged commit is not what staging runs, when the command reaches the tag phase, then it
  prints the staging commit, the candidate commit and the next step (promote that commit to staging and verify it, then run
  the release again).
- **AC-138.4** Given the release command, when it finishes, then its summary names the tagged commit and says it is the one
  staging runs.

## Non-goals

- No change to the prod digest rule of spec 106.
- No new command.

## Open questions

1. **Where do the version bump and the CHANGELOG go?**
   - (a) *Before staging (recommended):* the release PR (bump + CHANGELOG) merges first; its merge commit goes to dev and is
     promoted to staging (by hand or by `promotion.staging: auto`) and verified; `/component:release` then tags that commit.
     The tagged commit carries its own version. It costs one more dev → staging round per release.
   - (b) *After the tag:* `/component:release` tags the commit staging runs and writes the CHANGELOG (and the version of the
     next development cycle) in a follow-up PR. No extra round, but the tagged commit's version file shows the previous
     version, unless the version is read from the git tag.
   - (c) Both, chosen by a flag.

## Changelog

- 2026-11-05 created (tracks #426); draft, waiting for the answer to the open question
