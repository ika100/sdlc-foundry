---
plan_id: new-app
shape: none   # the platform repo itself; not a key in shapes.yml, so /component:build cannot run here, work by hand or with the generic coder
summary: /system:new creates the gitops-app repo and all component repos from an app.yml and opens one compose PR
story: STORY-033
status: implemented   # t1-t5 done on branch feature/new-app
tasks:
  - id: t1
    title: Manifest loading, validation, ordering and dry-run preview (cplat system new)
    files: [scripts/cplat/newapp.py, scripts/cplat/cplat.py]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Execute the plan, compose PR, failure report and --resume
    files: [scripts/cplat/newapp.py]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: Tests for validation, ordering, dry-run, execute, failure and resume
    files: [tests/cplat/test_newapp.py]
    parallel_safe: true
    depends_on: [t2]
  - id: t4
    title: Slash command, plugin version bump (shared minor)
    files: [plugins/shared/commands/new-app.md, plugins/shared/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, plugins/shared/README.md]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: Docs, changelog and status updates
    files: [docs/CHANGELOG.md, docs/USER-JOURNEY.md, docs/requirements/end-to-end-scenario.md, docs/backlog.md]
    parallel_safe: true
    depends_on: [t2]
---

# Plan: `/system:new`

Implements [STORY-033](../backlog.md). Design follows the existing conventions: the slash command is thin and runs `scripts/cplat/cplat.py`; all logic lives in a tested Python module that returns a `core.Report` (will do / did / next / undo).

## Design decisions

1. **Reuse, do not reimplement.** `newapp.py` builds argv lists and calls `newsvc.resolve` / `newsvc.execute` for every repo and `compose.main([... "add", ... "--pr"])` for the wiring. Rendering, bootstrap commit, topic rules, `.platform-app.yml` and plugin enablement therefore stay identical to `/component:new`. The only new logic is the manifest, the order, the pre-flight and the failure handling.
2. **Manifest is YAML, strict.** Unknown keys are errors (typos should not be silently ignored). The `app` value is both the gitops-app repo name and the `--app <org>/<app>` link, which matches `docs/USER-JOURNEY.md` (`<you>/taskboard`). The end-to-end scenario's `taskboard-app` name is changed to `taskboard` in t5 so the docs agree.
3. **Order is computed, not trusted.** gitops-app, then library shapes, then deployable services, then web (key: `shapes.yml` `library` flag, then shape id order `service-python`, `service-java`, `service-go`, `web-nextjs`). This resolves scenario question Q1.
4. **Pre-flight is all-or-nothing and runs for `--dry-run` too**, so a dry run is a trustworthy prediction. `gh repo view` is read-only. Without `gh`, pre-flight skips the remote checks and the run degrades like `new-service` (local render, printed commands).
5. **Failure model: stop, report, resume.** No rollback (deleting repos needs `delete_repo` and is destructive). The report lists created repos with their undo commands. `--resume` treats an existing local directory whose `.copier-answers.yml` matches the manifest's shape, and an existing GitHub repo, as done and continues.
6. **One compose PR.** `compose add <svc...> --pr` run inside the new gitops-app directory (`--repo-dir`). Compose already verifies the `deployable-service` topic, so the ordering (topics set during creation) is a hard requirement.
7. **Out of scope:** interactive mode, `compose` options per component (`--expose`, env wiring; use `/component:add` afterwards, the next steps say so), `shapes`.

## t1 — Manifest loading, validation, ordering and dry-run preview

**Files:** `scripts/cplat/newapp.py`, `scripts/cplat/cplat.py`
**Goal:** `cplat system new <app.yml> [--org] [--public] [--ref] [--dir] [--no-github] [--skip-tasks] [--dry-run] [--json]` parses and validates the manifest and prints the ordered plan.

**Implementation notes:**
- Register `"new-app": "newapp"` in `COMMANDS` and add a usage line to the module docstring in `cplat.py`.
- `load_manifest(path) -> dict`: `yaml.safe_load`, check keys (`app`, `org`, `visibility`, `components` required/optional as in the story), reuse `newsvc.NAME_RE`, reject duplicates and a component equal to `app`.
- For each component build the argv for `newsvc.resolve` (`[name, *description words, "--type", shape, "--app", f"{org}/{app}" if deployable, "--org", org, "--dir", dir, ...--data k=v]`) and call it; its `PlatformError`s carry the right hints (unknown shape, unknown option, non-empty directory). Prefix the component name in the error so the user finds the line.
- Reject `shape: gitops-app` in `components`. The app repo is resolved the same way with `--gitops` and no `--app`.
- Remote check: for every repo `gh repo view <org>/<name>` must fail with "not found"; reuse `core.has_gh()`.
- `order(components)` as in decision 3.
- `plan(req) -> Report`: one `will_do` line per repo (reusing `newsvc.plan` lines, numbered), then `[outward] open one compose PR adding: …`.

**Acceptance:** dry-run on a 5-component manifest prints seven steps (app repo, five repos, compose PR) in the right order and creates nothing; each validation case in the story fails with a `fix:` line.

