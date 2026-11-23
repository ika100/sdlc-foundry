# Design — 205 Acceptance tests are proven passable before they freeze

## Decisions

- **The red check is a pytest plugin plus a classifier, not log parsing.** `cplat quiet test-fast --red` loads a second
  injected plugin (`test_progress/cplat_red_check.py`, next to the spec 185 progress plugin and loaded the same way). The
  plugin writes the raw facts of each failure (exception type and MRO, message, module named, the traceback's files) as
  JSON lines. `quiet_red.py` classifies them against the shape's test globs. The class depends on the innermost
  *repo* frame, and `--tb=line` output drops that frame, so it cannot be parsed back from the log (AC-205.5).
- **The innermost frame is the innermost frame inside the repo.** Stdlib and site-packages frames are skipped. In the
  spec 157 case, `Path.mkdir` raises in `pathlib.py`, and the innermost repo frame is the helper `make_repo` in test
  code, so the test is classed `test error`.
- **Specific rules come before phase rules.** A `NotImplementedError`, or an import or attribute error that names a
  non-test module, is `missing behaviour` in any phase, collection included. The spec lists these as the signs of
  missing behaviour, and a top-level `import <new module>` is the most common red failure in Python tests. A collection
  error of that kind is reported once per test that the file defines statically (`def test…`), so the output keeps
  one line per test (AC-205.5).
- **Skips.** A skipped test that carries the `smoke` marker is printed as `skipped (not judged)` and does not count.
  Every other skip and every `xfail` is a `test error`. Smoke tests skip in `test-fast` by design (`SMOKE_BASE_URL=`),
  and any other skip or xfail proves nothing about the missing behaviour. This adds one output label to the three
  classes of AC-205.5. It never makes the check pass on its own: at least one judged test must be `missing behaviour`.
- **"Test-fast runs pytest"** means that the `test-fast` script in `./devbox.json` contains the word `pytest`. That
  holds in the platform repo and both Python templates. A run where the plugin wrote no header (pytest never started)
  also counts as not pytest.
- **The freeze is gated in code.** `cplat component build reviewed` refuses in a pytest repo until the last red check
  exited 0 on the current content of the trace's test files. "Freeze only at a commit where the check exits 0" then
  holds without relying on the prompt (AC-205.6).
- **The harness fix of AC-205.7 needs no new test-diff check.** After the tester's fix, `cplat spec test-diff $RED`
  prints `test helper …` or `type-only …` for a fix that leaves assertion lines, test definitions, criterion ids and
  skips alone (AC-171.7, AC-179.4). The tester then records it with `--tighten` and the harness reason. Any other
  `changed —` line goes to the person (`build-test-approval.md`). The PR lists the change through the existing
  `approved_test_diffs` record (kind `tightened`, AC-165.3).
- **Criterion ids are compared as a set**, as `formatting_only` already does (spec 169: a test may name its criterion
  again). The set compare refuses a criterion id that is added, dropped or changed, as AC-205.4 asks. A second mention
  of an id already in the file is no change to the trace.
- **Directive comments are not plain comments.** A comment that changes what a tool does (`noqa`, `type:`, `pragma`,
  `nolint`, `//go:build`, `eslint-…`, `@ts-…`, `@vitest-environment`, the full list in Contract 1) is excluded from the
  `comments` kind. A changed directive leaves today's result in place, because spec 160 judges suppressions and every
  other directive can change what is tested.
- **ADR.** The decision outlives this feature, so it gets an ADR: a red acceptance test freezes only when it fails for
  the missing behaviour, and an edit that changes no assertion passes test-diff without a record. The ADR builds on
  ADR-101. The plan's t5 creates it with `cplat adr add red-tests-fail-for-the-missing-behaviour-before-they-freeze
  --decision "A red acceptance test freezes only when it fails for the missing behaviour; edits that change no assertion
  pass test-diff without a record"` (the architect session had no shell) and fills it from this section and Contract 2.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/testdiff_neutral.py` | `judge(old, new, name)`: comments, docstrings and static imports as the only difference (AC-205.1 to AC-205.4) | new |
| `scripts/cplat/spec.py` | `test_diff` calls `testdiff_neutral.judge` after the formatting check; nothing else changes | changed |
| `scripts/cplat/test_progress/cplat_red_check.py` | pytest plugin: writes one JSON line per failing phase or collection error, and per passed or skipped test | new |
| `scripts/cplat/quiet_red.py` | `run(cwd, args, raw, on)`, `runs_pytest(cwd)`, `classify(records, root, shape, files)`, the record file | new |
| `scripts/cplat/quiet.py` | parses `test-fast --red -- <args>` and hands it to `quiet_red.run`; usage line | changed |
| `scripts/cplat/buildtests.py` | `cplat component build tests <spec> --red` prints the red-check line or `none: …` | changed |
| `scripts/cplat/testreview.py` | `build reviewed` refuses without a passing red check on the current tests (pytest repos) | changed |
| build prompt, `build-tighten.md`, svc `tester.md` | Phase 1 red check and rounds; 2.5 harness fix; the tester's own check | changed |

## Contract

### 1. `cplat spec test-diff` — no assertion changed (AC-205.1 to AC-205.4)

`testdiff_neutral.judge(old: str, new: str, name: str) -> str | None` returns `"no assertion changed: <kinds>"` or
`None`. `<kinds>` is the comma-and-space-joined subset, in this order, of `comments`, `docstrings`, `imports` whose
content differs between `old` and `new`. It returns `None` in each of these cases:

- the suffix is not one of `.py`; `.ts .tsx .mts .cts .js .jsx .mjs .cjs`; `.go`; `.java`;
- the set of `AC-\d{3,}\.\d+` ids differs;
- the directive comments (below) differ as a multiset;
- the text does not lex or parse (an unterminated string or comment, a `SyntaxError`);
- the remaining code differs;
- no kind differs (pure formatting is `formatting_only`'s line).

Python (`.py`):
- Comments are the `COMMENT` tokens from `tokenize`, compared by their text with whitespace collapsed.
- Docstrings are the first statement of a `Module`, `ClassDef`, `FunctionDef` or `AsyncFunctionDef` body when it is
  `Expr(Constant(str))`. A string expression anywhere else is code.
- Imports are the `Import` and `ImportFrom` nodes at every level, compared as a multiset of `ast.dump`, so a reorder
  counts as a difference only when the set changes. `importlib.import_module(…)` and `__import__(…)` are calls, so
  they stay code.
- The remaining code is the AST with docstrings and imports removed. Its dump is normalised as `_py_shape` does
  (string constants with whitespace collapsed); `_py_shape` may be refactored to take a tree for this.

TS/JS, Go, Java: a lexer splits the text into code and comments and keeps string literals in the code.
- Comments are `//…` to the end of the line and `/*…*/` blocks.
- Strings are `"…"` and `'…'` with `\` escapes, and backtick strings (a TS/JS template literal with escapes, taken
  whole without parsing `${…}`; a Go raw string without escapes). Java also has `"""…"""` text blocks.
- In TS/JS, a `/` starts a regex literal when the previous code character is absent or one of `(,=:[!&|?{};+-*%<>~^`,
  or when the previous word is `return`. The regex runs to the next unescaped `/` outside `[…]` and stays code.
- Static imports are taken out of the code, anchored at the start of a line:
  - TS/JS: `import [type] <clause> from '<m>'[;]` (the clause may span lines inside `{…}`) and `import '<m>'[;]`.
    `import(`, `require(` and `import x = require(…)` stay code.
  - Go: `import [alias] "<m>"`, and `import ( … )` blocks. Each spec line in a block is one import.
  - Java: `import [static] a.b.C[.*];`.
- The remaining code is compared with all whitespace removed. Comments and imports are compared as multisets of their
  whitespace-squashed text.

Directive comments are comments whose text after the marker starts, after optional spaces, with one of: `noqa`, `type:`,
`pragma`, `pylint:`, `ruff:`, `flake8:`, `mypy:`, `fmt:`, `isort:`, `nosec`, `nolint`, `go:`, `+build`, `eslint`,
`@ts-`, `prettier-ignore`, `istanbul`, `c8`, `v8 ignore`, `@vitest-environment`, `@jest-environment`, `biome-ignore`,
`NOSONAR`, `CHECKSTYLE`, `/ <reference`, or a `#!` / `-*-` comment on the first two lines.

`spec.test_diff` per file:

```
lint = suppression_only(old, new, f)                 # unchanged, first
if lint[0] or lint[1]: out[f] = lint
else:
    fmt = formatting_only(old, new, f)
    why = testdiff_neutral.judge(old, new, f)
    out[f] = (True, why) if why else fmt             # refused → today's first reason (AC-205.4)
```

The approvals, helper (AC-171.7) and type-only (AC-179.4) passes that follow are unchanged. The command prints
`<file>: no assertion changed: comments, imports` and exits 0 when every file passes. It records nothing: no approval
entry, no `approved_test_diffs` entry, no refused-diff metric. A Python change that only edits comments now prints
`no assertion changed: comments` instead of `formatting only`.

### 2. `cplat quiet test-fast --red` (AC-205.5)

```
cplat quiet [--raw] test-fast --red -- <test file or node id>...
```

- `--red` excludes `--repeat` and needs at least one argument after `--`. A refusal prints the usage line on stderr
  and exits 2. The usage line becomes
  `usage: cplat quiet [--raw] <devbox-script> | cplat quiet [--raw] test-fast [--repeat N | --red] -- <test args>   (a key of shell.scripts in ./devbox.json; only test-fast takes arguments, after --)`.
- A repo whose `test-fast` script does not contain `pytest` gets the usage line on stderr and exit 2, without running
  anything. The same happens after the run when the plugin wrote no header.
- The run is `devbox run -e … test-fast -- <args>`, with the log path, the 9-minute limit and the gave-up lines of
  `quiet_limit` (exit 124). Both injected plugins are loaded: `PYTEST_ADDOPTS` gets `-p cplat_test_progress -p
  cplat_red_check`, plus `CPLAT_RED_FILE=<log>.red` and `CPLAT_RED_ROOT=<repo root>`.
- `--raw` changes nothing for `--red`: the per-test lines are the output.

Plugin (`cplat_red_check`, pytest hooks only, no `cplat` imports):
- The process without `workerinput` writes `{"kind": "start"}` at configure.
- Every process, xdist workers included, appends one JSON line per record:
  - `{"kind": "test", "nodeid", "file": <abs path>, "when": "setup"|"call"|"teardown", "outcome": "passed"|"failed"|"skipped", "xfail": bool, "smoke": bool, "exc": [MRO class names, innermost type first] | null, "message": str, "module": str | null, "module_file": str | null, "top_file": str | null, "frames": [abs paths of traceback entries, outermost first]}`
    for each failed or skipped phase and for each passed `call`;
  - `{"kind": "collect", "file", "exc", "message", "module", "module_file", "top_file", "frames"}` for each collection error.
- `module` is `exc.name` for an `ImportError`; for an `AttributeError` whose `obj` is a module, it is that module's
  `__name__`. `module_file` is the module's resolved file when it can be found, else null; `top_file` is the same for
  the module's top-level package (#956).
- The plugin keeps its options in the environment, because xdist workers need them. The classifier ignores records
  whose `file` is not one of the files the run was given, so a pytest started inside a test (in a temp dir) changes
  nothing.

Classification (`quiet_red.classify`):
- **Test code** is a path that matches `spec.test_globs(spec.repo_shape(root))` relative to the root, or any
  `conftest.py`. A **repo frame** is a frame inside the root whose path has none of the `spec._ignored` parts and no
  `site-packages`.
- A module is a **test module** when its file is test code. When it has no file, it is a test module when its first
  dotted part is `conftest` or the first path segment of a test glob (e.g. `tests`).
- The rules apply per test, first match wins:
  1. Collection error in its file: rule 4 or 5 decides, else `test error`.
  2. Every phase passed → `passes`.
  3. Skipped with the smoke marker → `skipped (not judged)`. Skipped otherwise, or xfail → `test error`.
  4. `NotImplementedError` in any phase → `missing behaviour`.
  5. `ImportError`, `ModuleNotFoundError` or `AttributeError` in any phase whose module is not a test module: an
     `AttributeError`, or an import error whose top-level package is **own code** (`top_file` is a repo frame, or a
     directory or `.py` of that name sits under the root or `src/`, or it is the normalised `[project] name` of
     `pyproject.toml`) → `missing behaviour`; any other import error → `test error`, with the line
     `<pkg> is not installed: add it to the dev dependencies` when `top_file` is null (#956).
  6. Failure in setup or teardown → `test error`.
  7. Call phase `AssertionError` (or subclass) or pytest's `Failed` (`pytest.fail`, `pytest.raises` "DID NOT RAISE") →
     `missing behaviour`.
  8. Call phase, any other exception: the innermost repo frame is not test code → `missing behaviour`; it is test code,
     or there is no repo frame → `test error`.

Output, sorted by node id:

```
tests/cplat/test_x.py::test_a: missing behaviour — ModuleNotFoundError: No module named 'redcheck'
tests/cplat/test_x.py::test_b: test error — FileNotFoundError: [Errno 2] No such file or directory: '/tmp/r/a/b'
tests/cplat/test_x.py::test_c: passes
tests/cplat/test_x.py::test_d: skipped (not judged) — SMOKE_BASE_URL is not set
red check: 1 missing behaviour, 1 test error, 1 passes, 1 skipped (log: <path>)
```

- The exception line is `<innermost type>: <last non-empty line of the message>`, cut at 200 characters, or the type
  alone when the message is empty.
- For a collection error, each test name found statically in the file becomes `<file>::<name>`. When there is none,
  the line names the file.
- Exit codes: 0 when at least one test was judged and every judged test is `missing behaviour`; 1 otherwise,
  including `red check: no test ran`; 2 usage; 124 gave up.
- Record: after an exit of 0 or 1, `<git dir>/cplat-red-check.json` is overwritten with
  `{"head": <sha>, "exit": 0|1, "files": {<repo-relative test file>: <sha256 of content>}, "at": <ISO-8601 UTC>}`.
  The files come from the arguments, with node ids reduced to their file. Nothing is written to the run record:
  AC-205.6 records wrong failures through `cplat platform runs agent tester --wrong-failure`.

### 3. `cplat component build tests <spec> --red` (AC-205.6)

- Prints `cplat quiet test-fast --red -- <files>`. The files are the trace's test files that match the shape's
  `TEST_FAST` globs (so `e2e/` stays out), sorted and shell-quoted.
- Prints `none: test-fast does not run pytest` when `quiet_red.runs_pytest(root)` is false, and
  `none: no acceptance test files test-fast runs` when the list is empty.
- `--red` together with a task or `--load` is a `PlatformError` ("use one of a task, --load, --red"). `--json` adds
  `"red": true` to the existing document.

### 4. `cplat component build reviewed <spec>` freeze gate (AC-205.6)

- When `buildtests` would print a red-check command for the spec (pytest repo, at least one file), `commit()` first
  reads `cplat-red-check.json`.
- It raises a `PlatformError` with "the red check has not passed on the current acceptance tests" and the hint "run
  the line `cplat component build tests <spec> --red` prints; it must exit 0" in each of these cases:
  - the file is missing;
  - `exit` is not 0;
  - a file of the command is missing from `files`;
  - a recorded hash differs from the file's current content.
- A repo that is not pytest, or a spec without such files, behaves as today. `already reviewed` stays first.

### 5. Build orchestration (AC-205.6, AC-205.7)

- **Phase 1.** After the tester's commit and a passing trace, the orchestrator runs the line `cplat component build
  tests <id> --red` prints. Each `test error` or `passes` line goes back to the tester ("**Acceptance mode.** Change only
  these tests so that each fails because the behaviour is missing: <lines>"), and one
  `cplat platform runs agent tester --wrong-failure <node id>`… call records them. The check runs again after every
  tester round, the test-review fix round included. After 2 tester rounds with lines left, the orchestrator escalates
  with `--cause code` and the reason `wrong failures after 2 tester rounds: <node id> (<class>: <exception line>); …`,
  before Phase 2. `none: …` keeps today's bullet (one erroring for another reason goes back).
- **2.5 and a task's test run.** A failing acceptance test in a pytest repo is run as `cplat quiet test-fast --red --
  <failing tests>`. A `test error` line goes to the tester as a harness fix (`build-tighten.md`, new section): "Fix
  only test code so that `<test>` no longer raises `<exception line>`. Change no assertion, test definition or criterion
  id. Run `cplat spec test-diff $RED --task <task>`. On a `test helper` or `type-only` line, run `cplat spec test-diff
  $RED --tighten <file> --task <task> --reason '<test>: <exception line>'`. Any other `changed —` line: revert and
  report `UNRESOLVED`." An unresolved fix goes to the person (`build-test-approval.md`). `missing behaviour` lines go
  to a coder as today. In repos without the check, the orchestrator reads the innermost frame from the failure summary.
