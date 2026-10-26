---
spec_id: 112-fast-cplat-test-job-shared-renders-and
spec_hash: 9ee0c6249ed4
summary: A session-scoped shared-render cache (one build per key per worker, a private copy per test) behind a
  drop-in new_service fixture, the render fixtures moved onto it, a round-robin --shard plugin with per-shard reports,
  4 CI shards plus a coverage check that ci-success needs, and the before/after measurements
tasks:
  - id: t1
    title: Shared-render cache (SharedRenders, RenderFailed) and the shared_renders / new_service fixtures
    files: [tests/cplat/shared_render.py, tests/cplat/conftest.py]
    covers: [AC-112.2, AC-112.5, AC-112.6, AC-112.8, AC-112.15]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Sharding plugin (--shard I/N, --shard-report, round-robin over sorted ids) and scripts/check-shards.py
    files: [tests/cplat/sharding.py, scripts/check-shards.py, tests/cplat/conftest.py]
    covers: [AC-112.10, AC-112.11, AC-112.15]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: Gitops fixtures from the cache (gitops_repo, the composed todo-api repo of alerts_render and staging_093_setting)
    files: [tests/cplat/test_gitops.py, tests/cplat/test_alerts_render.py, tests/cplat/test_staging_093_setting.py]
    covers: [AC-112.1, AC-112.2, AC-112.4, AC-112.7, AC-112.8]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: Service fixtures from the cache (fleet seed, update pair, update/doctor repos, rename, old web repo, generated repos)
    files: [tests/cplat/fleet_world.py, tests/cplat/test_update_lost.py, tests/cplat/test_update_doctor.py,
      tests/cplat/test_rename_migration.py, tests/cplat/test_smoke_091_templates.py, tests/cplat/test_generated_repos.py]
    covers: [AC-112.1, AC-112.2, AC-112.4, AC-112.7, AC-112.8]
    parallel_safe: true
    depends_on: [t1]
  - id: t5
    title: CI runs 4 shards and checks their coverage; ci-success needs the check; docs, changelog, ADR index
    files: [.github/workflows/ci.yml, CONTRIBUTING.md, docs/CHANGELOG.md, docs/adr/README.md]
    covers: [AC-112.10, AC-112.12, AC-112.13, AC-112.14]
    parallel_safe: true
    depends_on: [t2]
  - id: m1
    title: Measure and record (ids before/after, reverse and per-file runs, setup total, shard times, ci wall time)
    files: [docs/specs/112-fast-cplat-test-job-shared-renders-and/measurements.md]
    covers: [AC-112.1, AC-112.3, AC-112.7, AC-112.9, AC-112.12]
    parallel_safe: false
    depends_on: [t3, t4, t5]
human_steps:
  - "After the merge, take the next five pull requests that change code but no smoke-tested template, record each ci
    run's wall time (first job started to ci-success completed, command in measurements.md) in
    docs/specs/112-fast-cplat-test-job-shared-renders-and/measurements.md; AC-112.9 holds when the median is at most 120 s"
---

# Plan — 112 Fast cplat test job: shared renders and sharding

Design: [design.md](design.md) (the contract of the cache, the fixtures, `--shard`, the report and `check-shards.py`).
ADR: [052](../../adr/052-shared-renders-in-the-platform-test-suite.md).

Levels: t1 → t2, t3, t4 (parallel, disjoint files) → t5 → m1. t2 waits for t1 only because both edit
`tests/cplat/conftest.py`.

Before any change, m1's baseline needs the old suite: the coder of t1 (or the orchestrator) saves
`pytest tests/cplat --collect-only -q` of the base commit and its `--durations=0 --durations-min=0` run as the baseline
for m1 (or m1 checks out the merge base in a scratch worktree for it).

## t1 — Shared-render cache and fixtures

**Files:** tests/cplat/shared_render.py, tests/cplat/conftest.py
**Covers:** AC-112.2, AC-112.5, AC-112.6, AC-112.8, AC-112.15
**Goal:** one build per key per test process, a private copy per request, and a failure that every requester sees,
exactly as design.md "Contract" describes.

**Implementation notes:**
- `shared_render.py`: `RenderFailed`, `SharedRenders` (`copy`, `builds`), `service_key`. Each key builds in its own
  fresh subdirectory of `root`; capture stdout/stderr of the build with `contextlib.redirect_stdout/redirect_stderr`
  (the newsvc report is printed with `print`), keep the last 20 lines for the failure message.
