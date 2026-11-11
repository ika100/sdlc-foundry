# Design — 178 One way to land and tests that do not race

## Decisions

- **One land path, one mode per command.** The five commands already reach `land_merge` (four through `pr.wait`, ship
  land through `ship._merge_locked`), but none says how it treats a branch behind `main`, so the release took the
  catch-up of ADR-092. `land_merge.wait_green` and `land_merge.settle` get a `mode`; each caller passes its mode
  explicitly. ADR: [docs/adr/100-every-merge-into-main-takes-one-land-path-with-a-stated-mode.md](../../adr/100-every-merge-into-main-takes-one-land-path-with-a-stated-mode.md).
- **A release behind `main` stops; it is never rebuilt** (A1). `RELEASE` mode raises `BaseMoved` where `CATCH_UP`
  would update the branch or regenerate a conflict; `platrelease` turns it into the two lines of AC-178.1.
- **After the land moved the head, the merge waits for the new head's expected checks** (AC-178.2): required checks
  plus the checks that passed on the previous head, a missing one counts as pending.
- **A refused merge is a wait, bounded at 3** (A3, AC-178.3), inside the merge lock.
- **The test command a unit runs never sees the outer run's `CPLAT_*` variables.** Today only `tests/cplat/conftest.py`
  strips them, so only the platform's own pytest is protected and the seam test (AC-178.8, first variant) has nothing to
  catch. The strip moves into `cplat` where it spawns a repository's own commands (`devbox run …`).
- **Tests wait for events; a repository check forbids fixed sleeps** (A5). ADR:
  [docs/adr/097-tests-wait-for-events-never-for-a-fixed-time.md](../../adr/097-tests-wait-for-events-never-for-a-fixed-time.md).
- **The seam test world is test code** (like `tests/cplat/land171_world.py` for spec 171): the fake `claude`, the fake
  `gh` backed by the bare origin and the clone are written by the testers. Production offers the seams it already has
  (`CPLAT_CLAUDE`, `gh` and `devbox` from `PATH`) plus the env strip above.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/land_merge.py` | `Mode`, `BaseMoved`, `MergeRefused`, refusal loop, expected checks after an update, `ensure_current` | changed |
| `scripts/cplat/merge_lock.py` | `catch_up(allow=…)`, `Behind`, `await_change` (new head after `update-branch`, bounded by the wait timeout) | changed |
| `scripts/cplat/ship.py` | `CheckWatch.expected` honoured by `poll`; `_land`/`_merge_locked` pass `CATCH_UP`; `run_ci` and the no-progress test run use the clean env | changed |
| `scripts/cplat/pr.py` | `wait(..., mode=CATCH_UP)` threads the mode to `land_merge` | changed |
| `scripts/cplat/platrelease.py` | `RELEASE` mode, `ensure_current` before the waits, `BaseMoved` → AC-178.1 output; drops its duplicate post-merge local steps (`land_merge.cleanup` does them) | changed |
| `scripts/cplat/dispatch_units.py`, `scripts/cplat/spec_pr.py` | pass `mode=land_merge.CATCH_UP` explicitly | changed |
| `scripts/cplat/core.py` | `repo_env(extra)`; `run(..., repo_command=True)` | changed |
| `scripts/cplat/quiet.py`, `quiet_repeat.py`, `validate.py`, `mutation.py` | spawn repository commands with `core.repo_env` | changed |
| `tests/cplat/waiting.py` | the one polling helper and the fake-program prelude | new |
| `scripts/check-test-sleeps.py` | the repository check of AC-178.6 | new |

## Contract

### Landing (`scripts/cplat/land_merge.py`)

```python
@dataclass(frozen=True)
class Mode:
    name: str            # "catch-up" | "release"
    catch_up: bool       # may the land change the PR branch to follow its base?

CATCH_UP = Mode("catch-up", True)
RELEASE  = Mode("release", False)
MAX_REFUSALS = 3

class BaseMoved(PlatformError):        # RELEASE only: the branch is behind its base or conflicts with it
    base: str; url: str                # message: f"{url} is behind {base}: {base} moved"
class MergeRefused(MergeFailed):       # message: f"merge refused 3 times: {reason}"
    reason: str                        # hint: "wait for the checks of the pull request, then run the land again"

@dataclass
class Rounds:
    used: int = 0                      # regeneration rounds (AC-171.6), unchanged
    refused: int = 0                   # refused merges in this land (AC-178.3)
    reason: str = ""                   # GitHub's last refusal reason

def wait_green(repo, url, watch, timeout, interval, rounds, run, mode: Mode = CATCH_UP) -> tuple[str, list, list, list[str]]
def settle(repo, url, watch, timeout, interval, rounds, run, before_merge=None, mode: Mode = CATCH_UP) -> Settled
def merge(repo, url, head, run) -> tuple[str, str]
    # ("merged", sha) | ("head-moved", new head) | ("refused", reason) | ("conflicting", ""); MergeFailed otherwise
