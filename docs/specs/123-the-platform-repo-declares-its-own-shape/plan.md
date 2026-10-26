---
spec_id: 123-the-platform-repo-declares-its-own-shape
spec_hash: 251f90338851
summary: "The platform repo declares `shape: platform` in its committed .platform-settings.yml; a template-less, declared-only registry entry hidden from every create/adopt/update/fleet path; cplat shape routes it to svc/shared agents without a release role; spec check keeps old shape-less specs unchanged; ship deploys nothing; update refuses, doctor reports the source version; the component commands stop on a bad declaration and release refuses"
tasks:
  - id: t1
    title: Red acceptance tests for AC-123.1 to AC-123.23 (tester, acceptance mode)
    files: [tests/cplat/test_platform_shape_123.py]
    covers: []
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: Registry — platform entry, load()/load_all()/get()/declared_ids(), declared-entry validation; site table hides it
    files: [shapes.yml, scripts/shapes.py, site/scripts/generate-reference.mjs]
    covers: [AC-123.9, AC-123.10, AC-123.1]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: settings.declared_shape + ShapeDeclarationError; shapecmd.resolve and the platform routing
    files: [scripts/cplat/settings.py, scripts/cplat/shapecmd.py]
    covers: [AC-123.1, AC-123.2, AC-123.3, AC-123.4, AC-123.5, AC-123.6, AC-123.7, AC-123.8]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: cplat spec — declaration errors pass repo_shape, platform is a known shape, spec_shape keeps old specs shape-less
    files: [scripts/cplat/spec.py]
    covers: [AC-123.3, AC-123.15, AC-123.16, AC-123.17]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t5
    title: component ship — start resolves and records the shape, deploy ends at once for platform
    files: [scripts/cplat/ship.py]
    covers: [AC-123.3, AC-123.19, AC-123.20, AC-123.21, AC-123.22]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t6
    title: platform update refuses the platform repo
    files: [scripts/cplat/update.py]
    covers: [AC-123.11]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t7
    title: platform doctor — repo shape platform, platform source at v<version>, FAIL row for a bad declaration
    files: [scripts/cplat/doctor.py]
    covers: [AC-123.13]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t8
    title: platform fleet — explicit skip reason for the platform repo under --only
    files: [scripts/cplat/fleet.py]
    covers: [AC-123.12]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t9
    title: spec, plan, verify, build commands stop on a declaration error and never ask for the shape
    files: [plugins/component/commands/spec.md, plugins/component/commands/plan.md, plugins/component/commands/verify.md, plugins/component/commands/build.md]
    covers: [AC-123.14, AC-123.18]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t10
    title: ship final report for a non-deployable run; release refuses without a release role
    files: [plugins/component/commands/ship.md, plugins/component/commands/release.md]
    covers: [AC-123.19, AC-123.22, AC-123.23]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t11
    title: The repo commits shape platform; CLAUDE.md, specs README and CONTRIBUTING say so
    files: [.platform-settings.yml, CLAUDE.md, docs/specs/README.md, CONTRIBUTING.md]
    covers: [AC-123.8]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t12
    title: component plugin 1.1.0 (catalog + manifest) and the CHANGELOG [Unreleased] entry
    files: [.claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, docs/CHANGELOG.md]
    covers: [AC-123.14, AC-123.23]
    parallel_safe: true
    depends_on: [t1]
    done: true
---

# Plan — 123 The platform repo declares its own shape

The contract (messages, routing JSON, registry entry, settings key order) is in [design.md](design.md); the decision is
[ADR-056](../../adr/056-the-platform-repo-declares-its-shape.md). Levels: t1 → t2, t8, t9, t10, t11, t12 → t3 → t4, t5, t6, t7.

## t1 — Red acceptance tests for AC-123.1 to AC-123.23 (tester, acceptance mode)

**Files:** tests/cplat/test_platform_shape_123.py
**Covers:** none (it writes the tests every other task is measured against)
**Goal:** one criterion-tagged test file, red because the behaviour is missing, written against design.md's contract.

