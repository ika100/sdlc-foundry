---
spec_id: 130-quality-gates-fail-when-they-checked
shape: platform
spec_hash: d85f900526a0
summary: "Every covered gate (test, test-fast, validate, render-check, secrets-scan) of the 7 templates counts what it checked and fails on 0 with one stderr line `<gate>: checked nothing: <what> - <fix>`: one byte-identical bash helper scripts/gate.sh in every template (source gitops-app, copies kept by sync-template-copies.py) with `nothing`, `files` and `tests <gate> pytest|maven|go|vitest -- <cmd>` (JUnit XML for pytest/Maven, go test -v result lines, Vitest JSON report via VITEST_GATE_REPORT in vitest.config.mts); the test/test-fast/secrets-scan recipes call it; gitops-app validate counts kustomize + kubeconform resources and stops at the first failing step; cluster-gitops validate prints the line instead of the #278 message; render.py --check (gitops-app, system_render.py, cluster-gitops) fails on 0 compared files with GATE_NAME as gate; platform smoke jobs run the real recipes with and without tests; ADR-074, CONTRIBUTING and template guide rule, CHANGELOG behaviour change"
tasks:
  - id: t1
    title: scripts/gate.sh (nothing, files, tests for pytest/maven/go/vitest) in gitops-app with byte-identical copies in the other six templates, kept equal by sync-template-copies.py
    files: [templates/gitops-app/scripts/gate.sh, templates/cluster-gitops/scripts/gate.sh, templates/service-python/scripts/gate.sh, templates/library-python/scripts/gate.sh, templates/service-go/scripts/gate.sh, templates/service-java/scripts/gate.sh, templates/web-nextjs/scripts/gate.sh, scripts/sync-template-copies.py, tests/cplat/test_sync_template_copies.py]
    covers: [AC-130.1, AC-130.6, AC-130.13, AC-130.14]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: the rule in CONTRIBUTING.md and docs/templates.md with the pointer to the platform test, ADR-074 in the ADR index, CHANGELOG behaviour change under [Unreleased]
    files: [CONTRIBUTING.md, docs/templates.md, docs/CHANGELOG.md, docs/adr/README.md]
    covers: [AC-130.15, AC-130.16]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: test, test-fast and secrets-scan recipes of service-python, library-python, service-go, service-java and web-nextjs through gate.sh; Vitest JSON reporter under VITEST_GATE_REPORT
    files: [templates/service-python/devbox.json, templates/library-python/devbox.json, templates/service-go/devbox.json.jinja, templates/service-java/devbox.json.jinja, templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/vitest.config.mts]
    covers: [AC-130.1, AC-130.2, AC-130.3, AC-130.4, AC-130.5, AC-130.6, AC-130.10, AC-130.11, AC-130.12, AC-130.13, AC-130.14, AC-130.16]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: gitops-app and cluster-gitops - validate counts resources (gitops-app stops at the first failing step), render.py --check fails on 0 compared files with GATE_NAME, secrets-scan through gate.sh
    files: [templates/gitops-app/devbox.json, templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, templates/cluster-gitops/scripts/render.py, templates/cluster-gitops/devbox.json]
    covers: [AC-130.1, AC-130.7, AC-130.8, AC-130.9, AC-130.10, AC-130.11, AC-130.12, AC-130.13, AC-130.14, AC-130.16]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: platform smoke jobs run each template's real test/test-fast recipe (must pass) and test-fast with the tests removed (must fail with the line)
    files: [.github/workflows/ci.yml]
    covers: [AC-130.2, AC-130.3, AC-130.4, AC-130.5, AC-130.12]
    parallel_safe: true
    depends_on: [t2, t3]
---

# Plan — 130 Quality gates fail when they checked nothing

Contract: [design.md](design.md). ADR: [074](../../adr/074-a-gate-that-checked-nothing-fails.md). The platform test of AC-130.14
(`tests/cplat/test_130_empty_gates.py`) and the other acceptance tests are written by the testers before t1 starts; no task edits them.

