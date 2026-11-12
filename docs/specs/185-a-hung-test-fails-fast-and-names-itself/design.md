# Design — 185 A hung test fails fast and names itself

## Decisions

- **Per-test limit through pytest-timeout, configured in `tests/cplat/pytest.ini`** (`timeout = 120`, `timeout_method = signal`, `required_plugins = pytest-timeout pytest-xdist`). Every entry point (`devbox run test-fast`, `scripts/test-fast.sh`, `scripts/ci-local.sh`, the CI shards) runs pytest on `tests/cplat` or a path inside it, so pytest finds this ini file and no command line changes. The signal method raises inside the test, so the test fails with pytest-timeout's `Timeout (>120.0s)` line and the stack, and the worker goes on with the next test; the thread method would kill the xdist worker. pytest-timeout times setup, call and teardown together (`timeout_func_only` stays false), so a slow setup or teardown is caught as well. `required_plugins` makes a run without the pinned file fail at once instead of silently running without limits (AC-185.1, AC-185.2).
- **The sleep guard replaces `time.sleep` and `asyncio.sleep` before any `cplat` module is imported.** Several modules bind the function at import (`core.sleep = time.sleep`, `engine.sleep`, `dispatch.sleep`, `dispatch_view.wait_result(sleep=time.sleep)`), so a monkeypatch per test would miss them. `tests/cplat/conftest.py` calls `sleepguard.install()` as its first statement after the `sys.path` line, before it imports `console_support` and `sharding`. Outside a test the guard passes every call through (AC-185.3).
- **Only sleeps called from repository code count.** The guard looks at the caller's frame: a call from a file under the repository root counts, a call from the standard library or site-packages does not (`subprocess.Popen.wait(timeout=…)` polls with `time.sleep`, execnet sleeps in its I/O thread), and `tests/cplat/waiting.py` is exempt, because its poll is the sanctioned wait for an event or a file (spec 178). Fake programs run as separate processes and never load the guard (A3).
- **A crossing sleep raises `pytest.fail.Exception`** (a `BaseException`), so an `except Exception` in the code under test cannot swallow it, and the guard also records it, so a sleep in a thread the test started, or one caught by `except BaseException`, still fails the test in its report.
- **`cplat quiet test-fast` learns which tests run through an injected pytest plugin**, not by parsing output, because the output is quiet (`-q`) and buffered. quiet sets `PYTHONPATH` to a directory that holds only `cplat_test_progress.py` (so no `cplat` module shadows a repo's own), adds `-p cplat_test_progress` to `PYTEST_ADDOPTS` and names a progress file. The plugin works in every repo whose test-fast runs pytest, with no change to that repo. **devbox resets `PYTHONPATH`** in its environment (found when t3 ran under a real `devbox run test-fast`, decided 2026-11-12 on the build escalation): quiet passes the three variables as `devbox run -e KEY=VALUE … <script>` instead of only through its own environment; the command after the `-e` pairs is unchanged, and spec 172's tests compare the argv without the `-e` pairs. The progress file's variable has **no `CPLAT_` prefix** (`PYTEST_PROGRESS_FILE`): spec 178's seam test (AC-178.8) keeps every `CPLAT_*` variable away from the test command, and quiet's own variable must not look like one of the outer run's (decided 2026-11-12 on the t4 escalation). A progress file that was never created means the runner is not pytest (AC-185.5), so quiet needs no guess from `devbox.json`.
- **The run starts in its own session** (`start_new_session=True`), so quiet stops `devbox`, `uv`, pytest and the xdist workers together with `killpg`: SIGTERM, then SIGKILL after 5 s.
- **The give-up text always says `9 min`.** `quiet_limit.GIVE_UP_SECONDS = 540` is the seam that tests lower; the printed label is the constant `GIVE_UP_LABEL = "9 min"`, so a test with a 1-second limit checks the real line.
- **Suite time comes from the shard reports.** `tests/cplat/sharding.py` adds the wall time and the 15 slowest tests to the report it already writes. `scripts/check-shards.py` sums them, prints them and writes `suite-time.json`, which the coverage job uploads on pushes to `main` (AC-185.7).
- **The retro reads the artifacts through `gh`** (`gh api …/actions/artifacts`, `gh run download`), with the `GH_TOKEN` the retro job already has (A9). `retro_suite.fetch` is the one seam; `conftest.py` replaces it with "no runs" for every test, so no test reaches GitHub (AC-185.8).
- **The cross-cutting part gets an ADR**, made with `cplat adr add` in t7: test time is bounded at three levels (120 s per test, 1 s of real sleep per test, 9 min per quiet test-fast run in every shape).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `requirements-test.in`, `requirements-test.txt` | pytest-timeout added and pinned (`uv pip compile --universal requirements-test.in -o requirements-test.txt`) | changed |
| `scripts/check-pins.py` | `TEST_TOOLS` holds `pytest-timeout` | changed |
| `tests/cplat/pytest.ini` | `timeout`, `timeout_method`, `required_plugins` | changed |
| `tests/cplat/sleepguard.py` | `install()`, the per-test budget, the two pytest hooks | new |
| `tests/cplat/conftest.py` | installs the guard first, imports its hooks; autouse `no_real_suite_times` | changed |
| `scripts/cplat/quiet_limit.py` | start in a new session, wait with a deadline, stop the group, read the progress file, print the give-up block | new |
| `scripts/cplat/test_progress/cplat_test_progress.py` | the pytest plugin quiet injects | new |
| `scripts/cplat/quiet.py`, `scripts/cplat/quiet_repeat.py` | run through `quiet_limit`, exit 124 without the flaky rerun on give-up | changed |
| `tests/cplat/sharding.py` | `wall_s` and `slowest` in the shard report | changed |
| `scripts/check-shards.py` | optional timing fields, the suite-time lines, `--timing-out` | changed |
| `.github/workflows/ci.yml` | coverage job writes and (on `main` pushes) uploads `cplat-suite-time` | changed |
| `scripts/cplat/retro_suite.py` | fetch the timing artifacts, build and render "Test suite time" | new |
| `scripts/cplat/retro.py`, `scripts/cplat/retro_report.py` | call it, keep it in the report, render it | changed |
| `plugins/{component,system}/commands/ship.md` + their register files | the decision-becomes-a-task rule | changed |

## Contract

### Per-test limit (AC-185.1)

`tests/cplat/pytest.ini`:

```ini
[pytest]
timeout = 120
timeout_method = signal
required_plugins = pytest-timeout pytest-xdist
markers =
    slow: renders real templates with copier (needs copier or uv)
```

A test over the limit is reported by pytest-timeout as failed: its node id in the `FAILED` line, `Failed: Timeout (>120.0s) from pytest-timeout.` and the stack of the interrupted frame. The run exits 1. There is no per-test override (A1).

### Pins (AC-185.2)

`requirements-test.in`, one name per line, unpinned, in this order: `pytest`, `pytest-timeout`, `pytest-xdist`, `pyyaml`, `ruamel.yaml`. `requirements-test.txt` is the `uv pip compile --universal` output. `check-pins.py` part 4 reports `ERROR: <file>:<line>: --with pytest-timeout: installs pytest-timeout without requirements-test.txt` for a suite command that installs it with `--with`, as for the other four.

### Sleep guard (AC-185.3)

```python
# tests/cplat/sleepguard.py
LIMIT_S = 1.0
ROOT: Path                        # repository root
EXEMPT = {ROOT / "tests/cplat/waiting.py"}

def install() -> None             # idempotent; replaces time.sleep and asyncio.sleep
def pytest_runtest_protocol(item, nextitem)   # hookwrapper: arms a fresh budget for setup+call+teardown, disarms after
def pytest_runtest_makereport(item, call)     # hookwrapper: a recorded crossing turns a passed report of that test into a failed one
```

Per call, while a test is armed and the caller's file is under `ROOT` and not in `EXEMPT`:

```
if used + s > LIMIT_S:
    msg = f"real sleep of {s:g} s at {rel_file}:{line} takes this test over 1 s; wait for an event or a file, or use the fake clock"
    record(msg); raise pytest.fail.Exception(msg)     # never sleeps
used += s; real_sleep(s)
```

`rel_file` is the caller's path relative to the repository root, POSIX separators (for example `scripts/cplat/headless.py:562`). The first recorded message is the test's failure text. Unarmed (collection, session fixtures, between tests) or a caller outside `ROOT`: the real sleep, uncounted. `asyncio.sleep` follows the same rule before it awaits the original.

### quiet gives up (AC-185.4, AC-185.5)

```python
# scripts/cplat/quiet_limit.py
GIVE_UP_SECONDS = 540             # seam: tests lower it
GIVE_UP_LABEL = "9 min"
MAX_LISTED = 20
STOP_GRACE_SECONDS = 5
PROGRESS_ENV = "PYTEST_PROGRESS_FILE"
PLUGIN_DIR: Path                  # scripts/cplat/test_progress

def progress_env(log: Path) -> tuple[dict[str, str], Path]
    # env additions: PYTHONPATH=<PLUGIN_DIR>[:<old>], PYTEST_ADDOPTS=<old> -p cplat_test_progress,
    # PYTEST_PROGRESS_FILE=<log>.progress; and that path
def start(cmd, *, cwd, out, env) -> subprocess.Popen          # start_new_session=True
def wait_until(proc, deadline: float) -> int | None           # exit code, or None at the deadline (monotonic)
def stop(proc) -> None                                        # killpg SIGTERM, grace, killpg SIGKILL; reaps
def still_running(progress: Path) -> list[str] | None         # None: the file does not exist (not pytest)
def gave_up_lines(script: str, log: Path, progress: Path) -> list[str]
```

Progress file (written by the plugin, read by quiet; a fake `devbox` in a test may write it):

```
# cplat test progress
start tests/cplat/test_a.py::test_one
end tests/cplat/test_a.py::test_one
start tests/cplat/test_b.py::test_two
```

The plugin creates the file at `pytest_configure` of the controller (not of an xdist worker), appends `start <nodeid>` at `pytest_runtest_logstart` and `end <nodeid>` at `pytest_runtest_logfinish` (in the controller xdist relays both), and removes `PYTEST_PROGRESS_FILE` and its `-p` from `os.environ`, so a pytest started by a test does not write to it. "Still running" = started and not ended, in start order.

Output and exit when the deadline passes (whole block, nothing else):

```
FAILED (gave up after 9 min): devbox run test-fast (log: <log path>)
still running: <node id>            # one per test, at most 20
... and <n> more                    # only when more than 20
```

or, with no progress file, the first line and `still running: not reported by this test runner`. Exit 124. No failsum, no sidecar, no flaky rerun (AC-165.7). With `--repeat N` all N runs share one deadline; each run that gave up prints its block with its own log; the result is 124 and no test runs again alone. A run that ends before the deadline prints and exits exactly as before. Any other `cplat quiet <script>` is unchanged (the limit is test-fast's only).

### Shard report and coverage job (AC-185.7)

Shard report (`--shard-report`), new keys beside `shard`, `total`, `collected`, `ran`:

```json
{"wall_s": 71.43, "slowest": [{"id": "tests/cplat/test_x.py::test_y", "s": 12.07}]}
```

`wall_s`: seconds from `pytest_sessionstart` to `pytest_sessionfinish` of the controller, 2 decimals. `slowest`: at most 15, each node id with the sum of its setup, call and teardown durations, 2 decimals, sorted by seconds descending, then id. Written green or red.

`scripts/check-shards.py [--timing-out PATH] REPORT...`: a report without `wall_s`/`slowest` stays valid; present but of the wrong type (`wall_s` not a number, `slowest` not a list of `{id: str, s: number}`) is `not a shard report`. After the coverage result, when every report has timing:

```
suite time: 284.6 s over 4 shards (slowest shard 75.1 s)
slowest tests:
  12.1 s  tests/cplat/test_x.py::test_y
  ...                                # 15 lines at most, over all shards
```

(`<sum>` and the shard time with 1 decimal; test seconds with 1 decimal, two spaces, the id.) When only some reports have timing: `suite time: not available: shard <i> has no timing` (lowest such shard). None has timing: no suite-time line. The exit code depends on coverage alone. `--timing-out` writes, when every report has timing:

```json
{"schema": 1, "suite_s": 284.6, "slowest_shard_s": 75.1, "shards": {"1": 70.2, "2": 75.1, "3": 68.0, "4": 71.3},
 "slowest": [{"id": "...", "s": 12.07}], "sha": "<GITHUB_SHA or null>", "run_id": "<GITHUB_RUN_ID or null>"}
```

`ci.yml` job `platform-tests-cover`: `python3 scripts/check-shards.py --timing-out suite-time.json shards/*.json`, then an upload step `if: always() && github.event_name == 'push' && github.ref == 'refs/heads/main'`, artifact name `cplat-suite-time`, path `suite-time.json`, `retention-days: 35`, `if-no-files-found: ignore`, the pinned `upload-artifact` SHA already in the file. The shard artifacts keep `retention-days: 1`.

### Retro section (AC-185.8)

```python
# scripts/cplat/retro_suite.py
ARTIFACT = "cplat-suite-time"
TOP = 15
def fetch(repo: str, since: datetime.date) -> list[dict]
    # [{"run_id": str, "created_at": RFC3339, "data": <suite-time.json>}] of non-expired artifacts named ARTIFACT
    # whose workflow_run.head_branch is "main", created on or after `since`; through retro_github.gh:
    # `api --paginate repos/<repo>/actions/artifacts?name=cplat-suite-time&per_page=100`, then per run
    # `run download <run_id> -R <repo> -n cplat-suite-time -D <tmp>`. Raises SuiteTimeError(reason) on any failure.
def section(week: str, runs: list[dict]) -> dict
def unavailable(reason: str) -> dict
def render(sec: dict) -> str
```

`section` dict (stored as `report["suite_time"]`):

```json
{"weeks": [{"week": "2026-W45", "runs": 12, "median_suite_s": 281.0, "median_slowest_shard_s": 74.2}, {"week": "2026-W44", "runs": 0}],
 "slowest": [{"id": "tests/cplat/test_x.py::test_y", "median_s": 12.1, "runs": 9}],
 "unavailable": null}
```

`weeks`: the retro week first, then the 3 before it (`retro_rules.weeks_of`, reversed); a run belongs to the ISO week of its `created_at`. `slowest`: the retro week's runs only; for each test id in any run's `slowest`, the median of its seconds over the runs that list it and that count; top 15 by median descending, then id. `unavailable`: a reason string, then the other keys are empty.

Rendered (private and public alike), after "Agents" and before the footer:

```
## Test suite time
| week | runs | median suite time | median slowest shard |
|---|---|---|---|
| 2026-W45 | 12 | 281.0 s | 74.2 s |
| 2026-W44 | no data | | |
Slowest tests of 2026-W45 (median over runs):
  1. 12.1 s  tests/cplat/test_x.py::test_y (9 runs)
```

A retro week with no runs prints `Slowest tests of <week>: no data`. Unreadable data: the section is the heading and `not available: <reason>`. `retro.build_report` calls `fetch(autoissue.default_repo(), <first day of the 4-week window>)` in a `try` that turns `SuiteTimeError` and any other exception into `unavailable(<reason>)`; the retro never fails on it. A `report.json` without `suite_time` renders without the section.

### Ship prompts (AC-185.6)

One sentence in each ship prompt, of the form: a decision taken on an escalation that needs code, test or document work becomes a task in the spec's plan before the ship goes on, so that it is carried out and not only recorded. Component ship: under "Unattended rules"; system ship: under "Escalate". Register entries: next free `R<n>` in `docs/rules/plugins/component/commands/ship.yml` and `docs/rules/plugins/system/commands/ship.yml`, `class: practice`, `source: spec 185`, `text` a quote of the sentence. The two prompt files together stay at most at their bytes before the change (rule 6 of the register README), so other sentences in them are tightened to make room, with their register `text` updated.
