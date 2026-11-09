---
spec_id: 161-a-tested-quickstart-and-leaner-user-docs
title: A tested quickstart and leaner user docs
status: approved
priority: P1
shape: platform
tracks: []
---

# 161 — A tested quickstart and leaner user docs

## Problem

The platform is about to be promoted, and a newcomer's first five minutes decide whether they stay. Today those minutes break:

- Three getting-started paths disagree. The README quickstart and the user journey install only `shared` and then run `/platform:doctor` and `/system:new`, which live in the `platform` and `system` plugins since 5.0; the user journey even says "you can already create repos with just `shared`". The site's "Your first system" installs `system`, `component`, `instance` and `platform` but not `shared`, which carries the `cplat` launcher every command calls. It never shows its `shop.yml` and runs `/component:new … --system` after `/system:new` already created the components.
- Outdated material is still published: the v3 rename banner on top of the README, field reports of v4.0.0, a design-history scenario full of 4.x commands, a 4.x mapping table in the domain model, and plugin READMEs that bootstrap with `/shared:new-service`.
- The README is 213 lines and mixes the pitch with a full command table, maintainer instructions and legal text; the site's "Get started" opens with performance tables before the first step.

Nothing tests what the docs tell a user to do. Links are checked (`scripts/check-links.py`, the site's link validator) and some specs assert single sentences, but no check knows whether a slash command, flag, plugin, `devbox run` recipe or manifest named in the docs exists and works. That is how the broken quickstart survived several releases.

## Stories

As a newcomer, I want one quickstart that works as written, says how long each step takes and what I will see, so that I get a system running without reading the rest of the docs.

As the maintainer, I want CI to fail when a user-facing page names a command, flag, plugin, recipe or manifest that does not exist, so that the docs stay correct as the platform changes.

As a reader of the README or the site, I want the current story without history and internal spec numbers, so that I understand the platform quickly.

## Acceptance criteria

- **AC-161.1** Given the user-facing pages (README, `docs/QUICKSTART.md`, the guides synced to the site, the hand-written site pages and the plugin READMEs), when `python3 scripts/check-docs.py` runs, then it fails and names file and line for every slash command `/<plugin>:<command>` that does not exist or is a tombstone, every `--flag` written after a slash command in code that its command file does not name (`[flags]` in the usage allows any), every `/plugin install <name>@sdlc-foundry` whose plugin does not exist or holds only tombstones, and every `devbox run <recipe>` that no template's `devbox.json` or this repo's `devbox.json` defines (recipes a repo owns itself, such as `ci-extra`, are allowed). A tombstone may appear in a `## … 4.x …` section or on a line that also names its replacement. Pages marked `<!-- historical -->`, the changelog, ADRs, specs and the READMEs of tombstone-only plugins are not checked.
- **AC-161.2** Given a fenced YAML block on a checked page that has the top-level keys `system` and `components`, when `check-docs.py` runs, then the block is validated as a system manifest with the same loader `cplat system new` uses, and an invalid block fails the check with its file and line.
- **AC-161.3** Given a page that installs plugins in fenced code blocks, when `check-docs.py` runs, then the installed set includes `shared` and the starter plugins `system`, `component` and `platform`, defined once in the script, so no page can again install a set that cannot run its own commands.
- **AC-161.4** Given CI and `devbox run quality`, when a pull request changes the docs, then `check-docs.py` runs in both, next to `check-links.py`.
- **AC-161.5** Given `docs/QUICKSTART.md`, when the fast test suite runs, then a test takes the manifest block and the install block from the file and runs `cplat system new <manifest> --no-github` with them to a gitops-app repo and one repo per component, so the quickstart's manifest is the tested one.
- **AC-161.6** Given `docs/QUICKSTART.md`, when a newcomer reads it, then it is the single getting-started page: prerequisites with one check (`/platform:doctor`), the starter install, the full sample manifest, and per step the time it takes, what they will see and what to do when it fails; it ends with "what just happened" and next steps. The site shows it as the first page of "Get started", and the README and the user journey link to it instead of repeating it.
- **AC-161.7** Given the README, when it is read, then it has the pitch, the demo, a short quickstart that links to `docs/QUICKSTART.md`, links into the docs, and the disclaimer, privacy, contributing and license sections, in at most 120 lines. The v3 rename banner and the full command table are gone (the generated command reference replaces it), and the maintainer's "Updates" section moves to CONTRIBUTING.
- **AC-161.8** Given the outdated material, when the change lands, then the v4 field reports and the two design-history pages are no longer on the site and carry a "Historical" note in the repository, the 4.x→5.0 mapping tables move from `DOMAIN-MODEL.md` into the migration section of `ADOPTING.md`, the plugin READMEs name only 5.x commands, and the user journey's setup chapter installs the starter set and names `devbox run cluster-up` for a local cluster.
- **AC-161.9** Given the site navigation, when a visitor opens "Get started", then the order is Quickstart, Run it on your laptop, Watch a real run; "Performance measurements" is under Reference; and the landing page's first call to action leads to the quickstart.
- **AC-161.10** Given the newcomer pages (README, `docs/QUICKSTART.md`, the user journey, how it works, and the site's get-started, concepts and scenarios pages), when `check-docs.py` runs, then it fails on a spec number (`spec NNN`) or criterion id (`AC-NNN.n`) in their body text; spec references stay allowed in a closing section whose heading starts with "Background".

## Non-goals

- A bundle plugin that installs the whole set in one command.
- Running the recorded journey automatically per release; it stays a manual run that updates the performance page.
- Letting the cluster e2e (`tests/e2e/run.sh`) execute marked doc snippets.
- Rewriting the deep guides (unattended delivery, domain model, agents) for jargon; only their outdated parts change here.

## Assumptions

- **A1** The starter set is `shared`, `system`, `component` and `platform`; `instance`, `resource`, `api`, `issue` and the shape plugins are listed as optional, and generated repos enable the rest through their `.claude/settings.json` (other option: a bundle plugin; affects AC-161.3, AC-161.6).
- **A2** Historical pages stay in the repository with a note and leave the site, rather than being deleted (other option: delete them; affects AC-161.8).
- **A3** The quickstart test stops at `cplat system new --no-github`; the cluster and a shipped feature stay covered by the cluster e2e and the recorded journey (other option: a cluster test driven by the quickstart; affects AC-161.5).
- **A4** The jargon rule covers the newcomer pages only, so the deep guides can keep provenance until a later round (other option: every guide; affects AC-161.10).

## Open questions

## Changelog

- 2026-11-09 drafted from the documentation review of 2026-11-08; the user asked to write the spec and start the implementation, so it is approved with the assumptions above as defaults.
- 2026-11-09 amended during the build: flags come from the whole command file (usage lines are incomplete, e.g. `--type` of `/component:add`), install blocks count only in fenced code, 4.x sections may name tombstones, and the 4.x tables go to the existing migration section of `ADOPTING.md` instead of `UPGRADES.md`.