Order: t1 and t5 first (independent), then t2 and t3 (both call `gate.sh`), then t4 (runs the recipes of t2 and t3 in CI). The build
will most likely run sequentially (#319); the tasks are coarse for that. Estimated build cost: about 25-30 (5 coder passes, the largest
t3; plus tester, reviewer and the template smoke matrix and e2e on the PR).

**Update reach (AC-130.16).** Every file this plan changes in a template is platform-owned: `devbox.json` (template recipes win in the
`/platform:update` merge), `scripts/gate.sh` (a new file outside every `_skip_if_exists`, so the update adds it), `scripts/render.py`,
`scripts/system_render.py`, `vitest.config.mts`. Nothing touches `pyproject.toml`, `pom.xml`, `package.json`, `tests/**`, `src/**`,
`cluster/**` or `applications/**/overlays/**`, which are `_skip_if_exists` and would never update.

## t1 — scripts/gate.sh and its copies

**Files:** templates/gitops-app/scripts/gate.sh (source, new), templates/{cluster-gitops,service-python,library-python,service-go,service-java,web-nextjs}/scripts/gate.sh (copies, new), scripts/sync-template-copies.py, tests/cplat/test_sync_template_copies.py
**Covers:** AC-130.1, AC-130.6, AC-130.13, AC-130.14
**Goal:** the one helper every shell recipe uses to print the AC-130.1 line and to decide whether a test run, or a file list, checked
anything, exactly as in design.md "scripts/gate.sh".

**Implementation notes:**
- Subcommands `nothing`, `files`, `tests`; the line format, exits and per-runner counting rules are in design.md. Usage errors exit 2.
- `tests`: run the command with its output shown live; capture what the count needs: stdout via `tee` for `go`; combined output for
  `vitest` (to see `No test files found`); keep the command's exit with `PIPESTATUS`/`pipefail`.
- JUnit sum (pytest, maven): read the `<testsuite …>` start tags (not `<testsuites>`), take `tests="N"` and `skipped="N"` with
  `grep -o`/`sed`, sum `tests - skipped`. Missing files count 0.
- `pytest`: append `--junitxml=<tmp>/junit.xml` as the last argument. `maven`: remove both report dirs before running. `vitest`: export
  `VITEST_GATE_REPORT=<tmp>/vitest.json` (overwrite any inherited value) and read `"numPassedTests":N` and `"numFailedTests":N`.
- No environment variable, flag or setting skips the decision (AC-130.13).
- bash 3.2 compatible; only `git`, `grep`, `sed`, `tee`, `mktemp`; a `trap` removes the temp dir.
- The file must contain no `{{`, `{%`, `{#` (rendered by Jinja in the two Python templates; the rendered copy must equal the source).
  Verify with a `copier copy` of service-python that `scripts/gate.sh` is byte-identical.
- `sync-template-copies.py`: add `templates/gitops-app/scripts/gate.sh` → `templates/<t>/scripts/gate.sh` for the six other templates.
  Generalise `COPIES` to (source path, copy path) pairs; skip a pair whose source does not exist (the existing sandbox tests have no
  `gate.sh`) and create the copy's directory when rewriting. Docstring: no longer cluster-only.
- Add one case to `test_sync_template_copies.py` for a drifted `gate.sh` copy; keep the existing cases unchanged.

**Done when:** the AC-130.14 tests that call `gate.sh` directly pass; `uv run scripts/sync-template-copies.py --check` passes;
`tests/cplat/test_sync_template_copies.py` passes.

## t5 — the rule in the guides, the ADR index, the changelog

**Files:** CONTRIBUTING.md, docs/templates.md, docs/CHANGELOG.md, docs/adr/README.md
**Covers:** AC-130.15, AC-130.16
**Goal:** contributors read the rule where they work on templates, and repos learn what turns red after the update and how to fix it.

