---
spec_id: 205-acceptance-tests-are-proven-passable
shape: platform
spec_hash: 5b917ca2d63a
summary: test-diff accepts comment, docstring and static-import edits on its own; cplat quiet test-fast --red classifies red pytest tests, the build sends wrong failures back to the tester and freezes only on a passing check; harness fixes after the freeze go to the tester
tasks:
  - id: t1
    title: test-diff accepts edits that change no assertion (comments, docstrings, static imports)
    files: [scripts/cplat/testdiff_neutral.py, scripts/cplat/spec.py]
    covers: [AC-205.1, AC-205.2, AC-205.3, AC-205.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat quiet test-fast --red classifies each red pytest test
    files: [scripts/cplat/test_progress/cplat_red_check.py, scripts/cplat/quiet_red.py, scripts/cplat/quiet.py]
    covers: [AC-205.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: build tests --red prints the red check; build reviewed freezes only after it passed
    files: [scripts/cplat/buildtests.py, scripts/cplat/testreview.py]
    covers: [AC-205.6]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t4
    title: Build and tester prompts - red check rounds in Phase 1, harness fix by the tester after the freeze
    files: [plugins/component/commands/build.md, docs/rules/plugins/component/commands/build.yml, plugins/component/references/build-tighten.md, docs/rules/plugins/component/references/build-tighten.yml, plugins/svc/agents/tester.md, docs/rules/plugins/svc/agents/tester.yml]
    covers: [AC-205.6, AC-205.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: ADR, plugin versions, changelog fragment and guides
    files: [docs/adr/, docs/adr/README.md, plugins/component/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/205-acceptance-tests-are-proven-passable.added.md, docs/HOW-IT-WORKS.md, docs/AGENTS.md]
    covers: []
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 205 Acceptance tests are proven passable before they freeze

The contract is [design.md](design.md). Level 0 runs four tasks with disjoint files in parallel. t1 adds the
no-assertion-change judgement to test-diff. t2 adds the red check (plugin, classifier, `quiet --red`). t4 changes the
prompts. t5 does the release bookkeeping and the ADR. Level 1 adds the build helper and the freeze gate (t3), which
import `quiet_red` from t2. t1 changes `spec.py` only inside `test_diff` (and `_py_shape`, if it is refactored to take
a tree), so a parallel spec that edits other parts of `spec.py` does not collide.

## t1 — test-diff accepts edits that change no assertion (comments, docstrings, static imports)

**Files:** scripts/cplat/testdiff_neutral.py, scripts/cplat/spec.py
**Covers:** AC-205.1, AC-205.2, AC-205.3, AC-205.4
**Goal:** `cplat spec test-diff <red>` passes a frozen test whose only differences are comments (any judged language),
Python docstrings and imports, or TS/JS, Go and Java static imports. It prints
`<file>: no assertion changed: <kinds>`, exits 0 and records nothing. Every other change keeps today's first reason
and today's helper, type-only and tightening paths.

**Implementation notes:**
- New `testdiff_neutral.py` with `judge(old, new, name) -> str | None`, exactly as design Contract 1. Its only cplat
  import is `spec` (lazily, for `AC_ANY` and the `_py_shape` normalisation), so `spec.py` can import it lazily inside
  `test_diff` without a cycle.
- Python: `tokenize` for comments; an `ast.NodeTransformer` that drops docstrings and `Import`/`ImportFrom` at every
  level and collects them; the remaining tree is compared with `_py_shape`'s normalisation. A `SyntaxError` or a
  `tokenize.TokenError` returns `None`.
- C-like lexer, shared by TS/JS, Go and Java, as the design describes: strings, template, raw and text-block literals,
  the JS regex-literal rule, and `None` on an unterminated literal or comment. Then the anchored static-import
  patterns per language; Go `import ( … )` blocks are split into one import per spec line.
- Directive comments (design list) are compared as a multiset. Any difference returns `None`, so suppressions stay
  with spec 160's `suppression_only` and every other directive stays refused.
- `spec.test_diff`: the three-line hook of Contract 1 at the `lint` / `formatting_only` step. No change to the
  approvals loop, the helper and type-only passes, `main` or the run-record calls (A2: nothing listed in the PR).
- Kinds are printed in the fixed order `comments, docstrings, imports`, and only the kinds whose multiset differs.

**Done when:** the AC-205.1 to AC-205.4 tests pass, and the existing test-diff tests still pass (`test_spec.py`,
`test_160_*`, `test_165_*`, `test_169_*`, `test_172_*`, `test_179_*`, `test_spec_324.py`), apart from a `formatting
only` expectation on a Python comment-only edit, which now reads `no assertion changed: comments`. Update such an
expectation in that test only if it exists and is not an acceptance test of this spec.

## t2 — cplat quiet test-fast --red classifies each red pytest test

**Files:** scripts/cplat/test_progress/cplat_red_check.py, scripts/cplat/quiet_red.py, scripts/cplat/quiet.py
**Covers:** AC-205.5
**Goal:** `cplat quiet test-fast --red -- <test files>` runs them once and prints one line per test: `missing
behaviour`, `test error` or `passes` with the exception line (plus `skipped (not judged)` for a smoke skip). It exits 0
only when every judged test is `missing behaviour`, and 2 with the usage line in a repo whose test-fast does not run
pytest. It writes `cplat-red-check.json` for the freeze gate.

**Implementation notes:**
- `cplat_red_check.py`: pytest hooks only, as design Contract 2. A `pytest_runtest_makereport` hookwrapper reads
  `call.excinfo`: type MRO, message, traceback entry paths, `ImportError.name`, `AttributeError.obj`, the `smoke`
  marker and the xfail flag. Collection errors come from `pytest_collectreport` / `pytest_exception_interact`. It
  appends JSON lines in every process, including xdist workers (the platform's test-fast uses `-n auto`); only the
  controller writes the header.
- `quiet_red.py`: `runs_pytest(cwd) -> bool` (the `test-fast` script in `devbox.json` contains `pytest`);
  `classify(records, root, shape, files) -> list[tuple[str, str, str]]` (node id, class, exception line), the
  8 rules of the design in order; `run(cwd, args, *, raw, on) -> int` (environment as the design says, merged with
  `quiet_limit.progress_env`; start, wait and gave-up through `quiet_limit`; prints the lines and the summary line;
  writes the record file after an exit of 0 or 1).
- Test code uses `spec.test_globs(spec.repo_shape(root))` (platform: `tests/**/*`) plus `conftest.py`. Repo frames
  skip `spec._ignored` parts and `site-packages`.
- Collection errors expand to one line per `def test…` name found in the file (the Python pattern of
  `spec._TEST_DEFS`), else one line naming the file.
- `quiet.py`: `_parse` accepts `test-fast --red -- <args>` (exclusive with `--repeat`, at least one argument) and
  returns a mode that `main` hands to `quiet_red.run` after `failsum.enabled`, as `--repeat` does. New usage line
  verbatim from the design. Every other path stays unchanged.
- Records are filtered to the files given (absolute paths under the root), so nested pytest runs inside tests are
  ignored.

**Done when:** the AC-205.5 tests pass, including the spec 157 case (a helper's `mkdir` without parents gives
`test error` with `FileNotFoundError`) and a run under `-n 2`. The existing quiet tests (`test_172_*`, `test_185_*`,
`test_quiet*.py`) still pass.

## t3 — build tests --red prints the red check; build reviewed freezes only after it passed

**Files:** scripts/cplat/buildtests.py, scripts/cplat/testreview.py
**Covers:** AC-205.6
**Goal:** the build gets the exact red-check command for the spec's trace from `cplat component build tests <id>
--red`, and the tests cannot freeze (`cplat component build reviewed`) in a pytest repo until that check exited 0 on
their current content.

**Implementation notes:**
- `buildtests.build_tests(..., red: bool)` and `--red` flag as design Contract 3: trace files ∩ `TEST_FAST` globs of
  the repo shape, `none: test-fast does not run pytest` via `quiet_red.runs_pytest(root)`, and `none: no acceptance
  test files test-fast runs`. Refuse a task or `--load` together with `--red`. Update the module docstring's usage
  lines.
- `testreview.commit`: before the commit, when `build_tests(repo, spec, None, False, None, red=True)["command"]` is
  set, check `<git dir>/cplat-red-check.json` as design Contract 4 (read the file name from a constant in
  `quiet_red`). Leave the `already reviewed` early return in `main` first.
- Repos without `devbox.json`, or without `pytest` in test-fast (the existing tests' temp repos), keep today's
  behaviour.

**Done when:** the AC-205.6 tests that check the command line and the freeze gate pass, and the existing
`build reviewed` and `build tests` tests (`test_179_*`, `test_172_build_tests.py`) still pass.

## t4 — Build and tester prompts: red-check rounds in Phase 1, harness fix by the tester after the freeze

**Files:** plugins/component/commands/build.md, docs/rules/plugins/component/commands/build.yml,
plugins/component/references/build-tighten.md, docs/rules/plugins/component/references/build-tighten.yml,
plugins/svc/agents/tester.md, docs/rules/plugins/svc/agents/tester.yml
**Covers:** AC-205.6, AC-205.7
**Goal:** the orchestrator runs the red check in Phase 1 and after every tester round, sends `test error` and `passes`
lines back with `--wrong-failure` records, and escalates with cause `code` after 2 rounds before any coder. After the
freeze it hands a test that raises in test code to the tester as a harness fix, recorded with `--tighten`.

**Implementation notes:**
- build.md Phase 1: after the trace bullet, run the line `cplat component build tests <id> --red` prints. Each
  `test error` or `passes` line goes back to the tester (only those tests), together with the existing
  `cplat platform runs agent tester … --wrong-failure <test>` call. Run it again after each tester round, including
  the test-review round, and before `cplat component build reviewed` (which refuses otherwise). After 2 rounds with
  lines left, escalate with `--cause code` naming each line, before Phase 2, because a broken frozen test stops the run
  later at a higher cost. `none: …` keeps today's "one erroring for another reason goes back".
- build.md 2.5 (and a coder's report of a failing acceptance test): in a pytest repo, `cplat quiet test-fast --red --
  <failing tests>`. A `test error` line goes to the tester per `build-tighten.md`'s new harness section without asking,
  because the test, not the code, is wrong. In other repos, the failure summary's innermost frame in a test file is
  the sign.
- build-tighten.md: a short "Harness fix" section with the tester prompt of design 5, the `--tighten … --reason
  '<test>: <exception line>'` record and the fallback to `build-test-approval.md`. Merge it with the existing
  helper/type-only paragraph, since both run the same test-diff then `--tighten` sequence.
- svc tester.md, Acceptance mode step 3: when `cplat component build tests <spec> --red` prints a command, the tester
  runs it on its own tests before committing, and every line must be `missing behaviour`.
- **Bytes:** the touched prompt files together must not grow (docs/rules/README.md rule 6). Pay for the new sentences
  by tightening the text they replace (Phase 1's "erroring" bullet, tester step 3, build-tighten's last paragraph).
  Do not rebaseline in this build.
- Register: update the `text` of every changed rule sentence in the three `.yml` files; give new practice sentences a
  reason clause and `source: spec 205`. Add no new hard rule. Keep `--wrong-failure` and `--untraced` in build.md
  (pinned by `test_runs_agents.py`).

**Done when:** `cplat platform rules check` passes (no size growth, every target resolves), the AC-205.6 and
AC-205.7 prompt-structure tests pass (build.md points to `cplat component build tests` and `build-tighten.md`), and
`tests/cplat/test_runs_agents.py` still passes.

## t5 — ADR, plugin versions, changelog fragment and guides

**Files:** docs/adr/, docs/adr/README.md, plugins/component/.claude-plugin/plugin.json,
plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json,
docs/changelog.d/205-acceptance-tests-are-proven-passable.added.md, docs/HOW-IT-WORKS.md, docs/AGENTS.md
**Covers:** none (release bookkeeping)
**Goal:** the decision is recorded as an ADR, the changed plugins carry new minor versions in both places, and the
guides no longer say that test-diff accepts only formatting.

**Implementation notes:**
- Run the `cplat adr add …` command of design.md's ADR decision (never hand-number the file) and fill in Status
  (Accepted, spec 205), Context (W46: 63 stops, the spec 157 `make_repo` case), Decision (the red check classes,
  the freeze gate, the harness fix, edits that change no assertion) and Consequences (Go/Java/Vitest keep the
  orchestrator's judgement; one more pytest run per Phase 1 round). Builds on ADR-101.
- Bump the minor version: component 1.24.0 → 1.25.0 and svc 4.13.0 → 4.14.0, each in `plugin.json` and
  `marketplace.json`. If `main` has moved, bump the minor of whatever version is current.
- Changelog fragment per `docs/changelog.d/README.md`: `cplat quiet test-fast --red`, `build tests --red`, the freeze
  gate, and test-diff accepting comments, docstrings and static imports.
- HOW-IT-WORKS.md §2: the test-diff sentence names formatting, comments, docstrings and static imports. Add one
  sentence: red tests must fail for the missing behaviour before they freeze. AGENTS.md: the merge step's
  "(acceptance tests may only be reformatted)" is updated the same way.

**Done when:** `devbox run validate` passes, `cplat platform pr-check` reports no version or fragment finding, and
`scripts/check-docs.py` (via `devbox run quality`) passes.