def ensure_current(repo, url) -> None  # BaseMoved when behind > 0 or mergeable == CONFLICTING; merge_lock.Unknown when unreadable
```

Mode table (AC-178.4); every caller passes `mode=` explicitly:

| Command | Reaches `land_merge` through | Mode |
|---|---|---|
| `cplat component ship land` | `ship._land` → `wait_green`, `ship._merge_locked` → `settle` | `CATCH_UP` |
| `cplat pr wait --merge` | `pr.wait` → `pr._watch` | `CATCH_UP` |
| dispatcher land of a unit (`cplat dispatch land <unit>`) | `dispatch_units.land` → `pr.wait` | `CATCH_UP` |
| `cplat spec land` | `spec_pr.land` → `pr.wait` | `CATCH_UP` |
| `cplat platform release --confirm merge` | `platrelease._wait_pr` → `pr.wait` | `RELEASE` |

Behaviour by mode:

| Situation | `CATCH_UP` | `RELEASE` |
|---|---|---|
| branch behind base inside the lock (`merge_lock.catch_up`) | `gh pr update-branch`, wait for the new head (AC-178.2) | `merge_lock.Behind` → `BaseMoved`; no `update-branch`, no push, no merge |
| `ship.Conflicting` in `wait_green`, or `merge()` → `conflicting` | `regenerate` (ADR-092 rule 4) | `BaseMoved` |
| `merge()` → `head-moved` or `refused` | refusal loop below | refusal loop below |

Refusal classification in `merge()`: after a non-zero exit of `gh pr merge` and a view that is neither `MERGED` nor
`CONFLICTING`, the result is `head-moved` when the view's `headRefOid` differs from the judged head, `refused` when
GitHub's last line matches `REFUSED = re.compile(r"required status check|is expected|head branch was modified|base branch was modified|match-head-commit", re.I)`,
else `MergeFailed` as today (draft, review, permission).

Refusal loop in `settle` (pseudocode; still inside the merge lock):

```
kind, value = merge(...)
if kind in ("head-moved", "refused"):
    rounds.refused += 1; rounds.reason = value if kind == "refused" else f"the head moved to {value[:7]}"
    if rounds.refused >= MAX_REFUSALS: raise MergeRefused(f"merge refused {MAX_REFUSALS} times: {rounds.reason}")
    say(f"  merge of {url} refused ({rounds.reason}): waiting for the checks of its head (refusal {rounds.refused}/{MAX_REFUSALS})")
    wait_green(... mode)            # the PR's current head; red stops the land as red
    continue                        # back to the behind check, then merge
```

Expected checks after the land moved the head (AC-178.2). Before any change of the head made by the land
(`merge_lock.catch_up` before `update-branch`, `regenerate` before its push) the land calls `watch.expect_from_current()`.
`ship.push_ahead` is the exception (amended 2026-11-10, decided by the user's delegate): AC-171.5 forbids judging or
reading the old head's checks, so it never calls `expect_from_current()`; its expectation is the base branch's required
status checks from the branch protection (`gh api repos/<slug>/branches/<base>/protection/required_status_checks`,
failure or none -> `{}`), set on the watch before the push, so no checks query of the old head is made:

```python
class CheckWatch:
    expected: dict[str, bool]          # check name -> required; {} = no expectation (today's behaviour)
    def expect_from_current(self) -> None:
        # required: `gh pr checks <url> --required --json name` on the current head (failure or none -> empty)
        # seen: names with bucket pass/skipping on the current head
        # expected = {n: True for n in required} | {n: False for n in seen - required}
```

`CheckWatch.poll` on the new head returns `green` only when every expected name is present on that head with bucket
`pass` or `skipping`; a missing or pending expected name keeps it `pending`. A non-required expected name still absent
`NO_CHECKS_GRACE` seconds after every present check concluded is dropped with the line
`  <name> did not run on <sha7>: not expected` (a path-filtered workflow). A required one is never dropped; the wait
timeout then ends it as `ChecksPending` naming it. `expected` is cleared after the green that precedes a merge attempt.

After `gh pr update-branch`, `merge_lock.await_change(watch, old_head, timeout, interval)` polls until the PR head
differs from `old_head` (bounded by the wait timeout, not by `HEAD_POLLS`); a timeout raises
`PlatformError("GitHub does not show the updated head of <url>", hint="run the land again")`. No merge call happens
on the old head after an update.

### Release (AC-178.1)

`platrelease._ci_and_merge` calls `land_merge.ensure_current(repo, url)` before the e2e wait and passes
`mode=land_merge.RELEASE` to both `pr.wait` calls; the plain wait's `ship.Conflicting` becomes `BaseMoved`.
`platrelease.main` catches `land_merge.BaseMoved`, pushes and merges nothing, and writes to **stderr** exactly:

```
main moved: start the release again
  fix: close the release PR (gh pr close <PR url>), delete the release branch (git push origin --delete release/<version>; git branch -D release/<version>), run cplat platform release
