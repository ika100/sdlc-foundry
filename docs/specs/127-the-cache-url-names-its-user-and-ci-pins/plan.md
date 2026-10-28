---
spec_id: 127-the-cache-url-names-its-user-and-ci-pins
shape: platform
spec_hash: 73735bf01438
summary: "Two loose ends of the 5.x resources round: the in-cluster cache Secret's url template names the ACL user (redis://default:{{ .password }}@<host>:6379/0, cluster-gitops copy synced), the e2e cluster test probes with the component's variable unchanged, /platform:update adds a url row per cache and environment to its change list (detected from the rendered ExternalSecret before and after the re-render; an existing Secret is written once and keeps its url, both forms authenticate as default); the platform's test tools are pinned in requirements-test.txt compiled from requirements-test.in with uv pip compile --universal, CI, ci-local.sh and devbox test-fast install only from it, check-pins.py gains a part that fails on a suite command installing them otherwise, and a monthly grouped Dependabot pip entry moves them"
tasks:
  - id: t1
    title: cache url names default — render.py cache_files() url template (+ synced system_render.py), spec 118 fixtures and tests, e2e run.sh Secret check and probe without the rewrite, resource add.md, resource plugin 1.6.1, CHANGELOG
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, tests/cplat/cache_fixtures.py, tests/cplat/test_cache_118.py, tests/cplat/test_cache_118_cmds.py, tests/e2e/run.sh, plugins/resource/commands/add.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md]
    covers: [AC-127.1, AC-127.3]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: platform update — a cache's rendered url template before and after the re-render, one url row per changed cache and environment in the versions change list (report, JSON, fleet PR body)
    files: [scripts/cplat/update.py]
    covers: [AC-127.2]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: pinned test tools — requirements-test.in/.txt, the three suite commands install from it, check-pins.py part 4, Dependabot pip entry, test_drift and CONTRIBUTING follow
    files: [requirements-test.in, requirements-test.txt, .github/workflows/ci.yml, scripts/ci-local.sh, devbox.json, scripts/check-pins.py, .github/dependabot.yml, tests/cplat/test_drift.py, CONTRIBUTING.md]
    covers: [AC-127.4, AC-127.5, AC-127.6]
    parallel_safe: true
    depends_on: []
---

# Plan — 127 The cache URL names its user and CI pins its test tools

Design: [design.md](design.md). Three independent tasks, one level, no shared file.

## t1 — cache url names default

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, tests/cplat/cache_fixtures.py, tests/cplat/test_cache_118.py, tests/cplat/test_cache_118_cmds.py, tests/e2e/run.sh, plugins/resource/commands/add.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md
**Covers:** AC-127.1, AC-127.3
**Goal:** a component that uses an in-cluster cache gets `REDIS_URL` as `redis://default:<password>@<host>:6379/0`, and the e2e cluster test uses it as it is.

**Implementation notes:**
- `cache_files()` (render.py:2365): the `url` template becomes `redis://default:{{ .password }}@{n}.{ns}.svc:6379/0`; nothing else in the ExternalSecret changes (`refreshPolicy: CreatedOnce` stays). Then `python3 scripts/sync-template-copies.py` for `system_render.py`.
- Spec 118 regression tests amended by AC-127.1: `cache_fixtures.py:73` (expected render), `test_cache_118.py:509` (the url) and `:543` (the guard against a literal password in a url: match `redis://default:` followed by anything but `{`, and keep catching the old `redis://:` form), `test_cache_118_cmds.py:447` (run.sh now carries `redis://default:`).
- `tests/e2e/run.sh`: lines 709 and 717 expect `redis://default:${pw_sessions}@e2e-sessions.e2e-dev.svc:6379/0`; delete the comment and the `fix` variable at 755–757 and drop `$fix` from the probe script at 758, so the probe runs `valkey-cli -u "$SESSIONS_REDIS_URL"` on the rendered variable.
- `tests/e2e/upgrade.sh` stays as it is: its cache is created by the previous release and its Secret keeps `redis://:` (design, Decisions); the sed is a no-op on the new form.
- `plugins/resource/commands/add.md`, Cache bullet: say that an in-cluster cache's `url` is `redis://default:<password>@<host>:6379/0` (works unchanged with client libraries and `valkey-cli`/`redis-cli -u`; a cache created before this release keeps `redis://:<password>@…` in its Secret, which authenticates as the same user). Keep the external-store advice. The needles of `test_cache_118_cmds.py:485` stay.
- Resource plugin 1.6.0 → 1.6.1 in `plugin.json` and `marketplace.json`.
- `docs/CHANGELOG.md` [Unreleased]: one paragraph for spec 127 (both halves: url form with the existing-Secret note, the `/platform:update` url row, the pinned test tools and the Dependabot entry); add `resource` 1.6.1 to the Plugins line. No Versions rows change.