**Implementation notes:**
- Style of the existing suite: `cplat` as a subprocess in a temporary git repo (`git init`, a commit), `XDG_CONFIG_HOME`
  pointed at a temporary directory for the personal settings file; `shapes.py` checks against a copied `shapes.yml` with
  `ROOT` patched, as `tests/cplat/test_spec_driven.py` does; `ship` and `fleet` with `gh` faked the way
  `tests/cplat/test_ship*.py` and `test_fleet*.py` already fake it.
- AC-123.8 and AC-123.16 run against the platform checkout itself (`.platform-settings.yml` present, `cplat spec check`
  on every spec before 123 adds no error compared with a run where the repo shape is `None`).
- AC-123.14, 18, 22, 23 assert the command texts named in design.md (Commands); AC-123.18 also asserts the routing has
  `deployable: false` so Phase 5 prints `## Phase 5 skipped — platform is not deployable`.
- Commit only the test file: `test(123): acceptance tests for 123-the-platform-repo-declares-its-own-shape`.

**Done when:** `cplat spec trace 123` passes and the new tests fail for the missing behaviour, nothing else newly fails.

## t2 — Registry: platform entry, load()/load_all()/get()/declared_ids(), declared-entry validation; site table hides it

**Files:** shapes.yml, scripts/shapes.py, site/scripts/generate-reference.mjs
**Covers:** AC-123.9, AC-123.10, AC-123.1
**Goal:** `platform` is registered without a template, every existing `load()` caller still sees only template shapes,
and `shapes.py check` passes with it and still fails for any other shape without template, plugin or detection.

**Implementation notes:**
- Append the entry exactly as design.md (Registry entry); update the file's header comment (a declared shape needs only
  an entry and a plugin, ADR-056).
- `load_all()`, `is_declared()`, `load()` (filtered), `get()`, `declared_ids()`, `DECLARED_IN` as design.md.
- `main`: `ids` uses `load()`; `get` uses `load_all()`; `validate`/`check` run on `load_all()`.
- `validate()`: the declared branch and its messages; the new "template missing" rule for non-declared entries; skip the
  copier_src/sniff, test_globs and ci_checks rules for declared entries.
- `check_files`: declared entries check only the plugin dir. `check_contract` and `check_prd` skip declared entries.
- `generate-reference.mjs`: filter out entries whose `detection.declared` is set (the table lists shapes the platform can
  create and operate).
- No caller of `core.registry.load()` changes: `/component:new`, `/system:new`, `cplat adopt --type platform` (fails with
  `unknown shape 'platform'`, hint listing the six template shapes), `model.TYPE_LANGS`, fleet, compose stay as they are.

**Done when:** the AC-123.9, AC-123.10 tests pass; `uv run scripts/shapes.py check` is green; `scripts/test-detect-shape.sh`
still passes.

## t3 — settings.declared_shape + ShapeDeclarationError; shapecmd.resolve and the platform routing

**Files:** scripts/cplat/settings.py, scripts/cplat/shapecmd.py
**Covers:** AC-123.1, AC-123.2, AC-123.3, AC-123.4, AC-123.5, AC-123.6, AC-123.7, AC-123.8
**Goal:** `cplat shape` resolves a committed `shape: platform`, prints the platform routing, and refuses every invalid
declaration with the messages of design.md; repos without the key resolve exactly as before.

**Implementation notes:**
- `settings.py`: `ShapeDeclarationError(PlatformError)`; `declared_shape(repo)` with the check order and messages of
  design.md (user file first, then project file, component shape, unknown value); extend the module docstring with `shape`.
  The other readers are not touched.
- `shapecmd.py`: `resolve(repo)` (declaration, the `.copier-answers.yml` conflict check by `_src_path`, else
  `detect-shape.sh`); `route()` uses it and `core.registry.get()`; a declared shape drops `release` (and, being not
  deployable, `deployment` and `observability`). Key order of the JSON as design.md.
- Nothing is written anywhere; "cannot determine the repo's shape" keeps its text and hint.

