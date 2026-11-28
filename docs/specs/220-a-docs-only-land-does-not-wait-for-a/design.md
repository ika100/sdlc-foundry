# Design — 220 A docs-only land does not wait for a code PR's catch-up e2e

## Decisions

- **The merge lock becomes two parts in the same place: the flock (the merge step) and a catch-up claim (a record).** An
  in-scope land that waits on its catch-up checks writes `<owner>__<name>.merge-claim.json` beside `merge.lock`, while it
  holds the flock, then releases the flock for the wait and takes it back for its merge. A land that finds a live claim of
  another process either queues (in scope, undecidable, RELEASE: AC-220.6, AC-220.7) or takes the fast lane (outside the
  e2e scope: AC-220.4). No second lock file (A4): the claim is plain JSON written only under the flock, and the merge step
  stays exclusive because every merge still happens under the one flock. This changes ADR-089, so the plan amends it
  (precedent: spec 198) instead of adding an ADR.
- **A land claims only when its own change is in the e2e scope**, which it knows without a scope run: the head it is
  catching up from has a green e2e that ran (all checks of the e2e workflow `pass`, none `skipping`). An out-of-scope land
  keeps the flock through its catch-up as today; its checks are the short ones.
- **A kept e2e is tracked as `(e2e head, judged base)` across catch-up rounds**, so a land whose base moves again after a
  kept round (a fast-lane merge, AC-220.5) judges the whole range since the head whose e2e really ran. The judged base is
  `git merge-base <e2e head> origin/<base>`: the oldest base that e2e can have seen, so the range is never too short (CI
  tested the PR merge ref, which may hold a newer base; a longer range only makes keeping rarer, never wrong).
- **The scope of a range and of a change is decided by the `e2e-scope.py` of the current base, run in a temporary
  detached worktree of `origin/<base>`** (A1), with a new `--diff FROM TO` mode: the existing `--base` mode adjusts for a
  PR merge commit (`pr_base`), which would misread an update-branch merge commit as the base. A script that is missing at
  the base, exits non-zero, prints no `run=` line, or a commit that is not known, makes the scope undecidable (AC-220.2).
  Judging B's change with the base's code is sound: a change that makes a module exercised edits an exercised module,
  which is in scope by itself.
- **E2e workflows are read from the CI, never listed** (A2, ADR-080): the `name:` of each `.github/workflows/*.y*ml` whose
  text runs `scripts/e2e-scope.py`. A repo with none (every non-platform shape today) has no claims, no kept e2e and no
  fast lane, and prints none of the new lines: its lands behave exactly as before.
- Departs from assumption A2 for the upgrade e2e workflows: `e2e-upgrade` and `e2e-upgrade-drill` decide their scope with
  a paths filter and `release-check.py needs-upgrade-e2e`, not with `e2e-scope.py`, so a range outside the cluster e2e
  scope can still change what they test; their checks on the new head are waited for as today.
- **Keeping ignores the e2e workflows only on the one new head the land produced** (`CheckWatch.skip`): a head that moves
  to any other commit (a push, a regeneration) drops the skip, so nothing merges unchecked.
- **Cancel after the merge, not before** (A3): the e2e runs of the new head are cancelled once GitHub accepted the merge;
  a failed cancel is a `WARNING:` line, never a failed land.
- **At most `MAX_CLAIMED_ROUNDS = 3` claimed catch-up rounds per land**; a fourth round keeps the flock through its
  checks, so a stream of fast-lane merges cannot starve a code land (no new failure mode).
- **The release hold is checked again when a claiming land takes the flock back** (AC-220.7). A land that finds a foreign
  hold then drops its claim before it waits, so the release's own land (RELEASE mode, which queues behind claims) is never
  blocked by a land that waits for the release. `set_release_hold` stays unchanged.
- **With `serialize: [merge, e2e]` the first wait for green stays inside the flock**; only catch-up waits claim. The spec's
  fast lane is about a land "waiting on the checks of its updated head".
