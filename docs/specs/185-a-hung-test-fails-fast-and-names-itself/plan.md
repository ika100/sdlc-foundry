---
spec_id: 185-a-hung-test-fails-fast-and-names-itself
shape: platform
spec_hash: "cb3176ccd495"
summary: 120 s per-test limit (pinned pytest-timeout), 1 s real-sleep guard, cplat quiet test-fast gives up after 9 min naming running tests, decision-becomes-task rule in the ship prompts, suite time in CI and the weekly retro
tasks:
  - id: t1
    title: Per-test limit through a pinned pytest-timeout
    files: [requirements-test.in, requirements-test.txt, scripts/check-pins.py, tests/cplat/pytest.ini]
    covers: [AC-185.1, AC-185.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Real-sleep guard for the cplat suite
    files: [tests/cplat/sleepguard.py, tests/cplat/conftest.py, "tests/cplat/test_*.py"]
    covers: [AC-185.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: cplat quiet test-fast gives up after 9 minutes and names running tests
    files: [scripts/cplat/quiet_limit.py, scripts/cplat/test_progress/cplat_test_progress.py, scripts/cplat/quiet.py, scripts/cplat/quiet_repeat.py]
    covers: [AC-185.4, AC-185.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Shard reports carry wall time and slowest tests; coverage job prints and keeps them
    files: [tests/cplat/sharding.py, scripts/check-shards.py, .github/workflows/ci.yml]
    covers: [AC-185.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Ship prompts turn an escalation decision into a plan task
    files: [plugins/component/commands/ship.md, plugins/system/commands/ship.md, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/system/commands/ship.yml]
    covers: [AC-185.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: Weekly retro section "Test suite time"
    files: [scripts/cplat/retro_suite.py, scripts/cplat/retro.py, scripts/cplat/retro_report.py, tests/cplat/conftest.py]
    covers: [AC-185.8]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t7
    title: ADR, contributor guide, changelog fragment and plugin versions
    files: [docs/adr/, docs/adr/README.md, CONTRIBUTING.md, docs/changelog.d/185-a-hung-test-fails-fast.added.md, .claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json]
    covers: [AC-185.1, AC-185.3, AC-185.4, AC-185.6]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 185 A hung test fails fast and names itself

Contracts, formats and module seams are in [design.md](design.md). Level 1: t1, t2, t3, t4, t5, t7 in parallel; level 2: t6 (it shares `tests/cplat/conftest.py` with t2).

## t1 — Per-test limit through a pinned pytest-timeout

**Files:** requirements-test.in, requirements-test.txt, scripts/check-pins.py, tests/cplat/pytest.ini
**Covers:** AC-185.1, AC-185.2
**Goal:** every test of the `cplat` suite fails after 120 s with its id, the limit and its stack, from every entry point, and pytest-timeout is pinned like the other test tools.

**Implementation notes:**
- `requirements-test.in`: the five names of design.md, unpinned. Recompile with `uv pip compile --universal requirements-test.in -o requirements-test.txt` (keep the generated header).
- `check-pins.py`: add `pytest-timeout` to `TEST_TOOLS`; update the docstring's part 4 sentence if it names the tools.
- `pytest.ini`: `timeout = 120`, `timeout_method = signal`, `required_plugins = pytest-timeout pytest-xdist`; keep the `slow` marker.
- No change to `devbox.json`, `scripts/test-fast.sh`, `scripts/ci-local.sh` or `ci.yml`: they all run pytest on `tests/cplat`, which finds this ini file.

**Done when:** the acceptance tests of AC-185.1 and AC-185.2 pass, `python3 scripts/check-pins.py` is OK and `devbox run test-fast` is green.

## t2 — Real-sleep guard for the cplat suite

**Files:** tests/cplat/sleepguard.py, tests/cplat/conftest.py, tests/cplat/test_*.py
**Covers:** AC-185.3
**Goal:** a test whose own process sleeps more than 1 s in total fails at the crossing sleep with the message of design.md and does not sleep.

**Implementation notes:**
- `sleepguard.py` per design.md: `install()` (idempotent) wraps `time.sleep` and `asyncio.sleep`; a per-test budget armed by a `pytest_runtest_protocol` hookwrapper; a `pytest_runtest_makereport` hookwrapper that fails a passed report when a crossing was recorded (threads, swallowed exceptions).
- Count only callers under the repository root, not `tests/cplat/waiting.py`; stdlib and site-packages callers pass through uncounted.
- Raise `pytest.fail.Exception(msg)` so `except Exception` in code under test cannot hide it; record the first message per test.
- `conftest.py`: `import sleepguard; sleepguard.install()` right after the `sys.path.insert`, before `console_support` and `sharding` are imported (modules bind `time.sleep` at import); import the two hooks beside the sharding hooks.
- `tests/cplat/test_*.py` is listed only for existing tests the guard now fails: fix each by replacing the module's sleep seam (`ship.sleep`, `waits.sleep`, `core.sleep`, ...) with a fake or by waiting through `waiting.py`. Never edit `test_185_*` (the acceptance tests). Name each changed test in the commit message.
- Keep `scripts/check-test-sleeps.py` green (spec 178): save the original as `_REAL_SLEEP = time.sleep` and call `_REAL_SLEEP(s)`, a call that check does not match, rather than exempting another file.

**Done when:** the acceptance tests of AC-185.3 pass, `devbox run test-fast` is green (no existing test crosses the budget) and `python3 scripts/check-test-sleeps.py` is OK.

## t3 — cplat quiet test-fast gives up after 9 minutes and names running tests

**Files:** scripts/cplat/quiet_limit.py, scripts/cplat/test_progress/cplat_test_progress.py, scripts/cplat/quiet.py, scripts/cplat/quiet_repeat.py
**Covers:** AC-185.4, AC-185.5
**Goal:** a test-fast run that has not ended 9 minutes after its start is stopped with all its processes, prints the give-up block of design.md and exits 124.

**Implementation notes:**
- `quiet_limit.py` per design.md: `progress_env`, `start` (`start_new_session=True`), `wait_until`, `stop` (`killpg` SIGTERM, 5 s grace, SIGKILL, reap), `still_running`, `gave_up_lines`; constants `GIVE_UP_SECONDS = 540`, `GIVE_UP_LABEL = "9 min"`, `MAX_LISTED = 20`.
- `test_progress/cplat_test_progress.py`: the pytest plugin of design.md, pytest hooks only, no imports from `cplat`; controller-only writes (skip when `config.workerinput` exists); remove its env var and `-p` from `os.environ` at configure.
- `quiet.py`: test-fast (with or without arguments) runs through `quiet_limit` with the progress env; on give-up print the block, return 124 before failsum and `_flaky`. A run that ends in time keeps today's output; other scripts keep `subprocess.run` unchanged.
- `quiet_repeat.py`: the N runs start in their own sessions with one shared deadline; each run that gave up prints its block (its own log and progress file); then return 124 and skip the alone-reruns.
- Stop the group on `KeyboardInterrupt` too, so an interrupted quiet leaves no pytest behind.

**Done when:** the acceptance tests of AC-185.4 and AC-185.5 pass (they lower `quiet_limit.GIVE_UP_SECONDS`) and the existing tests of `cplat quiet` (specs 100, 165, 172) still pass.

## t4 — Shard reports carry wall time and slowest tests; coverage job prints and keeps them

**Files:** tests/cplat/sharding.py, scripts/check-shards.py, .github/workflows/ci.yml
**Covers:** AC-185.7
**Goal:** each shard report holds `wall_s` and its 15 slowest tests, the coverage job prints the suite time and the 15 slowest tests of the run, and pushes to `main` keep `suite-time.json` for 35 days.

**Implementation notes:**
- `sharding.py`: start time at `pytest_sessionstart` (controller), per-node duration sum in `pytest_runtest_logreport` (setup + call + teardown), `wall_s` and `slowest` added in `pytest_sessionfinish` whatever the exit status; formats in design.md.
- `check-shards.py`: accept the optional fields, refuse wrong types as `not a shard report`, print the suite-time lines after the coverage result, `--timing-out PATH` writes `suite-time.json` (with `GITHUB_SHA` / `GITHUB_RUN_ID` when set); the exit code still depends on coverage alone.
- `ci.yml` job `platform-tests-cover`: pass `--timing-out suite-time.json`; add the upload step of design.md (`cplat-suite-time`, 35 days, push to `main` only, `if: always()`), reusing the pinned upload-artifact SHA.
- Keep `scripts/pin-actions.py --check` and actionlint green.

**Done when:** the acceptance tests of AC-185.7 pass and the existing tests of spec 112 (old reports without timing) still pass.

## t5 — Ship prompts turn an escalation decision into a plan task

**Files:** plugins/component/commands/ship.md, plugins/system/commands/ship.md, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/system/commands/ship.yml
**Covers:** AC-185.6
**Goal:** both ship prompts state, with a reason clause, that a decision taken on an escalation that needs code, test or document work becomes a task in the spec's plan before the ship goes on.

**Implementation notes:**
- Component ship: one bullet under "Unattended rules"; system ship: one sentence under "Escalate". Wording per design.md, reason clause of at least 3 words, no `only when` / `unless`.
- Register entries: next free `R<n>`, `class: practice`, `source: spec 185`, `text` quoting the sentence.
- Make room in the same two prompts by tightening other sentences, so the two files together are not larger than before (register rule 6) and the total stays within `baseline.prompt_bytes`; update the `text` of every register entry whose sentence changed. Do not raise the baseline.
- Check with `cplat platform rules check` (whole run, not only `--only`).

**Done when:** the acceptance test of AC-185.6 passes and `cplat platform rules check` passes.

## t6 — Weekly retro section "Test suite time"

**Files:** scripts/cplat/retro_suite.py, scripts/cplat/retro.py, scripts/cplat/retro_report.py, tests/cplat/conftest.py
**Covers:** AC-185.8
**Goal:** the weekly retro shows, for its week and the 3 before, the `main` runs with timing data and their median times, and the week's 15 slowest tests, without ever failing on missing data.

**Implementation notes:**
- `retro_suite.py` per design.md: `fetch` through `retro_github.gh` (artifact list filtered to `main`, not expired, in the window; `gh run download` per run into a temp dir), `SuiteTimeError`, `section`, `unavailable`, `render`.
- `retro.build_report`: call `fetch(autoissue.default_repo(), <window start>)` in a `try`; any failure → `unavailable(reason)`; pass the result to `retro_report.build(..., suite_time=...)`.
- `retro_report.build`: optional `suite_time` stored under `report["suite_time"]`; `_render` appends `retro_suite.render(...)` after "Agents", before the footer, only when the key exists (old `report.json` files render as before).
- `conftest.py`: an autouse fixture `no_real_suite_times` that sets `retro_suite.fetch` to return `[]`, so no test reaches GitHub; tests of the real fetch call a saved `retro_suite.REAL_FETCH` with a fake `retro_github.gh`. Depends on t2 because t2 rewrites the top of this file.
- The RetroTracker protocol stays unchanged, so the existing fake tracker keeps working.

**Done when:** the acceptance tests of AC-185.8 pass and the existing retro tests (specs 090, 168) still pass.

## t7 — ADR, contributor guide, changelog fragment and plugin versions

**Files:** docs/adr/, docs/adr/README.md, CONTRIBUTING.md, docs/changelog.d/185-a-hung-test-fails-fast.added.md, .claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json
**Covers:** AC-185.1, AC-185.3, AC-185.4, AC-185.6
**Goal:** the bounds are documented where contributors look, the decision is an ADR, and the changed plugins carry new versions.

**Implementation notes:**
- `cplat adr add test-time-is-bounded --decision "The cplat suite stops a test after 120 s or when its real sleeps pass 1 s, and cplat quiet test-fast gives up after 9 min in every shape, naming the tests still running"`; fill Status (Accepted), Context (spec 184's 2.5-hour hang), Decision (the three bounds, the injected progress plugin), Consequences (one short red run instead of hours; no per-test override; repos whose pytest ignores `PYTHONPATH` see no test names). Link it from CONTRIBUTING.
- `CONTRIBUTING.md`, the "Tests wait for events" bullet: add the 120 s limit and the 1 s real-sleep budget, and that `cplat quiet test-fast` gives up after 9 min (exit 124).
- Changelog fragment (format in `docs/changelog.d/README.md`): the per-test limit, the sleep guard, quiet's give-up, the decision rule, suite time in CI and the retro.
- Minor bump of the `component` and `system` plugins in their `plugin.json` and in `marketplace.json` (t5 changes their prompts).
- Run the `cplat platform pr-check` rules that apply locally (changelog fragment, plugin versions).

**Done when:** `python3 scripts/check-links.py` and `devbox run validate` pass, and the ADR index lists the new ADR.