```

then returns **1**. The status lines `st.render` prints first go to stdout as today; "first line" in AC-178.1 is the
first line of stderr. The same holds when `main` moves during the waits: the behind check inside `settle` raises it.

### Refused merges (AC-178.3) at the command surface

`MergeRefused` is a `MergeFailed`: `cplat pr wait --merge`, `ship land`, `spec land` and the release exit **1** with
`ERROR: merge refused 3 times: <reason>` (stderr, `cplat.py`'s format); the dispatcher records `landed: merge-failed`
with that line as the summary; a `pr-wait` run record gets `pr_wait.result = "merge-failed"`.

### Repository commands get a clean environment (AC-178.8, first variant)

```python
def repo_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """os.environ without any CPLAT_* variable, then `extra` (which may set CPLAT_* on purpose, e.g. CPLAT_REPEAT_RUN)."""
def run(cmd, *, ..., repo_command: bool = False)   # True: the base env is repo_env(), not os.environ
```

Used for every `devbox run <script>` `cplat` starts in a repository: `ship.run_ci`, the no-progress `test-fast` in
`ship`, `quiet` (both spawns), `quiet_repeat`, `validate` (both spawns), `mutation`. Not used for `cplat`'s own child
processes (sessions, dispatcher units, lands), which need their `CPLAT_*`.

### Test waits (AC-178.5, AC-178.6)

`tests/cplat/waiting.py`:

```python
DELAY: float                                     # float(os.environ.get("TEST_FAKE_DELAY", "0"))
def budget(base: float = 30) -> float            # base + 20 * DELAY: every timeout of a wait
def wait_for(pred, timeout: float | None = None, what: str = "") -> object   # truthy result, else AssertionError("timed out after <t>s waiting for <what>")
def wait_file(path, timeout=None, contains: str | None = None) -> str        # the file's text once it exists (and holds `contains`)
def wait_process(proc, timeout=None) -> int      # Popen.wait(timeout=budget()), AssertionError on timeout
def wait_gone(pid: int, timeout=None) -> None    # the process no longer exists
def fake_prelude(kind: str = "python") -> str    # program text that sleeps TEST_FAKE_DELAY at start ("python" | "sh"), marked fake-delay
```

`TEST_FAKE_DELAY` is deliberately not a `CPLAT_*` name: `conftest.py` strips those. `waiting.py` polls every 0.02 s;
it is the only file in `tests/cplat` whose sleep the check exempts. Time-dependent `cplat` behaviour in tests runs on a
fake clock: the module's `sleep`/`now` replaced (as `ship.sleep`, `ship.now`, `merge_lock.sleep` are today) or the
`clock` fixture of `conftest.py`.

`python3 scripts/check-test-sleeps.py [--root DIR]` scans `<root>/tests/cplat/**/*.py` (default root: the repo):

- flags, with Python's `ast`: calls of `time.sleep`, `asyncio.sleep`, and of a `sleep` imported from `time` or
  `asyncio`; inside string literals (fake program text): `time.sleep(`, `asyncio.sleep(` and a shell `sleep <n|$var>`
  at a line start or after `;`, `&&`, `|`;
- a flagged line inside a string literal that carries `fake-delay: <non-empty reason>` is allowed; the marker outside a
  string literal, or without a reason, allows nothing;
- skips `tests/cplat/waiting.py`;
- prints one line per occurrence, then exits 1:
  `tests/cplat/<file>.py:<line>: <call text> waits a fixed time: wait for an event or a file (waiting.wait_for, waiting.wait_file) or use the fake clock; a fake program marks its delay "fake-delay: <reason>"`
  and finally `check-test-sleeps: <n> fixed sleep(s) in tests/cplat`; with none it prints
  `OK: no fixed sleeps in tests/cplat` and exits 0.

It runs in `devbox run quality`, `scripts/ci-local.sh` and the `validate-shapes` CI job. Acceptance tests written for
this spec follow the same rule (the seam test included).

The stress gate (A4) runs during the build's verification, not in CI:
`for i in $(seq 10); do devbox run test-fast || break; done` and `TEST_FAKE_DELAY=2 devbox run test-fast`.

### The seam test (AC-178.7, AC-178.8): what production guarantees

- `cplat headless` starts the executable named by `CPLAT_CLAUDE` (else `claude`) and runs every `gh`, `git` and `devbox`
  from `PATH`; nothing in the ship path needs the network when those are fakes.
- The Stop hook is `cplat`'s stop gate as configured in the plugin `hooks.json`; a fake `claude` that runs that command
  with Claude Code's hook input (JSON on stdin) is served like the real one.
- A test command started by the unit's `cplat` commands has no `CPLAT_*` variable of the outer run (above).
- The preflight (AC-171.1), push-ahead (AC-171.5) and running-wait marks (AC-171.8) are unchanged; their variants
  break them inside the test world (a committed allowlist without the rule, a session that ends after a local commit,
  a stop during `cplat pr wait`).
- The fake `gh` of the seam world answers `pr checks --required` and refuses `pr merge` the way GitHub does
  (`--match-head-commit` mismatch, a pending required check), so the same world serves the AC-178.4 scenarios.
- `units.py`'s Stop-gate change was needed by AC-178.8.
