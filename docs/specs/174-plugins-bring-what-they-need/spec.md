---
spec_id: 174-plugins-bring-what-they-need
title: Plugins bring what they need, and one plugin installs the starter set
status: approved
priority: P1
shape: platform
tracks: []
---

# 174 — Plugins bring what they need, and one plugin installs the starter set

## Problem

Every live command calls `cplat`, and `cplat` comes from the `shared` plugin. A developer who installs only `component` gets commands that cannot start; the docs made that mistake for several releases (spec 161), and the docs check guards the docs, not a user typing installs. A newcomer types four `/plugin install` lines before the first command.

Claude Code plugins can declare `dependencies` on other plugins of the same marketplace. A manual check on 2026-11-10 with Claude Code 2.1.311 and a local copy of this marketplace showed: installing `component` with `"dependencies": ["shared"]` installs and enables `shared` too (`+ 1 dependency: shared`); disabling `shared` while `component` needs it is refused; `uninstall --prune` offers to remove `shared` afterwards; `shared` installed by hand is marked manually installed and never pruned; a plugin with only `name` and `dependencies` installs all four starter plugins; `claude plugin validate` accepts the manifests.

## Stories

As a developer who works on one component, I want to install only `component` and have it work, so that I do not need the full set or a list of what else to install.

As a newcomer, I want one install command for the starter set, so that I reach `/platform:doctor` in two lines.

As the maintainer, I want the starter set defined in one place, so that the docs, the docs check and the plugin cannot disagree.

## Acceptance criteria

- **AC-174.1** Given every plugin in `.claude-plugin/marketplace.json` that holds more than tombstones, except `shared` itself, when its `plugin.json` is read, then its `dependencies` contain `"shared"` (a bare name, which resolves in this marketplace), so installing it alone also installs `shared`. Tombstone-only plugins (`app`, `gitops`) declare no dependencies.
- **AC-174.2** Given the marketplace, when it is read, then it lists a plugin `starter` whose `plugin.json` has `name`, `version`, `description`, `author`, `license` and `dependencies` exactly `["shared", "system", "component", "platform"]`, and no commands, agents, skills, hooks or bin; `plugins/starter/README.md` says what it installs, that each plugin can still be installed on its own, and how to remove the set (`claude plugin uninstall starter@sdlc-foundry --prune`). Its versions in `plugin.json` and `marketplace.json` match.
- **AC-174.3** Given `devbox run validate` and the CI `validate` job, when a `plugin.json` or a marketplace entry declares `dependencies`, then every entry is a bare name or `name@sdlc-foundry` of a plugin the marketplace lists that is not tombstone-only, no plugin depends on itself, and the dependency graph has no cycle; a violation fails with the plugin and the entry. Version ranges are refused, because this repo does not tag `<plugin>--v<version>` (non-goal).
- **AC-174.4** Given `scripts/check-docs.py`, when it runs, then the starter set is read from `plugins/starter/.claude-plugin/plugin.json` instead of a constant of its own, and a fenced install block that installs `starter@sdlc-foundry` counts as installing the whole starter set; a block with neither `starter` nor the four plugins still fails as in AC-161.3.
- **AC-174.5** Given `docs/QUICKSTART.md`, the README quickstart, the setup chapter of `docs/USER-JOURNEY.md` and the site's "Run it on your laptop" page, when a newcomer reads them, then the install is `/plugin marketplace add ika100/sdlc-foundry` and `/plugin install starter@sdlc-foundry`, with one sentence that each plugin can be installed alone (for example `component`, which brings `shared`) and the minimum Claude Code version of AC-174.6. The quickstart test of AC-161.5 checks this install block.
- **AC-174.6** Given `/platform:doctor`, when Claude Code is older than the minimum version that installs plugin dependencies, then it reports a warning row with the installed and the minimum version and the fix `claude update`; and when a live sdlc-foundry plugin is installed without `shared`, it reports a failing row with the fix `claude plugin install shared@sdlc-foundry`. The minimum version is one constant, named in the quickstart.
- **AC-174.7** Given the plugins changed here, when the change lands, then each one's version is bumped by a minor in both `plugin.json` and `marketplace.json`, the `shared` description names what it holds today (the `cplat` launcher, the quality and security agents and the session hooks) instead of the 4.x `/new-service` command, and a changelog fragment tells users that `starter` exists and that `/plugin marketplace update` followed by a plugin update is all an existing installation needs.

## Non-goals

- Version ranges on dependencies: they need a git tag `<plugin>--v<version>` per plugin; dependencies follow the marketplace's current version, as installs do today.
- Dependencies between shape plugins and the pipeline plugins (for example `svc` on `component`); generated repos keep enabling what they need in `.claude/settings.json`.
- Installing plugins from a committed `.claude/settings.json` in an empty folder; Claude Code does not download plugins it finds only there.
- Removing the per-plugin install from the docs: it stays documented next to `starter`.

## Assumptions

- **A1** The bundle is named `starter` (other option: `sdlc-foundry`, which repeats the marketplace name in `sdlc-foundry@sdlc-foundry`; affects AC-174.2, AC-174.5).
- **A2** The minimum Claude Code version is 2.1.311, the version the manual check passed on, until an older version is shown to work (affects AC-174.6).
- **A3** Every live plugin depends on `shared`, the shape plugins included: their agents run `devbox run` recipes that call `cplat` (affects AC-174.1).

## Open questions

## Changelog

- 2026-11-10 drafted after the manual dependency check; the user asked to write the spec and implement it with the dispatcher, so it is approved with the assumptions above as defaults.
