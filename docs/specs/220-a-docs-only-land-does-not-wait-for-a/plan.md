---
spec_id: 220-a-docs-only-land-does-not-wait-for-a
shape: platform
spec_hash: 69042bd38eaf
summary: "An in-scope land releases the merge lock's flock under a catch-up claim so out-of-scope lands merge in a fast lane; a green e2e is kept when the base moved only by out-of-scope commits; every land records its lock and catch-up waits"
tasks:
  - id: t1
    title: "e2e-scope.py --diff and the e2e_gate module (workflows, ran, scope of a range and of a change)"
    files: [scripts/e2e-scope.py, scripts/cplat/e2e_gate.py]
    covers: [AC-220.1, AC-220.2, AC-220.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "CheckWatch: the workflow of each check, skipping workflows on one head, cancelling their runs"
    files: [scripts/cplat/ship.py]
    covers: [AC-220.1, AC-220.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: "runs report: lock wait median and p90 for docs and code lands"
    files: [scripts/cplat/runs_report.py]
    covers: [AC-220.8, AC-220.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: "ADR-089 amendment, docs/dispatch.md and the changelog fragment"
    files: [docs/adr/089-every-merge-into-main-holds-the-repo-merge-lock.md, docs/dispatch.md, docs/changelog.d/220-docs-land-fast-lane.changed.md]
    covers: [AC-220.4, AC-220.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: "merge_lock: the catch-up claim, the fast lane in held, catch-up rounds that keep a green e2e"
    files: [scripts/cplat/merge_lock.py]
    covers: [AC-220.1, AC-220.2, AC-220.4, AC-220.5, AC-220.6, AC-220.7, AC-220.10]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
  - id: t4
    title: "Lands pass the fast lane and the hold, cancel the kept e2e run and record the land"
    files: [scripts/cplat/land_merge.py, scripts/cplat/pr.py, scripts/cplat/ship.py]
    covers: [AC-220.3, AC-220.4, AC-220.7, AC-220.8, AC-220.10]
    parallel_safe: true
    depends_on: [t2, t3]
    done: true
human_steps:
  - "7 days after the release that carries spec 220: run `cplat platform runs report --since 7`, check that both AC-220.9 counts in the Lands block are 0, and write the Lands block into #280"
---

# Plan — 220 A docs-only land does not wait for a code PR's catch-up e2e

The contract is [design.md](design.md): every printed line, the claim file, the `Hold`/`LandStats`/`CatchUp` and
`e2e_gate` signatures, the run record item and the report block. Levels: t1, t2, t5, t6 (no shared files) → t3 → t4.
t3 calls `e2e_gate` (t1) and `CheckWatch.skip_workflows` (t2); t4 calls `held(fast_lane=)`/`Hold` (t3) and
`CheckWatch.cancel_runs` (t2) and edits `ship.py` after t2.

## t1 — e2e-scope.py --diff and the e2e_gate module

**Files:** scripts/e2e-scope.py, scripts/cplat/e2e_gate.py
**Covers:** AC-220.1, AC-220.2, AC-220.4
**Goal:** one place decides whether a range of base commits or a PR's own change is inside the e2e scope, with the
`e2e-scope.py` of the current base, and which workflows are the e2e workflows; every failure is "undecidable", never an
exception.

**Implementation notes:**
- `e2e-scope.py`: `--diff FROM TO` as design.md, "`scripts/e2e-scope.py --diff FROM TO`" — a `decide_diff(frm, to)` next
  to `decide`, sharing `triggers` and `_new_headings`; mutually exclusive with `--base`; docstring usage line.
- `e2e_gate.py`: `Scope`, `Range`, `workflows`, `ran`, `local`, `range_scope`, `change_scope` exactly as design.md.
- `workflows`: `yaml.safe_load` of each `.github/workflows/*.yml|*.yaml` whose text contains `scripts/e2e-scope.py`; the
  top-level `name`, else the file stem; an unreadable file is skipped.
- `ran`: checks with `workflow` in the names exist, all `bucket == "pass"`, none `skipping`.
- Git through `core.run(..., check=False)`; PR number from the URL; temporary worktree removed in `finally`
  (`git worktree remove --force`, then `shutil.rmtree(ignore_errors=True)`).
- Script run with `[sys.executable, "-I", script, "--diff", FROM, TO]`, `cwd=<worktree>`, a 120 s timeout; parse
  `run=` from stdout and `trigger: ` lines from stderr; `ERROR: ` line becomes `Scope.error`.
- Module docstring in the style of `merge_lock.py`.

**Done when:** the acceptance tests that exercise `--diff` and `e2e_gate` directly pass, the spec-134 scope tests still
pass, and `devbox run test-fast` is green.

## t2 — CheckWatch: the workflow of each check, skipping workflows on one head, cancelling their runs

**Files:** scripts/cplat/ship.py
**Covers:** AC-220.1, AC-220.3
**Goal:** a land can wait for every check of a new head except those of the e2e workflows, bound to that one head, and
cancel those runs after the merge.

**Implementation notes:**
- `checks()`: add `workflow` to `--json`; `_list_head_runs`: add `workflowName`.
- `CheckWatch.skip`, `expected_workflow`, `all_head_runs`, `skip_workflows(head, names)`, `cancel_runs(names)` as
  design.md, "`ship.CheckWatch` (additions)".
- `_current`: when the head differs from `skip[0]`, set `skip = None` before filtering; filter checks by `workflow` and
  `head_runs` by `workflowName` only while it matches. `_newest_runs`, `_runs_pending`, `_pr_run_missing` and
  `_transient` then see the filtered lists unchanged.
- `cancel_runs`: one fresh `_list_head_runs` for `all_head_runs`; `gh run cancel <id> -R <slug>`; lines through return
  value (the caller prints), WARNING on a non-zero exit with its last line.
- No change to `cplat ship land`'s lock calls here (t4).

**Done when:** the acceptance tests for the CheckWatch part of AC-220.1/AC-220.3 pass, the existing CheckWatch tests
(`tests/cplat/test_*check*`, `test_171_land.py`, `test_178_landing.py`) still pass, and `devbox run test-fast` is green.

## t5 — runs report: lock wait median and p90 for docs and code lands

**Files:** scripts/cplat/runs_report.py
**Covers:** AC-220.8, AC-220.9
**Goal:** `cplat platform runs report` shows how long docs and code lands waited for the merge lock and the two AC-220.9
counts, from the `lands` items of the run records.

**Implementation notes:**
- `aggregate_lands(kept) -> dict` with the JSON of design.md, "`cplat platform runs report`"; items that are not dicts or
  lack numbers are skipped; median/p90 computed like `phases`.
- `aggregate` adds `out["lands"]`; `render_text` adds the Lands block after the phases block (`  none` without items).
- Minutes formatted with one decimal and ` min`.

**Done when:** the acceptance tests for the report part of AC-220.8/AC-220.9 pass, the existing `runs report` tests still
pass, and `devbox run test-fast` is green.

## t6 — ADR-089 amendment, docs/dispatch.md and the changelog fragment

**Files:** docs/adr/089-every-merge-into-main-holds-the-repo-merge-lock.md, docs/dispatch.md, docs/changelog.d/220-docs-land-fast-lane.changed.md
**Covers:** AC-220.4, AC-220.1
**Goal:** the person reading the lock's documentation finds its two parts, the fast lane and the kept e2e.

**Implementation notes:**
- ADR-089: under Status `**Amended by:** spec 220 ([design](../specs/220-a-docs-only-land-does-not-wait-for-a/design.md))`;
  a "Catch-up claim and fast lane" paragraph in Decision (claim beside the lock, written under the flock, in-scope lands
  queue, out-of-scope lands merge, the merge step stays exclusive, kept e2e when the range is outside the e2e scope, the
  release hold checked again before the merge); two Consequences bullets (docs lands no longer queue behind a cluster
  e2e; a land's merge may contain out-of-scope commits its e2e did not see).
- `docs/dispatch.md`, "The merge lock": one paragraph with the fast-lane and the kept-e2e lines (wording from design.md)
  and that repos without an e2e workflow running `scripts/e2e-scope.py` behave as before.
- Fragment `changed`, README style of `docs/changelog.d/`: what waited (docs PRs ~35 min behind #801, lock waits up to 26
  min) and what happens now; ends with `(#NNN).` for the PR number.

**Done when:** `python3 scripts/check-docs.py` (or `devbox run quality`) passes on the changed docs and
`cplat platform pr-check` accepts the fragment.

## t3 — merge_lock: the catch-up claim, the fast lane in held, catch-up rounds that keep a green e2e

**Files:** scripts/cplat/merge_lock.py
**Covers:** AC-220.1, AC-220.2, AC-220.4, AC-220.5, AC-220.6, AC-220.7, AC-220.10
**Goal:** an in-scope land waits on its catch-up checks without blocking out-of-scope merges, in-scope and RELEASE lands
still queue, the release hold is checked right before every merge, a land whose base moved during its wait catches up
again, and a green e2e is kept when everything new in the base is outside the e2e scope.

**Implementation notes:**
- `LandStats`, `Hold`, `MAX_CLAIMED_ROUNDS`, the claim path and format, `held(..., fast_lane=)`, `CatchUp.kept`,
  `catch_up(..., hold=)` as design.md, "`merge_lock`"; the acquisition loop factored into one helper used by `held` and by
  `Hold.waiting`'s retake.
- Keep today's queue and `Busy` rules: a live claim of another process is a queue (resets `begin`, `QUEUE_LIMIT` applies);
  the queue line names the claim's `who` with `(waiting on its checks)`.
- `fast_lane` is called at most once per `held` and only when a live foreign claim is seen; the fast-lane line once.
- Stale claim: `release_hold.alive(pid)` false → removed while holding the flock. Own claim removed in every `finally`.
- `Hold.waiting` retake: a foreign release hold → remove the own claim, unlock, `release_hold.wait_clear`, acquire again
  (other live claims respected); it never merges itself, so the caller's next `_known` sees the moved base (AC-220.5).
- `catch_up`: the round loop of design.md; the e2e head and the judged base come from `e2e_gate`; the three AC-220.1/220.2
  lines through `ship.say`; `watch.skip_workflows` only when kept; stats timed with `time.monotonic()`.
- Without a hold (`hold=None`) or without e2e workflows the behaviour and lines are those of today.
- Module docstring: the two parts of the lock, the fast lane, the kept e2e.

**Done when:** the acceptance tests for AC-220.1, 220.2 and 220.4–220.7 that drive `held`/`catch_up` with fakes pass, the
existing merge-lock tests (`tests/cplat/test_167_merge_lock.py`, `test_171_land.py`, `test_178_landing.py`, the spec-198
hold tests) still pass, and `devbox run test-fast` is green.

## t4 — Lands pass the fast lane and the hold, cancel the kept e2e run and record the land

**Files:** scripts/cplat/land_merge.py, scripts/cplat/pr.py, scripts/cplat/ship.py
**Covers:** AC-220.3, AC-220.4, AC-220.7, AC-220.8, AC-220.10
**Goal:** `pr wait --merge` and `cplat ship land` take the fast lane when their change is outside the e2e scope, hand the
hold to the catch-up, cancel the new head's e2e run after a kept merge, and record every land in the run record.

**Implementation notes:**
- `land_merge.settle(..., hold=None)`, `Settled.kept`, the cancel after a kept merge, `record_land` as design.md,
  "`land_merge`".
- Fast-lane predicate built by one helper `land_merge.fast_lane(repo, url, mode, stats)`: `None` for RELEASE (AC-220.7);
  else a callable that runs `e2e_gate.change_scope`, stores `"docs"|"code"|"unknown"` in `stats.scope`, and returns
  `run is False`. The base branch from `gh pr view --json baseRefName`.
- `pr.py` `_wait`/`_watch` and `ship.py` land (lines ~1391 and ~1491): `with merge_lock.held(..., fast_lane=...) as hold`
  in both the whole-phase and the merge-only form; pass `hold` to `settle`; call `record_land` after `settle` in a
  `finally` that never changes the result.
- In whole-phase mode the `Hold` comes from the outer `held`; the nullcontext branches pass it through.
- No other caller of `settle` exists; `dispatch_units.py` keeps catching `merge_lock.Busy`.

**Done when:** the acceptance tests for AC-220.3, AC-220.4 (end to end through `pr wait --merge`), AC-220.7 (RELEASE mode)
and AC-220.8 pass, the existing land/pr-wait tests still pass, and `devbox run test-fast` is green.
