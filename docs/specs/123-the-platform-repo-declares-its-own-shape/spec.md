---
spec_id: 123-the-platform-repo-declares-its-own-shape
title: The platform repo declares its own shape
status: approved
priority: P1
---

# 123 — The platform repo declares its own shape

## Problem

The sdlc-foundry repo has no shape. `cplat shape` fails here with "cannot determine the repo's shape", so `/component:build` and `/component:ship` cannot run on the platform itself: specs 113 and 114 were built and shipped by hand, without the gates, verification and run records every component repo gets. Platform changes already have to start with a spec (CLAUDE.md, ADR-026), and the repo already has the devbox gates the commands expect (`test-fast`, `test`, `quality`, `ci`, `lint-fix`, #219). What is missing is a way for the repo to say what it is. This must be an explicit opt-in: guessing it from the repo's files would risk treating a component repo as the platform.

## Stories

As a platform maintainer, I want `/component:spec|plan|build|verify|ship` to work in the platform repo like in any component repo, so that platform specs are built, verified and merged unattended with the same gates and run records.

As a platform maintainer, I want the platform repo to say what it is with one committed setting, so that nothing guesses it and nothing else (new repos, fleet updates, adoption) mistakes the platform for a component.

As a component repo owner, I want nothing to change in my repo, so that the new setting cannot change how my repo's shape is found.

## Acceptance criteria

### Declaring and resolving the shape

- **AC-123.1** Given a repo whose committed `.platform-settings.yml` contains `shape: platform`, when `cplat shape` runs, then it prints `shape: platform`, `plugin: svc`, `deployable: false`, `library: false`, no `unsupported`, and `agents` routing coder, tester, reviewer, architect and product-manager to `svc:<role>` and quality and security to `shared:<role>`, with no deployment, observability, migrations or release role.
- **AC-123.2** Given the platform repo without a `shape:` key in its settings file, when `cplat shape` runs, then it fails with "cannot determine the repo's shape" as today: the platform repo is never recognised from its files.
- **AC-123.3** Given a `.platform-settings.yml` whose `shape:` is not a known value (e.g. `platfrom`), when any command that needs the repo's shape runs (`cplat shape`, `cplat spec new`, `cplat component ship start`), then it fails before doing anything, naming the file and the value and listing the values that may be declared.
- **AC-123.4** Given a `.platform-settings.yml` that declares a component shape (e.g. `shape: service-python`), when any command that needs the repo's shape runs, then it fails saying that only `platform` can be declared and that a component repo's shape comes from its `.copier-answers.yml` (`cplat adopt` for an existing repo).
- **AC-123.5** Given a repo with a `.copier-answers.yml` naming a platform template and `shape: platform` in its settings file, when any command that needs the repo's shape runs, then it fails naming both sources and changes nothing.
- **AC-123.6** Given `shape: platform` only in the personal settings file (`~/.config/sdlc-foundry/settings.yml`), when any command that needs the repo's shape runs, then it fails saying that `shape` belongs in the repo's committed `.platform-settings.yml`.
- **AC-123.7** Given a `.platform-settings.yml` with `shape: platform` next to `coordinator_model`, `budget`, `kube_context` and `validation`, when headless runs, budgets, cluster commands and `cplat validate` read their settings, then each behaves exactly as it did without the `shape` key; and a settings file without `shape` changes nothing for any repo.
- **AC-123.8** Given a fresh clone of the platform repo's `main` after this spec ships, when `cplat shape` runs, then it resolves `platform` without any local setup: the declaration is committed.

### The shape is never offered elsewhere

- **AC-123.9** Given `/component:new`, `/system:new` and `cplat adopt`, when they list or validate the types, languages or shapes a repo can be created or adopted as, then `platform` is not among them, and `cplat adopt --type platform` fails listing the valid shapes without `platform`.
- **AC-123.10** Given the shape registry check, when it runs with `platform` registered, then it passes although `platform` has no template, and it still fails for any other shape that lacks its template, plugin or detection rule.
- **AC-123.11** Given the platform repo with `shape: platform`, when `cplat platform update` runs in it, then it exits non-zero with "the platform repo is not updated from a template" and changes no file.
- **AC-123.12** Given an owner whose repos include the platform repo (shape `platform`, no `.platform-version` stamp), when `cplat platform fleet` runs, with or without `--only` naming that repo, then it opens no PR and changes nothing in it.
- **AC-123.13** Given the platform repo with `shape: platform`, when `cplat platform doctor` runs in it, then it reports `repo shape: platform` as OK and, instead of the "no .platform-version stamp" warning, reports `platform source at v<version>` with the repo's own platform version.

### The commands on the platform repo

- **AC-123.14** Given the platform repo with `shape: platform`, when `/component:spec`, `/component:plan` or `/component:verify` runs, then it proceeds with the routed agents and never asks for the repo's shape.
- **AC-123.15** Given the platform repo with `shape: platform`, when `cplat spec new` runs, then the new spec's front matter records `shape: platform`, and `cplat spec check` accepts it.
- **AC-123.16** Given every spec in the platform repo's `docs/specs/` before this change, when `cplat spec check` runs after the shape is declared, then it reports no error it did not report before: existing specs keep no `shape:` line and still pass, including AC-104.4, whose line ends in `(smoke)`.
- **AC-123.17** Given a new spec with `shape: platform` that has a criterion ending in `(smoke)`, when `cplat spec check` runs, then it fails for that criterion with "(smoke) needs a deployable shape (platform has no smoke tests)".
- **AC-123.18** Given an approved platform spec, when `/component:build` runs, then its gates run through the repo's own `devbox run test-fast`, `devbox run quality`, `devbox run lint-fix` and `devbox run ci`, and the image phase prints `## Phase 5 skipped — platform is not deployable` and builds no image.
- **AC-123.19** Given an approved platform spec and no gitops-app link, when `cplat component ship start` runs, then it does not ask for `GITOPS_TOKEN` or a gitops-app link and starts the run.
- **AC-123.20** Given a platform ship run with an open PR, when `cplat component ship land` runs, then it waits for every check the platform CI reports on the PR (including `ci-success`, `DCO sign-off`, `spec-required` and `pr-title`), treats jobs the CI skipped for an unaffected change as not blocking, ends at the first red check, and squash-merges the PR when all are green.
- **AC-123.21** Given a platform ship run whose PR was merged, when `cplat component ship deploy` runs, then the run reaches `done` at once with the line `not deployable (platform): nothing to deploy`, without waiting for a pin PR, Argo CD, smoke tests or staging, and without running `devbox run smoke` (which in this repo smoke-tests the templates).
- **AC-123.22** Given a platform ship run that reached `done`, when the final report is printed, then the dev, promotion and smoke rows read `not deployable`, no `/instance:promote` next step is printed, and the run record names the shape `platform`.
- **AC-123.23** Given the platform repo with `shape: platform`, when `/component:release` runs, then it refuses before changing anything, saying that the platform is released through its own procedure (version bumps in the marketplace catalog and the plugin manifests, a release PR and a tag), and naming where that procedure is described.

## Non-goals

- Recognising the platform repo from its files (sniffing) or from its name.
- A template for the platform repo, or creating a new repo of shape `platform`.
- Stamping the platform repo with `.platform-version`, or updating it through `/platform:update` or the fleet.
- Deploying anything from the platform repo (images, pins, promotion, dev or staging smoke).
- Changing how component repos find their shape (`.copier-answers.yml`, then sniffing).
- Adding `shape: platform` to the existing specs' front matter.
- Changing the platform's own release procedure (version bumps in the marketplace catalog and plugin manifests).

## Open questions

- ~~Is a `shape:` in `.platform-settings.yml` honoured only for `platform`, or may it override detection for any shape?~~ Answered: only `platform`; any other value is an error; component repos keep `.copier-answers.yml` and `cplat adopt`. See AC-123.3, AC-123.4.
- ~~What does `/component:release` do in the platform repo?~~ Answered: it refuses and names the platform's own release procedure; `platform` has no release role. See AC-123.1, AC-123.23.
- ~~Confirm: a repo with both a `.copier-answers.yml` naming a template and `shape: platform` is refused.~~ Answered: yes, refused, naming both sources. See AC-123.5.
- ~~Confirm: `shape:` in the personal settings file is an error.~~ Answered: yes. See AC-123.6.
- ~~Confirm: `cplat platform doctor` reports "platform source at v<version>" instead of the missing-stamp warning.~~ Answered: yes. See AC-123.13.
- ~~Confirm: existing specs keep no `shape:` line and only new specs record `shape: platform`.~~ Answered: yes, and every existing spec still passes `cplat spec check`, AC-104.4's `(smoke)` included. See AC-123.15, AC-123.16.

## Changelog

- 2026-10-26 created
- 2026-10-26 amended: the user's answers folded in: no release role and AC-123.23 (`/component:release` refuses), doctor wording in AC-123.13, AC-104.4 named in AC-123.16; all open questions answered
- 2026-10-26 approved
