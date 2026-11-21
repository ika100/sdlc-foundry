---
spec_id: 215-a-typescript-library-shape
title: A TypeScript library shape
status: approved
priority: P1
shape: platform
tracks: [717]
---

# 215 — A TypeScript library shape

## Problem

Shared types and client code between a `web-nextjs` website and a `service-typescript` backend are a common need (#717),
but the platform has no TypeScript library shape. That code is copied between repos or lives in a repo the platform does
not manage, without specs, gates, a release or a published package. Spec 213 (ADR-125) set the convention every library
shape follows to publish its package on the release tag, and spec 214 brought the Node tooling and the `svc-ts` agents a
TypeScript library can reuse; what is missing is the shape itself.

## Stories

- As a developer, I want `/component:new <name> --type library --lang typescript` to create an npm package repo, so that
  the website and the services of my product share code through a versioned package instead of copies.
- As a library owner, I want the release tag to build my package and publish it to GitHub Packages as `@<owner>/<repo>`,
  so that consumers install exactly the version that passed the gates.
- As a developer of a consuming repo, I want the library's guide to say how to install a released version with a read
  token, so that I do not reverse-engineer the registry setup.
- As the platform owner, I want the shape to reuse the TypeScript tooling and the `svc-ts` agents, so that there is one
  way to build TypeScript backends and libraries.

## Acceptance criteria

- **AC-215.1** Given the shape registry, when it is read, then it holds a `library-typescript` entry (plugin `svc-ts`,
  template `library-typescript`, library, not deployable, language `typescript`, no runtime, `publish: {registry:
  github-npm}`), `scripts/shapes.py check` passes (including the ADR-125 publish contract of the template), the pair
  `library/typescript` resolves to it, and `--lang typescript` alone still means `website/typescript`.
- **AC-215.2** Given `cplat component new <name> <description> --type library --lang typescript`, when it runs, then it
  renders `templates/library-typescript` into a repo whose `.copier-answers.yml` names that template, and
  `scripts/detect-shape.sh` resolves the repo to `library-typescript` from the answers file and by sniffing a
  `package.json` that depends on neither `next` nor `fastify`; a `next` app stays `web-nextjs` and a `fastify` one
  `service-typescript`.
- **AC-215.3** Given a fresh render with the defaults, when `devbox run ci` runs, then quality (ESLint + `tsc`), the tests
  (Vitest with an 80 % coverage gate, through `scripts/gate.sh` so that a run of 0 tests fails) and security (pnpm audit +
  detect-secrets) pass; the template's `devbox.json` has the canonical recipes (`lint`, `lint-fix`, `typecheck`,
  `quality`, `test`, `test-fast`, `security`, `secrets-baseline`, `ci` ending in `ci-extra`, `build`, `publish`,
  `deps-findings`, `deps-bump`, `spec-check`) and no image or smoke recipe, and the repo has no Dockerfile.
- **AC-215.4** Given the rendered `package.json`, when it is read, then the package is named `@<owner>/<repo>` with the
  owner lowercased, is an ES module (`"type": "module"`) with an `exports` entry giving `types` and `import` for `dist/`,
  ships only `dist` (`files`), names its repository, and publishes to `https://npm.pkg.github.com` (`publishConfig`); no
  CommonJS build is produced.
- **AC-215.5** Given a rendered repo whose `HEAD` carries the tag `vX.Y.Z` and a clean work tree, when `devbox run publish
  vX.Y.Z` runs, then it builds `dist/` with type declarations, packs the package with version `X.Y.Z` (the tag is the
  version, whatever development version `package.json` holds), and publishes it to `npm.pkg.github.com` with
  `NODE_AUTH_TOKEN`; when that version is already in the registry it publishes nothing and exits 0 saying so; afterwards
  `package.json` is unchanged.
