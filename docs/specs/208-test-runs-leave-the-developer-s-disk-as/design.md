# Design — 208 Test runs leave the developer's disk as they found it

## Decisions

- **One pytest plugin, no entry-point changes.** Every cplat entry point (`devbox run test-fast` with or without arguments, `scripts/test-fast.sh`, `scripts/ci-local.sh`, the CI shards, a plain serial or `-n auto` run) goes through `tests/cplat/conftest.py`. A new self-contained plugin `tests/cplat/runtemp.py`, loaded from the conftest with `pytest_plugins = ["runtemp"]`, owns the run's directory, its uv cache and its cleanup. `devbox.json`, `scripts/test-fast.sh`, `scripts/ci-local.sh` and `.github/workflows/ci.yml` stay unchanged, and no new variable, flag or setup step is needed (A9, AC-112.15). The plugin cannot be a second `pytest_configure` in the conftest, because the conftest already imports sharding's `pytest_configure`.
- **The run, not pytest, owns the base temp.** The controller (the serial process, or the xdist controller) creates its own run directory under the developer's pytest temp root and sets `config.option.basetemp` to `<run>/tmp` before pytest's tmpdir plugin reads it (`tryfirst`). This turns off pytest's numbered `pytest-N` directories and their keep-3-of-any-run cleanup. That cleanup counts passing runs and runs still in progress, so it cannot give AC-208.5 (3 *failing* runs, A4) or AC-208.6. xdist derives each worker's base temp from the controller's (`<run>/tmp/popen-gwN`).
- **uv isolation through `UV_CACHE_DIR`.** The controller sets `UV_CACHE_DIR=<run>/uv-cache` in `os.environ` before workers start, and passes it to workers in `workerinput`, which each worker writes into its own `os.environ` as well. Every `uv run` a test starts, directly or through cplat, inherits it. `UV_CACHE_DIR` takes precedence over uv's default location and over `cache-dir` in a uv config file, so a developer's custom cache location gets the same protection (A6). The cache starts empty (A7) and lives inside the run directory (A1).
- **Nested pytest runs stay inside the run.** Several tests start nested pytest processes in scratch projects without this conftest (spec 185, 197 tests). Without care, those processes would create `pytest-N` directories in the developer's temp root and break AC-208.3. The controller therefore sets `PYTEST_DEBUG_TEMPROOT=<run>/temproot` (pytest's own override of the temp root), so every nested run's temp lands in the run directory and goes with it. The developer's temp root is computed from the *original* `PYTEST_DEBUG_TEMPROOT`, or failing that `tempfile.gettempdir()`, before the override, exactly as pytest computes it.
- **Liveness by `flock`, not by pid.** The controller holds an exclusive `fcntl.flock` on `<run>/.lock` for its whole life. The kernel releases the lock even on SIGKILL, and pid reuse cannot fool it. Another run treats a run directory as live while it cannot take that lock without blocking, and never touches a live run (AC-208.6). A run directory is created under a staging name and renamed once the lock is held and `run.json` is written, so no scanner ever sees a half-created run.
- **Per-test attribution by directory diff.** Each pytest process (serial or worker) lists the top-level entries of its base temp before and after each test's `pytest_runtest_protocol`. The new entries are that test's directories: `tmp_path` and the function-scoped `mktemp` dirs of the autouse fixtures (`runs-state*`, `state-home*`). This works without changing any fixture. Session-scoped `shared-renders*` directories are created inside the first test that needs them and would be attributed to it, so they are excluded by name (AC-208.4).
- **Decisions at the end, nothing deleted during the run.** Deleting a passed test's directories at once could break a module-scoped fixture whose directory the diff attributed to that test. Cleanup therefore happens once, in the controller's `pytest_unconfigure`, which pytest calls on pass, failure and Ctrl-C alike.
- **An interrupted run is a failing run (A5).** The controller turns SIGTERM into `KeyboardInterrupt` (only when SIGTERM still has its default handler), so `cplat quiet test-fast` giving up (SIGTERM to the process group, SIGKILL 5 s later) takes the normal interrupted path. Tests that started and did not end count as failed. A run killed before its cleanup ends leaves an *orphan*: its lock is free and `run.json` still says `running`. The next run that ends settles the orphan (removes its `uv-cache` and `temproot`, and every `shared-renders*` under its `tmp`) and counts it as a failing run for the limit of 3. The developer's uv cache is untouched in every case, because nothing ever wrote to it.
- **Retention runs at the end of every run.** It runs after the run's own cleanup, over `cplat-run-*` directories only. It never touches `pytest-N` directories, other projects' directories or leftovers from before this change (non-goal). A passing run only removes something when more than 3 failing leftovers already exist, which only an orphan can cause, so AC-208.3's "untouched except as AC-208.5 says" holds.
- **e2e scripts: a throwaway cache per script run.** `tests/e2e/run.sh`, `cluster.sh` and `upgrade.sh` source a new `tests/e2e/lib/uv-cache.sh`. It exports `UV_CACHE_DIR` set to a fresh `mktemp -d` directory *outside* `$work`, because `$work` may be given (`E2E_WORK`) and is kept on failure for debugging. Each script's existing `cleanup` trap removes the cache, pass or fail (AC-208.2). `upgrade-drill.sh` and `lib/upgrade-system.sh` are sourced by `upgrade.sh` and inherit the cache.
- **The entry point's own `uv run --with-requirements requirements-test.txt` stays on the developer's cache.** It is the launcher of the suite, not an inline-script run the tests make. On a warm cache it reuses its cached environment and adds nothing. AC-208.1 is measured from a warm cache, meaning after one earlier run of the same entry point. Redirecting it to a per-run cache would download pytest and its plugins on every run and break AC-208.7.
- **An explicit `--basetemp` is respected.** When the developer passes `--basetemp`, the plugin leaves pytest's handling of that directory alone: no run directory, no retention, no `failed/` layout. It still sets `UV_CACHE_DIR=<basetemp>/uv-cache` and `PYTEST_DEBUG_TEMPROOT=<basetemp>/temproot`, and removes both at the end, so the uv guarantee holds there too.
- No ADR: the behaviour is enforced by the plugin itself. No convention is left that later code must follow, and ADR-108 (bounded test time) already covers the time budget.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `tests/cplat/runtemp.py` | the run directory, `UV_CACHE_DIR` / `PYTEST_DEBUG_TEMPROOT`, lock, per-test manifest, cleanup, `failed/` layout, retention | new |
| `tests/cplat/conftest.py` | `pytest_plugins = ["runtemp"]` | changed |
| `tests/e2e/lib/uv-cache.sh` | `e2e_uv_cache_start` / `e2e_uv_cache_end` | new |
| `tests/e2e/run.sh`, `cluster.sh`, `upgrade.sh` | source the lib, start the cache before the first `uv`, end it in `cleanup` | changed |
| `CONTRIBUTING.md` | one line: where a failing run keeps its failed tests' files, and the limit of 3 runs | changed |