**Done when:** the acceptance tests for AC-127.1 and AC-127.3 pass, the amended spec 118 tests pass, `uv run scripts/sync-template-copies.py --check` and `python3 scripts/check-pins.py` pass, `bash -n tests/e2e/run.sh` passes.

## t2 — platform update names the url change

**Files:** scripts/cplat/update.py
**Covers:** AC-127.2
**Goal:** `/platform:update` on a gitops repo whose cache ExternalSecret has the 5.3 url form lists, per cache and environment, the new form and what happens to the existing Secret.

**Implementation notes:**
- `_instances()`: for `typ == "cache"` also record `url`: `spec.target.template.data.url` of `app_dir/addons/<env>/<r>/externalsecret.yaml`, `None` when the file or key is missing (external caches are skipped already).
- `render_and_compare()`: per instance key, when the before and after `url` are both present and differ, append the `kind: "url"` row exactly as the design's Contract gives it (`from`/`to` with `{{ .password }}` → `<password>`, `moves: false`, the `text` sentence). Check it before the existing pin-row `continue`, so an instance without a pin row still gets its url row; order after that instance's pin row.
- Nothing else changes: the rows flow into `versions.lines`, the printed block, `--json` and `fleet_pr.py`'s body as they are.

**Done when:** the acceptance tests for AC-127.2 pass (they need t1's renderer for the end-to-end form; the row logic itself is renderer-independent), and the spec 121 update tests stay green.

## t3 — pinned test tools

**Files:** requirements-test.in, requirements-test.txt, .github/workflows/ci.yml, scripts/ci-local.sh, devbox.json, scripts/check-pins.py, .github/dependabot.yml, tests/cplat/test_drift.py, CONTRIBUTING.md
**Covers:** AC-127.4, AC-127.5, AC-127.6
**Goal:** the cplat suite runs on the same tool versions everywhere until a Dependabot PR that passes CI moves them.

**Implementation notes:**
- `requirements-test.in`: `pytest`, `pytest-xdist`, `pyyaml`, `ruamel.yaml`. Compile with `uv pip compile --universal requirements-test.in -o requirements-test.txt` (today: pytest 9.2.0, pytest-xdist 3.8.0, pyyaml 6.0.3, ruamel.yaml 0.19.1 and their dependencies); keep uv's header.
- `ci.yml` step `pytest` (line 178), `ci-local.sh` (line 38), `devbox.json` `test-fast` (line 28): `uv run --with-requirements requirements-test.txt pytest tests/cplat …`, the rest of each command unchanged (`--shard`, `--shard-report`, `-n auto`).
- `check-pins.py`: part 4 as in the design's Contract (suite lines in the three files, `--with-requirements requirements-test.txt` present, no `--with`/`--with=` of the four packages, every requirement line `==`); extend the module docstring to four parts. It already runs in CI's `validate-shapes` and `devbox run validate`.
- `.github/dependabot.yml`: the `pip` entry for `/`, monthly, group `test-tools` with `patterns: ["*"]`; extend the file's head comment by the test tools.
- `test_drift.py:35` (AC-084.1): assert `--with-requirements requirements-test.txt` and `pytest tests/cplat -q -n auto` instead of `--with pytest-xdist`.
- `CONTRIBUTING.md:43`: the documented test command uses `--with-requirements requirements-test.txt`.

**Done when:** the acceptance tests for AC-127.4 to AC-127.6 pass, `python3 scripts/check-pins.py` prints OK and fails on a scratch copy of `devbox.json` with `--with pytest` restored, and `bash scripts/ci-local.sh` passes.
