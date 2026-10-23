# ADR-031 — Repo-owned companions for skeleton files

**Status:** accepted (2026-10-23, spec 086) · **Extends:** spec 060 (`devbox.json` merge)

## Context

`/shared:update-service` overwrites skeleton files (CI workflow, `CLAUDE.md`, `.claude/settings.json`, Dockerfile,
lint config) with the template's version and merges only `devbox.json`, where the template wins on shared recipes. Repos
had no supported place to add to these files. An update therefore silently removed repo gates: ai-ops lost its `chart-lint` gate
when `ci` was reset (#132). It also removed extra CI jobs, permissions for the repo's own tools and project guidance in
`CLAUDE.md`. The report only said "review MODIFIED skeleton files" and did not tell a template change from a lost repo change.
Updates are about to be rolled out to every repo unattended (spec 096), and that needs a reliable "nothing was lost" signal.

## Decision

1. **Skeleton files stay platform-owned and are overwritten. Edits are never merged into them.** Every skeleton file
   that repos extend has a **repo-owned companion** that updates never touch:
   - gates: the `ci-extra` recipe in `devbox.json`. The template's `ci` recipe ends by running it when it exists, and
     every template's CI workflow has a `ci-extra` check (a required check, green when the recipe is absent);
   - other tools: recipes, packages and env vars of the repo's own in `devbox.json` (spec 060);
   - permissions: the repo's own `allow`/`ask`/`deny` entries in `.claude/settings.json`, which the update keeps.
     Entries the platform removed since the repo's version are removed;
   - extra CI jobs: workflow files of the repo's own in `.github/workflows/`;
   - project guidance: `.claude/project-notes.md`. It is created empty, imported by the template's `CLAUDE.md` and
     project-owned (`_skip_if_exists`).
   No template defines a companion's content. `shapes.py check` enforces the hooks (the `ci` step, the `ci-extra` job, the
   notes file and its import).
2. **An update compares against a baseline.** It renders the template as it was at the repo's previous platform
   version with the repo's answers. Only a difference between the repo and that baseline is a repo customisation. When
   no baseline can be rendered, every difference counts. That can over-report losses, but it never misses one.
3. **The update reports every repo customisation it overwrote** in one `lost` list (text and `--json`). Each entry
   names the companion the addition belongs in. An empty `lost` list means nothing the repo added was lost, and it is the merge
   signal for unattended fleet updates.
4. Gates that a repo had chained into the old `ci` recipe are moved into a new `ci-extra` once, automatically, when the
   repo has none yet.

## Consequences

- A skeleton update can no longer weaken a repo's gates or break its unattended runs without saying so.
- `CLAUDE.md` and the CI workflow stay identical across the fleet, so platform changes reach every repo in full.
- Customisations with no companion (Dockerfile, the template's CI jobs, lint config) are still overwritten. They
  show up in `lost` and belong in the platform, proposed through `/shared:report-issue`.
- Any new skeleton file that repos are expected to extend needs a companion and a `shapes.py check` rule before it ships.
- An update renders the template twice when something changed. The baseline needs the platform's `v<version>` tags
  in the checkout that runs `cplat`.

## Not included

- Merging repo edits into skeleton files (a three-way merge like `copier update`).
- Changing `cplat adopt`'s merge of an existing `ci` recipe (spec 071).