**Implementation notes:**
- CONTRIBUTING.md, in "Pull request rules" (next to the template-change rule): "A gate that checked nothing fails", one or two
  sentences, a link to `tests/cplat/test_130_empty_gates.py` and ADR-074.
- docs/templates.md, section 2 (the `devbox.json` row or a short paragraph after the table): the same rule for new templates and new
  gate recipes — covered gates call `scripts/gate.sh` (copied by `scripts/sync-template-copies.py`), a new template gets an entry in the
  coverage table of `tests/cplat/test_130_empty_gates.py` or the suite fails.
- docs/adr/README.md: the ADR-074 row (one-line summary in the style of the others).
- docs/CHANGELOG.md, `[Unreleased]`: a bold-titled entry with a `**Behaviour change:**` sentence (the style of earlier entries): the
  symptom (a repo with 0 tests, only skipped tests, an empty build or no files to scan turns red after `/platform:update`, with the
  line `<gate>: checked nothing: …`), the fix (add at least one test / make the build non-empty), no opt-out, #285, spec 130 and
  ADR-074 links; also that gitops-app `validate` now stops at its first failing step, that Go tests run with `-v`, and that a
  `package.json` test script with its own `--reporter` makes the web gate fail. Nothing breaks the CLI: the release is a minor.

**Done when:** the AC-130.15 and AC-130.16 doc tests pass; `scripts/check-links` (or `ci-local.sh`) is green.

## t2 — test-running templates: test, test-fast, secrets-scan

**Files:** templates/service-python/devbox.json, templates/library-python/devbox.json, templates/service-go/devbox.json.jinja, templates/service-java/devbox.json.jinja, templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/vitest.config.mts
**Covers:** AC-130.1, AC-130.2, AC-130.3, AC-130.4, AC-130.5, AC-130.6, AC-130.10, AC-130.11, AC-130.12, AC-130.13, AC-130.14, AC-130.16
**Goal:** the five test-running templates' `test`, `test-fast` and `secrets-scan` recipes are the design.md target texts.

**Implementation notes:**
- Recipes exactly as in design.md "Recipes"; keep `SMOKE_BASE_URL=` where it is today, `--cov={{ module_name }}` stays templated.
- Go: both recipes gain `-v`. Java: no `-DskipTests` in `test`/`test-fast` (the `typecheck` recipe keeps its own). Web: no
  `--passWithNoTests` anywhere.
- `secrets-scan`: prefix `bash scripts/gate.sh files secrets-scan <same pathspec> && `; the `git ls-files -z … | xargs -0
  detect-secrets-hook <flags>` part stays byte-identical (test_ci_templates.py splits on `detect-secrets-hook`).
- `vitest.config.mts`: reporters/outputFile only when `process.env.VITEST_GATE_REPORT` is set (design.md); must pass the template's
  eslint and `tsc --noEmit`.
- `ci`, `quality`, `security` are not edited; check they still chain the covered gates with `&&` (AC-130.11).
- Render each template once (`copier copy … --defaults --trust --skip-tasks`) and, where the toolchain is at hand, run `test` and
  `test-fast` through `sh -c "$(jq -r …)"`: green with the shipped tests, red with the line after deleting them.

**Done when:** the acceptance tests of AC-130.2-.6, .10, .11, .13 and the AC-130.14 rows of these five templates pass; the existing
template tests (`test_ci_templates.py`, `test_update_doctor.py`, `test_smoke_091_templates.py`) still pass.

## t3 — gitops-app and cluster-gitops

**Files:** templates/gitops-app/devbox.json, templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, templates/cluster-gitops/scripts/render.py, templates/cluster-gitops/devbox.json
**Covers:** AC-130.1, AC-130.7, AC-130.8, AC-130.9, AC-130.10, AC-130.11, AC-130.12, AC-130.13, AC-130.14, AC-130.16
**Goal:** `validate`, `render-check`/`test-fast` and `secrets-scan` of the two gitops templates fail with the line when they checked
nothing, as in design.md.

