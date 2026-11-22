---
spec_id: 213-library-releases-publish-their-package
title: Library releases publish their package
status: done
priority: P1
shape: platform
---

# 213 — Library releases publish their package

## Problem

A library repo exists to be used by other repos, but a release of one publishes nothing. `/component:release` tags `main`'s head of a `library-python` repo and writes the changelog, and the tag's CI run only repeats the gates: no wheel or source archive is built and nothing is uploaded anywhere. The template's `CLAUDE.md` still says the library is "distributed as a wheel via internal index", an index that does not exist. A team that wants to share code between services therefore copies it or installs it from a git branch by hand, and nothing ties the installed code to a released, gated version. The planned TypeScript, Java and .NET library shapes (#717, #718, #720) each ask for "a release that publishes the package"; without one convention each would invent its own registry, version check and token handling. The platform owner needs library releases that publish a gated package on the release tag, the same way for every library shape, starting with `library-python`.

## Stories

- As a library owner, I want the release tag to build my package and publish it to the GitHub repo that owns it, so that consumers install the exact version that passed the gates.
- As a library owner, I want a release whose package version differs from the tag to fail before anything is published, so that a published version always means the tagged code.
- As a platform owner, I want one recorded convention (where packages go, which CI job and recipe publish, which permissions it gets, how consumers authenticate) that the registry checks for every library shape, so that the TypeScript, Java and .NET libraries follow it instead of inventing their own.
- As a developer of a consuming repo, I want the library repo's guide to say how to install a released version, so that I do not reverse-engineer it from the workflow.

## Acceptance criteria

- **AC-213.1** Given `shapes.yml`, when `scripts/shapes.py check` runs, then it passes only if every library shape that is not `planned` has a `publish` block whose `registry` is one of `github-release`, `github-npm`, `github-maven` or `github-nuget`, and no non-library shape has one; each violation is reported naming the shape and the rule; `library-python` declares `registry: github-release`.
- **AC-213.2** Given the template of a library shape with a `publish` block, when `scripts/shapes.py check` runs, then it fails, naming the shape and the missing piece, unless its `devbox.json` has a `publish` recipe and its `.github/workflows/ci.yml` has a job `publish` that runs only on a pushed `v*` tag, needs the `quality`, `test`, `security` and `ci-extra` jobs, runs `devbox run publish` with the tag, and is the only job that is granted a write permission while the workflow's default permission stays `contents: read`.
- **AC-213.3** Given a rendered `library-python` repo whose `HEAD` carries the tag `vX.Y.Z`, when `devbox run publish vX.Y.Z` runs, then it builds the wheel and the source archive of version `X.Y.Z`, creates the GitHub release `vX.Y.Z` when it does not exist, and uploads both files to that release, replacing files of the same name; run a second time it ends with the same two files on the release and no error.
- **AC-213.4** Given a rendered `library-python` repo where the built version is not the tag's version (for example the tag is on another commit, or the checkout has no tags), when `devbox run publish vX.Y.Z` runs, then it exits non-zero with a message that names the tag's version, the built version and how to fix it, and it creates no release and uploads nothing.
- **AC-213.5** Given `devbox run publish vX.Y.Z --dry-run` in a rendered `library-python` repo, when it runs, then it builds and checks the version as in AC-213.3 and AC-213.4 and prints the files it would upload and the release it would use, without calling GitHub.
- **AC-213.6** Given the platform's CI, when a change touches the `library-python` template, then the template smoke job renders the library, tags a commit and runs the publish recipe with `--dry-run` successfully, and runs it once more for a tag on another commit and expects the version failure of AC-213.4.
- **AC-213.7** Given the rendered `library-python` repo's `CLAUDE.md`, when a reader looks up how the library is released, then a section `## Releasing the package` names the `publish` job and recipe and the release assets, and says how another repo installs a released version, for a public repo and for a private one; the claim of an internal index is gone.
- **AC-213.8** Given the platform docs, when a maintainer adds a library shape, then an ADR records the convention (tag-only publishing to GitHub under the repo's owner, the `publish` job and recipe with `--dry-run`, the version check, the permissions, the registry per ecosystem and how consumers authenticate), ADR-015 lists the `publish` field, and the shape authoring guide names the `publish` block as checked.

## Non-goals

- The TypeScript, Java and .NET library shapes themselves (#717, #718, #720): they implement the convention in their own specs.
- PyPI, npmjs.org, Maven Central, nuget.org or any public registry, and private package mirrors.
- Wiring a library dependency into consuming templates (tokens in a consumer's CI, `.npmrc`, `uv` index settings): documented, not generated.
- Changing `/component:release`: it keeps tagging; the tag's CI run publishes.
- Signing packages or attaching provenance attestations.

## Assumptions

- **A1** Packages go to GitHub under the repo's owner and `GITHUB_TOKEN` publishes; Python has no GitHub Packages registry, so a Python library attaches its wheel and source archive to the GitHub release of the tag (decided with the user; affects AC-213.1, AC-213.3).
- **A2** Publishing happens only in the tag's CI run, after every gate job of that run passed; `main` builds publish nothing (other option: publish development versions from `main`; affects AC-213.2).
- **A3** The publish logic lives in one template script behind a `publish` recipe that takes the tag and `--dry-run`, so CI, a person and the platform's smoke test run the same code (other option: inline workflow steps; affects AC-213.2, AC-213.5, AC-213.6).
- **A4** The tag decides the version and the package must match it; for `library-python` the version already comes from the tag (hatch-vcs, spec 138), so the check catches a missing tag in the checkout or a tag on another commit (other option: trust the build; affects AC-213.4).
- **A5** The publish job gets `contents: write` (release assets) for `github-release`, and `packages: write` for the GitHub Packages registries; no other job gets a write permission (affects AC-213.2).
- **A6** Consumers read with a token: a public Python library installs from the release asset URL, a private one from its git tag with a token that can read the repo; the npm, Maven and NuGet registries read with a token that has `read:packages`, given to CI as the secret `PACKAGES_READ_TOKEN` (other option: one convention for public repos only; affects AC-213.7, AC-213.8).

## Open questions

none

## Changelog

- 2026-11-21 created
- 2026-11-21 priority P1 proposed: P1: normal bug or feature
- 2026-11-21 approved
- 2026-11-21 building: merged in #889
- 2026-11-21 done: merged in #889