- **Measuring goes into a `lands` list of the run record** (one item per land, a ship run may land more than once), and
  `cplat platform runs report` aggregates it. The land's scope for the measure (A5) is the fast-lane decision when one was
  made, else one `change_scope` call after the land (only in repos with an e2e workflow).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/e2e-scope.py` | `--diff FROM TO` mode | changed |
| `scripts/cplat/e2e_gate.py` | e2e workflow names, "e2e ran", scope of a range and of a change (temporary base worktree) | new |
| `scripts/cplat/ship.py` | `CheckWatch`: the `workflow` of each check, `skip` of workflows on one head, `cancel_runs`; `cplat ship land` passes the fast lane and the hold | changed |
| `scripts/cplat/merge_lock.py` | `Hold` handle, the claim, the fast lane in `held`, `catch_up` rounds with keep/claim, `LandStats` | changed |
| `scripts/cplat/land_merge.py` | `settle(hold=)`, cancel after a kept merge, `record_land` | changed |
| `scripts/cplat/pr.py` | `pr wait --merge` passes the fast lane and the hold, records the land | changed |
| `scripts/cplat/runs_report.py` | the `lands` block of the report | changed |
| `docs/adr/089-…`, `docs/dispatch.md` | the lock's two parts, the fast lane, the kept e2e | changed |

## Contract

### Printed lines (exact; `<sha7>` is the first 7 characters)

| When | Line |
|---|---|
| AC-220.1 kept | `e2e: kept the green e2e of <e2e head sha7>; <n> commit(s) since are outside the e2e scope` |
| AC-220.2 in scope | `e2e: waiting for the e2e of <new head sha7>: <first reason> is inside the e2e scope` + ` (and <k> more)` when there are more |
| AC-220.2 undecidable | `e2e: waiting for the e2e of <new head sha7>: the e2e scope could not be decided (<error>)` |
| AC-220.3 cancelled | `e2e: cancelled run <run id> (<workflow>) on <new head sha7>: the kept e2e covers it` |
| AC-220.3 cancel failed | `WARNING: cancelling run <run id> (<workflow>) failed: <last error line>` |
| AC-220.4 fast lane (once per land) | `fast lane: <A's PR URL> waits on its checks; merging <B's PR URL> outside the e2e scope` |
| AC-220.6 queue (first contention, then every `WAIT_LINE_EVERY`) | `waiting for the merge lock of <slug>: held by <who> (waiting on its checks) since <HH:MM:SS>` |
| a claimed round starts | `  released the merge lock of <slug> while the checks of <new head sha7> run; in-scope merges wait, others may merge` |

`<n>` is `git rev-list --count <judged base>..<current base>`; `<first reason>` is the first `trigger:` line of
`e2e-scope.py` without its prefix (a path, or `release heading X.Y.Z`). The lines of today (`was behind … updated`, `GREEN:
all <n> check(s) passed … after the update`, `waiting for the merge lock … held by … since …`) stay.

### `scripts/e2e-scope.py --diff FROM TO`

`e2e-scope.py --diff FROM TO` compares commit `TO` with commit `FROM` with the code of this checkout: files =
`git diff --name-only FROM TO`, triggers as today, plus a release heading that `TO:docs/CHANGELOG.md` adds over
`FROM:docs/CHANGELOG.md`. No `pr_base` adjustment. Output and exit codes as `--base` (`run=true|false` on stdout,
`trigger: …` on stderr, `ERROR: …` and exit 1 for an unknown commit). `--diff` and `--base` together: argparse error.

### `scripts/cplat/e2e_gate.py`

```python
SCRIPT = "scripts/e2e-scope.py"

@dataclass(frozen=True)
class Scope:
    run: bool | None            # None: undecidable
    reasons: list[str]          # trigger lines without "trigger: "
    error: str = ""             # why undecidable (one line)

@dataclass(frozen=True)
class Range:
    scope: Scope
    since: str                  # the judged base (full sha) or "" when unknown
    to: str                     # the current base (full sha) or ""
    commits: int                # commits in since..to (0 when unknown)

