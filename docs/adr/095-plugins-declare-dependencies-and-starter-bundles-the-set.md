# ADR-095: Plugins declare their dependencies, and `starter` bundles the starter set

**Status:** Accepted (2026-11-10, spec 174)
**Builds on:** [ADR-087](087-user-docs-are-checked-against-the-code.md) (the docs check and its starter set)

## Context

Every live command runs `cplat`, which only the `shared` plugin puts on the PATH. A user who installs `component` alone gets
commands that cannot start, and a newcomer types four `/plugin install` lines before the first command. The starter set was a
constant in `scripts/check-docs.py`, repeated by hand in four pages. Claude Code (checked with 2.1.311) installs, keeps and prunes
the `dependencies` a plugin's `plugin.json` declares, within one marketplace.

## Decision

- Every plugin that holds more than tombstones, except `shared`, declares `"dependencies": ["shared"]` in its `plugin.json`, as a
  bare name. Tombstone-only plugins declare none. The marketplace entries do not repeat the list.
- The plugin `starter` holds nothing but a manifest whose `dependencies` are the starter set (`shared`, `system`, `component`,
  `platform`) and a README. It is the one definition of that set: the docs check reads it, the docs install it.
- Dependencies carry no version ranges: those need a `<plugin>--v<version>` tag per plugin, which this repository does not cut.
  A dependency follows the marketplace's current version.
- `scripts/check-plugin-deps.py` (in `validate`, CI and `ci-local`) refuses a dependency that is not a bare name or
  `name@sdlc-foundry`, names no plugin of the marketplace or a tombstone-only one, names the plugin itself, or closes a cycle.
  `scripts/cplat/plugin_set.py` is the one test of "tombstone-only" for the validator, the docs check and `/platform:doctor`.
- `/platform:doctor` warns below Claude Code 2.1.311 (`doctor.MIN_CLAUDE_VERSION`), where dependencies are not installed, and fails
  when a live plugin is installed without `shared`.

## Consequences

- Installing one plugin is enough for its commands to start; `claude plugin uninstall starter@sdlc-foundry --prune` removes the set.
- A new live plugin must declare `shared`; a new member of the starter set is one line in `plugins/starter`, and the docs check then
  fails every page that installs the set plugin by plugin without it.
- Shape plugins and pipeline plugins do not depend on each other; generated repos keep enabling what they need in
  `.claude/settings.json`.
- An older Claude Code ignores `dependencies`; the doctor's warning and the per-plugin install in the docs cover it.