## Contract

### Paths

- **Temp root** `R = Path(<original PYTEST_DEBUG_TEMPROOT> or tempfile.gettempdir()).resolve() / f"pytest-of-{_pytest.tmpdir.get_user() or 'unknown'}"`, created with mode `0o700` if missing (pytest's own rule).
- **Run directory** `R/cplat-run-<pid>-<hex6>/`, where `<pid>` is the controller's pid and `<hex6>` is 6 random lowercase hex characters. It is created as `R/.cplat-starting-<pid>-<hex6>/` and renamed once `.lock` is held and `run.json` is written.

While a run is in progress the run directory holds:

| Entry | What |
|---|---|
| `.lock` | empty file; the controller holds an exclusive `flock` on it |
| `run.json` | `{"pid": int, "started": float (epoch seconds), "state": "running" \| "passed" \| "failed"}` |
| `tmp/` | pytest's base temp (`--basetemp`); xdist workers use `tmp/popen-gw<N>/` |
| `uv-cache/` | the run's uv cache (`UV_CACHE_DIR`) |
| `temproot/` | `PYTEST_DEBUG_TEMPROOT` for nested pytest processes |
| `manifest/<worker>.jsonl` | `<worker>` is `gw<N>` or `main` (serial); one JSON object per line: `{"start": "<nodeid>"}` before the test, `{"end": "<nodeid>", "dirs": ["tmp/popen-gw3/test_x0", ...]}` after it (paths relative to the run directory) |

### Environment seen by tests and their subprocesses

- `UV_CACHE_DIR=<run>/uv-cache` and `PYTEST_DEBUG_TEMPROOT=<run>/temproot` in the controller and in every worker. Both are restored to their earlier value, or unset, in the controller at `pytest_unconfigure`.

### End of a run (controller `pytest_unconfigure`)

A run **passes** when the final `session.exitstatus` is 0 (OK) or 5 (no tests collected), and no test report has outcome `failed`. Otherwise it **fails**, which includes exit status 2 (interrupted).

**Failed tests** are the node ids with a report of outcome `failed` in `setup`, `call` or `teardown`. That covers pytest-timeout (signal method), the sleep guard of spec 185, and xdist's report for a crashed worker. A node id with a `start` and no `end` line in a manifest (interrupted) counts as failed too.

- **Pass:** `run.json` state becomes `passed`, then the whole run directory is removed (AC-208.3).
- **Fail:**
  1. For each failed test, its manifest `dirs` that still exist, minus any whose name starts with `shared-renders`, are moved to `failed/<slug>/`. The test's original directory names are kept (for example `failed/<slug>/test_x0/`, `failed/<slug>/runs-state12/`). The file `failed/<slug>/NODEID` holds the full node id (one line).
  2. `<slug>` is `re.sub(r"[^A-Za-z0-9._-]", "_", nodeid)[:100] + "-" + sha1(nodeid).hexdigest()[:8]`, so the test file and function names can be read and two ids never collide.
  3. `tmp/`, `uv-cache/`, `temproot/` and `manifest/` are removed. `run.json` state becomes `failed`.
  4. What remains is exactly `.lock`, `run.json` and `failed/` (AC-208.4). `failed/` exists, possibly empty, even when no test failed, for example on a collection error.
  5. One line goes to stderr: `runtemp: kept the files of <n> failed test(s) in <run>/failed`.
- Removal uses `shutil.rmtree` with an error handler that adds `u+w` and retries, because uv caches and git objects are read-only.

### Retention (after the own cleanup, every run, passing or failing)

Over `R/cplat-run-*` (the run's own directory included when it failed):

1. A directory whose `.lock` cannot be taken with `LOCK_EX | LOCK_NB` is **live** and is skipped (AC-208.6).
2. `state == "passed"` (a passing run whose removal was cut short): removed.
3. `state == "running"` with a free lock is an **orphan**. It is settled: `uv-cache/`, `temproot/` and every `shared-renders*` under `tmp/` are removed, `state` becomes `failed`, and it counts as a failing run.
4. `state == "failed"`: a failing run.
5. The failing runs are sorted by `started`, newest first (the directory's mtime when `run.json` is missing or unreadable). The first 3 are kept and the rest are removed (AC-208.5).

### Explicit `--basetemp`

`UV_CACHE_DIR` and `PYTEST_DEBUG_TEMPROOT` are set as above but under `<basetemp>/`, and both directories are removed at the end. pytest's own handling of `<basetemp>` is otherwise unchanged.

### Testability

`runtemp` imports nothing from `scripts/cplat`. A nested run loads it with `-p runtemp` and `PYTHONPATH=tests/cplat`. With `PYTEST_DEBUG_TEMPROOT` and `UV_CACHE_DIR` pointing at sandbox directories (the sandbox `UV_CACHE_DIR` playing the developer's cache), it shows every behaviour above on a scratch suite.

### e2e lib (`tests/e2e/lib/uv-cache.sh`)

```bash
e2e_uv_cache_start   # export UV_CACHE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/e2e-uv-cache.XXXXXX")"; remembers it in E2E_UV_CACHE
e2e_uv_cache_end     # chmod -R u+w and rm -rf "$E2E_UV_CACHE" (no-op when unset); never fails the cleanup
```

Each script calls `e2e_uv_cache_start` right after `work=` is set (before any `uv`), and calls `e2e_uv_cache_end` in `cleanup` before `exit $rc` (AC-208.2).