def workflows(repo: Path) -> frozenset[str]          # e2e workflow names from .github/workflows of the checkout
def ran(cs: list[dict], names: frozenset[str]) -> bool   # checks of those workflows exist, all "pass", none "skipping"
def local(repo: Path, slug: str) -> bool             # the checkout is the PR's repo (dispatch_state.slug_of(repo) == slug)
def range_scope(repo: Path, url: str, base: str, e2e_head: str) -> Range
def change_scope(repo: Path, url: str, base: str) -> Scope
```

- `range_scope`: `git fetch -q origin <base> pull/<n>/head`; `since = merge-base <e2e_head> origin/<base>`, `to =
  rev-parse origin/<base>`; run the script from a worktree of `to` with `--diff since to`. `change_scope`: same fetch;
  `--diff $(merge-base <PR head> origin/<base>) <PR head>`.
- Both run `[sys.executable, "-I", "<worktree>/scripts/e2e-scope.py", "--diff", FROM, TO]` with `cwd=<worktree>`; the
  worktree is `git worktree add -q --detach <tmp> <to>` under `tempfile.mkdtemp(prefix="cplat-e2e-scope-")`, removed with
  `git worktree remove --force` in `finally`. Every failure (not `local`, fetch, unknown sha, no script, exit ≠ 0, no
  `run=` line) returns `Scope(None, [], "<one line>")`; nothing raises.
- Tests replace `range_scope`, `change_scope` and `workflows` (module attributes, looked up at call time by
  `merge_lock` and `land_merge`).

### `ship.CheckWatch` (additions)

- `checks()` asks `--json name,state,bucket,link,startedAt,workflow`; `_list_head_runs` adds `workflowName`.
- `skip: tuple[str, frozenset[str]] | None` — `(head sha, workflow names)`. While `self.head == skip[0]`, `_current` drops
  checks whose `workflow` is in the set, and `head_runs` drops runs whose `workflowName` is in it (so `_runs_pending`,
  `_pr_run_missing` and `lone_cancelled` ignore them); `all_head_runs` keeps the unfiltered list. A different head sets
  `skip = None`.
- `expect_from_current()` also fills `expected_workflow: dict[name, workflow]`; `skip_workflows(head, names)` sets `skip`
  and deletes the `expected` names whose workflow is in `names`.
- `cancel_runs(names) -> list[str]`: for each run of `all_head_runs` (re-listed once) with `workflowName` in `names` and
  `status != "completed"`: `gh run cancel <id> -R <slug>`; returns the AC-220.3 lines.

### `merge_lock`

Claim file `dispatch_state.merge_lock_path(slug).with_name(f"{slug_dir}.merge-claim.json")`:

```json
{"who": "pr 805 (unit-3)", "pid": 4242, "pr": "https://github.com/o/r/pull/805", "since": "14:02:11"}
```

A claim whose `pid` is not alive (`release_hold.alive`) is stale: ignored, and removed by the next process holding the
flock. The info file `merge.json` gains `"phase": "merge" | "checks"` (`checks` while the flock holder waits on catch-up
checks without a claim).

```python
MAX_CLAIMED_ROUNDS = 3

@dataclass
class LandStats:
    lock_wait_s: float = 0.0              # every wait for the flock and for claims, the retake included
    lock_wait_catch_up_s: float = 0.0     # the part of it while a claim or a "checks" holder was seen
    catch_up_s: float = 0.0               # time in catch-up check waits
    catch_up_e2e: bool = False            # a catch-up waited on e2e checks
    range_scope: str | None = None        # "out" | "in" | "unknown" | None (no kept-e2e decision was made)
    fast_lane: bool = False
    e2e_kept: bool = False
    scope: str | None = None              # "docs" | "code" | "unknown" | None

class Hold:
    slug: str; who: str; stats: LandStats; locked: bool
    def phase(self, name: str) -> None                         # rewrites merge.json with the phase
    @contextlib.contextmanager
    def waiting(self, pr: str) -> Iterator[None]               # claim, release, wait, take back

@contextlib.contextmanager
def held(slug, who, timeout, interval=5, *, fast_lane: Callable[[], bool] | None = None) -> Iterator[Hold]

@dataclass
class CatchUp:                           # existing fields kept
    ...
    kept: frozenset[str] = frozenset()   # e2e workflow names skipped on the merged head (empty: nothing kept)

def catch_up(repo, url, watch, timeout, interval, allow=True, hold: Hold | None = None) -> CatchUp
```

`held` acquisition (pseudocode; the release-hold check and `Busy`/queue rules of today stay):

```
loop:
    flock LOCK_NB, else wait as today (wait time -> stats.lock_wait_s)
    hold = release_hold.foreign(slug) -> as today: unlock, wait_clear, continue
    claim = live foreign claim (remove a stale one)
    if claim:
        if fast_lane and fast_lane():  say fast-lane line once; stats.fast_lane = True; break
        unlock; queue line; sleep(interval); continue        # a live claim is a queue: not counted against timeout
    break