## t2 — Execute, compose PR, failure report and `--resume`

**Files:** `scripts/cplat/newapp.py`
**Goal:** the non-dry-run path.

**Implementation notes:**
- Loop `newsvc.execute(req)` per repo in order; collect each `Report`. On `PlatformError` or any exception: build a failure `Report` (`did` = created repos, `next_steps` = `new-app <manifest> --resume`, `undo` = union of the per-repo undo commands) and exit non-zero via `core.PlatformError` with that text as the hint.
- `--resume`: skip a component when the target directory contains a repo with the right shape and (with `gh`) the GitHub repo exists. Skipped repos show as `already exists` in `did`.
- After the loop (GitHub mode only): run `compose.main(["add", *deployable_names, "--repo-dir", str(app_dir), "--pr"])`; capture its PR URL from the report. In `--no-github` mode print the commands (as `new-service` does).
- `Report.data` holds `repos`, `pr`, and the paths, for `--json`.
- `next_steps`: `cd <app> && devbox run cluster-up` after merging the PR; "adjust env wiring or `--expose` with `/component:add`"; "start a feature in any repo with `/component:build`".

**Acceptance:** with a faked `gh` and `--skip-tasks`, a three-component manifest produces four local repos, calls `compose add` once with exactly the deployable names, and a forced failure on the third repo yields a report that names the two created repos and `--resume` finishes the rest without recreating them.

## t3 — Tests

**Files:** `tests/cplat/test_newapp.py`
**Goal:** cover the story's acceptance criteria without network or Docker, in the style of `test_newsvc.py` (real local render with `--no-github` / `--skip-tasks`) and `test_gitops.py` (fake `gh`, real `compose`).

**Implementation notes:**
- Validation: parametrized bad manifests, one assertion on the message and hint each (unknown key, bad name, duplicate, shape `gitops-app` in components, unknown shape, unknown `data` key, existing directory, existing remote repo).
- Ordering: shuffled input gives gitops-app → library → services → web.
- Dry-run creates nothing (directory listing before/after).
- Execute: local render of the repos; assert `.platform-app.yml` on services and not on the library; compose called once with the right services.
- Failure and resume: monkeypatch `newsvc.execute` to raise on the third call; assert the report and that `--resume` skips the first two.
- `shapes.py check` and the full `tests/cplat` suite stay green.

**Acceptance:** `devbox run` equivalent of `pytest tests/cplat` passes; the new file adds no network access.

## t4 — Slash command and plugin bump

**Files:** `plugins/shared/commands/new-app.md`, `plugins/shared/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `plugins/shared/README.md`
**Goal:** `/system:new <manifest|--from file> [flags]` available after a version bump.

**Implementation notes:**
- Copy the structure of `plugins/shared/commands/new-service.md` (cached checkout prefix, preview with `--dry-run`, run, relay output, report-issue footer). Keep the description under about 200 characters; always-on descriptions are token-budgeted (CHANGELOG 2.1.0).
- No new settings entry is needed: `uv run * cplat.py *`, `gh repo create * --private *` and `gh repo edit * --add-topic *` are already allowed; `--public` stays in `ask`.
- Bump `shared` 0.7.4 → 0.8.0 in both `plugin.json` and `marketplace.json` (minor: new command).

**Acceptance:** `devbox run validate` passes; the command appears in the plugin README.

## t5 — Docs, changelog, status

**Files:** `docs/CHANGELOG.md`, `docs/USER-JOURNEY.md`, `docs/requirements/end-to-end-scenario.md`, `docs/backlog.md`
**Goal:** the docs describe what exists.

**Implementation notes:**
- CHANGELOG `[Unreleased]`: new command, the manifest format, `--resume`, no-rollback behaviour.
- USER-JOURNEY: add the one-command path next to the step-by-step one.
- End-to-end scenario: remove the "planned, not built" notes for UX-2, use the repo name `taskboard`, update the command-count table to 1.
- Backlog: STORY-033 `planned` → `done`; remove the row from the "not built" table.

**Acceptance:** `python3 scripts/check-links.py` passes; no remaining text calls `new-app` planned.

## Order and parallelism

`t1` and `t4` can start together. `t2` follows `t1` (same file). `t3` and `t5` follow `t2` and can run together. Because this repo has no shape, `/component:build` cannot orchestrate it; run the tasks by hand or with `general-purpose` agents in worktrees, one per parallel-safe group.

## Risks

- **Partial state:** repos are created on GitHub one by one; a crash leaves some behind. Mitigated by `--resume` and an explicit undo list, not by rollback.
- **Rate limits and time:** each `new-service` runs `devbox install` and lockfile tasks; five components take several minutes. Acceptable; the progress lines per repo keep the user informed.
- **Topic timing:** compose rejects a repo without the `deployable-service` topic; creation sets it before compose runs, but GitHub may take a moment to expose it. If a test against real GitHub shows lag, add a short retry in the compose step (not before).
