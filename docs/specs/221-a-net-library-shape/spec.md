---
spec_id: 221-a-net-library-shape
title: A .NET library shape
status: approved
priority: P1
shape: platform
tracks: [720]
---

# 221 — A .NET library shape

## Problem

Spec 218 brought the .NET service shape (`service-dotnet`, ADR-127), but shared .NET code still has no managed home (#720):
it is copied between services or lives in a repo the platform does not manage, without specs, gates, a release or a
published package. Python, TypeScript and Java offer a service and a library; spec 213
([ADR-125](../../adr/125-library-releases-publish-to-github-on-the-tag.md)) set how a library publishes on its release
tag and named `github-nuget` for .NET. What is missing is the shape itself.

## Stories

- As a developer, I want `/component:new <name> --type library --lang csharp` to create a C# library repo, so that the
  .NET services of my product share code through a versioned NuGet package instead of copies.
- As a library owner, I want the release tag to pack my library and push it to GitHub Packages, so that consumers depend
  on exactly the version that passed the gates.
- As a developer of a consuming service, I want the library's guide to say how to add the package source with a read
  token and reference a released version, so that I do not reverse-engineer the registry setup.
- As the platform owner, I want the shape to reuse the .NET tooling and the `svc-dotnet` agents, so that there is one way to
  build .NET services and libraries.

## Acceptance criteria

- **AC-221.1** Given the shape registry, when it is read, then it holds a `library-dotnet` entry (plugin `svc-dotnet`,
  template `library-dotnet`, library, not deployable, language `csharp`, no runtime, `publish: {registry: github-nuget}`),
  `scripts/shapes.py check` passes (including the ADR-125 publish contract of the template), the pair `library/csharp`
  resolves to it, and `--lang csharp` alone still means `service/csharp`.
- **AC-221.2** Given `cplat component new <name> <description> --type library --lang csharp`, when it runs, then it renders
  `templates/library-dotnet` into a repo whose `.copier-answers.yml` names that template, and `scripts/detect-shape.sh`
  resolves the repo to `library-dotnet` from the answers file and by sniffing a solution or project file (`*.sln`,
  `*.slnx`, `*.csproj`, or a `*.csproj` one level down) without a `Dockerfile`; with a `Dockerfile` it stays
  `service-dotnet`.
- **AC-221.3** Given a fresh render with the defaults, when `devbox run ci` runs, then the install (locked restore), quality
  (`dotnet format` and the analyzers with warnings as errors), the tests (xUnit through `scripts/gate.sh`, so that a run of 0
  tests fails, with an 80 % coverlet line gate) and security (the locked packages scanned by trivy + detect-secrets) pass;
  the template's `devbox.json` has the canonical recipes (`install`, `build`, `lint`, `lint-fix`, `typecheck`, `quality`,
  `test`, `test-fast`, `audit`, `secrets-scan`, `security`, `secrets-baseline`, `ci` ending in `ci-extra`, `publish`,
  `deps-findings`, `deps-bump`, `spec-check`) and no image, smoke, `dev` or `start` recipe, and the repo has no Dockerfile.
- **AC-221.4** Given the rendered library project, when it is read, then it targets `net<major>.0` from the same pinned SDK
  as `service-dotnet`, is packable with the PackageId `<Namespace>` (the PascalCase project name), the development version
  `0.0.0-dev`, a description, the repository URL and a readme in the package, and the test project is not packable; the
  solution holds exactly the library and its test project.
- **AC-221.5** Given a rendered repo whose `HEAD` carries the tag `vX.Y.Z` and a clean work tree, when `devbox run publish
  vX.Y.Z` runs, then it packs the library with version `X.Y.Z` (the tag is the version, whatever the project file holds)
  and pushes the `.nupkg` to `https://nuget.pkg.github.com/<owner>/index.json` with a temporary NuGet config whose
  credentials come from `GH_TOKEN` (never written to the repo); when that version is already in the registry it pushes
  nothing new and exits 0 saying so; afterwards the work tree is unchanged.
- **AC-221.6** Given a rendered repo where `HEAD` does not carry the tag (or the work tree has changes), when `devbox run
  publish vX.Y.Z` runs, then it exits 1 with `publish: the built version is <v> but the tag is vX.Y.Z (X.Y.Z)` and a `fix:`
  line, and packs and pushes nothing; a wrong argument list exits 2 with `usage: publish.sh vX.Y.Z [--dry-run]`.
