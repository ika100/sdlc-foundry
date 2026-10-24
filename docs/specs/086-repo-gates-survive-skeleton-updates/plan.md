---
spec_id: 086-repo-gates-survive-skeleton-updates
spec_hash: 7a0226c6fb44
summary: ci-extra recipe and CI check, kept repo permissions, a project notes file, and an update report that lists every lost customisation against a baseline render
tasks:
  - id: t1
    title: gates.py knows ci-extra (doctor check gate ci = CI workflow)
    files: [scripts/cplat/gates.py]
    covers: [AC-086.7, AC-086.8, AC-086.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Every template's ci recipe ends by running ci-extra
    files: [templates/service-python/devbox.json, templates/library-python/devbox.json, templates/gitops-app/devbox.json, templates/service-go/devbox.json.jinja, templates/service-java/devbox.json.jinja, templates/web-nextjs/devbox.json.jinja]
    covers: [AC-086.1, AC-086.2, AC-086.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Every template's CI workflow has a ci-extra check
    files: [templates/service-python/.github/workflows/ci.yml, templates/library-python/.github/workflows/ci.yml, templates/gitops-app/.github/workflows/ci.yml, templates/service-go/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml, shapes.yml]
    covers: [AC-086.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Project notes file and the "Where your additions go" section in every template
    files: [templates/service-python/CLAUDE.md, templates/library-python/CLAUDE.md, templates/gitops-app/CLAUDE.md.jinja, templates/service-go/CLAUDE.md.jinja, templates/service-java/CLAUDE.md.jinja, templates/web-nextjs/CLAUDE.md.jinja, templates/service-python/.claude/project-notes.md, templates/library-python/.claude/project-notes.md, templates/gitops-app/.claude/project-notes.md, templates/service-go/.claude/project-notes.md, templates/service-java/.claude/project-notes.md, templates/web-nextjs/.claude/project-notes.md, templates/service-python/copier.yml, templates/library-python/copier.yml, templates/gitops-app/copier.yml, templates/service-go/copier.yml, templates/service-java/copier.yml, templates/web-nextjs/copier.yml]
    covers: [AC-086.15, AC-086.16]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: settingsmerge.py keeps repo permission entries and drops platform-removed ones
    files: [scripts/cplat/settingsmerge.py]
    covers: [AC-086.10, AC-086.11, AC-086.12]
    parallel_safe: true
    depends_on: []
  - id: t6
    title: Docs, the update-service command and the shared plugin version
    files: [docs/ADOPTING.md, docs/templates.md, docs/CHANGELOG.md, plugins/shared/commands/update-service.md, plugins/shared/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-086.12, AC-086.13]
    parallel_safe: true
    depends_on: []
  - id: t7
    title: update-service renders a baseline, moves gates into ci-extra, merges settings and reports what was lost
    files: [scripts/cplat/update.py]
    covers: [AC-086.4, AC-086.6, AC-086.10, AC-086.11, AC-086.12, AC-086.13, AC-086.14, AC-086.16]
    parallel_safe: true
    depends_on: [t1, t5]
  - id: t8
    title: The shape contract enforces ci-extra and the notes file; cplat shape check
    files: [scripts/shapes.py, scripts/cplat/shapecmd.py, scripts/cplat/cplat.py]
    covers: [AC-086.5, AC-086.15, AC-086.16]
    parallel_safe: true
    depends_on: [t1, t2, t3, t4]
    done: true
---

# Plan — 086 Repo gates survive skeleton updates

The contract (exact recipe text, CI job, doctor outcomes, settings merge, the update's text and `--json` output, the
shape-check errors) is in [design.md](design.md). The decision behind it is
[ADR-031](../../adr/031-repo-owned-companions-for-skeleton-files.md), which is already written and indexed. Acceptance tests go in
`tests/cplat/` and name the AC ids. Update tests monkeypatch `update.render_baseline`, because CI checkouts may have
no tags.

Levels: t1, t2, t3, t4, t5, t6 → t7, t8.

## t1 — gates.py knows ci-extra (doctor check gate ci = CI workflow)

**Files:** scripts/cplat/gates.py
**Covers:** AC-086.7, AC-086.8, AC-086.9
**Goal:** `cplat doctor` treats `ci-extra` as part of the gate chain: it shows what `ci-extra` runs, warns when CI does
not run it, and points gates that only `ci` runs to `ci-extra`.

**Implementation notes:**
- Add `CI_EXTRA = "ci-extra"` and `CI_EXTRA_STEP` (the exact decoded string from design.md) plus `chain(cmd) -> list[str]`
  (the `devbox run <name>` steps of a recipe, in order). Use `chain` where `check_gates` now uses `re.findall`.
- Never collapse `ci-extra` with `_real` (a `ci-extra` that is only `devbox run chart-lint` must stay `ci-extra`).
- Implement the four rows of the "gate ci = CI workflow" table in design.md in that order of precedence: the repo
  defines `ci-extra` but the workflow has no `ci-extra` gate → warn, fix `/shared:update-service`. Otherwise equal → ok with the
  detail `quality → test → security → ci-extra (chart-lint)`. Otherwise extra gates in `ci` → warn with the "move … into
  ci-extra" fix line, which includes the recipe line to write. Otherwise the existing warning.
- `ci_gaps` and `GATES` stay unchanged (template gates only).

**Done when:** the AC-086.7–9 tests and the existing `tests/cplat/test_gates.py` pass.

## t2 — Every template's ci recipe ends by running ci-extra

**Files:** templates/service-python/devbox.json, templates/library-python/devbox.json, templates/gitops-app/devbox.json, templates/service-go/devbox.json.jinja, templates/service-java/devbox.json.jinja, templates/web-nextjs/devbox.json.jinja
**Covers:** AC-086.1, AC-086.2, AC-086.4
**Goal:** `devbox run ci` runs the template's gates and then `ci-extra` when the repo defines it, and nothing more when
it does not.

**Implementation notes:**
- Append ` && ` + `CI_EXTRA_STEP` to each `ci` recipe. Escape the inner quotes for JSON (`'\"ci-extra\"[[:space:]]*:'`) and keep
  the column alignment of the recipe block. Leave the gates before it exactly as they are.
- No template defines a `ci-extra` key.
- `service-python` and `library-python` render every file through Jinja: the step contains no `{{`, `{%` or `{#`, so it
  needs no escaping. Confirm by rendering once with `copier copy`.

**Done when:** the AC-086.1 and AC-086.2 tests pass. They run the rendered `ci` command under `bash` with a stub
`devbox` on `PATH` that records the recipe names and fails a chosen one. The AC-075.1 test
(`test_devbox_ci_runs_the_workflow_gates_in_job_order`) passes once t3 is in as well.

## t3 — Every template's CI workflow has a ci-extra check

**Files:** templates/service-python/.github/workflows/ci.yml, templates/library-python/.github/workflows/ci.yml, templates/gitops-app/.github/workflows/ci.yml, templates/service-go/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml, shapes.yml
**Covers:** AC-086.3
**Goal:** every PR has a `ci-extra` check that runs `devbox run ci-extra`, fails when it fails, and passes with a notice
when the repo has no such recipe.

**Implementation notes:**
- Add the `ci-extra` job from design.md directly after the `security` job, with the same action pins as the
  neighbouring jobs. gitops-app's checkout takes `ref: ${{ inputs.ref }}` like its other jobs. web-nextjs adds the guarded
  `devbox run install` step before `devbox run ci-extra`.
- In `service-python` and `library-python`, write every `${{ … }}` as `${{ '{{' }} … {{ '}}' }}` (CLAUDE.md, Jinja
  gotcha). Do not escape in the other four templates, which do not render `ci.yml`.
- Add `"ci-extra"` to every shape's `ci_checks` in `shapes.yml`.
- Run `python3 scripts/pin-actions.py --check` and `actionlint` on a rendered workflow.

**Done when:** the AC-086.3 tests pass. They parse each rendered workflow, find the job and its guarded steps, and run the
detection step's script with a temp `devbox.json` and `GITHUB_OUTPUT`. `test_every_shape_lists_ci_checks_that_exist_in_its_workflow`
must pass too.

## t4 — Project notes file and the "Where your additions go" section in every template

**Files:** the six `CLAUDE.md[.jinja]`, the six `.claude/project-notes.md` (new), the six `copier.yml` (paths in the metadata)
**Covers:** AC-086.15, AC-086.16
**Goal:** new repos say in `CLAUDE.md` where each kind of addition belongs, and load an empty, repo-owned notes file
in every session.

**Implementation notes:**
- Create `templates/<t>/.claude/project-notes.md` as an empty file in each template.
- Add `.claude/project-notes.md` to `_skip_if_exists` in each `copier.yml`.
- Add the `## Where your additions go` section from design.md to each `CLAUDE.md`. It names `ci-extra`, the repo's own
  recipes in `devbox.json`, its own permission entries in `.claude/settings.json`, its own workflow files in
  `.github/workflows/`, and `.claude/project-notes.md`.
- End each `CLAUDE.md` with `## Project notes`, one sentence, and `@.claude/project-notes.md` on its own line (not in a
  code span).
- In each recipe table, the `ci` row says that `ci` ends with `ci-extra` when the repo defines it.

**Done when:** the AC-086.15 and AC-086.16 tests pass. They render each shape with `newsvc --skip-tasks`, and check the
section, the import, an empty notes file, and that an update leaves an edited notes file unchanged.

## t5 — settingsmerge.py keeps repo permission entries and drops platform-removed ones

**Files:** scripts/cplat/settingsmerge.py
**Covers:** AC-086.10, AC-086.11, AC-086.12
**Goal:** a pure, unit-testable merge of `.claude/settings.json`, used by the update in t7.

**Implementation notes:**
- `merge_settings(project, template, baseline)` and `merge_settings_file(repo, before, baseline)` with the exact rules
  and report shape in design.md (`kept`, `removed_by_platform`, `replaced`).
- With `baseline=None`, keep every project entry the template lacks and remove nothing.
- Keep the template's text byte-for-byte and insert kept entries before each list's closing `]`. Reuse the
  bracket-matching approach of `update._close` (copy the small helper, so there is no import cycle with `update.py`). Fall back
  to `json.dumps(indent=2)`.
- If the project JSON is invalid, return the note from design.md and leave the template's file in place.

**Done when:** the AC-086.10, AC-086.11 and AC-086.12 (settings part) unit tests pass on `merge_settings`.

## t6 — Docs, the update-service command and the shared plugin version

**Files:** docs/ADOPTING.md, docs/templates.md, docs/CHANGELOG.md, plugins/shared/commands/update-service.md, plugins/shared/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-086.12, AC-086.13
**Goal:** users and the agent that relays the update know where additions go and what the `lost` list means.

**Implementation notes:**
- `update-service.md` step 3: relay the `moved to ci-extra`, settings kept/removed lines and every `replaced …` line
  verbatim, and say that an empty `lost` (`--json`) means nothing the repo added was lost. Drop the "review MODIFIED"
  reminder in favour of those lines.
- `docs/ADOPTING.md` Step 5 point 2/3: companions instead of `git checkout -- <file>`, and a link to ADR-031.
- `docs/templates.md`: add the new **[checked]** contract items (the `ci` step, the `ci-extra` job, the notes file and the
  `CLAUDE.md` section and import).
- `docs/CHANGELOG.md` under `[Unreleased]`: one entry, plus a migration note: run `/shared:update-service`, and gates in
  `ci` move to `ci-extra` automatically.
- Bump the shared plugin by a patch in both `plugin.json` and `marketplace.json`.

**Done when:** `uv run scripts/check-links.py` (or the repo's link check), `devbox run validate` and
`uv run scripts/shapes.py check` (front matter) pass.

## t7 — update-service renders a baseline, moves gates into ci-extra, merges settings and reports what was lost

**Files:** scripts/cplat/update.py
**Covers:** AC-086.4, AC-086.6, AC-086.10, AC-086.11, AC-086.12, AC-086.13, AC-086.14, AC-086.16
**Goal:** an update keeps every repo companion, moves repo gates into `ci-extra` once, and its report (`--json`
`lost`) is empty exactly when nothing the repo added was overwritten.

**Implementation notes:**
- `render_baseline(template, old, answers, dest)`: `git archive v<old> templates/<t>` from `PLATFORM_ROOT`, then `copier copy`
  with the pre-update answers, `--defaults --trust --skip-tasks --overwrite`. Return `None` on any failure. Render it only
  when the update changed something, in a `TemporaryDirectory`.
- `merge_devbox(project, template, baseline=None)`: with a baseline, `replaced` lists only entries whose project value
  differs from the baseline's. Without one, the behaviour is unchanged (the existing `test_merge_devbox` cases stay green).
- `move_ci_gates(project, template, baseline)` per design.md. It compares by `gates._real` on the merged scripts. When
  gates are moved, insert `"ci-extra": "devbox run g1 && devbox run g2"` through the existing `_insert_kept` path. When the
  repo already has `ci-extra`, those gates go in `dropped_gates` with the line that would add them.
- `scripts ci` is not a replaced entry when its chain, minus the moved gates, equals the baseline's chain (design.md).
- Capture `.claude/settings.json` before copier, then call `settingsmerge.merge_settings_file` with the baseline's
  parsed settings.
- Customised skeleton files: compare `git show HEAD:<path>` with `<baseline>/<path>` for each path in `modified`, except
  `devbox.json`, `.claude/settings.json`, `.copier-answers.yml` and `.platform-version`. With no baseline every such
  path counts.
- Build `lost` and the `where` hints from design.md's table. Add `baseline`, `devbox.moved_to_ci_extra`,
  `devbox.dropped_gates`, `settings` and `lost` to `r.data`. Replace the "review MODIFIED skeleton files" line with one
  `replaced …` line per `lost` entry, and add the did/next lines from design.md.
- Leave `.claude/project-notes.md` alone. It is project-owned through `_skip_if_exists`, so a repo that lacks it does
  not get it from an update (`drop_new_project_owned_files`). Workflow files the template does not ship are never
  touched (AC-086.14); a test only confirms it.
- The update must still complete when the baseline fails (a `null` baseline is reported, not raised).

**Done when:** the AC-086.4, .6, .10–.14 and .16 (update part) tests pass, together with all existing
`tests/cplat/test_update_doctor.py` tests. The no-op update still creates no branch and renders no baseline.

## t8 — The shape contract enforces ci-extra and the notes file; cplat shape check

**Files:** scripts/shapes.py, scripts/cplat/shapecmd.py, scripts/cplat/cplat.py
**Covers:** AC-086.5, AC-086.15, AC-086.16
**Goal:** a template without the `ci-extra` hooks or the notes file fails `cplat shape check`, so a future shape
cannot skip them.

**Implementation notes:**
- In `shapes.py`, add `CI_EXTRA_STEP` (the same string as `gates.CI_EXTRA_STEP`; a test asserts that they are equal) and
  the six `check_contract` errors listed in design.md. Decode the `ci` recipe from the devbox text with a regex plus
  `json.loads`, the same way `test_ci_gates.recipe` does.
- In `shapecmd.py`, `cplat shape check` puts `PLATFORM_ROOT/scripts` on `sys.path` and returns `shapes.main(["check"])`.
  `cplat shape [--repo DIR]` stays unchanged.
- In `cplat.py`, add `shape check` to the usage docstring line for `shape`.

**Done when:** the AC-086.5 tests pass. Each one copies a template to a temp root, breaks one hook, and expects the named error
(the same pattern as `test_the_shape_contract_requires_the_pin_dev_job`). `shapes.check_contract(...) == []` holds on the
real templates, and `uv run scripts/shapes.py check` is green.
