# Design — 198 A platform release holds main through the merge lock

## Decisions

- **The hold is a file next to the merge lock, not the lock itself.** A release takes hours and exits at its confirmation
  stops; a `flock` dies with its process. The hold is `<state>/locks/<owner>__<name>.release-hold.json`, beside
  `<owner>__<name>.merge.lock` (ADR-089). Every change to that file (set, take over, stop, drop, clear) happens under a
  short `flock` on `<owner>__<name>.release-hold.lock`, held only for the read-modify-write, so a takeover and a drop never race.
- **The hold is checked inside the merge lock, by `merge_lock.held`** (A4). Every cplat merge into a repo's `main` already
  enters `held()` (ship land, pr wait --merge, dispatch land and spec land through `pr.wait`, the release's own merge), so
  one check there covers runs started before the hold. A merge that meets a foreign hold **lets go of the merge lock while
  it waits**, then takes the lock again and checks again: holding the lock while waiting would deadlock the release's own
  merge. This also holds for a land with `serialize: [e2e]` that takes the lock for its whole land phase.
- **The release writes the hold first, then waits for the merge lock to be free once.** A merge already inside the lock
  passed its check and finishes (A4); every merge that enters after the write sees the hold. Waiting for the lock before
  writing would let new merges keep winning the non-FIFO `flock`. The release does not keep the merge lock afterwards.
- **Own hold = same process.** A hold records the release's `pid`; `held()` lets a merge through when `hold.pid ==
  os.getpid()` (AC-198.4). The release merges in its own process (`platrelease._wait_pr` → `pr.wait`), so no token is needed.
- **The wait for a hold is not timed** (A3): `held()` adds the seconds spent waiting for a hold to its lock-wait start, so
  only the time spent waiting for another merge counts against `timeout` (and still ends as `merge_lock.Busy`).
- **The release holds `main` only while `main` matters:** the hold is set for runs that start in phase `idle`, `branch`,
  `pr-open` or `merged`, and it is cleared right after the tag is pushed (the GitHub release and the release-guard wait
  need no still `main`). A run that starts in `tagged`, `guarding` or `guard-red` sets no hold.
- **The hold is set after the argument and phase checks and before the first repo check.** The version is known only
  after `platrelease_state.detect` (a proposal or the release in flight), and the hold records it (AC-198.1). Order in
  `main`: parse → `check_syntax` → fetch → detect → version → status lines → `check_in_flight` → `--confirm` phase checks →
  set the hold (not for `--dry-run`) → `plugin_mismatches` → `check_version` → `_preflight` → guard-red check →
  `--dry-run` returns → the rest. `plugin_mismatches` moves from the first line of `main` to after the hold; a dry run
  still runs every check it runs today.
- **A stop keeps the hold for 2 hours** (A1): at `CONFIRM: merge` / `CONFIRM: tag` the hold becomes `stopped` with
  `expires = stop + 2 h`, named in the stop block. A later release run in the same repo takes it over (its own pid,
  `running`, no expiry, the original `since` kept, the version set to that run's version).
- **A hold whose release is gone is dropped by whoever checks it** (A7, AC-198.7): a `running` hold whose pid is not
  alive (`os.kill(pid, 0)` raises `ProcessLookupError`; `PermissionError` counts as alive) is removed with the `dropped`
  line; a `stopped` hold past `expires` is removed with the `expired` line. Readers that only show (`cplat platform hold`,
  `cplat dispatch status`) treat such a hold as absent and do not remove it. PID reuse after a kill is not guarded: it
  keeps the hold at most until the release is run again or cleared by hand, acceptable for a machine-local hold.
- **A system ship's merge is covered through the component lands it drives.** A system ship merges its component repos
  through `cplat component ship land` (→ `held()`); its own gitops-app merges (`appship_merge`, `ship.merge_gitops`) go
  into gitops-app repos, which keep their own path (ADR-100) and are never the platform repo, the only repo a hold is set on.
- **A decline needs no flag** (A2): the stop already ends the process; `cplat platform hold --clear` or the expiry lifts it.
- **No prompt change.** `/platform:release` shows the stop block verbatim, and the block names the expiry and
  `cplat platform hold --clear`; a rule in the command prompt would cost a register entry and a benchmark for no new behaviour.
- **Times** are shown local as `YYYY-MM-DD HH:MM` (A6) and stored as ISO-8601 local seconds (`2026-11-16T10:20:00`),
  read from `dispatch_state.now()`.
- **ADR-089 is amended, no new ADR:** the hold is a rule of the merge lock, not a separate mechanism; ADR-089 gets an
  `**Amended by:**` line and a "Release hold" decision paragraph (the same practice spec 194 used for ADR-082).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/release_hold.py` | the hold file: read, effective view, claim/take over, stop, release, clear, the wait loop for merges, text and JSON rendering | new |
| `scripts/cplat/merge_lock.py` | `held()` checks the hold after taking the lock and waits outside it; `set_release_hold()` for the release | changed |
| `scripts/cplat/platrelease.py` | sets the hold, keeps it at the merge stop, clears it on every exit | changed |
| `scripts/cplat/platrelease_publish.py` | keeps the hold at the tag stop, clears it right after the tag push | changed |
| `scripts/cplat/holdcmd.py` | `cplat platform hold [--clear] [--json] [--repo DIR]` | new |
| `scripts/cplat/cplat.py` | routes `platform hold` to `holdcmd` | changed |
| `scripts/cplat/dispatch_view.py` | `release_hold` in `status --json`, the `release hold:` line in the text | changed |

## Contract

### The hold file

`<XDG_STATE_HOME or ~/.local/state>/sdlc-foundry/locks/<owner>__<name>.release-hold.json` (path:
`dispatch_state.merge_lock_path(slug).with_name(f"{dispatch_state.slug_dir(slug)}.release-hold.json")`), written atomically
with `dispatch_state.write_json`:

```json
{"slug": "ika100/sdlc-foundry", "version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": 41234,
 "state": "running", "confirm": null, "expires": null}
```

- `state`: `"running"` | `"stopped"`; `confirm`: `null` | `"merge"` | `"tag"` (set when `stopped`); `expires`: `null` when
  `running`, ISO local seconds when `stopped`.
- An unreadable or non-object file counts as no hold and is replaced by the next claim.

The slug of a release (and of `cplat platform hold`, `cplat dispatch status`) is `dispatch_state.slug_of(repo)`; a merge
uses `merge_lock.slug_of(repo, pr_url)` as today (both are `owner/name` for a GitHub origin).

### `release_hold.py` (public; `now`, `sleep`, `alive` are module seams tests replace)

```python
HOLD_POLL = 5            # seconds between two checks of a waiting merge (AC-198.3: ≤ 30)
WAIT_LINE_EVERY = 60     # seconds between two "waiting for the release hold" lines
STOP_TTL = 2 * 3600      # a hold at a confirmation stop expires this long after the stop (A1)

@dataclass
class Hold:
    slug: str; version: str; since: str; pid: int
    state: str = "running"; confirm: str | None = None; expires: str | None = None

class HoldTaken(PlatformError):      # AC-198.7, second release
    # message: f"release {version} holds {slug} (process {pid}, since {YYYY-MM-DD HH:MM}): one release at a time"
    # hint:    "wait for it to end, or see it with `cplat platform hold`"

def path(slug: str) -> Path
def read(slug: str) -> Hold | None                  # the raw file
def stale(h: Hold) -> str | None                    # "expired" | "dropped" | None (pure; uses now() and alive())
def view(slug: str) -> dict | None                  # effective hold for display (None when absent or stale), JSON shape below
def resolve(slug: str) -> Hold | None               # under the mutex: removes a stale hold, says its line, returns the live hold
def claim(slug: str, version: str) -> tuple[Hold, bool]   # under the mutex, after resolve: a new running hold, or the
                                                    # take-over of a stopped one; (hold, taken_over). HoldTaken (nothing
                                                    # written) when a live running hold of another pid exists
def stop(slug: str, confirm: str) -> Hold | None    # own running hold → stopped, confirm, expires = now + STOP_TTL;
                                                    # None when this process holds no running hold
def release(slug: str) -> bool                      # removes the hold only when it is this process's AND running; True when removed
def clear(slug: str) -> Hold | None                 # by hand: removes any hold file; the removed hold, else None
def foreign(slug: str) -> Hold | None               # resolve(), then None when the live hold is this process's own
def wait_clear(slug: str, h: Hold) -> float         # the wait loop of a merge (below); returns the seconds waited
def describe(h: Hold) -> str                        # "release 5.24.0 since 2026-11-16 10:20"
def text(slug: str, v: dict | None) -> str          # the `cplat platform hold` line
```

`wait_clear` (pseudocode):

```
say(f"waiting for the release hold of {slug}: release {h.version} since {hhmm(h.since)}")
loop every HOLD_POLL s:
    cur = read(slug)
    if cur is None:                 say(f"release hold of {slug} cleared");  return waited
    why = stale(cur)
    if why == "expired":            remove under the mutex if unchanged; say(f"release hold of {slug} expired"); return waited
    if why == "dropped":            remove under the mutex if unchanged; say(f"release hold of {slug} dropped: process {cur.pid} is gone"); return waited
    every WAIT_LINE_EVERY s:        say the waiting line again (for cur, which may be a take-over)
```

`resolve` says the same `expired` / `dropped: process <pid> is gone` line when it removes a stale hold.

### Lines (exact; `<slug>` is `owner/name`, `<time>` is `YYYY-MM-DD HH:MM` local)

| When | Line | Printed by |
|---|---|---|
| release sets a hold (AC-198.1) | `release hold set on <slug> for <version>` | `merge_lock.set_release_hold` |
| release takes over a stopped hold (AC-198.6) | `release hold set on <slug> for <version> (taken over from the stop at confirm <merge\|tag>)` | same |
| a merge is inside the lock when the release sets its hold (AC-198.1) | `waiting for the merge of <who> to end before the release` (at once, then every 60 s; `<who>` from `merge.json`, else `another merge`) | same |
| a merge meets a foreign hold (AC-198.2) | `waiting for the release hold of <slug>: release <version> since <time>` (at once, then every 60 s) | `release_hold.wait_clear` |
| the hold ends while a merge waits (AC-198.3) | `release hold of <slug> cleared` / `release hold of <slug> expired` | same |
| a stale running hold is found (AC-198.7) | `release hold of <slug> dropped: process <pid> is gone` | `resolve` / `wait_clear` |
| the release clears its hold (AC-198.5) | `release hold cleared` | `platrelease`, `platrelease_publish` |
| a stop keeps the hold (AC-198.6) | `  release hold: merges into <slug> wait until <time> (lift it now: cplat platform hold --clear)` — inside the `CONFIRM:` block, the line before `  continue: …` | `platrelease` / `platrelease_publish` |

All progress lines go through `ship.say` (stdout, flushed); the stop line is part of the printed block.

### `merge_lock.py`

```python
@contextlib.contextmanager
def held(slug, who, timeout, interval=5):
    # loop:
    #   take the flock (LOCK_NB poll as today; only this time counts against timeout → Busy)
    #   h = release_hold.foreign(slug)              # drops a stale hold; None for no hold or this process's own
    #   if h is None: write merge.json, yield, unlink merge.json, unlock — as today
    #   else: unlock; waited = release_hold.wait_clear(slug, h); begin += waited; loop again
    #         (a merge that waited takes the lock again and runs its normal catch-up: a branch now behind main is updated
    #          and its checks are waited for again — AC-198.3, unchanged land_merge.settle)

def set_release_hold(slug: str, version: str, timeout: float, interval: float = 5) -> release_hold.Hold:
    # 1. hold, taken = release_hold.claim(slug, version)        # HoldTaken → nothing written (AC-198.7)
    # 2. wait until the merge lock is free: LOCK_NB poll of merge.lock; at the first contention and every 60 s say
    #    "waiting for the merge of <who> to end before the release"; on success unlock at once.
    #    Past `timeout`: release_hold.release(slug), then raise PlatformError(
    #      f"the merge of {who} in {slug} did not end within {int(timeout)}s; the release did not start",
    #      hint="run the release again")
    # 3. say the "release hold set on …" line (with the take-over suffix when taken); return hold
```

### `platrelease.main`

```
... (order in Decisions)
slug = dispatch_state.slug_of(repo); hold = None
if not o.dry_run and state.phase in (IDLE, BRANCH, PR_OPEN, MERGED):
    hold = merge_lock.set_release_hold(slug, version, o.timeout)
try:
    return <the existing flow>
finally:
    if hold and release_hold.release(slug):      # error, Ctrl-C, success; a stopped hold is not removed
        print("release hold cleared")
```

- At the merge stop (in `_ci_and_merge`, before the `CONFIRM: merge` block) and the tag stop
  (`platrelease_publish._tag_stop`): `release_hold.stop(slug, "merge"|"tag")`; when it returns a hold, the block carries
  the `release hold:` line. `release()` in the `finally` then removes nothing, because the hold is `stopped`.
- `platrelease_publish.continue_from`: right after `_tag(...)`, `release_hold.release(slug)` and, when it removed the hold,
  print `release hold cleared` (the later `finally` removes nothing and prints nothing).
- `KeyboardInterrupt` reaches the `finally` (AC-198.5). A kill without `finally` leaves a `running` hold with a dead pid,
  which the next check drops (AC-198.7).
- A second release while a live one runs: `set_release_hold` raises `HoldTaken` before anything else is done; exit 1
  with the usual `ERROR:` / `fix:` lines (AC-198.7).

### `cplat platform hold [--clear] [--json] [--repo DIR]`

The slug is `dispatch_state.slug_of(<repo>)` (`--repo` default `.`). Exit 0 in every case below; 2 for a usage error.

- No flags, a hold: `release hold on <slug>: release <version> since <time>, process <pid>, running`, or
  `release hold on <slug>: release <version> since <time>, process <pid>, stopped at confirm <merge|tag>, expires <time>`.
- No flags, none (or only a stale one): `no release hold on <slug>`.
- `--json`: `release_hold.view(slug)` as one JSON object, or `null`:

  ```json
  {"version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": 41234, "state": "running", "expires": null}
  ```

  `state` is exactly `"running"`, `"stopped at confirm merge"` or `"stopped at confirm tag"`; `since`/`expires` ISO local
  seconds; `expires` is `null` when running.
- `--clear`: removes any hold file (stale or live) and prints `release hold of <slug> cleared by hand`; with none:
  `no release hold on <slug>`. `--clear --json` prints `{"cleared": <the view of the removed hold, or null>}`. Waiting
  merges see the file gone and continue (`release hold of <slug> cleared`, AC-198.3).

### `cplat dispatch status`

- `status_doc` gains `"release_hold": release_hold.view(slug)` (the object above, or `null`); `SCHEMA` is unchanged (an
  added key).
- `render_status` adds, as the second line (right after `dispatcher: …`), when there is a hold:
  `release hold: <version> since <time>` for a running hold, and
  `release hold: <version> since <time>, stopped at confirm <merge|tag>, expires <time>` for a stopped one. No line without one.

## Data

One JSON file per repo (above), plus the empty mutex file `<owner>__<name>.release-hold.lock` beside it. No migration:
an absent file is no hold.