- Catch `BaseException` subclasses `Exception` and `SystemExit` (argparse) in the build; never `KeyboardInterrupt`.
  A non-zero return of `newsvc.main` is a failure too.
- Copy with `shutil.copytree(src, dest, symlinks=True)`; an existing empty `dest` is removed first, a non-empty one
  raises `FileExistsError`.
- `conftest.py`: `shared_renders` (session, `tmp_path_factory.mktemp("shared-renders")`) and `new_service`
  (function) built on `service_key` + `newsvc.main`; import `newsvc` inside the fixture, as the other fixtures do.
- No marker, option or environment variable.

**Done when:** the acceptance tests for AC-112.2, AC-112.5, AC-112.6 and AC-112.8 that target the cache and the
fixtures pass, and `pytest tests/cplat -n auto` is still green.

## t2 — Sharding plugin and checker

**Files:** tests/cplat/sharding.py, scripts/check-shards.py, tests/cplat/conftest.py
**Covers:** AC-112.10, AC-112.11, AC-112.15
**Goal:** `--shard I/N` selects a deterministic round-robin slice of the sorted node ids and `--shard-report` writes
what the shard collected and ran; `check-shards.py` proves the union of the shards is the suite.

**Implementation notes:**
- Hooks in `sharding.py`: `pytest_addoption`, `pytest_configure` (validate, `UsageError`), `pytest_collection_modifyitems`
  (`trylast=True`; record the full sorted collection, deselect via `config.hook.pytest_deselected`),
  `pytest_report_header`, `pytest_runtest_logreport` (controller / serial process only), `pytest_sessionfinish`
  (workers: `config.workeroutput["shard_collected"]`; controller / serial: write the report),
  `pytest_testnodedown` with `@pytest.hookimpl(optionalhook=True)`.
- `conftest.py` re-exports the hooks by name (`from sharding import pytest_addoption, ...  # noqa: F401`); there is
  one `pytest_addoption` in the conftest, so merge if one exists.
- Worker detection: `hasattr(config, "workerinput")`. A serial run with `--shard` writes the report itself.
- Differing worker collections: report `"collected": null`, set `session.exitstatus` non-zero.
- `scripts/check-shards.py`: stdlib only, messages and exit codes as in design.md; usable on the reports of a local
  `for i in 1 2 3 4` loop.
- Without `--shard` nothing is deselected, nothing is written, the header is unchanged.

**Done when:** the acceptance tests for AC-112.10 and AC-112.11 that target the plugin and the checker pass; a local
run of the four shards plus `check-shards.py` prints `OK`.

## t3 — Gitops fixtures from the cache

**Files:** tests/cplat/test_gitops.py, tests/cplat/test_alerts_render.py, tests/cplat/test_staging_093_setting.py
**Covers:** AC-112.1, AC-112.2, AC-112.4, AC-112.7, AC-112.8
**Goal:** `gitops_repo` (imported by about 14 files) and the composed `todo-api` repos come from the cache; no test,
assertion or id changes.

**Implementation notes:**
- `gitops_repo(tmp_path, new_service)`: `new_service([...same argv...])`. Its importers keep importing it unchanged
  (fixtures it depends on are found in conftest).
- `test_alerts_render.py::repo` and `test_staging_093_setting.py::app`: one shared key
  ("gitops todo-gitops + compose add todo-api"), built with `shared_renders.copy` from a `new_service` copy, composing
  under `pytest.MonkeyPatch.context()` with a fresh `test_gitops.FakeGh` on `compose.gh`/`promote.gh`, then
  `commit`. The fixture still requests `gh` so later calls in the test see the test's own fake.
- Leave `test_promote_digest.py::at_staging` and every test body as they are.
- Do not touch tests whose subject is the render (design.md "Decisions").

**Done when:** the moved files and every file that imports `gitops_repo` pass in a full run, in reverse order and on
their own; their collected ids are unchanged.

## t4 — Service fixtures from the cache

**Files:** tests/cplat/fleet_world.py, tests/cplat/test_update_lost.py, tests/cplat/test_update_doctor.py,
tests/cplat/test_rename_migration.py, tests/cplat/test_smoke_091_templates.py, tests/cplat/test_generated_repos.py
**Covers:** AC-112.1, AC-112.2, AC-112.4, AC-112.7, AC-112.8
**Goal:** every remaining fixture or setup render that is not the subject of its test comes from the cache.

**Implementation notes:**
- `fleet_world.seed`: function scope, both paths via `new_service` (one key, so one build per worker);
  `World.add` keeps copying from `seed[0]`.
