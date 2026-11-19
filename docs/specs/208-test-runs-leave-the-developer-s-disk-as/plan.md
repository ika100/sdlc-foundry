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
    done: true
  - id: t3
    title: "e2e scripts run inline scripts with a throwaway uv cache"
    files: [tests/e2e/lib/uv-cache.sh, tests/e2e/run.sh, tests/e2e/cluster.sh, tests/e2e/upgrade.sh]
    covers: [AC-208.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: "runtemp plugin: seed the run cache from a persistent test wheel cache, remove the run directory in the background, measure AC-208.7"
    files: [tests/cplat/runtemp.py, CONTRIBUTING.md]
    covers: [AC-208.1, AC-208.3, AC-208.4, AC-208.5, AC-208.6, AC-208.7]
    parallel_safe: false
    depends_on: [t1, t2]
    done: true
---

# Plan — 208 Test runs leave the developer's disk as they found it

The contract (paths, `run.json`, manifest, end-of-run rules, retention, test wheel cache, detached remover, e2e lib) is in [design.md](design.md).

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

## t4 — runtemp plugin: seed the run cache from a persistent test wheel cache, remove the run directory in the background, measure AC-208.7

**Files:** tests/cplat/runtemp.py, CONTRIBUTING.md
**Covers:** AC-208.1, AC-208.3, AC-208.4, AC-208.5, AC-208.6, AC-208.7
**Goal:** bring a full `devbox run test-fast` within 10 % of `main` (measured +28 %: about 60 s of cold-cache downloads per run and about 75 s of deletion after the summary). The run's uv cache is seeded from the persistent test wheel cache `W` (A10). The run directory's bulk deletion moves to a detached process after pytest's summary (A11). Every guarantee of AC-208.1 and AC-208.3 to AC-208.6 still holds.

**Before this task (acceptance-test work, not the coder's).** Testers adjust and extend `tests/cplat/runtemp_support.py` and `tests/cplat/test_208_runtemp.py` without changing any existing assertion:
- `Sandbox.env` sets `XDG_CACHE_HOME=<base>/xdg-cache`.
- `Sandbox.run`, and the popen-based tests after `communicate`, wait until `R` has no `.cplat-removing-*` entry (0.05 s poll, 60 s cap, then fail with a listing).
- New tests:
  - A10 (AC-208.1, AC-208.6, AC-208.7): a second run finds in its own `UV_CACHE_DIR` the `archive-v0` / `wheels-v5` entries a first run's scratch test wrote, with the developer cache unchanged. `W` never holds `environments-v*` or any bucket other than `archive-v*`, `wheels-v*` and `sdists-v*`. A `W` over 2 GiB (sparse file) is emptied at the next run start and nothing is seeded. A missing, unwritable or cross-device `W` leaves the run's result unchanged. Two overlapping runs that both write wheels both pass, and `W` ends with both entries.
  - A11 (AC-208.3, AC-208.4, AC-208.5, AC-208.6): the nested pytest returns while its removal may still run (stdio not inherited, so `capture_output` returns at once), and after the wait `R` is clean. The remover deletes only its own `.cplat-removing-*` path, so an overlapping live run and the kept failing runs are byte-for-byte unchanged. A `.cplat-removing-*` directory with a held lock is not counted by AC-208.5 retention and is not touched. One with a free lock is removed by the next run.

**Implementation notes:**
- Seeding at controller start, after the run directory exists and before workers start: one walk of `W`, the 2 GiB check over distinct inodes, then hard links into `<run>/uv-cache/`. Pointer files are listed first. Each archive is linked under `.seed-<id>` and renamed into place when complete. `.tmp-*` names are skipped. Any error skips the entry, and `EXDEV` or a missing `W` skips seeding (design.md, "Start of a run"). Nothing new appears at the run directory's top level, because AC-208.7's proxy test lists it.
- Over the bound: rename `W` to `W.old-<pid>-<hex6>` (`ENOENT` means someone else emptied it), then start the detached emptier on it and on any other `W.old-*`.
- End of a run, foreground: renames only. On a pass, `state: passed`, then rename the run directory to `R/.cplat-removing-<tag>/` with the lock held. On a fail, move the failed tests' dirs first, then create a locked `.cplat-removing-<tag>/` and rename `tmp/`, `uv-cache/`, `temproot/` and `manifest/` into it. Start the remover with `pass_fds=(lock_fd,)`, `start_new_session=True`, stdio on `/dev/null` and `close_fds=True`, then close the controller's fd. A failed rename falls back to removal in the foreground.
- Detached remover = `runtemp.py`'s `__main__` (`--remove <path>` / `--empty <paths>`). It runs `os.nice(10)`, then flow-back from `<path>/uv-cache` into `W`: archive dirs by `os.rename`, skipping `EEXIST`/`ENOTEMPTY`, then pointer files by link to `.tmp-*` and rename. Then `_force_remove(path)`. It never raises and deletes nothing but its given paths.
- Retention: also scan `.cplat-removing-*`. Skip the live ones (held lock) and remove the ones with a free lock. Never count them as runs.
- Explicit `--basetemp`: seed too. At the end, flow back and remove in the foreground.
- CONTRIBUTING.md: one sentence saying that the cplat tests keep downloaded wheels in `${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/test-wheels` (bounded at 2 GB, safe to delete at any time) and remove a run's files in the background right after the summary.
- The test_202 failure (`FileNotFoundError` for `…/tmp/popen-gw3/test_no_session_starts_while_a0/shop-api/.git/cplat-waits/detached/w1.json` in `test_202_wait_detach.py::test_no_session_starts_while_a_wait_of_the_ended_session_runs_and_the_next_one_gets_its_result`):
  - Before this task, nothing of 208 deletes inside a live run's `tmp/`. Only the controller's end does, after every worker has ended, and other runs skip a locked run. So a 208 cause would be a liveness bug.
  - Reproduce by running that test repeatedly under `-n auto` on `main` and on the branch, alone and next to an overlapping run.
  - If it is a 208 race, fix it in `runtemp.py`.
  - If not, name it as pre-existing in the PR body, with the evidence. The likely cause is test 202's own detached sleeper removing `w1.json` while `stop_wait` or `end_wait` reads it. Do not edit test 202.
- Measure AC-208.7:
  - Run a full `devbox run test-fast` on `main` and on this branch, on the same quiet machine, at least twice each, alternating.
  - Start each run only after the previous run's `.cplat-removing-*` is gone and the developer's uv cache is warm (one earlier run of each).
  - Record the wall time of the whole command for each run, and both medians, in the PR body. The branch median must be at most 1.10 × the `main` median.

**Done when:** both AC-208.7 timings (main vs branch, full `devbox run test-fast`, same machine, branch at most 10 % longer) are measured and recorded for the PR body. The test_202 failure is explained: fixed if it is a 208 race, otherwise named as pre-existing with the evidence. The new A10/A11 acceptance tests and all existing AC-208.1 and AC-208.3 to AC-208.6 tests pass unchanged in their assertions. The full suite passes with `-n auto` and serially.