**Implementation notes:**
- gitops-app `validate`: the inline shape of design.md — `|| exit 1` after each step, kustomize output counted (`^kind:` lines) instead
  of sent to `/dev/null`, kubeconform output captured, printed and its `Summary: N resource` added; `n = 0` → `gate.sh nothing validate
  '0 resources' '<fix>'` and exit 1, before `check-policies.sh`. Keep `kubeconform -strict … -summary "$f"` contiguous and the
  `SERVICE_CRD_SKIP` expansion where it is (test_service_crds.py extracts and runs it).
- gitops-app `test-fast` and `validate` prefix the render check with `GATE_NAME=test-fast` / `GATE_NAME=validate`; `render-check`
  stays `uv run scripts/render.py --check`.
- cluster-gitops `validate`: `GATE_NAME=validate` on the render check; replace the #278 `echo … >&2` by `bash scripts/gate.sh nothing
  validate '0 resources' '<fix>'` (exit ignored, `rc=1` kept); kubeconform's report still printed. `test-fast` gets `GATE_NAME=test-fast`.
- `render.py` (gitops-app) `main()`: in `--check` mode, no `applications/*/system.yaml` → the line (`0 files compared`), exit 1;
  after the drift check, compared = sum of `len(rendered)` over the plans + `len(operators)`; 0 → the line, exit 1. Gate name
  `os.environ.get("GATE_NAME") or "render-check"`. Write mode unchanged. Then `uv run scripts/sync-template-copies.py` to refresh
  `system_render.py`.
- cluster-gitops `render.py` `--check`: after the drift check, `len(files) == 0` → the line, exit 1 (same gate-name rule).
- `secrets-scan` of both: `bash scripts/gate.sh files secrets-scan . && <unchanged pipeline>`.
- `ci`, `quality`, `security`, `test` (= `devbox run validate`) are not edited (AC-130.11).

**Done when:** the acceptance tests of AC-130.7-.11 and .13 and the AC-130.14 rows of both templates pass; the existing tests
`test_service_crds.py`, `test_cluster_125_delivery.py`, `test_cluster_125_render.py`, `test_broker_119.py` and the sync check pass.

## t4 — the template smoke jobs run the real recipes

**Files:** .github/workflows/ci.yml
**Covers:** AC-130.2, AC-130.3, AC-130.4, AC-130.5, AC-130.12
**Goal:** the real runners prove what stub tests cannot: a fresh render passes its own `test`/`test-fast`, and an empty one fails
with the line (design.md, Risks).

**Implementation notes:**
- In the rendered project of each smoke job, run a recipe without devbox as `sh -c "$(jq -r '.shell.scripts["<name>"]' devbox.json)"`.
- `smoke-test-templates` (python, both variants), `smoke-test-service-go`, `smoke-test-service-java`, `smoke-test-web-nextjs`: replace
  the direct test-runner call by the `test` recipe (keep the spec 091 `SMOKE_BASE_URL is not set` assertion for service-python, e.g. by
  running pytest with `-rs` as today in addition, or grepping the recipe output); then delete the shipped tests (`tests/`,
  `*_test.go`, `src/test`, `tests/`) in a copy and assert that `test-fast` exits non-zero and stderr has
  `test-fast: checked nothing: 0 tests ran - add at least one test`. Java: one variant (the first matrix entry) is enough for the
  negative run.
- web-nextjs: the recipe calls `pnpm`; install `pnpm@11.22.0` globally before the recipe step (the job already does this later).
- `smoke-test-gitops-app` and `smoke-test-cluster-gitops`: run the `test-fast` recipe (positive) next to the existing `render.py --check`.
- No new tools on the runners (jq, git are there); keep `fail-fast: false` and the job names (required checks, `ci-success` needs list).

**Done when:** the PR's smoke jobs are green; the workflow passes the platform's workflow checks (pinned actions, `test_ci_*`).