- **AC-221.7** Given `devbox run publish vX.Y.Z --dry-run`, when it runs, then it checks and packs as in AC-221.5 and
  AC-221.6 and prints the package file, `<PackageId> X.Y.Z` and the registry it would push to, without a registry call or a
  token.
- **AC-221.8** Given the rendered `.github/workflows/ci.yml`, when it is read, then it has the jobs `quality`, `test`,
  `security`, `ci-extra`, `publish` and `pr-title` with the registry's `ci_checks` as job names, every action pinned by
  commit SHA, the workflow default `contents: read`, and the ADR-125 `publish` job (tag only, after every gate, `packages:
  write` as the only write permission, `GH_TOKEN` from `GITHUB_TOKEN`); no docker job.
- **AC-221.9** Given the rendered `CLAUDE.md`, when a reader looks up the release, then a section `## Releasing the
  package` names the `publish` job and recipe, the PackageId and the registry, and says how another repo depends on a
  released version: a `nuget.config` package source for the registry with credentials from a token that can read packages
  (`PACKAGES_READ_TOKEN` in the consumer's CI), and the `PackageReference`/`PackageVersion` lines.
- **AC-221.10** Given the platform's shape-wide tooling, when it handles a `library-dotnet` repo, then it is covered like
  `service-dotnet` for the build and like `library-typescript` for the release: the repository CI smoke-tests the template
  (render, the shape detection, lint, the coverage gate, a `publish --dry-run` on a tagged commit and the version failure for
  a tag on another commit) and actionlint checks its workflow; `gate.sh` and `deps.sh` stay copies of their sources;
  dependency findings and bumps (`deps_parse`), the build-test globs, the template pin bump, template lint, the gitops-app
  valid pairs and plan shapes, and `/component:release` (no version file: the version comes from the tag) know the shape;
  the template enables `svc-dotnet`, `svc` and `shared`, and `cplat shape` routes `coder` to `svc-dotnet:coder` in a
  rendered repo.
- **AC-221.11** Given the platform docs, when a reader looks for the shapes, then `docs/templates.md`, the site's shapes
  page, the PRD shape table, `CLAUDE.md`'s layout and the `svc-dotnet` README name `library-dotnet`.

## Non-goals

- Several target frameworks (multi-targeting), and .NET Framework 4.x.
- Multi-project solutions and several packages in one repo.
- Publishing to nuget.org or any registry but GitHub Packages.
- Generating the consumer wiring (the package source, the read token) in the `service-dotnet` template: it is documented
  in the library's guide (ADR-125, #965).
- Signing packages, symbol packages (`.snupkg`) or provenance attestations (#966).

## Assumptions

- **A1** The package is a C# NuGet package on GitHub Packages built like `service-dotnet` (the pinned .NET LTS SDK, `dotnet
  format` + analyzers with warnings as errors, xUnit + coverlet, trivy over the lock files), and the agents are the
  `svc-dotnet` plugin's (decided for the round; other option: a plugin of its own; affects AC-221.1, AC-221.3).
- **A2** One target framework, `net<major>.0` of the pinned LTS (decided for the round; other option: also `netstandard2.0`;
  affects AC-221.4).
- **A3** The tag is the version, as for `library-typescript` and `library-java`: the project keeps `0.0.0-dev`,
  `publish.sh` passes the tag's version to `dotnet pack` only, and `/component:release` writes no version file (other
  option: a committed version that the release bumps; affects AC-221.5, AC-221.10).
- **A4** The version check compares the version the commit would build (the tag only when `HEAD` carries it and the work
  tree is clean, otherwise the project's version) with the tag (affects AC-221.6).
- **A5** A rerun of the same tag is a no-op: the push uses `--skip-duplicate`, because GitHub Packages refuses a republished
  version (other option: fail the rerun; affects AC-221.5).
- **A6** Publishing skips the tests: the `publish` job runs only after every gate of the same run passed (affects AC-221.5).
- **A7** Detection: a .NET solution or project without a `Dockerfile` is a library, so existing `service-dotnet` repos
  (which have one) keep their shape (affects AC-221.2).
- **A8** The language value stays `csharp`, as for `service-dotnet` (ADR-127), and the template ships one sample class with
  a test, like the other library templates (affects AC-221.1, AC-221.3).

## Open questions

none

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-23 created
- 2026-11-23 approved
