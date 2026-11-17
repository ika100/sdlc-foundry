---
spec_id: 208-test-runs-leave-the-developer-s-disk-as
shape: platform
spec_hash: e03fe2083a98
summary: "A pytest plugin gives every cplat test run its own directory with its own uv cache and temp root, removes it on pass, keeps only the failed tests' files of the last 3 failing runs; e2e scripts use a throwaway uv cache"
tasks:
  - id: t1
    title: "runtemp plugin: the run's own directory, uv cache and temp root, removed on pass"
    files: [tests/cplat/runtemp.py, tests/cplat/conftest.py]
    covers: [AC-208.1, AC-208.3, AC-208.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "runtemp plugin: keep the failed tests' files, limit to 3 failing runs, settle orphans"
    files: [tests/cplat/runtemp.py, CONTRIBUTING.md, docs/changelog.d/208-test-runs-leave-the-disk-clean.fixed.md]
    covers: [AC-208.4, AC-208.5, AC-208.6, AC-208.7]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: "e2e scripts run inline scripts with a throwaway uv cache"
    files: [tests/e2e/lib/uv-cache.sh, tests/e2e/run.sh, tests/e2e/cluster.sh, tests/e2e/upgrade.sh]
    covers: [AC-208.2]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 208 Test runs leave the developer's disk as they found it

The contract (paths, `run.json`, manifest, end-of-run rules, retention, e2e lib) is in [design.md](design.md).

## t1 — runtemp plugin: the run's own directory, uv cache and temp root, removed on pass

**Files:** tests/cplat/runtemp.py, tests/cplat/conftest.py
**Covers:** AC-208.1, AC-208.3, AC-208.6
**Goal:** every run of the cplat tests, through any entry point, keeps all its inline-script environments in a uv cache of its own inside its own run directory under the developer's pytest temp root. A passing run leaves nothing behind there.

**Implementation notes:**
- New `tests/cplat/runtemp.py`, a self-contained pytest plugin that imports nothing from `scripts/cplat`. The conftest loads it with `pytest_plugins = ["runtemp"]`. Leave the sharding imports alone.
- Controller only (no `workerinput`), `pytest_configure(tryfirst=True)`: compute the temp root `R` from the *original* `PYTEST_DEBUG_TEMPROOT` (as design.md says). Create `R/.cplat-starting-<pid>-<hex6>`, take `flock(LOCK_EX)` on `.lock` and keep the fd open, write `run.json` (`state: running`), then rename the directory to `R/cplat-run-<pid>-<hex6>`.
- Set `config.option.basetemp = <run>/tmp` (only when the user gave no `--basetemp`), and set `os.environ` `UV_CACHE_DIR=<run>/uv-cache` and `PYTEST_DEBUG_TEMPROOT=<run>/temproot`. Remember the earlier values.
- `pytest_configure_node(node)` (optionalhook): put both values into `node.workerinput`. In a worker's `pytest_configure`, write them into `os.environ`.
- SIGTERM: in the controller, when the handler is `SIG_DFL`, install one that raises `KeyboardInterrupt`. Restore the old handler at unconfigure.
- Record the final exit status in a `pytest_sessionfinish` hookwrapper (after the yield, so sharding's change counts). Record failed node ids in `pytest_runtest_logreport` (controller side).
- Controller `pytest_unconfigure`: restore the environment. On pass (design.md rule) set `state: passed`, release the lock and remove the run directory (rmtree with the `u+w` retry handler). On fail, for now leave the directory as is and set `state: failed` (t2 adds the layout).
- Explicit `--basetemp`: only `<basetemp>/uv-cache` and `<basetemp>/temproot`, removed at the end; no run directory.
- A test that starts uv with an environment built without `os.environ` would bypass `UV_CACHE_DIR`. A scan of `tests/cplat` found none that reach uv (the scratch environments there have `PATH=/usr/bin:/bin` or exit before any `uv`). If the AC-208.1 acceptance test shows one, fix that test in this task and add its file here.

**Done when:** the acceptance tests for AC-208.1 (developer cache unchanged, envs only in the run cache), AC-208.3 (a passing run leaves nothing under `R`) and AC-208.6 (two overlapping runs, each with its own directory) pass, and the full suite passes with `-n auto` and serially.

## t2 — runtemp plugin: keep the failed tests' files, limit to 3 failing runs, settle orphans

**Files:** tests/cplat/runtemp.py, CONTRIBUTING.md, docs/changelog.d/208-test-runs-leave-the-disk-clean.fixed.md
**Covers:** AC-208.4, AC-208.5, AC-208.6, AC-208.7
**Goal:** a failing run (including an interrupted one) keeps exactly its failed tests' directories under `failed/<slug>/` and nothing else. At most the 3 most recent failing runs keep leftovers, and a live run is never touched.

**Implementation notes:**
- Every pytest process (worker or serial) gets a `pytest_runtest_protocol` hookwrapper. It lists the base temp's top-level entries before and after the test and appends `{"start"}` / `{"end", "dirs"}` lines to `<run>/manifest/<gw<N>|main>.jsonl`, flushed per line. The run directory reaches workers through `workerinput`.
- Failed set = failed reports (setup/call/teardown) plus manifest starts without an end.
- Failing end, in order: move each failed test's dirs (minus `shared-renders*`) to `failed/<slug>/` and write `NODEID`; remove `tmp/`, `uv-cache/`, `temproot/` and `manifest/`; set `state: failed`; print the stderr line from design.md.
- Retention after the own cleanup, every run: skip live dirs (non-blocking `flock` fails); remove `state: passed`; settle orphans (`state: running` with a free lock); keep the 3 newest failing runs by `started` and remove the rest.
- CONTRIBUTING.md: one sentence next to the `pytest tests/cplat` line saying where a failing run keeps its failed tests' files (`pytest-of-<user>/cplat-run-*/failed/`) and that only the last 3 failing runs are kept.
- Changelog fragment (`fixed`): test runs no longer grow the uv cache or the pytest temp root (#810, #811).
- Measure a full local `devbox run test-fast` on `main` and on this branch, on the same machine. Put both wall times in the PR body. The branch may take at most 10 % longer (AC-208.7).

**Done when:** the acceptance tests for AC-208.4 (setup, call, teardown and timeout failures keep exactly their directories, recognisable by name; uv cache and shared renders gone), AC-208.5 (the oldest of 4 failing runs removed) and AC-208.6 (a run's cleanup and retention leave an overlapping live run alone) pass, the full suite passes, and the PR body holds both AC-208.7 timings.

## t3 — e2e scripts run inline scripts with a throwaway uv cache

**Files:** tests/e2e/lib/uv-cache.sh, tests/e2e/run.sh, tests/e2e/cluster.sh, tests/e2e/upgrade.sh
**Covers:** AC-208.2
**Goal:** an e2e script run never writes to the developer's uv cache, and the cache it used is gone when it ends, pass or fail.

**Implementation notes:**
- New `tests/e2e/lib/uv-cache.sh` with `e2e_uv_cache_start` / `e2e_uv_cache_end` as in design.md. Add the REUSE header the other `lib/*.sh` files carry, if any.
- `run.sh`, `cluster.sh` and `upgrade.sh`: source the lib and call `e2e_uv_cache_start` right after `work=` (after the `E2E_PART` check in `run.sh`, so AC-134.5's early exit stays as it is). Call `e2e_uv_cache_end` in `cleanup` before `exit $rc`, whatever `E2E_KEEP` says.
- The cache lives outside `$work`, because `$work` is kept on failure.
- `upgrade-drill.sh` and `lib/upgrade-system.sh` are sourced by `upgrade.sh` and need no change.
- Keep `scripts/check-e2e-probes.py` and the e2e-scope tests green (they read these scripts' text).

**Done when:** the acceptance tests for AC-208.2 pass (they may run a script against a stubbed `uv` / an early failure, without a cluster), and `bash -n` passes on each changed script.
