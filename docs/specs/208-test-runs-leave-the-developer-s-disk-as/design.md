# Design — 208 Test runs leave the developer's disk as they found it

## Decisions

- **One pytest plugin, no entry-point changes.** Every cplat entry point (`devbox run test-fast` with or without arguments, `scripts/test-fast.sh`, `scripts/ci-local.sh`, the CI shards, a plain serial or `-n auto` run) goes through `tests/cplat/conftest.py`. A new self-contained plugin `tests/cplat/runtemp.py`, loaded from the conftest with `pytest_plugins = ["runtemp"]`, owns the run's directory, its uv cache and its cleanup. `devbox.json`, `scripts/test-fast.sh`, `scripts/ci-local.sh` and `.github/workflows/ci.yml` stay unchanged, and no new variable, flag or setup step is needed (A9, AC-112.15). The plugin cannot be a second `pytest_configure` in the conftest, because the conftest already imports sharding's `pytest_configure`.
- **The run, not pytest, owns the base temp.** The controller (the serial process, or the xdist controller) creates its own run directory under the developer's pytest temp root and sets `config.option.basetemp` to `<run>/tmp` before pytest's tmpdir plugin reads it (`tryfirst`). This turns off pytest's numbered `pytest-N` directories and their keep-3-of-any-run cleanup. That cleanup counts passing runs and runs still in progress, so it cannot give AC-208.5 (3 *failing* runs, A4) or AC-208.6. xdist derives each worker's base temp from the controller's (`<run>/tmp/popen-gwN`).
- **uv isolation through `UV_CACHE_DIR`.** The controller sets `UV_CACHE_DIR=<run>/uv-cache` in `os.environ` before workers start, and passes it to workers in `workerinput`, which each worker writes into its own `os.environ` as well. Every `uv run` a test starts, directly or through cplat, inherits it. `UV_CACHE_DIR` takes precedence over uv's default location and over `cache-dir` in a uv config file, so a developer's custom cache location gets the same protection (A6). The cache lives inside the run directory (A1) and is seeded from the persistent test wheel cache (A10, below).
- **A persistent test wheel cache, outside the developer's uv cache (A10).** It lives at `W = ${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/test-wheels/`, the same base and platform folder that `scripts/cplat/headless.py` and `console/mirror.py` already use, on macOS too. It is never the developer's uv cache, and it is never handed to uv as `UV_CACHE_DIR`: uv only ever sees the run's own cache. So no uv process can write an environment, an interpreter record or an index response into `W`, and the developer's uv cache stays untouched (AC-208.1). `W` holds uv's wheel and source-archive buckets only (`archive-v*`, `wheels-v*`, `sdists-v*`, whatever version suffix the installed uv uses). Index metadata (`simple-v*`), `environments-v*`, `interpreter-v*`, `builds-v*` and uv's root files are never copied into it.
- **Seeding by hard links, at run start, in the controller.** Before workers start, the controller walks `W` once. It hard-links each file of the three bucket kinds into `<run>/uv-cache/` at the same relative path (`os.link`), creating directories as needed. A hard link costs no disk and takes about as long as a `stat`. Today's inline scripts need `pyyaml` and `ruamel.yaml` only, so `W` holds a few MB and seeding takes well under a second. uv treats its archive and wheel entries as immutable: it clones (macOS) or hard-links (Linux) them into environments and never rewrites them in place. So a run cannot change `W` through these links. Each `archive-v*/<id>/` directory is seeded under a temporary name in the run cache and renamed into place only when all its files linked, because uv would build a broken environment from a half-copied archive. The pointer files (`wheels-v*`, `sdists-v*`) are listed *before* the archives are linked and copied *after* them. Flow-back writes an archive before its pointer, so every pointer seeded has its archive seeded too, unless `W` is emptied mid-seed. In that case the later reads fail and fewer pointers are seeded, never more. Names starting with `.tmp-` (a flow-back in progress) are skipped. On any error (`EXDEV` when `W` and the temp root lie on different file systems, a missing or unreadable `W`, a vanished entry) the entry or the whole seeding is skipped. uv then downloads what it needs, as on a cold cache, so the run is slower but does not fail (A10).
- **New wheels flow back after the run, from the detached remover (A10, A11).** Before it deletes anything, the detached removal process (below) moves the run cache's new entries into `W`. "New" means the relative path does not exist in `W`. The seeded entries already exist there and are skipped. Each `archive-v*/<id>/` directory moves with one `os.rename`. That rename is atomic, the run cache and `W` share a file system (otherwise seeding was skipped and flow-back is skipped too), and it fails harmlessly when another run put the same id there first. Then each pointer file is hard-linked to `W/<dir>/.tmp-<pid>-<hex6>` and renamed onto its final name. Archives go first, so a pointer never names an archive that `W` lacks. Nothing from `environments-v*` or any other bucket moves. Flow-back happens off the run's wall time. Errors skip the entry. An orphan's cache (a run killed before its end) flows nothing back, and the next run downloads those wheels again.
- **The 2 GB bound is checked at run start, from the seeding walk (A10).** The walk that lists `W` for seeding also sums `st_size` over distinct inodes. When the sum exceeds 2 GiB (`2 * 1024**3` bytes), nothing is seeded. `W` is renamed to `W.old-<pid>-<hex6>` (atomic, so an overlapping run sees either the whole old cache or none) and that directory goes to a detached emptier. The emptier is the same detached-process mechanism, deleting only the paths it is given, and it also deletes any `W.old-*` left behind by an emptier that was killed. The run then fills a fresh `W` through its own flow-back. When two runs start at once and both find `W` too big, one rename wins and the other's fails with `ENOENT`, which counts as already emptied.
- **Concurrency of the wheel cache (A10, AC-208.6).** Readers only ever see `W` through hard links taken at their own start. Writers only add entries, by atomic rename. Emptying moves the whole tree aside by atomic rename. So an overlapping run is never affected by another run's seeding, flow-back or emptying. At worst it downloads a wheel again. No lock on `W` is needed.
- **Nested pytest runs stay inside the run.** Several tests start nested pytest processes in scratch projects without this conftest (spec 185, 197 tests). Without care, those processes would create `pytest-N` directories in the developer's temp root and break AC-208.3. The controller therefore sets `PYTEST_DEBUG_TEMPROOT=<run>/temproot` (pytest's own override of the temp root), so every nested run's temp lands in the run directory and goes with it. The developer's temp root is computed from the *original* `PYTEST_DEBUG_TEMPROOT`, or failing that `tempfile.gettempdir()`, before the override, exactly as pytest computes it.
- **Liveness by `flock`, not by pid.** The controller holds an exclusive `fcntl.flock` on `<run>/.lock` for its whole life. The kernel releases the lock even on SIGKILL, and pid reuse cannot fool it. Another run treats a run directory as live while it cannot take that lock without blocking, and never touches a live run (AC-208.6). A run directory is created under a staging name and renamed once the lock is held and `run.json` is written, so no scanner ever sees a half-created run. The same rule protects a removal in progress: the detached remover holds the lock of the directory it deletes.
- **Per-test attribution by directory diff.** Each pytest process (serial or worker) lists the top-level entries of its base temp before and after each test's `pytest_runtest_protocol`. The new entries are that test's directories: `tmp_path` and the function-scoped `mktemp` dirs of the autouse fixtures (`runs-state*`, `state-home*`). This works without changing any fixture. Session-scoped `shared-renders*` directories are created inside the first test that needs them and would be attributed to it, so they are excluded by name (AC-208.4).
- **Decisions at the end, nothing deleted during the run.** Deleting a passed test's directories at once could break a module-scoped fixture whose directory the diff attributed to that test. Cleanup therefore happens once, in the controller's `pytest_unconfigure`, which pytest calls on pass, failure and Ctrl-C alike, after the terminal summary and with the exit status already decided.
- **The bulk deletion is detached, and only renames happen in the foreground (A11).** A full run's directory holds hundreds of thousands of files (git repos, renders, environments), and deleting them took about 75 s after the summary. In `pytest_unconfigure` the controller now only *renames*. Everything to delete is moved, by `os.rename` within the temp root, into `R/.cplat-removing-<pid>-<hex6>/`. On a pass that is the whole run directory. On a fail it is `tmp/`, `uv-cache/`, `temproot/` and `manifest/`, after the failed tests' directories have moved to `failed/`. The controller then starts one detached process for that single path and returns. That process does the flow-back, then the `rmtree`. Renames are O(1), so the run directory reaches its final shape (gone, or `.lock` + `run.json` + `failed/`) before pytest exits. The process is started with `start_new_session=True`, `stdin`, `stdout` and `stderr` on `/dev/null`, and `close_fds=True`. So a caller that reads the run's output to EOF (`subprocess.run(capture_output=True)`, `cplat quiet test-fast`, CI) is not held up, and a SIGTERM to the run's process group does not stop it. It lowers its own priority (`os.nice(10)`) so that it competes less with a run that starts right after. It deletes nothing but the `.cplat-removing-*` path it was given (A11). Retention keeps running in the foreground. It deletes only old failing runs (small: failed tests' directories) and rare leftovers, so it costs no measurable time.
- **A removal in progress is visible and owned.** The removing directory holds a `.lock`. For a pass it is the run's own `.lock`, which moved with the rename. For a fail it is a new one the controller creates and locks. The controller passes the locked fd to the remover (`pass_fds`) and then closes its own copy. `flock` locks belong to the open file description, so the lock stays held until the remover exits. A `.cplat-removing-*` directory whose lock is free belongs to a killed remover, and the next run's retention deletes it. Retention never counts a `.cplat-removing-*` directory as a run, so a passing run whose removal is still going counts as no failing run (AC-208.5, A11).
- **Tests of AC-208.3 and AC-208.4 wait for the removal (A11).** A run counts as clean once no `.cplat-removing-*` entry is left under `R`. The acceptance-test sandbox (`tests/cplat/runtemp_support.py`, `Sandbox.run`) therefore polls, after the nested pytest returns, until `R` has no `.cplat-removing-*` entry. It polls every 0.05 s for at most 60 s and then fails with a listing of `R`. The existing assertions stay as they are. The sandbox also sets `XDG_CACHE_HOME=<sandbox>/xdg-cache`, so scratch runs never seed from or flow back into the developer's real `W`.
- **An interrupted run is a failing run (A5).** The controller turns SIGTERM into `KeyboardInterrupt` (only when SIGTERM still has its default handler), so `cplat quiet test-fast` giving up (SIGTERM to the process group, SIGKILL 5 s later) takes the normal interrupted path. Tests that started and did not end count as failed. A run killed before its cleanup ends leaves an *orphan*: its lock is free and `run.json` still says `running`. The next run that ends settles the orphan (removes its `uv-cache` and `temproot`, and every `shared-renders*` under its `tmp`) and counts it as a failing run for the limit of 3. The developer's uv cache is untouched in every case, because nothing ever wrote to it.
- **Retention runs at the end of every run.** It runs after the run's own renames, over `cplat-run-*` and `.cplat-removing-*` directories only. It never touches `pytest-N` directories, other projects' directories or leftovers from before this change (non-goal). A passing run only removes something when more than 3 failing leftovers already exist (which only an orphan can cause) or when a killed remover left a `.cplat-removing-*` directory behind. So AC-208.3's "untouched except as AC-208.5 says" holds.
- **e2e scripts: a throwaway cache per script run.** `tests/e2e/run.sh`, `cluster.sh` and `upgrade.sh` source a new `tests/e2e/lib/uv-cache.sh`. It exports `UV_CACHE_DIR` set to a fresh `mktemp -d` directory *outside* `$work`, because `$work` may be given (`E2E_WORK`) and is kept on failure for debugging. Each script's existing `cleanup` trap removes the cache, pass or fail (AC-208.2). `upgrade-drill.sh` and `lib/upgrade-system.sh` are sourced by `upgrade.sh` and inherit the cache. The e2e cache is neither seeded from `W` nor flows back to it. A10 is about the cplat tests' run cache, and AC-208.7 measures `test-fast` only.
- **The entry point's own `uv run --with-requirements requirements-test.txt` stays on the developer's cache.** It is the launcher of the suite, not an inline-script run the tests make. On a warm cache it reuses its cached environment and adds nothing. AC-208.1 is measured from a warm cache, meaning after one earlier run of the same entry point. Redirecting it to a per-run cache would download pytest and its plugins on every run and break AC-208.7.
- **An explicit `--basetemp` is respected.** When the developer passes `--basetemp`, the plugin leaves pytest's handling of that directory alone: no run directory, no retention, no `failed/` layout, no detached removal. It still sets `UV_CACHE_DIR=<basetemp>/uv-cache` and `PYTEST_DEBUG_TEMPROOT=<basetemp>/temproot`. It seeds the cache from `W`, and at the end it flows new wheels back and removes both directories in the foreground, so the uv guarantee holds there too.
- No ADR: the behaviour is enforced by the plugin itself. No convention is left that later code must follow (`W` is read and written by `runtemp.py` alone, and deleting it at any time is safe), and ADR-108 (bounded test time) already covers the time budget.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `tests/cplat/runtemp.py` | the run directory, `UV_CACHE_DIR` / `PYTEST_DEBUG_TEMPROOT`, lock, per-test manifest, cleanup, `failed/` layout, retention; seeding from `W`, the 2 GB bound, the detached remover with flow-back (its `__main__` entry) | new (t1, t2), changed (t4) |
| `tests/cplat/conftest.py` | `pytest_plugins = ["runtemp"]` | changed |
| `tests/e2e/lib/uv-cache.sh` | `e2e_uv_cache_start` / `e2e_uv_cache_end` | new |
| `tests/e2e/run.sh`, `cluster.sh`, `upgrade.sh` | source the lib, start the cache before the first `uv`, end it in `cleanup` | changed |
| `CONTRIBUTING.md` | where a failing run keeps its failed tests' files and the limit of 3 runs; where the test wheel cache lives and that deleting it is safe | changed |

## Contract

### Paths

- **Temp root** `R = Path(<original PYTEST_DEBUG_TEMPROOT> or tempfile.gettempdir()).resolve() / f"pytest-of-{_pytest.tmpdir.get_user() or 'unknown'}"`, created with mode `0o700` if missing (pytest's own rule).
- **Run directory** `R/cplat-run-<pid>-<hex6>/`, where `<pid>` is the controller's pid and `<hex6>` is 6 random lowercase hex characters. It is created as `R/.cplat-starting-<pid>-<hex6>/` and renamed once `.lock` is held and `run.json` is written.
- **Removal in progress** `R/.cplat-removing-<pid>-<hex6>/`, with the run's `<pid>-<hex6>`. It holds a `.lock` held by the detached remover, plus what is being deleted: on a pass, the former run directory's whole content; on a fail, `tmp/`, `uv-cache/`, `temproot/` and `manifest/`.
- **Test wheel cache** `W = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sdlc-foundry" / "test-wheels"`. It holds only `archive-v*/`, `wheels-v*/` and `sdists-v*/` in uv's own layout, plus transient `.tmp-*` files of a flow-back in progress. `W.old-<pid>-<hex6>/` is a cache being emptied.

While a run is in progress the run directory holds:

| Entry | What |
|---|---|
| `.lock` | empty file; the controller holds an exclusive `flock` on it |
| `run.json` | `{"pid": int, "started": float (epoch seconds), "state": "running" \| "passed" \| "failed"}` |
| `tmp/` | pytest's base temp (`--basetemp`); xdist workers use `tmp/popen-gw<N>/` |
| `uv-cache/` | the run's uv cache (`UV_CACHE_DIR`), seeded from `W` at start |
| `temproot/` | `PYTEST_DEBUG_TEMPROOT` for nested pytest processes |
| `manifest/<worker>.jsonl` | `<worker>` is `gw<N>` or `main` (serial); one JSON object per line: `{"start": "<nodeid>"}` before the test, `{"end": "<nodeid>", "dirs": ["tmp/popen-gw3/test_x0", ...]}` after it (paths relative to the run directory) |

Seeding adds nothing at the top level of the run directory. AC-208.7's test reads exactly the six entries above.

### Environment seen by tests and their subprocesses

- `UV_CACHE_DIR=<run>/uv-cache` and `PYTEST_DEBUG_TEMPROOT=<run>/temproot` in the controller and in every worker. Both are restored to their earlier value, or unset, in the controller at `pytest_unconfigure`. `W` is never exported to tests.

### Start of a run (controller `pytest_configure`, after the run directory exists, before workers start)

```
entries = walk(W, buckets=archive-v*, wheels-v*, sdists-v*; skip names starting ".tmp-")
size    = sum(st_size over distinct (st_dev, st_ino))
if size > 2 * 1024**3:
    rename W -> W.old-<pid>-<hex6>   (ENOENT: someone else emptied it)
    detach(emptier, [W.old-<pid>-<hex6>] + other W.old-* )
    seed nothing
else:
    pointers = [pointer files from entries]        # listed first
    for each archive-v*/<id>/ in entries: link all files into <run>/uv-cache/archive-v*/.seed-<id>/, then rename to <id>; on error drop it
    for each p in pointers: os.link(W/p, <run>/uv-cache/p); on error skip
    any EXDEV / missing W: stop seeding, no error
```

### End of a run (controller `pytest_unconfigure`)

A run **passes** when the final `session.exitstatus` is 0 (OK) or 5 (no tests collected), and no test report has outcome `failed`. Otherwise it **fails**, which includes exit status 2 (interrupted).

**Failed tests** are the node ids with a report of outcome `failed` in `setup`, `call` or `teardown`. That covers pytest-timeout (signal method), the sleep guard of spec 185, and xdist's report for a crashed worker. A node id with a `start` and no `end` line in a manifest (interrupted) counts as failed too.

- **Pass:** `run.json` state becomes `passed`. The run directory is renamed to `R/.cplat-removing-<pid>-<hex6>/` with the lock still held. The detached remover is started with the lock fd, and the controller closes its copy (AC-208.3).
- **Fail:**
  1. For each failed test, its manifest `dirs` that still exist, minus any whose name starts with `shared-renders`, are moved to `failed/<slug>/`. The test's original directory names are kept (for example `failed/<slug>/test_x0/`, `failed/<slug>/runs-state12/`). The file `failed/<slug>/NODEID` holds the full node id (one line).
  2. `<slug>` is `re.sub(r"[^A-Za-z0-9._-]", "_", nodeid)[:100] + "-" + sha1(nodeid).hexdigest()[:8]`, so the test file and function names can be read and two ids never collide.
  3. `R/.cplat-removing-<pid>-<hex6>/` is created with a `.lock` the controller locks. `tmp/`, `uv-cache/`, `temproot/` and `manifest/` are renamed into it, and the detached remover is started with that lock fd. `run.json` state becomes `failed`.
  4. What remains in the run directory is exactly `.lock`, `run.json` and `failed/` (AC-208.4). `failed/` exists, possibly empty, even when no test failed, for example on a collection error.
  5. One line goes to stderr: `runtemp: kept the files of <n> failed test(s) in <run>/failed`.
- When a rename fails (it should not: the same file system, the run's own entries), that entry is removed in the foreground as before, so the run stays correct and is only slower.
- Removal uses `shutil.rmtree` with an error handler that adds `u+w` and retries, because uv caches and git objects are read-only.

### Detached remover

```
argv:   [sys.executable, <runtemp.py>, "--remove", <R/.cplat-removing-<tag>>]    # emptier: "--empty", <W.old-*>...
popen:  start_new_session=True, stdin/stdout/stderr=DEVNULL, close_fds=True, pass_fds=(lock_fd,)
does:   os.nice(10)
        flow_back(<removing>/uv-cache -> W)      # only when the path exists and W is on the same file system
        rmtree(<removing>)                       # the .lock goes with it; the lock ends when the process exits
        never raises, writes nothing anywhere else
```

`flow_back`: first each `archive-v*/<id>/` absent from `W` is moved by `os.rename`. `EEXIST`/`ENOTEMPTY` means another run already added it, so it is skipped. Then each `wheels-v*` / `sdists-v*` file absent from `W` is hard-linked as `W/<dir>/.tmp-<pid>-<hex6>` and renamed onto its name. Nothing else moves.

### Retention (after the own renames, every run, passing or failing)

Over `R/cplat-run-*` (the run's own directory included when it failed) and `R/.cplat-removing-*`:

1. A directory whose `.lock` cannot be taken with `LOCK_EX | LOCK_NB` is **live** and is skipped (AC-208.6). That includes every removal still in progress.
2. `.cplat-removing-*` with a free lock (its remover was killed): removed. It never counts as a run.
3. `state == "passed"` (a passing run whose cleanup was cut short before its rename): removed.
4. `state == "running"` with a free lock is an **orphan**. It is settled: `uv-cache/`, `temproot/` and every `shared-renders*` under `tmp/` are removed, `state` becomes `failed`, and it counts as a failing run.
5. `state == "failed"`: a failing run.
6. The failing runs are sorted by `started`, newest first (the directory's mtime when `run.json` is missing or unreadable). The first 3 are kept and the rest are removed (AC-208.5).

### Explicit `--basetemp`

`UV_CACHE_DIR` and `PYTEST_DEBUG_TEMPROOT` are set as above but under `<basetemp>/`. The cache is seeded from `W`. At the end, new wheels flow back and both directories are removed in the foreground. pytest's own handling of `<basetemp>` is otherwise unchanged.

### Testability

`runtemp` imports nothing from `scripts/cplat`. A nested run loads it with `-p runtemp` and `PYTHONPATH=tests/cplat`. It shows every behaviour above on a scratch suite, with these pointed at sandbox directories:

- `PYTEST_DEBUG_TEMPROOT`,
- `UV_CACHE_DIR` (playing the developer's cache),
- `XDG_CACHE_HOME` (so `W` lies in the sandbox).

A scratch test plays uv by writing `archive-v0/<id>/…`, `wheels-v5/…` and `environments-v2/…` entries into `$UV_CACHE_DIR`. A run counts as ended for cleanliness checks once `R` has no `.cplat-removing-*` entry (the sandbox waits for that). A `W` over 2 GiB can be made without using disk: a sparse file made by `truncate`, because the bound counts `st_size`.

### e2e lib (`tests/e2e/lib/uv-cache.sh`)

```bash
e2e_uv_cache_start   # export UV_CACHE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/e2e-uv-cache.XXXXXX")"; remembers it in E2E_UV_CACHE
e2e_uv_cache_end     # chmod -R u+w and rm -rf "$E2E_UV_CACHE" (no-op when unset); never fails the cleanup
```

Each script calls `e2e_uv_cache_start` right after `work=` is set (before any `uv`), and calls `e2e_uv_cache_end` in `cleanup` before `exit $rc` (AC-208.2).
