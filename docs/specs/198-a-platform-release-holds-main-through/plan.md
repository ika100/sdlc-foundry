---
spec_id: 198-a-platform-release-holds-main-through
shape: platform
spec_hash: 9af1a1eff416
summary: "`cplat platform release` sets a machine-local release hold that every cplat merge into the repo waits for inside the merge lock; `cplat platform hold` shows and clears it, `cplat dispatch status` names it"
tasks:
  - id: t1
    title: "The release hold file: claim, take over, stop, release, clear, drop, wait"
    files: [scripts/cplat/release_hold.py]
    covers: [AC-198.2, AC-198.3, AC-198.6, AC-198.7, AC-198.8, AC-198.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "Merges wait for a foreign hold outside the merge lock; the release sets its hold"
    files: [scripts/cplat/merge_lock.py, docs/dispatch.md]
    covers: [AC-198.1, AC-198.2, AC-198.3, AC-198.4, AC-198.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: "`cplat platform hold [--clear] [--json]`"
    files: [scripts/cplat/holdcmd.py, scripts/cplat/cplat.py]
    covers: [AC-198.8]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t5
    title: "`cplat dispatch status` shows the release hold"
    files: [scripts/cplat/dispatch_view.py]
    covers: [AC-198.9]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: "`cplat platform release` holds main from its first check until the tag, an error or a stop"
    files: [scripts/cplat/platrelease.py, scripts/cplat/platrelease_publish.py, docs/adr/089-every-merge-into-main-holds-the-repo-merge-lock.md, CONTRIBUTING.md, docs/changelog.d/198-release-holds-main.added.md]
    covers: [AC-198.1, AC-198.4, AC-198.5, AC-198.6, AC-198.7]
    parallel_safe: true
    depends_on: [t1, t2]
---

# Plan — 198 A platform release holds main through the merge lock

The contract is [design.md](design.md): file format, function signatures, every printed line. Levels: t1 → t2, t4, t5
(no shared files) → t3. t3 needs `merge_lock.set_release_hold` from t2; t4 and t5 only read through `release_hold.view`.

## t1 — The release hold file: claim, take over, stop, release, clear, drop, wait

**Files:** scripts/cplat/release_hold.py
**Covers:** AC-198.2, AC-198.3, AC-198.6, AC-198.7, AC-198.8, AC-198.9
**Goal:** one small module owns the hold: its file beside the merge lock, every mutation under a short mutex flock, the
stale rules (dead pid while running → dropped; stopped past `expires` → expired), the wait loop a merge runs, and the
text/JSON views the two commands print.

**Implementation notes:**
- Public API, constants and the `Hold` dataclass exactly as design.md, "`release_hold.py`"; module seams `now`
  (→ `dispatch_state.now()`), `sleep` (→ `time.sleep`), `alive(pid)` (`os.kill(pid, 0)`; `ProcessLookupError` → False,
  `PermissionError` → True) so tests replace them.
- Paths from `dispatch_state.merge_lock_path(slug)`; writes through `dispatch_state.write_json`; an unreadable file is no hold.
- Mutex: `fcntl.flock` (blocking, LOCK_EX) on `<owner>__<name>.release-hold.lock` around each read-modify-write
  (`resolve`, `claim`, `stop`, `release`, `clear`, the stale removal in `wait_clear`). Never hold it while sleeping.
- `claim`: after resolving stale holds; a live running hold of another pid → `HoldTaken` with nothing written; a stopped
  hold (not expired) → take over: own pid, `running`, `confirm`/`expires` null, `since` kept, version replaced.
- `stop` sets `expires = now() + STOP_TTL`; `release` removes only an own **running** hold, so the `finally` of a release
  that stopped leaves its hold.
- `wait_clear`: the pseudocode in design.md; the removal of a stale hold compares the file to what was read first. It
  counts its elapsed time as the sum of its `sleep(HOLD_POLL)` calls (no monotonic clock), so a test that replaces
  `sleep` drives the 60 s line cadence and the returned seconds. Lines through `ship.say`, exact wording from the design.
- `view`/`text`: the JSON object (`state` "running" | "stopped at confirm merge|tag") and the `cplat platform hold` line;
  a stale hold shows as absent and is not removed.
- Module docstring in the style of `merge_lock.py`: what the hold is, who sets it, who waits.

**Done when:** the acceptance tests of the covered criteria that exercise `release_hold` directly pass (claim/take over,
stale drop and expiry, the wait loop's lines and its ≤ 30 s reaction), and `devbox run test-fast` is green.

## t2 — Merges wait for a foreign hold outside the merge lock; the release sets its hold

**Files:** scripts/cplat/merge_lock.py, docs/dispatch.md
**Covers:** AC-198.1, AC-198.2, AC-198.3, AC-198.4, AC-198.7
**Goal:** every cplat merge (ship land, pr wait --merge, dispatch land, spec land) waits in `held()` while another
process holds the release hold, without holding the merge lock and without the wait counting against its timeout; the
release's own merge passes; `set_release_hold` writes the hold and waits once for a merge already inside the lock.

**Implementation notes:**
- `held()`: the loop of design.md, "`merge_lock.py`". Only the flock wait counts toward `timeout` (`begin += waited` after
  each `wait_clear`); `Busy` stays as today. After a hold wait the caller's normal `land_merge.settle` runs unchanged, so a
  branch now behind `main` is caught up and its checks waited for again (AC-198.3).
- `set_release_hold(slug, version, timeout, interval=5)`: claim first, then the LOCK_NB poll of `merge.lock` with the
  `waiting for the merge of <who> to end before the release` line at the first contention and every `WAIT_LINE_EVERY`;
  unlock at once; past `timeout` release the hold and raise the PlatformError of the design; finally say
  `release hold set on <slug> for <version>` (take-over suffix when taken over).
- No caller changes: `pr.py`, `ship.py`, `dispatch_units.py` already enter `held()`.
- Extend the module docstring (the hold check inside the lock).
- `docs/dispatch.md`, section "The merge lock": one paragraph — during a platform release every merge waits for the
  release hold (the waiting line, no timeout, continues by itself), `cplat dispatch status` shows `release hold:`, and
  `cplat platform hold --clear` lifts a hold left at a stop.

**Done when:** the acceptance tests for AC-198.2–198.4 and the `set_release_hold` part of AC-198.1/198.7 pass, the
existing merge-lock tests (`tests/cplat/test_167_merge_lock.py`, `test_171_land.py`, `test_178_landing.py`) still pass,
and `devbox run test-fast` is green.

## t4 — `cplat platform hold [--clear] [--json]`

**Files:** scripts/cplat/holdcmd.py, scripts/cplat/cplat.py
**Covers:** AC-198.8
**Goal:** a person sees the hold of the current repo and can lift it by hand.

**Implementation notes:**
- `holdcmd.main(argv)` with argparse `prog="cplat platform hold"`, flags `--clear`, `--json`, `--repo` (default `.`);
  slug `dispatch_state.slug_of(repo)`; output and exit codes exactly as design.md, "`cplat platform hold`".
- `cplat.py`: add `"hold": ("holdcmd", [])` to `NOUNS["platform"]`.
- Module docstring with the usage line (the `--help` text).

**Done when:** the acceptance tests for AC-198.8 pass and `devbox run test-fast` is green (including the tests that
check every routed module imports).

## t5 — `cplat dispatch status` shows the release hold

**Files:** scripts/cplat/dispatch_view.py
**Covers:** AC-198.9
**Goal:** the person running the dispatcher sees why land units are not merging.

**Implementation notes:**
- `status_doc`: add `"release_hold": release_hold.view(slug)`.
- `render_status`: the `release hold: …` line as the second line, only when `doc.get("release_hold")` is set; time format
  `YYYY-MM-DD HH:MM` from the ISO fields (design.md, "`cplat dispatch status`").
- Keep `SCHEMA` unchanged, so a document without the key still renders.

**Done when:** the acceptance tests for AC-198.9 pass and `tests/cplat/test_dispatch_view.py` still passes.

## t3 — `cplat platform release` holds main from its first check until the tag, an error or a stop

**Files:** scripts/cplat/platrelease.py, scripts/cplat/platrelease_publish.py, docs/adr/089-every-merge-into-main-holds-the-repo-merge-lock.md, CONTRIBUTING.md, docs/changelog.d/198-release-holds-main.added.md
**Covers:** AC-198.1, AC-198.4, AC-198.5, AC-198.6, AC-198.7
**Goal:** a release sets the hold before its first check, merges through its own hold, clears it after the tag push, on
an error and on Ctrl-C, and keeps it for 2 hours at a confirmation stop; a second live release is refused.

**Implementation notes:**
- `main`: the order of design.md ("Decisions", the hold-placement bullet): move `plugin_mismatches` after the hold; set the
  hold with `merge_lock.set_release_hold(dispatch_state.slug_of(repo), version, o.timeout)` only when not `--dry-run` and
  the phase is `idle`, `branch`, `pr-open` or `merged`; wrap the rest in `try/finally` that prints `release hold cleared`
  when `release_hold.release(slug)` returns True.
- Merge stop (`_ci_and_merge`): `release_hold.stop(slug, "merge")` before printing; when it returns a hold add the
  `  release hold: merges into <slug> wait until <time> (lift it now: cplat platform hold --clear)` line before
  `  continue: …`. Same for `_tag_stop` with `"tag"` (pass the slug in).
- `continue_from`: right after `_tag(...)`, `release_hold.release(slug)` and print `release hold cleared` when it removed it.
- Update both module docstrings (the hold).
- ADR-089: under the Status line `**Amended by:** spec 198 ([design](../specs/198-a-platform-release-holds-main-through/design.md))`
  and a "Release hold" paragraph in Decision (file beside the lock, checked inside `held()`, waits outside the lock and
  untimed, own process passes, 2-hour expiry at a stop, machine-local) and one Consequences bullet (a release no longer
  restarts because `main` moved through a cplat merge; merges by hand or from another machine are not held).
- CONTRIBUTING.md, "Releases": one sentence after the `main moved` sentence — the release holds every cplat merge on this
  machine until the tag, keeps the hold 2 hours at a stop, and `cplat platform hold [--clear]` shows or lifts it.
- Changelog fragment `added`, README style: bold summary ending `(#NNN).` with the PR number; what went wrong (5.21.0 and
  5.22.0 restarted because merges moved `main`) and what happens now.

**Done when:** the acceptance tests for AC-198.1, 198.4–198.7 that run `cplat platform release` pass, the existing
`tests/cplat/test_platrelease_129_*.py` and `test_178_release.py` still pass, `devbox run test-fast` is green and
`cplat platform pr-check` passes on the fragment.
