---
spec_id: 178-one-way-to-land-and-tests-that-do-not
shape: platform
spec_hash: 545420e0c980
summary: One land path with a stated mode per command (release never catches up and stops when main moved), merges only on the new head's finished checks, refused merges waited for (at most 3), repository commands without the outer run's CPLAT_* variables, and cplat tests that wait for events, checked by check-test-sleeps.py
tasks:
  - id: t1
    title: land_merge - modes, waits after an update, refused merges
    files: [scripts/cplat/land_merge.py, scripts/cplat/merge_lock.py, scripts/cplat/ship.py]
    covers: [AC-178.2, AC-178.3, AC-178.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: waiting helper and check-test-sleeps.py in quality, ci-local and CI
    files: [tests/cplat/waiting.py, scripts/check-test-sleeps.py, devbox.json, scripts/ci-local.sh, .github/workflows/ci.yml]
    covers: [AC-178.5, AC-178.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: Docs, ADR index and changelog fragment
    files: [docs/unattended-delivery.md, CONTRIBUTING.md, docs/adr/README.md, docs/changelog.d/648-one-way-to-land.fixed.md]
    covers: [AC-178.1, AC-178.3, AC-178.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Every merging command states its mode; the release stops when main moved
    files: [scripts/cplat/pr.py, scripts/cplat/platrelease.py, scripts/cplat/dispatch_units.py, scripts/cplat/spec_pr.py]
    covers: [AC-178.1, AC-178.4]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: Repository commands run without the outer run's CPLAT_* variables
    files: [scripts/cplat/core.py, scripts/cplat/quiet.py, scripts/cplat/quiet_repeat.py, scripts/cplat/validate.py, scripts/cplat/mutation.py, scripts/cplat/ship.py]
    covers: [AC-178.7, AC-178.8]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t5
    title: Dispatcher and merge-lock tests wait for events
    files: [tests/cplat/dispatch_world.py, tests/cplat/dispatch_fake_gh.py, tests/cplat/test_dispatch_units.py, tests/cplat/test_167_units.py, tests/cplat/test_167_merge_lock.py]
    covers: [AC-178.5]
    parallel_safe: true
    depends_on: [t4]
    done: true
  - id: t6
    title: Console, ui and launcher tests wait for events
    files: [tests/cplat/console_support.py, tests/cplat/test_console_server.py, tests/cplat/test_console_actions.py, tests/cplat/test_ui_cli.py, tests/cplat/test_launcher.py]
    covers: [AC-178.5]
    parallel_safe: true
    depends_on: [t4]
    done: true
  - id: t7
    title: Remaining process and time tests on events and the fake clock
    files: [tests/cplat/test_appship_097.py, tests/cplat/test_ship_no_duplicate_pr_452.py, tests/cplat/test_155_repo_sessions.py, tests/cplat/test_109_chain_remote.py, tests/cplat/land171_world.py, tests/cplat/units131_support.py]
    covers: [AC-178.5]
    parallel_safe: true
    depends_on: [t4]
    done: true
---

# Plan — 178 One way to land and tests that do not race

The contract (modes, refusal loop, expected checks, release output, `repo_env`, `waiting.py`, the check's output) is in
[design.md](design.md). Level 1: t1, t4, t8. Level 2: t2, t3 (after t1), t5, t6, t7 (after t4).

## t1 — land_merge - modes, waits after an update, refused merges

**Files:** scripts/cplat/land_merge.py, scripts/cplat/merge_lock.py, scripts/cplat/ship.py
**Covers:** AC-178.2, AC-178.3, AC-178.4
**Goal:** the one landing path takes a mode, never merges on a head the land just moved before that head's expected
checks are green, and treats a refused merge as a wait bounded at 3.

**Implementation notes:**
- `land_merge`: `Mode`, `CATCH_UP`, `RELEASE`, `MAX_REFUSALS = 3`, `BaseMoved`, `MergeRefused(MergeFailed)`, `Rounds.refused/reason`, `ensure_current` exactly as design.md.
- `wait_green(..., mode)` and `settle(..., before_merge, mode)`: in `RELEASE`, `ship.Conflicting`, a `conflicting` merge and `merge_lock.Behind` raise `BaseMoved`; `regenerate` is never called.
- `merge()`: add the `refused` result per the `REFUSED` pattern; `head-moved` stays; everything else stays `MergeFailed`.
- `settle`: the refusal loop of design.md (count both `head-moved` and `refused`, the line with `refusal n/3`, `MergeRefused` at the third), inside the lock the caller holds.
- `merge_lock.catch_up(..., allow=True)`: `allow=False` and behind > 0 raises `Behind(base, behind)` before any `update-branch`; before `update-branch` call `watch.expect_from_current()`; replace the `HEAD_POLLS` loop with `await_change(watch, old, timeout, interval)`.
- `regenerate`: `watch.expect_from_current()` before its push.
- `ship.CheckWatch`: `expected`, `expect_from_current()`, and `poll` honouring it (missing or pending expected name is pending; the non-required drop after `NO_CHECKS_GRACE` with its line; cleared after the green that precedes a merge attempt).
- `ship.push_ahead`: `watch.expect_from_current()` before the push; `ship._land` and `_merge_locked` pass `mode=land_merge.CATCH_UP` explicitly.
- Existing 167/171 tests that assert a refused merge fails at once contradict AC-178.3: report them, do not edit them.

**Done when:** the acceptance tests of AC-178.2 and AC-178.3 pass, the `ship land` and `pr wait --merge` rows of the
AC-178.4 parametrised test pass, and `tests/cplat/test_171_land.py` and `test_167_merge_lock.py` stay green.

## t4 — waiting helper and check-test-sleeps.py in quality, ci-local and CI

**Files:** tests/cplat/waiting.py, scripts/check-test-sleeps.py, devbox.json, scripts/ci-local.sh, .github/workflows/ci.yml
**Covers:** AC-178.5, AC-178.6
**Goal:** one sanctioned way for a test to wait, and a repository check that fails on every other real sleep.

**Implementation notes:**
- `tests/cplat/waiting.py` with `DELAY`, `budget`, `wait_for`, `wait_file`, `wait_process`, `wait_gone`, `fake_prelude` as in design.md; its own poll is the only exempt sleep.
- `scripts/check-test-sleeps.py [--root DIR]`: `ast` for calls, string literals for fake program text, the `fake-delay: <reason>` marker only inside string literals, output lines and exit codes exactly as design.md.
- Wire it into the `quality` script of `devbox.json`, `scripts/ci-local.sh` (a `step` line) and the `validate-shapes` job of `.github/workflows/ci.yml`.

**Done when:** the AC-178.6 acceptance tests pass (fixtures under `--root`); on the real tree the check lists the
occurrences that t5–t7 remove (it goes green once they are merged).

## t8 — Docs, ADR index and changelog fragment

**Files:** docs/unattended-delivery.md, CONTRIBUTING.md, docs/adr/README.md, docs/changelog.d/648-one-way-to-land.fixed.md
**Covers:** AC-178.1, AC-178.3, AC-178.6
**Goal:** say what a person sees when a release's base moved, that a refused merge is waited for, and how tests wait.

**Implementation notes:**
- `docs/adr/README.md`: rows for ADR-100 and ADR-097 (files exist), one sentence each in the table's style.
- `CONTRIBUTING.md`: Releases — a release whose branch fell behind `main` stops with `main moved: start the release again` (close the PR, delete the branch, run again); Checks — `python3 scripts/check-test-sleeps.py`; PR rules — tests wait through `tests/cplat/waiting.py`, never a fixed sleep (ADR-097).
- `docs/unattended-delivery.md`: the landing section names the modes (release never catches up), the wait for the new head's checks after a catch-up and the 3 refused merges.
- Fragment per `docs/changelog.d/README.md`, bold summary ending `(#648).`, relative links from that directory.

**Done when:** `python3 scripts/check-links.py`, `uv run scripts/shapes.py check` and `scripts/check-docs.py` pass.

## t2 — Every merging command states its mode; the release stops when main moved

**Files:** scripts/cplat/pr.py, scripts/cplat/platrelease.py, scripts/cplat/dispatch_units.py, scripts/cplat/spec_pr.py
**Covers:** AC-178.1, AC-178.4
**Goal:** the five commands reach `land_merge` with their mode from the table in design.md, and the release never
changes or merges a branch whose base moved.

**Implementation notes:**
- `pr.wait(..., mode=land_merge.CATCH_UP)` threads `mode` through `_wait`/`_watch` into `wait_green` and `settle`; the CLI keeps `CATCH_UP`.
- `dispatch_units.land` and `spec_pr.land` pass `mode=land_merge.CATCH_UP` explicitly.
- `platrelease._ci_and_merge`: `land_merge.ensure_current(repo, url)` before `_wait_e2e`; both `_wait_pr` calls pass `RELEASE`; `ship.Conflicting` from the plain wait becomes `BaseMoved`.
- `platrelease.main`: catch `land_merge.BaseMoved`, write the two stderr lines of design.md (PR URL and version filled in), return 1.
- Drop the release's own post-merge `git switch main` / `merge --ff-only` loop (`land_merge.cleanup` already ran them in `pr.wait`); keep the `git fetch origin main` the publish step needs.

**Done when:** the AC-178.1 acceptance tests and all five rows of the AC-178.4 parametrised test pass; the existing
platform release tests stay green.

## t3 — Repository commands run without the outer run's CPLAT_* variables

**Files:** scripts/cplat/core.py, scripts/cplat/quiet.py, scripts/cplat/quiet_repeat.py, scripts/cplat/validate.py, scripts/cplat/mutation.py, scripts/cplat/ship.py
**Covers:** AC-178.7, AC-178.8
**Goal:** a unit's test command sees no `CPLAT_*` variable of the run that started it, so the seam test's first variant
has a guard to catch, and the seam test runs a ship from preflight to land.

**Implementation notes:**
- `core.repo_env(extra)` and `core.run(..., repo_command=False)` as in design.md.
- Use them for every `devbox run …` spawn: `ship.run_ci`, the no-progress `test-fast` in `ship`, both spawns in `quiet`, `quiet_repeat` (keeps `CPLAT_REPEAT_RUN` through `extra`), both spawns in `validate`, `mutation`.
- Leave `cplat`'s own child processes (headless sessions, dispatcher units, land processes) on the full environment.
- Run the seam test (AC-178.7) and its variants (AC-178.8); a production change it needs outside these files is a finding for the architect, not an edit.

**Done when:** the AC-178.7 seam test passes in at most 120 s under `-n auto`, and each AC-178.8 variant fails naming
its seam.

## t5 — Dispatcher and merge-lock tests wait for events

**Files:** tests/cplat/dispatch_world.py, tests/cplat/dispatch_fake_gh.py, tests/cplat/test_dispatch_units.py, tests/cplat/test_167_units.py, tests/cplat/test_167_merge_lock.py
**Covers:** AC-178.5
**Goal:** the spec 167 land and unit tests pass the same way on the slow runner.

**Implementation notes:**
- Replace each polling loop and fixed sleep with `waiting.wait_for` / `wait_file` / `wait_process`; the `time.sleep(0.2)` after the call wait in `dispatch_world` becomes a wait for the event the test reads next.
- The fake `claude` and fake `gh` programs start with `waiting.fake_prelude()`; their remaining delays (`die_after`, `merge_delay`, the stop-file poll) carry `fake-delay: <reason>`.
- `test_167_merge_lock`: the patched `merge_lock.sleep` no longer sleeps for real; contention is shown by waiting for the lock holder's info file.

**Done when:** these files pass 10 times in a row under `-n auto` and once with `TEST_FAKE_DELAY=2`, and
`check-test-sleeps.py` reports nothing in them.

## t6 — Console, ui and launcher tests wait for events

**Files:** tests/cplat/console_support.py, tests/cplat/test_console_server.py, tests/cplat/test_console_actions.py, tests/cplat/test_ui_cli.py, tests/cplat/test_launcher.py
**Covers:** AC-178.5
**Goal:** the tests that start the console server, actions and the launcher wait for what they assert on.

**Implementation notes:**
- Polling loops become `waiting.wait_for`; `test_ui_cli`'s `time.sleep(2)` becomes a wait for the opener's marker file (or for the server's ready line).
- Fake programs inside strings (`time.sleep(4)`, `time.sleep(30)`) use `fake_prelude()` and mark their delay `fake-delay: <reason>`.

**Done when:** as t5, for these files.

## t7 — Remaining process and time tests on events and the fake clock

**Files:** tests/cplat/test_appship_097.py, tests/cplat/test_ship_no_duplicate_pr_452.py, tests/cplat/test_155_repo_sessions.py, tests/cplat/test_109_chain_remote.py, tests/cplat/land171_world.py, tests/cplat/units131_support.py
**Covers:** AC-178.5
**Goal:** no test outside the dispatcher and console waits a fixed time; fake programs of the 131 and 171 worlds honour
`TEST_FAKE_DELAY`.

**Implementation notes:**
- `test_appship_097`: the patched `sleep` records instead of sleeping.
- `test_ship_no_duplicate_pr_452`: the archive's second comes from a patched clock, not `time.sleep(1.1)`.
- `test_155_repo_sessions`: `wait_process` for the finished child; the long-running fake headless marks its sleep.
- `test_109_chain_remote`: drop the sleep or replace it with the fake clock the fingerprint needs.
- `land171_world` stub and the fake programs of `units131_support`: `fake_prelude()` at their start.

**Done when:** as t5, for these files, and the whole suite passes the stress gate of design.md (10 × `devbox run
test-fast`, once with `TEST_FAKE_DELAY=2`).