write merge.json {who, pid, since, phase: "merge"}; yield Hold
finally: if hold.locked: unlink merge.json, unlock; remove an own claim
```

`fast_lane` is evaluated at most once per `held` (its result cached), only when a live foreign claim is seen.

`Hold.waiting(pr)`: when another live claim exists, it only sets `phase("checks")` and yields (flock kept). Else it writes
the claim, says the "released" line, unlinks `merge.json`, unlocks (`locked = False`) and yields. On normal exit it takes
the flock back through the acquisition loop with `fast_lane=None` and its own claim counting as absent; a foreign release
hold found then removes the own claim before `wait_clear`. On an exception it removes the claim and does not take the flock.

`catch_up` (pseudocode):

```
names = e2e_gate.workflows(repo) if e2e_gate.local(repo, slug) else frozenset()
e2e = (head, base-at-start) if names and e2e_gate.ran(checks of watch.head, names) else None   # the green e2e head
claimed = 0
loop:
    behind, base, head = _known(...); if behind <= 0: return out
    if not allow: raise Behind
    kept = False
    if e2e:
        r = e2e_gate.range_scope(repo, url, base, e2e.head)
        kept = r.scope.run is False; say kept line | in-scope line | undecidable line
        stats.range_scope = "out" | "in" | "unknown"
    watch.expect_from_current(); gh pr update-branch (Conflict as today); await_change
    new = watch.head_sha()
    if kept: watch.skip_workflows(new, names)
    ctx = hold.waiting(url) if hold and e2e and claimed < MAX_CLAIMED_ROUNDS else hold.phase("checks")/nullcontext
    with ctx: wait checks as today (time -> stats.catch_up_s)      # claimed += 1 when it claimed
    stats.catch_up_e2e |= bool(e2e) and not kept
    if red: return red (kept = frozenset())
    out.kept = names if kept else frozenset(); stats.e2e_kept = kept
    if not kept and e2e and e2e_gate.ran(checks of new, names): e2e = new head
    # loop: the base may have moved during a claimed wait (AC-220.5)
```

### `land_merge`

- `settle(..., hold: merge_lock.Hold | None = None)` passes `hold` to `catch_up`. After `kind == "merged"` with
  `caught.kept`, it appends `watch.cancel_runs(caught.kept)` to the lines (after the merge line, before cleanup).
- `Settled.kept: bool` (the merged head kept an e2e).
- `record_land(repo, url, watch, hold, mode) -> None`: when `hold.stats.scope is None` and the repo has e2e workflows,
  `scope = "docs" | "code" | "unknown"` from `e2e_gate.change_scope`; then `runs.add_to(watch.run_id, "lands", item)`.
  Never raises. Called by `pr._watch` and `ship._merge_locked` after `settle`, also when it returned red.

Run record item of `lands` (minutes rounded to 1 decimal):

```json
{"pr": 805, "mode": "catch-up", "scope": "code", "lock_wait_min": 0.4, "lock_wait_catch_up_min": 0.0,
 "catch_up_min": 3.1, "catch_up_e2e": false, "range_scope": "out", "fast_lane": false, "e2e_kept": true}
```

### `cplat platform runs report`

JSON gains `"lands"`:

```json
{"docs": {"count": 12, "lock_wait_median_min": 0.3, "lock_wait_p90_min": 1.2},
 "code": {"count": 5, "lock_wait_median_min": 2.0, "lock_wait_p90_min": 9.5},
 "fast_lane": 4, "e2e_kept": 2,
 "docs_waited_behind_catch_up_over_5_min": 0,
 "code_catch_up_e2e_out_of_scope": 0}
```

`docs`/`code` group by `scope`; `unknown`/missing scope counts in neither group. `docs_waited_behind_catch_up_over_5_min`
counts docs lands with `lock_wait_catch_up_min > 5`; `code_catch_up_e2e_out_of_scope` counts lands with
`range_scope == "out"` and `catch_up_e2e` true (AC-220.9: both must be 0). Median and p90 as the `phases` block. Text,
after the phases block:

```
Lands (lock wait median / p90):
  docs: 0.3 min / 1.2 min (n=12)
  code: 2.0 min / 9.5 min (n=5)
  fast lane: 4, kept e2e: 2; docs lands > 5 min behind a catch-up: 0; code lands with an out-of-scope catch-up e2e: 0
```

`  none` when no record holds a `lands` item.
