# Design — 212 Local tests run what a change can affect

## Decisions

- **Record what tests touch, at run time** ([ADR-123](../../adr/123-local-test-runs-select-by-recorded-dependencies.md)).
  Half of the test files reach cplat through a subprocess and many read prompts and templates, so a static graph misses
  them. A full run started through `test-fast` traces every process of the run that matters: the pytest processes (with
  `--deps-record PATH`) and every cplat process started from them (SDLC_DEPS_TRACE set).
- **What counts (AC-212.2).** In a traced process: a Python audit hook records `open` (also the bytecode an import reads,
  mapped back to its source), `os.listdir`/`os.scandir` (the listed folder), `glob.glob` (the fixed part of the pattern, as a
  tree) and `subprocess.Popen` (each argument that is a repo path: a file, or a folder that counts for every file below
  it). A wrapper around `builtins.__import__` records every import statement that runs, also of a module already imported
  by an earlier test in the same worker (a lazy import inside a function). A cplat process adds every repo module in
  `sys.modules` at exit. Module-level imports are added statically (`depstrace.Imports`): of each test file and of every
  recorded `.py` file, closed over module-level imports only; imports inside functions count only when they run, since the
  static closure over every import reaches 91 % of the test files for the median module (measured).
- **Buckets.** A test file's events go to its bucket; the setup of a fixture of a wider scope than a function goes to
  `fixture:<name>`, and a shared render's build to `render:<key>` (`SharedRenders` switches and attaches). A test file
  depends on its bucket plus every fixture it names and every render it copied, transitively. A cplat process writes its
  record into the folder of the bucket that was current when it started (inherited through SDLC_DEPS_TRACE).
- **The suite's autouse fixtures are muted.** `conftest.py`'s autouse fixtures import a dozen cplat modules only to patch
  them; counting those would make every test depend on them. The import wrapper mutes imports made from those functions
  (found in conftest.py's AST), and everything they trigger. Non-autouse conftest fixtures (`new_service`, `clock`) count.
- **The selection (AC-212.1, AC-212.3).** `scripts/testselect.py args` (standard library only) picks a map, computes the
  changed files and prints the pytest arguments: `--deps-record <map to record>` (every test) or `--deps-select=<files>`
  (comma-separated, possibly empty). Rules in order: `--full`; no map;
  a shared file changed (`conftest.py` and its module-level import closure including `pytest_plugins`, `pytest.ini`,
  `requirements-test.txt`, `testselect.py`, `depstrace.py`, `depsmap.py`); then per changed file: a test
  file selects itself, another file selects the test files that depend on it (a file in their files, its folder in their
  listed folders, or a tree above it); a changed code or configuration file that still exists and that no test depends on
  runs everything; then the test files new since the map and the ones that failed in it are added; more than half of the
  test files runs everything.
- **The change set (AC-212.6).** `git diff --name-only --no-renames <map commit>` (working tree against the commit: committed,
  staged and unstaged), plus `git ls-files --others --exclude-standard`, plus the map's `dirty` list (files that differed
  from HEAD at the start or end of the recording). The map with the fewest changed files wins, ties to the newest.
- **Maps.** `<git common dir>/sdlc-test-deps/<time>-<pid>.json`, written to a temporary name and renamed, the 5 newest kept.
  A map is written only by a run that ends with status 0 or 1 (an interrupted run, or one that collected nothing, writes
  none). A map's `failed` paths come from the reports' fspath, which is relative to pytest's rootdir (`tests/cplat`).
- **The selection runs inside pytest.** Under `--deps-select` the plugin's `pytest_ignore_collect` skips every `test_*.py`
  outside the list (in each xdist worker, from the same option), and an empty list turns pytest's "no tests collected"
  (exit 5) into exit 0. So the suite command stays one literal line, `uv run --with-requirements requirements-test.txt
  pytest tests/cplat -q -n auto`, in `devbox.json` and `ci-local.sh`, where the pin check (spec 127), the timeout check
  (spec 185) and the suite-command tests (specs 084, 112, 184) read it; only the selector's arguments are appended.
- **Recipes (AC-212.4, AC-212.5).** `devbox run test-fast` with no argument or only `--full` runs that line with
  `$(python3 scripts/testselect.py args "$@")`; any other arguments go to `test-fast.sh` as before (spec 172, which is
  unchanged). `devbox run test` is `devbox run test-fast --full`. `ci-local.sh` parses `--full`, `--site` and `--render` in
  any order and appends `testselect.py args [--full]` to its suite line.
- **Off by default (AC-212.7).** Without `--deps-record` the plugin registers nothing and installs no hook; cplat checks one
  environment variable. CI's `pytest tests/cplat --shard` is unchanged.
- **A run with nothing to check passes and says so.** [ADR-074](../../adr/074-a-gate-that-checked-nothing-fails.md) covers the
  gates of generated repos; here CI still runs every test, and the line names the count and the `--full` way out.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/depstrace.py` | the recorder (audit hook, import wrapper, buckets), the cplat child record, module-level imports | new |
| `scripts/cplat/cplat.py` | starts the child record when SDLC_DEPS_TRACE is set | changed |
| `tests/cplat/depsmap.py` | pytest plugin: `--deps-record`, buckets per test file and fixture, merging the map | new |
| `tests/cplat/conftest.py` | loads `depsmap` | changed |
| `tests/cplat/shared_render.py` | renders record into their own bucket and attach to the copying test | changed |
| `scripts/testselect.py` | the selection and its message | new |
| `devbox.json`, `scripts/ci-local.sh` | the recipes append the selector's arguments to the suite line | changed |

## Contract

Map (JSON, version 1): `{"version": 1, "commit": sha, "dirty": [path], "recorded": "YYYY-MM-DDTHH:MM:SS", "failed": [test
file], "tests": {test file: {"files": [path], "dirs": [path], "trees": [path or "."]}}}`; paths are repo-relative posix.

`testselect.py args [--full]`: stdout one line, `--deps-record <path>` or `--deps-select=<file>,<file>…` (empty after `=`
when nothing is selected). One stderr line: `test-fast: all <N> test files: <reason>; this run records a new dependency map`,
`test-fast: <k> of <N> test files (map at <sha9>, <c> changed file(s)); devbox run test-fast --full runs every test`, or
`test-fast: 0 of <N> test files: no test file can see this change (map at <sha9>, <c> changed file(s)); devbox run test-fast --full runs every test`.
