# Design — 184 Parallel ships do not stop each other

## Decisions

- **The usage limit is an environment pause, decided after each session in one module** (`usagelimit.py`): both drivers
  (unit mode in `supervisor.py`, the legacy loop in `headless._drive`) ask it after every session whether the session hit
  the limit, and it says how long to wait or that the run must stop. Neither driver has its own pause logic, so the two
  modes cannot drift apart (A5).
- **Only the last non-empty line of a session's output is read for the limit message.** A session that talks about the
  usage limit (this spec's own build does) must not pause. In `-p --output-format text` mode a session that hits the limit
  prints only the CLI's message, so the last line is where it is.
- **A paused session is undone, not counted**: its invocation is taken back (`budget.count_invocation(rid, -1)`), it does
  not count toward `--max-runs`, it adds no stall to its unit, and the legacy loop does not compare its progress key. A
  checkpoint the session committed before the limit still counts (the work is kept).
- **Pause time is subtracted, not stopped**: the budget ledger keeps a `paused_minutes` figure on the current root and
  `used_of` subtracts it; `--max-minutes` moves the run's `begin` forward by the pause. No clock is stopped, so a crash during a
  pause leaves a consistent ledger.
- **Repo slots are flock files beside the merge lock** (`<state>/locks/<owner>__<name>.slot-<n>.lock`, ADR-089's key). A
  slot is held by an open, locked file descriptor of the `cplat headless` process, so it is freed by the kernel when that
  process dies; the JSON beside it only names the holder. A JSON whose pid is gone is "a stale slot" and is reported once
  when taken over. Child processes do not inherit the descriptor (Python opens files close-on-exec).
- **The slot pool size is the dispatcher's `slots`**: `cplat dispatch slots N` (the steering override in `state.json`)
  when set, else `slots` of `.platform/dispatch.yml`, else 1. Reason: the dispatcher's own units run `cplat headless` and take
  slots from the same pool; a pool smaller than the dispatcher's override would make its units wait on each other. The
  override is the runtime value of the same `slots` key, not an extra flag (A10).
- **A run inside a run never waits for its own slot**: while a slot is held, `CPLAT_SLOT=<owner>/<name>#<n>` is in the
  environment of every session; a `cplat headless` whose repo slug matches takes no slot. Without this a session that
  starts `cplat headless` in its own repo would wait forever.
- **The slot is taken before the run record and the budget ledger open**, so waiting for it costs no budget minutes and
  shows no half-started run (AC-184.8).
- **Land conflicts in id-keyed files get resolvers next to the generated-block regeneration** (`land_resolve.py`, called
  by `land_merge.regenerate`). Each resolver gets the three merge stages and returns the merged text plus the renumbering
  it did; a part it cannot key stops the land as `Unresolvable`, as today. The rounds stay `Rounds.used` of spec 171, so
  AC-171.6, AC-184.6 and AC-184.7 share the limit of 3.
- **The branch's side is always the one renumbered** (A8), with the numbers `cplat spec adr-next` (`adr.next_number`) and
  "max `R<n>` in the merged register file + 1" give. References are replaced only in files the branch changed.
- **One template-lint script for local CI and the CI smoke jobs** (`scripts/template-lint.py`): it knows the lint each
  template's smoke job runs, runs it without `-q`, and prints one uniform line per violation. The service-go smoke job
  keeps `golangci-lint-action` (it runs the same `golangci-lint run` with the template's `.golangci.yml` and caches it);
  locally the script runs `golangci-lint run` itself. The gitops templates' smoke jobs run no lint, so for them the
  script only renders.
- **`devbox run ci` gets the lint tools from devbox** (`go`, `golangci-lint`, a JDK 21 and `maven` join the root
  `devbox.json`): the repo's rule is that devbox provides everything after `devbox install`, and a missing tool failing
  the run is better than a skipped lint that reaches CI. A missing tool still fails with a line that names it.
- **Environment-prefixed commands are allowed verbatim, per spec folder, at each session start**: unit mode rebuilds
  the allowlist before every unit session, so a command the plan unit committed is allowed from the next unit on.
- ADR: to be created with `cplat adr add parallel-unattended-runs-share-repo-slots-and-pause-at-the-usage-limit` (see
  the architect's report; this session had no shell to run it).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/usagelimit.py` | detect a usage-limit session, the reset time, the pause schedule and the stop | new |
| `scripts/cplat/run_slot.py` | repo slots: take (wait / no-wait), stale takeover, live holders | new |
| `scripts/cplat/envprefix.py` | find `NAME=value … devbox run …` commands in a spec folder's plan and design; allow or refuse | new |
| `scripts/cplat/land_resolve.py` | ADR index union + ADR renumbering; rule register union + `R<n>` renumbering | new |
| `scripts/cplat/budget.py` | `add_pause`; `used_of` and `_fold_previous` subtract paused minutes | changed |
| `scripts/cplat/preflight.py` | land allowlist: saved CI logs `Read` rule and `gh run view … --log-failed` | changed |
| `scripts/cplat/units.py` | `end_session(..., paused=True)` adds no stall | changed |
| `scripts/cplat/supervisor.py` | pause handling in unit mode | changed |
| `scripts/cplat/headless.py` | slot, pause in the legacy loop, `stop_of` "environment pause", allowlist with CI-log and env-prefix rules | changed |
| `scripts/cplat/land_merge.py` | `regenerate` uses `land_resolve` for the paths it handles | changed |
| `scripts/cplat/dispatch_cycle.py` | manual slot holders take free slots | changed |
| `scripts/cplat/dispatch_view.py` | `plan` and `status` show manual holders | changed |
| `scripts/template-lint.py` | render changed templates and run their smoke-job lint; uniform violation lines | new |
| `scripts/ci-local.sh`, `.github/workflows/ci.yml`, `devbox.json` | call the script; lint tools | changed |

## Contract

### Usage-limit pause (AC-184.1, AC-184.2, AC-184.3)

`usagelimit.py`:

```python
QUICK_SECONDS = 60                    # a session this short with no output is a pause (A1)
BACKOFF_MINUTES = (5, 10, 20, 40, 60) # then 60 for every further try (A2)
CAP_MINUTES = 360                     # all pauses of one run together (A3)
GRACE_SECONDS = 60                    # after a given reset time (A2)
STOP_PREFIX = "environment pause: usage limit resets at "

@dataclass(frozen=True)
class Hit:
    reset: datetime | None            # local, naive; None when no reset time was printed or the session was silent

def detect(output: str, seconds: float, ended: datetime) -> Hit | None
    # output: the session's text after its `===` header (headless.last_message); seconds: its wall time
    # Hit when the last non-empty line matches the limit message, or output.strip() == "" and seconds < QUICK_SECONDS

@dataclass(frozen=True)
class Pause:
    seconds: float                    # how long to sleep before the next session (0 with stop)
    line: str                         # printed before sleeping
    stop: str | None                  # the run's result when it must not wait (STOP_PREFIX + time or "unknown")

class Pauser:                         # one per run
    total_seconds: float              # pauses so far
    def pause(self, hit: Hit, now: datetime) -> Pause
    def resumed(self) -> None         # a session that was not a pause: the backoff starts again at 5
```

- **Limit message** (last non-empty line, case-insensitive): contains `usage limit`, `limit reached` or `hit your … limit`.
  Reset time, first match wins:
  - `|<unix seconds>` at the end of the line (`Claude AI usage limit reached|1763035200`), as local time;
  - `resets [at] [<Mon> <d>[,] [at]] <h>[:<mm>][am|pm] [(<IANA zone>)]` (`resets 3pm`, `resets 3:30pm (Europe/Berlin)`,
    `resets Nov 14 at 9am`): the first such moment at or after `ended`, converted from the zone (else local) to local.
    An unknown zone is read as local.
- **With a reset time**: wait until `reset + 60 s`. Line: `paused: usage limit, resumes at <YYYY-MM-DD HH:MM>`, the time
  printed being `reset + 1 minute`, local.
- **Without** (message without time, or silent): wait `BACKOFF_MINUTES[i]` (i = consecutive pause tries of this run,
  reset by `resumed()`; 60 after the fifth). Line: `paused: usage limit, next try at <YYYY-MM-DD HH:MM>` (now + wait).
- **Cap**: when `total_seconds + wait > CAP_MINUTES * 60`, `pause` returns `stop`:
  `environment pause: usage limit resets at <YYYY-MM-DD HH:MM>` (the reset itself, not +1) or
  `environment pause: usage limit resets at unknown`, and the run starts no further session.
- **After a session** (both drivers, in this order): `detect`; unit mode calls
  `units.end_session(..., paused=hit is not None)` (a checkpoint is recorded as today; without one a paused session adds
  no stall); the legacy loop does not compare a paused session's progress key and keeps `last`. On a hit:
  `budget.count_invocation(rid, -1)`; the session does not count toward `--max-runs`; `Pauser.pause`; print
  `Pause.line`; `headless.sleep(Pause.seconds)`; `budget.add_pause(rid, minutes)`; `--max-minutes`' `begin += pause`;
  then the loop top (quiet window, stop flag, budget) runs as before and starts the same unit (or prompt) again. A real
  escalation found after the session (`_escalated`, `describe_end`) still wins over a pause.
- **Stop**: result `environment pause: …`, exit 1, `HEADLESS <repo>: environment pause: …`. `headless.stop_of` maps it
  to `("environment", "escalated")`; the run record's escalation is `{"reason": <result>, "cause": "environment"}`; the
  dispatcher result has `cause: environment`. The ship state and the units file are **not** escalated, so the same command
  continues where the run stopped.
- A session that was not a pause calls `Pauser.resumed()`.

`budget.py`:

```python
def add_pause(run_id: str | None, minutes: float) -> None
    # data["current"]["paused_minutes"] += minutes on the run's ledger; never raises
```

`used_of` returns `minutes` = carried + (now − current.started_at) − current.paused_minutes (never below carried);
`_fold_previous` subtracts the folded root's `paused_minutes` the same way.

`units.py`:

```python
def end_session(repo: Path, command: str, spec_id: str, unit: str, before: str, paused: bool = False) -> dict
    # paused and no checkpoint: the unit goes back to "open", hold None; stalls and sessions unchanged
```

A checkpoint still sets `stalls` to 0 (`_checkpoint`), in both modes (A5); the 179 case (two empty sessions, then a
checkpoint) ends with the unit done and the run on the next unit, without an escalation.

### Repo slots (AC-184.8, AC-184.9)

`run_slot.py`:

```python
POLL_SECONDS = 15
ENV = "CPLAT_SLOT"                    # "<owner>/<name>#<n>" while held

@dataclass(frozen=True)
class Holder:
    slot: int
    command: str                      # the headless prompt, e.g. "/component:ship 182"
    pid: int
    since: str                        # "YYYY-MM-DD HH:MM", local
    checkout: str                     # absolute path of the holder's repo
    unit: str | None                  # CPLAT_DISPATCH_UNIT of the holder, None for a manual run

class SlotBusy(PlatformError): ...    # --no-wait and all slots taken

def total(repo: Path) -> int          # steering override, else .platform/dispatch.yml `slots`, else 1 (broken file: 1)
def holders(slug: str) -> list[Holder]  # live holders: JSON present and its pid running
@contextmanager
def held(repo: Path, command: str, *, wait: bool = True, say=print) -> Iterator[int | None]
```

- Files: `<state>/locks/<owner>__<name>.slot-<n>.lock` (flock) and `.slot-<n>.json` (`{command, pid, since,
  checkout, unit}`), `<state>` and the slug as for the merge lock (`dispatch_state.state_root`, `slug_of`).
- `held` tries slots 1..`total` with a non-blocking exclusive flock. On success: a left-over JSON whose pid no longer
  runs prints `freed a stale slot of <command> (pid <pid> gone)`; the JSON is written; `CPLAT_SLOT` is set in
  `os.environ`; on exit the JSON is removed, the flock released and `CPLAT_SLOT` restored.
- All taken, `wait=False`: raises `SlotBusy("slot busy: held by <command> (pid <pid>, since <since>, <checkout>)")`
  naming the oldest holder.
- All taken, `wait=True`: prints `waiting for a slot: held by <command> (pid <pid>, since <since>, <checkout>)` (oldest
  holder; again only when the named holder changes), polls every `POLL_SECONDS` through a module-level `sleep` tests
  replace, no time limit (A10).
- `os.environ[ENV]` already names this repo's slug: yields `None` at once, prints nothing.

`cplat headless`:

- Takes the slot after the `--dry-run` return and before `runlog.start` / `budget.open_root`; holds it until it returns.
  `--dry-run` takes none. Every other run takes one, fixes and legacy prompts included (A9).
- `--no-wait` with all slots taken: prints the `slot busy: …` line, exit 1, no run record, no session. (`--no-wait`
  keeps exit 3 for the quiet window.)
- Help text names the slot and `--no-wait`'s two meanings.

Dispatcher:

- `_schedule` and `_record`: the manual holders (`holders(slug)` with `unit is None`) count as running, so
  `free = total − dispatcher units running − manual holders`; no unit starts while that is 0.
- `plan --json` `slots` and `status --json` `slots` gain `"manual": [{"command", "pid", "since", "checkout"}]`; plan's
  `running` and `free` count them.
- Text (`plan` and `status`): `slots: <n> of <total> in use` counts them, and one line per manual holder:
  `  held by <command> (manual)  pid <pid>  since <since>  <checkout>`.

### Land allowlist (AC-184.4)

`preflight.run_allowlist(command, branches, log_dirs=())`: for `/component:ship` and `/system:ship` it adds, after the
land rules:

```
Read(<log dir>/**)                       one per entry of log_dirs
Bash(gh run view * --log-failed)
Bash(gh run view * --log-failed -R *)
Bash(gh run view * -R * --log-failed)
```

- `log_dirs` (from `headless`): the folder `cplat` saves failed-check logs in (spec 108, `quiet._log_path`):
  `${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/logs/<repo folder name>`, written `~/…` when under the home, else as `//<absolute path>`;
  for `/system:ship` also one per component clone of its plans.
- No other `gh run` or `gh api` rule; `refused_rules` is unchanged; `/component:build` gets none of these.
- `_self_check` also asserts that no refused rule matches a sample of the new rules.

### Environment-prefixed commands (AC-184.10)

`envprefix.py`:

```python
REFUSED_NAMES = ("PATH", "HOME", "SHELL", "ENV", "BASH_ENV", "NODE_OPTIONS", "PYTHONPATH")
REFUSED_PREFIXES = ("LD_", "DYLD_", "CPLAT_", "GIT_", "GH_")

def candidates(text: str) -> list[str]
    # every inline code span (`…`) whose first word has the form NAME=value and that has at least one more word
def verdict(command: str) -> str | None
    # None: allowed; else the reason (only for the caller's log; the block shows the command alone)
def commands(repo: Path, spec_ids: list[str]) -> tuple[list[str], list[str]]
    # (allowed, not allowed), each de-duplicated in order of appearance; read from the committed plan.md and design.md
    # of docs/specs/<id>/ at the feature head (units.feature_head), so an uncommitted edit allows nothing
```

- Allowed when all hold: every leading word is `NAME=value` with `NAME` matching `^[A-Z_][A-Z0-9_]*$`, not in
  `REFUSED_NAMES` and not starting with a `REFUSED_PREFIXES` entry; the words after them are `devbox run <script>
  [args]`; the command contains none of `;`, `&&`, `||`, `|`, `$(`, a backtick, or a newline.
- `cplat headless` for `/component:ship` and `/component:build` with specs appends `Bash(<command>)` for each allowed
  command (verbatim) to the run allowlist, and the allowlist block (also in `--dry-run`) gets one line per refused
  candidate after the `refused:` line: `not allowed: <command>`.
- Unit mode recomputes before each session; a command newly allowed prints `run allowlist: added <command>` once.

### Index conflicts on land (AC-184.6, AC-184.7)

`land_merge.regenerate` (unchanged steps: checks, fetch, `merge --no-ff --no-commit origin/<base>`, signed-off commit,
push without force, `await_head`, the round count) resolves each unmerged path:

1. a `GENERATED` file: as today;
2. `land_resolve.handles(path)` (`docs/adr/README.md`, or any `docs/rules/**.yml`): `land_resolve.resolve`;
3. any other path: `Unresolvable` as today, merge aborted.

After all paths: if a register file was resolved, `rulescheck.check(repo)` must be ok, else `Unresolvable` naming its
first failure. Every file written is `git add`ed (renames by `git mv`). The returned lines are the existing round line
plus one line per renumbering.

`land_resolve.py`:

```python
@dataclass
class Context:
    base: str                         # merge base of the branch head and origin/<base>
    ours: str                         # the branch head before the merge
    theirs: str                       # "origin/<base>"
    changed: list[str]                # git diff --name-only <base> <ours>: the files the branch changed
    next_adr: Callable[[], int]       # adr.next_number(repo) (cplat spec adr-next); called after each rename

@dataclass
class Outcome:
    lines: list[str]
    written: list[str]                # repo-relative paths to `git add`
    renamed: list[tuple[str, str]]    # (old, new) done with `git mv`

class Refused(Exception): ...         # str(e) = the reason; regenerate turns it into Unresolvable
def handles(path: str) -> bool
def resolve(repo: Path, path: str, ctx: Context, run) -> Outcome
```

**ADR index** (`docs/adr/README.md`):

- Rows are lines matching `^\| \[(\d{3,4})\]\((\d{3,4}-[^)]+\.md)\) \|`. Everything else (text, header row, separator) of
  the three stages is merged with `git merge-file` with the rows masked; a conflict there raises `Refused`
  ("docs/adr/README.md outside its table").
- Rows: the union of both sides keyed by the linked file; a row both sides changed differently from the base raises
  `Refused`; a row one side removed (and the other left as in the base) is dropped.
- Clash: a file the branch added (in `ours`, not in `base`) whose number `theirs` uses for a different file. For each
  (lowest first): `n = ctx.next_adr()`; `git mv docs/adr/<old>-<slug>.md docs/adr/<n>-<slug>.md`; in it, the title
  `# ADR-<old>` becomes `# ADR-<n>`; the row becomes `| [<n>](<n>-<slug>.md) | …`; in every file of `ctx.changed`
  (as now in the working tree, other than the ADR and the index) each `ADR-<old>` (not followed by a digit) and each
  `<old>-<slug>.md` becomes the new value.
- Rows are written sorted by number, in place of the stage's rows.
- Line per renumbered ADR: `renumbered ADR-<old> to ADR-<n> (<k> references)`, numbers 3-digit, `k` = occurrences
  replaced in the `ctx.changed` files (the ADR's own file and the index are rewritten but not counted).

**Rule register** (`docs/rules/**.yml`):

- A file is a header (lines before the first entry) and entries; an entry starts at a line `^\s*- id: (R\d+)\s*$` and runs to the
  next one or the end. A header that `git merge-file` cannot merge, or an item under `rules:` that does not start with
  `- id:`, raises `Refused` ("<path> outside its id-keyed entries"). `docs/rules/register.yml` (keyed by name, with the
  baseline) has no entries, so any conflict in it is refused.
- Entries: keyed by id. In base and changed on one side: that side's. Changed on both sides differently: `Refused`.
  Added on one side only: kept. Added on both with the same id and different text: the branch's entry gets
  `R<max+1>` (max over every id in the merged file); repeated per clash.
- Order: `theirs`' entries in their order, then the branch's added entries in its order.
- References: in every file of `ctx.changed` that is not under `docs/rules/`, each `R<old>` (word-bounded) becomes
  `R<new>`. Line: `renumbered R<old> to R<new> in <path> (<k> references)`, `k` excluding the entry's own `id:`.

### Template lint (AC-184.5)

`scripts/template-lint.py`:

```
uv run scripts/template-lint.py --changed [--base REF]    lint each template the branch changes (devbox run ci)
python3 scripts/template-lint.py <template> <rendered dir> lint one rendered project (the CI smoke jobs)
```

- `--changed`: templates `t` with a path `templates/<t>/…` in `git diff --name-only $(git merge-base <base> HEAD)` plus
  uncommitted tracked changes plus untracked files under `templates/`; `<base>` defaults to `origin/main`, else `main`.
  None: prints `template lint: no template changed`, renders nothing, exit 0.
- Render: `copier copy ./templates/<t> <tmp>/<t> --defaults --trust --skip-tasks` with the `--data` the template's CI
  smoke job passes (names prefixed `lint-` / `lint_`); `copier` from `PATH`, else `uv tool run --from copier copier`.
- Lint per template (the smoke jobs' lint, without `-q`):

  | Template | Commands |
  |---|---|
  | service-python, library-python | `uv run ruff check --output-format=concise .`; `uv run ruff format --check .` |
  | service-java | `mvn -B --no-transfer-progress spotless:check checkstyle:check` |
  | service-go | `golangci-lint run ./...` |
  | web-nextjs | `npx -y pnpm@11.22.0 install` (when `node_modules` is missing); `npx -y pnpm@11.22.0 lint` |
  | gitops-app, cluster-gitops | none: `template lint: <t>: rendered (its smoke job runs no lint)` |

- The tools' output is printed as it comes. On a failing command, one line per violation found in it:
  `<template>: <file>:<line>: <rule>: <message>` (`<line>` is `-` for a whole-file format finding), then
  `template lint: <template> failed: <n> violation(s)`; exit 1. Parsed forms: Checkstyle `[WARN] <file>:[<l>,<c>]
  (<group>) <Rule>: <msg>` (also `[ERROR]`/`[WARNING]`), Spotless's list of files (rule `spotless`), ruff concise
  `<file>:<l>:<c>: <CODE> <msg>`, ruff format `Would reformat: <file>` (rule `ruff-format`), golangci-lint
  `<file>:<l>:<c>: <msg> (<linter>)`, ESLint stylish (file line, then `<l>:<c> error|warning <msg> <rule>`). A failing
  command with no parsed line still fails and prints `template lint: <template> failed: <command> exited <code>`.
- Pass: `template lint: <template> passed`. A missing tool: `template lint: <template> needs <tool>, which is not on PATH`, exit 1.
- `scripts/ci-local.sh` runs `--changed` as its own step before the cplat tests. The CI smoke jobs call it in place of
  their ruff, `mvn -q … checkstyle:check` and `pnpm lint` lines; the `changes` filter of each smoke job includes the
  script.

## Decisions taken during the ship (2026-11-11, by the user's delegate)

- Existing tests whose fake `claude` ends at once without output (`test_headless.py`, `test_budget.py`, `test_headless_167.py`,
  `test_ship_escalate_rules.py`, `test_supervisor_131.py`, `test_units_131.py` and any other the full suite shows) now meet
  AC-184.2's pause. Their fakes print one line, as a real session always does; no test sleeps real time for a pause (the
  pause tests fake the clock and the sleep).
- The coders' exemption stays: a silent short session that moved the feature head, reached a checkpoint or changed the ship
  state is not a usage-limit pause.
- Frozen-test fixes approved: AC-184.7's `untouched.md` is created on `main` (not a branch file); AC-184.6's round-limit test
  puts the branch's ADR last so every move of `main` conflicts (a clean catch-up is not a resolution round); AC-184.1/2's
  escalation check compares `reason` and `cause` and allows `cause_source`.
- 2026-11-11 23:30: the full suite hung for over an hour on older tests whose silent fake now paused (the opt-in fixture was not
  used by 16 of them). `silent_sessions_are_not_pauses` is now autouse for every test except spec 184's own. Left for the
  verification fix round: `test_headless_131.py::test_every_session_gets_exactly_the_run_allowlist_and_the_refused_rules`
  (it must expect the CI-log read rules of AC-184.4 the way headless computes them) and
  `test_184_envprefix.py::test_a_command_the_plan_unit_commits_is_allowed_from_the_next_unit_on_and_announced_once_ac_184_10`
  (a command committed by the plan unit is not yet granted to the next units: a code fix).
