---
spec_id: 217-a-java-library-shape
title: A Java library shape
status: done
priority: P1
shape: platform
tracks: [718]
---

# 217 — A Java library shape

## Problem

Java has only the Spring Boot service shape (#718). Code that several Java services share is copied between repos or lives in
a repo the platform does not manage, without specs, gates, a release or a published artifact. Python and TypeScript already
offer a service and a library; spec 213 ([ADR-125](../../adr/125-library-releases-publish-to-github-on-the-tag.md)) set
how a library publishes on its release tag, naming `github-maven` for Java. What is missing is the shape itself.

## Stories

- As a developer, I want `/component:new <name> --type library --lang java` to create a Maven library repo, so that the
  Java services of my product share code through a versioned jar instead of copies.
- As a library owner, I want the release tag to build my jar and publish it to GitHub Packages, so that consumers depend
  on exactly the version that passed the gates.
- As a developer of a consuming service, I want the library's guide to say how to depend on a released version with a
  read token, so that I do not reverse-engineer the registry setup.
- As the platform owner, I want the shape to reuse the Java tooling and the `svc-java` agents, so that there is one way to
  build Java services and libraries.

## Acceptance criteria

- **AC-217.1** Given the shape registry, when it is read, then it holds a `library-java` entry (plugin `svc-java`, template
  `library-java`, library, not deployable, language `java`, build tool `maven`, no runtime, `publish: {registry:
  github-maven}`), `scripts/shapes.py check` passes (including the ADR-125 publish contract of the template), the pair
  `library/java` resolves to it, and `--lang java` alone still means `service/java`.
- **AC-217.2** Given `cplat component new <name> <description> --type library --lang java`, when it runs, then it renders
  `templates/library-java` into a repo whose `.copier-answers.yml` names that template, and `scripts/detect-shape.sh`
  resolves the repo to `library-java` from the answers file and by sniffing a `pom.xml` with neither a `Dockerfile` nor a
  Spring Boot reference; a `pom.xml` next to a `Dockerfile`, or one that references Spring Boot, stays `service-java`, and
  a Gradle build stays `service-java`.
- **AC-217.3** Given a fresh render with the defaults, when `devbox run ci` runs, then quality (Spotless + Checkstyle +
  compile), the tests (JUnit 5 through `mvn verify` with an 80 % JaCoCo line gate, through `scripts/gate.sh` so that a run
  of 0 tests fails) and security (trivy or OWASP Dependency-Check + detect-secrets) pass; the template's `devbox.json` has
  the canonical recipes (`lint`, `lint-fix`, `typecheck`, `quality`, `test`, `test-fast`, `audit`, `security`,
  `secrets-baseline`, `ci` ending in `ci-extra`, `build`, `publish`, `deps-findings`, `deps-bump`, `spec-check`) and no
  image, smoke or `dev` recipe, and the repo has no Dockerfile.
- **AC-217.4** Given the rendered `pom.xml`, when it is read, then the artifact is `<group_id>:<project_name>` with packaging
  `jar` and the development version `0.0.0-SNAPSHOT`, has no parent POM, compiles for the template's JDK release, attaches a
  sources jar, names its `scm` and `url`, and deploys to `https://maven.pkg.github.com/<owner>/<repo>` (`distributionManagement`,
  repository id `github`); every build plugin version is pinned.
- **AC-217.5** Given a rendered repo whose `HEAD` carries the tag `vX.Y.Z` and a clean work tree, when `devbox run publish
  vX.Y.Z` runs, then it builds the jar with version `X.Y.Z` (the tag is the version, whatever `pom.xml` holds), and deploys
  it to the `github` repository with a temporary Maven settings file whose server credentials come from `GH_TOKEN` (never
  written to the repo); when that version is already in the registry it deploys nothing and exits 0 saying so; afterwards
  `pom.xml` is unchanged.
- **AC-217.6** Given a rendered repo where `HEAD` does not carry the tag (or the work tree has changes), when `devbox run
  publish vX.Y.Z` runs, then it exits 1 with `publish: the built version is <v> but the tag is vX.Y.Z (X.Y.Z)` and a `fix:`
  line, and builds and deploys nothing; a wrong argument list exits 2 with `usage: publish.sh vX.Y.Z [--dry-run]`.
- **AC-217.7** Given `devbox run publish vX.Y.Z --dry-run`, when it runs, then it builds and checks as in AC-217.5 and
  AC-217.6 and prints the jar, the coordinates `<group>:<artifact>:X.Y.Z` and the registry it would deploy to, without a
  registry call or a token.
- **AC-217.8** Given the rendered `.github/workflows/ci.yml`, when it is read, then it has the jobs `quality`, `test`,
  `security`, `ci-extra`, `publish` and `pr-title` with the registry's `ci_checks` as job names, every action pinned by
  commit SHA, the workflow default `contents: read`, and the ADR-125 `publish` job (tag only, after every gate, `packages:
  write` as the only write permission, `GH_TOKEN` from `GITHUB_TOKEN`); no docker job.
- **AC-217.9** Given the rendered `CLAUDE.md`, when a reader looks up the release, then a section `## Releasing the
  package` names the `publish` job and recipe, the coordinates and the registry, and says how another repo depends on a
  released version: the `<repository>` with id `github` and the registry URL, a `<server>` in the consumer's Maven settings
  with a token that can read packages (`PACKAGES_READ_TOKEN` in the consumer's CI), and the `<dependency>` block.
- **AC-217.10** Given the platform's shape-wide tooling, when it handles a `library-java` repo, then it is covered like
  `library-typescript`: the repository CI smoke-tests the template (render, the shape detection, lint, the coverage gate, the
  0-tests gate, a `publish --dry-run` on a tagged commit and the version failure for a tag on another commit) and actionlint
  checks its workflow; `gate.sh`, `deps.sh` and `PomDeps.java` stay copies of their sources; dependency findings and bumps
  (`deps_parse`), the build-test globs, the template pin bump, template lint, the gitops-app valid pairs and plan shapes,
  and `/component:release` (no version file: the version comes from the tag, and the `svc-java` release agent skips that
  step) know the shape; the template enables `svc-java`, `svc` and `shared`, and `cplat shape` routes `coder` to
  `svc-java:coder` in a rendered repo.
- **AC-217.11** Given the platform docs, when a reader looks for the shapes, then `docs/templates.md`, the site's shapes
  page, the PRD shape table, `CLAUDE.md`'s layout and the `svc-java` README name `library-java`.

## Non-goals

- A multi-module build, and several artifacts in one repo.
- A Spring Boot starter or auto-configuration library.
- Gradle.
- Publishing to Maven Central or any registry but GitHub Packages.
- Generating the consumer wiring (`<repository>`, the read token) in the `service-java` template: it is documented in the
  library's guide (ADR-125).
- A javadoc jar, signing artifacts or provenance attestations.

## Assumptions

- **A1** The artifact is a plain Java library jar on GitHub Packages built with Maven like `service-java` (same JDK, Spotless +
  Checkstyle, JUnit 5 + JaCoCo, the trivy/OWASP audit), and the agents are the `svc-java` plugin's (decided for the round;
  other option: a Spring Boot starter; affects AC-217.1, AC-217.4).
- **A2** The tag is the version, as for `library-typescript`: `pom.xml` keeps `0.0.0-SNAPSHOT`, `publish.sh` sets the tag's
  version for the build only (`versions:set`, restored afterwards), and `/component:release` writes no version file
  (other option: a committed version that the release bumps; affects AC-217.5, AC-217.10).
- **A3** The version check compares the version the commit would build (the tag only when `HEAD` carries it and the work
  tree is clean, otherwise the `pom.xml` version) with the tag (affects AC-217.6).
- **A4** A rerun of the same tag is a no-op when the registry already holds the version's POM, because GitHub Packages
  refuses a republished release version (other option: fail the rerun; affects AC-217.5).
- **A5** Publishing skips the tests: the `publish` job runs only after every gate of the same run passed (affects AC-217.5).
- **A6** Detection: a `pom.xml` without a `Dockerfile` and without a Spring Boot reference is a library, so existing
  `service-java` repos (which have both) keep their shape; Gradle builds stay `service-java` (affects AC-217.2).
- **A7** The template ships one sample class with a test, like the other library templates (affects AC-217.3).

## Open questions

none

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-22 created
- 2026-11-22 priority P1 proposed: P1: normal bug or feature
- 2026-11-22 approved
- 2026-11-22 building: built
- 2026-11-22 done: verified, 11/11