- `test_update_lost.render(parent)` becomes `render(new_service, parent)` (or a fixture-bound helper); `pair` and the
  importers in `test_update_lost_regressions.py` keep working without edits to that file.
- `test_update_doctor.py`: the `repo` fixture and the setup renders in `test_shape_routing`,
  `test_python_service_routes_to_svc_with_migrations`, `test_update_does_not_add_starter_files_to_project_owned_paths`,
  `test_update_keeps_the_web_apps_own_dependencies`, `test_update_that_brings_pin_dev_names_the_token_step` use
  `new_service` (they test update, doctor or routing, not the render).
- `test_rename_migration.py` and `test_smoke_091_templates.py::old_web_repo` likewise; keep
  `test_a_fresh_web_repo_has_the_playwright_scaffold_by_default_ac_091_16` rendering (AC-112.4).
- `test_generated_repos.py`: `py_on`, `py_off`, `web` become function-scoped copies through `shared_renders.copy`
  with `_render` as the build (key: template + data); the copier command itself is unchanged.

**Done when:** these files and `test_fleet.py`, `test_update_lost_regressions.py` pass in a full run, in reverse order
and on their own; their collected ids are unchanged.

## t5 — CI shards, coverage check, docs

**Files:** .github/workflows/ci.yml, CONTRIBUTING.md, docs/CHANGELOG.md, docs/adr/README.md
**Covers:** AC-112.10, AC-112.12, AC-112.13, AC-112.14
**Goal:** the CI runs the suite in 4 independent shards, checks their union in every run, and `ci-success` stays the
single aggregate.

**Implementation notes:**
- `platform-tests` and `platform-tests-cover` exactly as design.md "CI"; artifact actions use the pins the templates
  already use (`upload-artifact@ea165f8…`, `download-artifact@d3f86a1…`), so `pin-actions.py --check` stays green.
- `ci-success.needs`: add `platform-tests-cover`, keep the list ending `spec-required, pr-title]` (test_claims) and
  `fail-fast: false` on the matrix (test_drift AC-084.2).
- `scripts/ci-local.sh` stays unsharded (no edit).
- `CONTRIBUTING.md` "CI cost": the 4 shards and the coverage check; the test conventions: rendered repos come from
  `new_service` / `shared_renders`, render-subject tests render (ADR-052).
- `docs/CHANGELOG.md` `[Unreleased]`: one bullet "Perf (112): …" with the measured before/after once m1 has them
  (a placeholder sentence without numbers is fine here; m1 does not edit the changelog).
- `docs/adr/README.md`: the index row for ADR-052.
- actionlint (validate-shapes job) must pass on the new jobs.

**Done when:** the acceptance tests reading `ci.yml` (shards, fail-fast, needs, coverage job) pass,
`python3 scripts/pin-actions.py --check` and `python3 scripts/check-links.py` pass, and the PR's own ci run shows four
`cplat unit + integration tests (shard i/4)` jobs and a green `cplat shards cover the suite`.

## m1 — Measure and record

**Files:** docs/specs/112-fast-cplat-test-job-shared-renders-and/measurements.md
**Covers:** AC-112.1, AC-112.3, AC-112.7, AC-112.9, AC-112.12
**Goal:** the numbers the speed criteria ask for, recorded in the spec directory and copied into the PR description.

**Implementation notes:**
- AC-112.1: `pytest tests/cplat --collect-only -q` on the merge base and on the branch; record the diff (only the new
  acceptance tests of this spec may differ, and they are named).
- AC-112.3: a full run in reverse order (`uv run --with pytest-reverse ... pytest tests/cplat -n auto --reverse`) and
  each `tests/cplat/test_*.py` on its own; record pass/fail per run.
- AC-112.7: on the same 12-core machine, `pytest tests/cplat -n auto --durations=0 --durations-min=0`, sum the
  `setup` lines, before (479 s on 2026-10-26) and after; the after total must be at most 239.5 s. If it is not, stop
  and report it rather than widening the scope.
- AC-112.12: from the PR's ci run (`gh run view <id> --json jobs`), the pytest step duration of each shard, the
  average, the slowest/average ratio (at most 1.5) and the slowest (at most 75 s).
- AC-112.9: the PR's own wall time as a first sample, the `gh` / `jq` command that computes it (first job
  `startedAt` to `ci-success` `completedAt`), and an empty five-row table the human step fills after the merge.

**Done when:** measurements.md holds the before/after numbers for AC-112.1, .3, .7 and .12 that meet the criteria,
the PR description repeats them, and the AC-112.9 table and command are ready for the post-merge step.
