---
spec_id: 086-repo-gates-survive-skeleton-updates
title: Repo gates survive skeleton updates
status: approved
priority: P1
tracks: [132]
---

# 086 — Repo gates survive skeleton updates

## Problem

`/shared:update-service` keeps the `devbox.json` recipes only a repo has (spec 060), but when a repo and the template both define a recipe, the template's version wins. `ci` is a template recipe, so every update resets it and silently drops the repo's own gates: adopting 4.4.0 in ai-ops PR #25 lost the `chart-lint` gate chained into `ci` (#132). The same holds for every other skeleton file repos extend: an extra job in the CI workflow or an extra permission in the committed `.claude/settings.json` is overwritten, and the report only says "review MODIFIED skeleton files". A repo has no supported place for its own additions, so an update can weaken its gates without anyone noticing. This must be fixed before updates are rolled out to every repo unattended (spec 096).

## Stories

As a contributor, I want one place for my repo's own gates that `devbox run ci` and CI both run and that no platform update touches, so that a skeleton update can never remove a gate.

As a contributor, I want the permissions my repo added for its own tools to survive an update, so that unattended runs keep working after it.

As the fleet update (spec 096), I want the update report to say exactly which repo customisations it replaced or dropped, so that I merge only updates that lose nothing.

## Acceptance criteria

- **AC-086.1** Given a repo of any shape whose `devbox.json` defines a `ci-extra` recipe, when `devbox run ci` runs, then it runs the template's gates in their order and then `devbox run ci-extra`, and exits non-zero when `ci-extra` fails; when a template gate fails, `ci-extra` does not run.
- **AC-086.2** Given a repo without a `ci-extra` recipe, when `devbox run ci` runs, then it runs exactly the template's gates (AC-075.1) and passes or fails exactly as it did before this spec.
- **AC-086.3** Given any template's CI workflow and a pull request in a repo that defines `ci-extra`, when CI runs, then a check named `ci-extra` runs `devbox run ci-extra` and is red when it fails, so `cplat pr wait` and `cplat ship land` stop on it; in a repo without the recipe the `ci-extra` check is green and its log says that no `ci-extra` recipe is defined.
- **AC-086.4** Given a repo with a `ci-extra` recipe, when `/shared:update-service` runs, then `ci-extra` is unchanged, is not listed among the replaced entries, and `devbox run ci` still ends by running it.
- **AC-086.5** Given the templates, when `cplat shape check` runs, then it fails for any template that defines a `ci-extra` recipe itself, whose `ci` recipe does not end by running `ci-extra` when the repo defines it, or whose CI workflow has no `ci-extra` check.
- **AC-086.6** Given a repo without `ci-extra` whose `ci` recipe before the update ran `devbox run <gate>` steps that the template's `ci` does not run, when `/shared:update-service` runs, then it creates `ci-extra` running exactly those gates in their original order and the report says `moved to ci-extra: <gates>`; when the repo already has `ci-extra`, it is left unchanged and the report names the dropped gates with the line that would add them.
- **AC-086.7** Given a repo with `ci-extra`, when `cplat doctor` runs, then the check `gate ci = CI workflow` is ok when the gates of `devbox run ci` including `ci-extra` equal the gates the CI workflow runs, and its detail names what `ci-extra` runs (for example `quality → test → security → ci-extra (chart-lint)`).
- **AC-086.8** Given a repo whose `ci-extra` recipe exists but whose CI workflow runs no `ci-extra` check (a repo still on an older platform version), when `cplat doctor` runs, then `gate ci = CI workflow` warns that CI does not run `ci-extra`, with the fix `/shared:update-service`.
- **AC-086.9** Given a repo whose `ci` recipe runs a gate that the CI workflow does not, when `cplat doctor` runs, then the warning's fix says to move that gate into `ci-extra`.
- **AC-086.10** Given a repo whose committed `.claude/settings.json` has permission entries (allow, ask or deny) that the template never had, when `/shared:update-service` runs, then those entries are still there afterwards, the template's entries are updated, and the report lists the kept entries.
- **AC-086.11** Given a permission entry that the template had at the repo's previous platform version and has removed since, when `/shared:update-service` runs, then the entry is removed even if the repo still has it, and the report lists it as removed by the platform.
- **AC-086.12** Given a repo that changed parts of `.claude/settings.json` other than permission entries, or changed a skeleton file it has a companion for (the CI workflow, `CLAUDE.md`), when `/shared:update-service` runs, then the template's version wins and the report names, per file, what was replaced and where the repo's addition belongs instead (`ci-extra`, a workflow file of the repo's own, its own permission entries, the project notes file of AC-086.16).
- **AC-086.13** Given an update run with `--json`, when it finishes, then its output lists every repo customisation the update replaced or dropped (replaced recipes, permission entries removed, settings replaced, modified skeleton files); the list is empty exactly when nothing the repo had added was lost (the fleet update of spec 096 merges only when it is empty).
- **AC-086.14** Given a workflow file in the repo's CI workflows that the template does not ship, when `/shared:update-service` runs, then that file is unchanged and not listed as modified.
- **AC-086.15** Given a new repo of any shape, when it is created, then its `CLAUDE.md` has a section that names the skeleton files updates overwrite and, for each, the repo-owned place for additions: `ci-extra` for gates, its own recipes in `devbox.json`, its own permission entries in `.claude/settings.json`, its own workflow files for extra CI jobs, the project notes file (AC-086.16) for project guidance.
- **AC-086.16** Given a repo of any shape, when it is created, then it has a repo-owned project notes file, created empty, that the template's `CLAUDE.md` loads so agents read it in every session, including unattended ones; when `/shared:update-service` runs, the notes file is never changed, and a repo that lacks it still gets a working `CLAUDE.md` with no error about the missing file.

## Non-goals

- Merging repo edits to other skeleton files (Dockerfile, the template's CI jobs, `CLAUDE.md`) into the template's version; they are reported (AC-086.12, AC-086.13), not merged.
- Changing how `cplat adopt` merges an existing repo's `ci` recipe (spec 071).
- Ordering the CI jobs that build images after `ci-extra`; which jobs wait on which stays as the template defines it.
- Rolling updates out to every repo (spec 096).

## Open questions

- ~~Confirm: when the update finds repo gates in the old `ci` recipe and no `ci-extra`, it moves them into a new `ci-extra` automatically instead of only reporting them?~~ Answered: yes, moved automatically, see AC-086.6.
- ~~Confirm: in a repo without `ci-extra`, the `ci-extra` CI check still appears and passes with a notice, instead of being skipped?~~ Answered: yes, it appears and passes with a notice, see AC-086.3.
- ~~Should this spec also give `CLAUDE.md` a repo-owned companion (a project notes file that the template's `CLAUDE.md` loads and updates never touch, seeded empty at creation)?~~ Answered: yes, see AC-086.16 (and AC-086.12, AC-086.15).

## Changelog

- 2026-10-23 created
- 2026-10-23 open questions answered: repo gates move into `ci-extra` automatically (AC-086.6); the `ci-extra` check always appears (AC-086.3); new AC-086.16 adds a repo-owned project notes file loaded by `CLAUDE.md`, named in AC-086.12 and AC-086.15; AC-086.13 states it is the fleet update's merge signal (spec 096)
- 2026-10-23 approved