**Done when:** the AC-123.1 to AC-123.8 tests for `cplat shape` pass (AC-123.3's `spec new` and `ship start` cases need t4
and t5; AC-123.8 needs t11 merged).

## t4 — cplat spec: declaration errors pass repo_shape, platform is a known shape, spec_shape keeps old specs shape-less

**Files:** scripts/cplat/spec.py
**Covers:** AC-123.3, AC-123.15, AC-123.16, AC-123.17
**Goal:** `cplat spec new` records `shape: platform` and fails on a bad declaration; `cplat spec check` accepts
`shape: platform`, applies the `(smoke)` rule to new platform specs only, and reports nothing new for the existing specs.

**Implementation notes:**
- `repo_shape`: re-raise `settings.ShapeDeclarationError`, swallow other `PlatformError` as today.
- `check()`: `known` from `core.registry.load_all()`; `eff_shape = spec_shape(spec, shape)`.
- `spec_shape()` helper as design.md; use it for `own_shape` in `ci_problems()` and in the `trace` command.
- `smoke_tag`/`test_globs`/`smoke_globs` keep `load()`.

**Done when:** the AC-123.15, 16, 17 tests and the `spec new` case of AC-123.3 pass; `cplat spec check` on the platform
checkout is green with `.platform-settings.yml` in place.

## t5 — component ship: start resolves and records the shape, deploy ends at once for platform

**Files:** scripts/cplat/ship.py
**Covers:** AC-123.3, AC-123.19, AC-123.20, AC-123.21, AC-123.22
**Goal:** a platform ship run starts without gitops questions, lands like any PR, and reaches `done` at deploy without
waiting for anything; the run record names the shape.

**Implementation notes:**
- `start()`: `shape = shapecmd.resolve(repo)` as the first statement; `st["shape"]` on new and resumed runs; after
  `save_state`, `runs.set_section(st.get("run_id"), "shape", shape)` when set.
- `deploy()`: the platform early return of design.md, before the kube-context lookup; library path unchanged.
- `_file_platform_failure` and the `smoke.file_issue` call: shape falls back to `st.get("shape")`.
- `land()`: no change; the AC-123.20 test proves it with the platform's check names and a skipped job.

**Done when:** the AC-123.19 to AC-123.22 tests and the `ship start` case of AC-123.3 pass.

## t6 — platform update refuses the platform repo

**Files:** scripts/cplat/update.py
**Covers:** AC-123.11
**Goal:** `cplat platform update` in the platform repo exits 1 with "the platform repo is not updated from a template" and
changes no file.

**Implementation notes:**
- In `resolve()`, right after the `.git` check: `shapecmd.resolve(repo) == "platform"` → the PlatformError of design.md
  (also with `--migrate` and `--dry-run`).
- `detect_shape()` stays for component repos and `adopt`.

**Done when:** the AC-123.11 test passes (git status clean after the call).

## t7 — platform doctor: repo shape platform, platform source at v<version>, FAIL row for a bad declaration

**Files:** scripts/cplat/doctor.py
**Covers:** AC-123.13
**Goal:** doctor in the platform repo reports `repo shape: platform` OK and `platform source at v<version>` instead of the
missing-stamp warning.

**Implementation notes:**
- `check_repo`: shape from `shapecmd.resolve(repo)`; the rows of design.md; `core.platform_version(repo)` with `?` when
  the repo has no `docs/CHANGELOG.md`.
- `ShapeDeclarationError` → one FAIL row with the message and hint, no stamp row.
- `check_service_repos_token` and `check_alerts_token` keep `detect-shape.sh` (gitops-app only).

**Done when:** the AC-123.13 test passes; component-repo doctor rows are unchanged.

## t8 — platform fleet: explicit skip reason for the platform repo under --only

**Files:** scripts/cplat/fleet.py
**Covers:** AC-123.12
**Goal:** the fleet never opens a PR or changes anything in the platform repo; with `--only` it says why.

