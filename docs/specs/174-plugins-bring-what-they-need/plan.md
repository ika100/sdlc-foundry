---
spec_id: 174-plugins-bring-what-they-need
shape: platform
spec_hash: 897b6f331002
summary: Live plugins depend on shared, a starter bundle plugin installs the starter set, a validator guards dependencies, the docs check and doctor follow
tasks:
  - id: t1
    title: Declare dependencies on shared, add the starter plugin, bump versions
    files: [.claude-plugin/marketplace.json, plugins/svc/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, plugins/api/.claude-plugin/plugin.json, plugins/resource/.claude-plugin/plugin.json, plugins/instance/.claude-plugin/plugin.json, plugins/issue/.claude-plugin/plugin.json, plugins/platform/.claude-plugin/plugin.json, plugins/cluster/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/shared/README.md, plugins/starter/.claude-plugin/plugin.json, plugins/starter/README.md, docs/adr/README.md, docs/changelog.d/174-plugins-bring-what-they-need.added.md]
    covers: [AC-174.1, AC-174.2, AC-174.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: plugin_set module and the plugin dependency validator in validate, CI and ci-local
    files: [scripts/cplat/plugin_set.py, scripts/check-plugin-deps.py, devbox.json, .github/workflows/ci.yml, scripts/ci-local.sh]
    covers: [AC-174.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: The docs check reads the starter set from the starter plugin
    files: [scripts/check-docs.py]
    covers: [AC-174.4]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
  - id: t4
    title: Doctor warns below the minimum Claude Code and fails without shared
    files: [scripts/cplat/doctor.py]
    covers: [AC-174.6]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t5
    title: Two-line install on the quickstart, README, user journey and laptop page
    files: [docs/QUICKSTART.md, README.md, docs/USER-JOURNEY.md, site/src/content/docs/get-started/local-cluster.md]
    covers: [AC-174.5, AC-174.6]
    parallel_safe: true
    depends_on: [t3, t4]
    done: true
---

# Plan — 174 Plugins bring what they need, and one plugin installs the starter set

The contract is in [design.md](design.md); the decision record is
[ADR-095](../../adr/095-plugins-declare-dependencies-and-starter-bundles-the-set.md) (written, with an addendum to ADR-087).
Levels: t1, t2 → t3, t4 → t5.

## t1 — Declare dependencies on shared, add the starter plugin, bump versions

**Files:** `.claude-plugin/marketplace.json`, the `plugin.json` of svc, web, svc-go, svc-java, system, component, api, resource,
instance, issue, platform, cluster and shared, `plugins/shared/README.md`, `plugins/starter/.claude-plugin/plugin.json`,
`plugins/starter/README.md`, `docs/adr/README.md`, `docs/changelog.d/174-plugins-bring-what-they-need.added.md`
**Covers:** AC-174.1, AC-174.2, AC-174.7
**Goal:** every live plugin installs `shared` with it, `starter` exists as a bundle, the versions and the `shared` description are
current, and users are told.

**Implementation notes:**
- Add `"dependencies": ["shared"]` (bare name) to the 12 live plugins' `plugin.json`; `shared`, `app`, `gitops` get none. Do not
  add `dependencies` to marketplace entries (design, Decisions).
- `plugins/starter/.claude-plugin/plugin.json` with exactly the six keys of design.md; no other directory under `plugins/starter/`.
- Marketplace entry for `starter` as in design.md, appended after `cluster`.
- `plugins/starter/README.md`: what it installs (the four names), that each plugin can still be installed on its own (inline code,
  e.g. `/plugin install component@sdlc-foundry`, which brings `shared`), removing the set with
  `claude plugin uninstall starter@sdlc-foundry --prune`, the minimum Claude Code 2.1.311. Its one fenced install block holds only
  the two lines of design.md (the docs check reads this README once t3 lands).
- `shared` description: the design.md text, identical in `plugin.json` and `marketplace.json`. In `plugins/shared/README.md`
  replace the "Enable this plugin on every repo…" usage note with: every other live plugin declares it as a dependency, so it is
  installed with them.
- Minor bump of each changed plugin from its version on `main` at build time, both files (table in design.md); `starter` starts at
  1.0.0. `app` and `gitops` keep their versions.
- `docs/adr/README.md`: add the row for ADR-095 after 093 (one sentence: live plugins depend on `shared` by bare name, `starter`'s
  dependencies are the starter set, no version ranges, `check-plugin-deps.py`, doctor minimum 2.1.311). `scripts/shapes.py check`
  fails without it.
- Changelog fragment (`added`): bold summary ending `(spec 174).`, then: `/plugin install starter@sdlc-foundry` installs `shared`,
  `system`, `component` and `platform`; each plugin installed alone brings `shared`; Claude Code 2.1.311 or later; an existing
  installation needs only `/plugin marketplace update` followed by a plugin update (`claude plugin update <name>@sdlc-foundry`);
  link `../adr/094-….md`.

**Done when:** the AC-174.1, AC-174.2 and AC-174.7 tests pass; `devbox run validate` (version match) and
`uv run scripts/shapes.py check` pass.

## t2 — plugin_set module and the plugin dependency validator in validate, CI and ci-local

**Files:** `scripts/cplat/plugin_set.py`, `scripts/check-plugin-deps.py`, `devbox.json`, `.github/workflows/ci.yml`,
`scripts/ci-local.sh`
**Covers:** AC-174.3
**Goal:** a stdlib-only module that is the one definition of the catalog, "tombstone-only", dependency-entry parsing and the starter
set, and a validator that refuses bad dependencies in every place the manifests are validated.

**Implementation notes:**
- `plugin_set.py`: the API in design.md. `is_tombstone_only` reads the front matter of each `commands/*.md` (text between the first
  two `---` lines) for a `moved-to:` key; no yaml import. `starter(root)` maps each dependency through `dependency_name` and raises
  ValueError on an entry it cannot read.
- `check-plugin-deps.py`: stdlib only, `--root DIR` (default: the repo root), `problems(root)` importable; puts `scripts/cplat` on
  `sys.path` relative to its own file, not `--root`. Every line and exit code exactly as the design.md table.
- Read each catalog entry's `plugin.json` through `plugin_set.plugin_dir`; check both its `dependencies` and the entry's own, if any.
- Cycle detection on the union graph (DFS with colours); report each cycle once, rotated to start at its alphabetically first name.
- Wire `python3 scripts/check-plugin-deps.py`: append to the `validate` recipe in `devbox.json` (after `check-settings.py`), a step
  "plugin dependencies name live plugins of this marketplace (spec 174)" in the `validate-manifests` job of `ci.yml`, and in
  `ci-local.sh`'s first step after the version loop.
- The `validate` recipe must stay a single JSON string; keep `jq` checks first.

**Done when:** the AC-174.3 tests pass (fixtures under `--root`); `devbox run validate` and `scripts/ci-local.sh`'s first step pass
on the repo (with or without t1: zero declarations is `OK: 0 plugin(s) …`).

## t3 — The docs check reads the starter set from the starter plugin

**Files:** `scripts/check-docs.py`
**Covers:** AC-174.4
**Goal:** the starter set has one definition, and `starter@sdlc-foundry` is a complete install.

**Implementation notes:**
- `import plugin_set` (the script already puts `scripts/cplat` on `sys.path`); `STARTER = plugin_set.starter(ROOT)`; remove the literal
  tuple and its comment's claim that it is defined here.
- `live_plugins(cmds)` keeps its signature (the 161 and 173 tests call it) and returns the plugin directories with a `plugin.json`
  that `plugin_set.is_tombstone_only` rejects; `starter` becomes live, so its README is checked.
- In `check_page`, after scanning: when `plugin_set.STARTER` is in `installed`, add every name of `STARTER` before computing `missing`.
  The message for an incomplete block is unchanged.
- Update the module docstring (starter set source, `starter` counts as the set).

**Done when:** the AC-174.4 tests and the existing AC-161.1, AC-161.3 and 173 docs tests pass;
`uv run --with-requirements requirements-test.txt python scripts/check-docs.py` passes on the repo.

## t4 — Doctor warns below the minimum Claude Code and fails without shared

**Files:** `scripts/cplat/doctor.py`
**Covers:** AC-174.6
**Goal:** `/platform:doctor` tells a user on an old Claude Code to update, and one who lacks `shared` how to install it.

**Implementation notes:**
- `MIN_CLAUDE_VERSION = "2.1.311"` next to `MARKETPLACE`.
- In `check_tools()`, right after the `claude` row when `claude` is on PATH: `run(["claude", "--version"], check=False, timeout=10)`,
  catching `core.PlatformError` (timeout); first `\d+\.\d+\.\d+` of stdout; compare with `core.vtuple`; rows exactly as design.md;
  no row when the version cannot be read.
- In `check_plugins()`, after the `plugins` row (stale or ok): the `plugin shared` FAIL row of design.md; the live test is
  `plugin_set.is_tombstone_only(plugin_set.plugin_dir(PLATFORM_ROOT, entry))` on the catalog entry of each installed name.
- The "none installed" fix becomes `/plugin marketplace add ika100/sdlc-foundry && /plugin install starter@sdlc-foundry`.
- Do not add a top-level check function or change `run_checks`: tests stub `check_tools` and `check_plugins` by name.
- Do not change `plugins/platform/commands/doctor.md` (a prompt change needs a rules entry and the eval gate).

**Done when:** the AC-174.6 doctor tests pass, and `tests/cplat/test_update_doctor.py`, `test_notify.py` and
`test_122_producers_doctor.py` still pass.

## t5 — Two-line install on the quickstart, README, user journey and laptop page

**Files:** `docs/QUICKSTART.md`, `README.md`, `docs/USER-JOURNEY.md`, `site/src/content/docs/get-started/local-cluster.md`
**Covers:** AC-174.5, AC-174.6
**Goal:** a newcomer installs the platform with two lines and knows each plugin works alone and which Claude Code it needs.

**Implementation notes:**
- Replace the five-line block on QUICKSTART (step 1), README (Quickstart) and USER-JOURNEY (setup, before Chapter 1) with the fenced
  `text` block of design.md; keep "Restart Claude Code".
- Add on each page, outside the block, one sentence: `starter` installs `shared`, `system`, `component` and `platform`; each plugin
  can be installed alone (for example `component`, which brings `shared`); plugins bring their dependencies from Claude Code 2.1.311
  (`claude update`). On QUICKSTART also put "2.1.311 or later" in the Claude Code row of "Before you start".
- QUICKSTART: rewrite "The four plugins are the starter set" so it names `starter`; keep the sentence about generated repos enabling
  the rest.
- `local-cluster.md` ("Run it on your laptop") has no install today: add a short opening section with the same block and sentence
  before "In the GitOps repository".
- No spec numbers or criterion ids on these pages (they are reader pages); README stays at most 120 lines.
- Never put a single-plugin install in a fenced block.

**Done when:** the AC-174.5 tests (including the rewritten AC-161.5 and AC-161.8 assertions) and the AC-174.6 test that the
quickstart names `doctor.MIN_CLAUDE_VERSION` pass; `check-docs.py` and `check-links.py` pass.
