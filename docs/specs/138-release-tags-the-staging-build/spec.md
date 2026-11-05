---
spec_id: 138-release-tags-the-staging-build
title: A component release tags the build staging tested
status: approved
priority: P1
shape: platform
tracks: [426]
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
  promoted to prod without a digest mismatch and without another dev → staging round.
- As a reader of a component's history, I want every release to have its CHANGELOG entry, so that I can see what each
  version contains.
- As a developer on `main`, I want the version file to say that a build is a development build after the last release, so
  that I never mistake a `main` build for a release.

## Acceptance criteria

- **AC-138.1** Given a deployable component linked to a gitops-app whose staging pins `sha-<S>`, when `/component:release`
  runs, then it releases commit `S`: the gates run on `S`, the next version comes from the commits between the previous
  release tag and `S`, and the tag `vX.Y.Z` is on `S`; commits on `main` after `S` are named as not in this release.
- **AC-138.2** Given a component without a staging environment (a library, or a repo not linked to a gitops-app), when
  `/component:release` runs, then it releases `main`'s head, tags it only after `main`'s `ci` run on that commit passed
  (#470), and says why there is no staging commit.
- **AC-138.3** Given staging's commit cannot be released (no staging instance, a staging pin that is not a `sha-<40>`
  build, a commit not on `main`, a commit already released, or nothing new since the last release but release follow-up
  commits), when `/component:release` starts, then it stops before any gate, tag or PR and prints the staging commit, the
  candidate commit (`main`'s head) and the next step (promote that commit to staging and verify it, then run the release
  again).
- **AC-138.4** Given a release that was tagged, when the command continues, then the release agent opens a follow-up PR
  from `main` that adds the CHANGELOG entry for `vX.Y.Z` (the commits between the previous tag and `vX.Y.Z`) and sets the
  next development version: Python `X.Y.(Z+1).dev0` in `pyproject.toml` (and `uv.lock`, #468), Java `X.Y.(Z+1)-SNAPSHOT` in
  `pom.xml`, web `X.Y.(Z+1)-dev.0` in `package.json`, Go and a library whose version comes from the tag no version file;
  the PR is merged after green CI and is never tagged. No release PR is merged before the tag.
- **AC-138.5** Given a library made from `library-python`, when it is installed from a release tag, then its version is the
  tag's (read from git at build time), so a library needs no version file in its tagged commit; a `main` build without the
  tag reads as a development version.
- **AC-138.6** Given a Python service made from `service-python`, when it reports its version (package metadata, the
  OpenAPI document), then every place reads the one version in `pyproject.toml`, so the follow-up PR changes it in one
  place.
- **AC-138.7** Given the release command, when it finishes, then its summary names the tagged commit and why it is the
  one tagged (the commit staging runs, its `sha-<40>` image re-tagged `X.Y.Z` without a rebuild, spec 106; or `main`'s head
  when there is no staging), notes that the tagged commit's version file shows the previous development version and that
  the release version is the tag, the image's `X.Y.Z` tag and the CHANGELOG, and links the follow-up PR.

## Non-goals

- No change to the prod digest rule of spec 106.
- No new slash command; a `cplat component release` helper decides the commit to tag, the command stays the orchestrator.
- No rebuild of the tagged image and no version injected into an image after it was built: a service image keeps the
  version its build had.
- Version files of existing repos are not migrated: an existing library with a static version keeps it (the release agent
  treats it like a service's).

## Open questions

1. ~~**Where do the version bump and the CHANGELOG go?** (a) before staging, in a release PR whose merge commit is promoted
   and then tagged; (b) after the tag: tag the commit staging runs, write the CHANGELOG and the next development version in
   a follow-up PR; (c) both, chosen by a flag.~~ Answered by the user: (b). The tag is on the commit staging runs, the
   CHANGELOG and the next development version follow in a PR after the tag (AC-138.1, AC-138.4); the version file of the
   tagged commit is handled per template (AC-138.4 to AC-138.7).

## Changelog

- 2026-11-05 created (tracks #426); draft, waiting for the answer to the open question
- 2026-11-05 amended: open question answered by the user: (b)
- 2026-11-05 approved