**Implementation notes:**
- In `process()`, when the stamp is missing and `only` is set: read `.platform-settings.yml` with `_read`; a mapping
  with `shape: platform` → `_row(slug, None, None, "skipped", "the platform repo is not updated from a template")`.
- Without `--only` nothing extra is read (no API call per stamp-less repo); the repo stays out of the report.
- Never clone it.

**Done when:** the AC-123.12 tests (with and without `--only`) pass and assert no `clone`, no `pr create`.

## t9 — spec, plan, verify, build commands stop on a declaration error and never ask for the shape

**Files:** plugins/component/commands/spec.md, plugins/component/commands/plan.md, plugins/component/commands/verify.md, plugins/component/commands/build.md
**Covers:** AC-123.14, AC-123.18
**Goal:** in the platform repo these commands run with the routed agents; an invalid declaration stops them with its
message.

**Implementation notes:**
- Add the sentence of design.md (Commands) to each; `spec.md` step 4 adds that a repo with a shape, the platform repo
  included, records it (no `--no-shape`).
- `build.md`: keep the Phase 5 skip line and the `cplat quiet` gates as they are; no shape-specific gate.
- Keep descriptions under 260 characters (`shapes.py check`).

**Done when:** the AC-123.14 and AC-123.18 tests pass.

## t10 — ship final report for a non-deployable run; release refuses without a release role

**Files:** plugins/component/commands/ship.md, plugins/component/commands/release.md
**Covers:** AC-123.19, AC-123.22, AC-123.23
**Goal:** the ship report of a platform run shows `not deployable` rows and no promote step; `/component:release` refuses
in the platform repo and names the platform's release procedure.

**Implementation notes:**
- `ship.md`: the declaration-error sentence after the first calls; the platform sentence in Phase `deploy`; the Finish
  rule for `not deployable (<shape>)` runs (design.md, Commands).
- `release.md` Phase 0: the refusal block of design.md when `agents` has no `release` role, before Phase 1.

**Done when:** the AC-123.22 and AC-123.23 text tests pass.

## t11 — The repo commits shape platform; CLAUDE.md, specs README and CONTRIBUTING say so

**Files:** .platform-settings.yml, CLAUDE.md, docs/specs/README.md, CONTRIBUTING.md
**Covers:** AC-123.8
**Goal:** a fresh clone of main resolves `platform` without local setup, and the repo's guidance no longer says it has no
shape.

**Implementation notes:**
- `.platform-settings.yml` exactly as design.md (not git-ignored; REUSE covers it through `**`).
- `CLAUDE.md`: the `shapes.yml` Layout row (template shapes plus the declared `platform`, ADR-056) and the Conventions
  bullet "Platform changes start with a spec" (spec, plan, build, verify, ship work here; release per CONTRIBUTING.md).
- `docs/specs/README.md` line 5: `/component:spec`, the repo declares `shape: platform` (ADR-056).
- `CONTRIBUTING.md` Releases: one sentence that `/component:release` refuses here and this section is the procedure.
- `python3 scripts/check-links.py` stays green.

**Done when:** the AC-123.8 test passes once t3 is merged.

## t12 — component plugin 1.1.0 (catalog + manifest) and the CHANGELOG [Unreleased] entry

**Files:** .claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, docs/CHANGELOG.md
**Covers:** AC-123.14, AC-123.23
**Goal:** the changed component commands reach consumers as component 1.1.0; users can read the change.

**Implementation notes:**
- `component` 1.0.0 → 1.1.0 in both files (minor: behaviour added, nothing removed). No other plugin changes
  (`scripts/cplat` ships with the platform version).
- CHANGELOG `## [Unreleased]`: the platform repo declares `shape: platform` in `.platform-settings.yml` (ADR-056, spec 123);
  `/component:spec|plan|build|verify|ship` work here, `/component:release` refuses, `cplat platform update` refuses,
  doctor reports the source version; a `shape:` key anywhere else is an error; component 1.1.0.

**Done when:** `devbox run quality`'s version-match loop and `devbox run validate` are green.