- **AC-215.6** Given a rendered repo where `HEAD` does not carry the tag (or the work tree has changes), when `devbox run
  publish vX.Y.Z` runs, then it exits 1 with `publish: the built version is <v> but the tag is vX.Y.Z (X.Y.Z)` and a
  `fix:` line, and calls no registry; a wrong argument list exits 2 with `usage: publish.sh vX.Y.Z [--dry-run]`.
- **AC-215.7** Given `devbox run publish vX.Y.Z --dry-run`, when it runs, then it builds, packs and checks as in AC-215.5
  and AC-215.6 and prints the tarball, the package name and version and the registry it would publish to, without any
  network call.
- **AC-215.8** Given the rendered `.github/workflows/ci.yml`, when it is read, then it has the jobs `quality`, `test`,
  `security`, `ci-extra`, `publish` and `pr-title` with the registry's `ci_checks` as job names, every action pinned by
  commit SHA, the workflow default `contents: read`, and the ADR-125 `publish` job (tag only, after every gate, `packages:
  write` as the only write permission, `GH_TOKEN` and `NODE_AUTH_TOKEN` from `GITHUB_TOKEN`); no docker job.
- **AC-215.9** Given the rendered `CLAUDE.md`, when a reader looks up the release, then a section `## Releasing the
  package` names the `publish` job and recipe, the package name and registry, and says how another repo installs a
  released version: an `.npmrc` line `@<owner>:registry=https://npm.pkg.github.com`, a token with `read:packages`
  (`PACKAGES_READ_TOKEN` in the consumer's CI), and the install command.
- **AC-215.10** Given the platform's shape-wide tooling, when it handles a `library-typescript` repo, then it is covered
  like `library-python`: the repository CI smoke-tests the template (render, install, quality, tests, the 0-tests gate,
  a `publish --dry-run` on a tagged commit and the version failure for a tag on another commit) and actionlint checks its
  workflow; `gate.sh` stays a copy of the gitops-app source; dependency findings and bumps (`deps_parse`), the build-test
  globs, the template pin bump, the stage list, the gitops-app valid pairs and plan shapes, and `/component:release` (no
  version file: the version comes from the tag) know the shape; the template enables `svc-ts`, `svc` and `shared`, and
  `cplat shape` routes `coder` to `svc-ts:coder` in a rendered repo.
- **AC-215.11** Given the platform docs, when a reader looks for the shapes, then `docs/templates.md`, the site's shapes
  page, the PRD shape table, `CLAUDE.md`'s layout and the `svc-ts` README name `library-typescript`.

## Non-goals

- A monorepo or workspace layout, and several packages in one repo.
- A CommonJS or dual build.
- Publishing to npmjs.org or any registry but GitHub Packages.
- Generating the consumer wiring (`.npmrc`, the read token) in the `web-nextjs` and `service-typescript` templates: it is
  documented in the library's guide (ADR-125).
- New `svc-ts` agents or prompt changes beyond what a library needs to be named.
- Signing packages or provenance attestations.

## Assumptions

- **A1** The package is `@<owner>/<repo>` on GitHub Packages, ESM only, and the agents are the `svc-ts` plugin's (decided
  with the user; affects AC-215.1, AC-215.4).
- **A2** The tag is the version: `publish.sh` stamps the tag's version into the packed package only, so `package.json`
  keeps a development version and `/component:release` writes no version file, as for `library-python` (other option: a
  committed version that the release bumps; affects AC-215.5, AC-215.10).
- **A3** The version check compares the version the commit would build (the tag only when `HEAD` carries it and the work
  tree is clean, otherwise the `package.json` version) with the tag (affects AC-215.6).
- **A4** A rerun of the same tag is a no-op when the registry already holds the version, because the registry refuses a
  republished version and the tag builds the same commit (other option: fail the rerun; affects AC-215.5).
- **A5** The build is plain `tsc` to `dist/` with declarations and source maps, no bundler (affects AC-215.4, AC-215.5).
- **A6** The template ships one sample module (`src/index.ts`) with tests, like `library-python`'s package skeleton
  (affects AC-215.3).

## Open questions

none

## Changelog

- 2026-11-21 created
- 2026-11-21 approved
