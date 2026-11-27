# Design — 216 The system ship drives its repos without a model

## Decisions

- **Two new verbs, one new module** (A1). `cplat system ship drive` starts the driver; `cplat system ship wait` waits on
  it. The driver is `appship_driver.py`: the loop, its progress file, and three seams that tests replace: `spawn`,
  `alive` and `run_step`. `start` and `next --wait` stay as they are (non-goal, spec 194).
- **The driver runs `cplat` as a subprocess per step** (AC-216.2 to AC-216.4, AC-216.11). Each step is
  `[sys.executable, cplat.py, "system", "ship", "--repo", <gitops>, *argv]`. The driver reacts to the step's exit code
  and output, the same signals the session reacts to today, so the order of verbs is the order the rules prescribe and
  the log holds each step's output word for word. `run_step(gitops, argv) -> Step(code, out, err)` is the seam. The
  simulation (AC-216.11) replaces it with an in-process runner that calls `appship.main` with captured output (a
  `PlatformError` becomes `error: …` and exit 1, as `cplat.py` prints it), and it keeps today's fakes of `gh`, Argo CD
  (`ship.argo_health`), the repo sessions (`appship_proc.spawn`/`alive`) and the clock (`waits.now`/`sleep`). The suite
  then runs in seconds without network or cluster.
- **Detached as in spec 200, reusing its seams** (A2, note 4). `spawn` starts
  `cplat system ship --repo <gitops> drive --loop` (hidden flag) with `start_new_session=True`. Its log goes to
  `headless.log_dir(gitops)/<YYYY-mm-dd_HHMMSS>-system-ship-driver.log`. `alive(pid)` is
  `appship_proc.alive(pid, marker="drive")`. `appship_proc.alive` gets a `marker` keyword (default `"headless"`) for the
  reused-pid check, so one function serves both.
- **The driver's environment** (AC-216.1, AC-216.8). It copies the caller's environment, removes
  `CLAUDE_CODE_SESSION_ID`, `CPLAT_SESSION_ID`, `CPLAT_HEADLESS`, `CPLAT_SHIP_ANSWER` and `CPLAT_SHIP_ANSWER_FROM`, and
  sets `CPLAT_SYSTEM_DRIVER_RUN=<run id>`. Without a session id the driver claims nothing. Without `CPLAT_HEADLESS` its
  `next --wait` and `land` steps never detach under spec 202. `waits.running` writes `session: "driver:<run id>"` into
  its mark when `CPLAT_SYSTEM_DRIVER_RUN` is set, so the gate can tell the driver's waits from the session's.
  `appship_proc.spawn` removes `CPLAT_SYSTEM_DRIVER_RUN` from a repo session's environment. The `next --wait` and `land`
  steps keep recording their seconds into the system ship run through `waits.record`, as today. That is how the driver's
  waiting counts toward the run (AC-216.1). The session's `system ship wait` writes only a `waits.running` mark and no
  seconds, because the same seconds are already counted through the driver's steps.
- **Two files, two writers.** The system ship state (`cplat-app-ship.json`) gets one key, `driver`, written by `drive`
  under the state lock: `{pid, log, started, run_id, starts}` (AC-216.1). The driver's progress is in
  `<git dir>/cplat-app-ship-driver.json`, written only by the driver process (atomically: temporary file, then rename).
  That file outlives `finish`, which archives the state, so `wait` can still print `DONE:`.
- **The gitops entry ends the driver** (A3, AC-216.5). At the top of each loop turn, a repo of shape `gitops-app` in
  state `running` ends the driver with an `entry` end. After a `start` action the driver first runs `repo start` for
  every listed id, then ends the same way. So a `drive` run before the entry is built ends at once with the same
  `ENTRY:`, and a resumed run whose entry is running (AC-216.9) goes to the session too. Dependents wait through the
  scheduler, which is unchanged.
- **A stop rule ends the driver unescalated by the driver** (A4, AC-216.4). A publish that exits 1, and a `repo start`
  whose output contains `has uncommitted changes`, end the driver with a `stopped` end that holds that line. The driver
  adds no escalation. `wait` checks the `stopped` end before the escalation, so it prints `STOPPED:`. A red publish
  check is escalated by `cplat system ship publish` itself (cause `code`), today as with the driver. The spec's "the run
  stays unescalated" holds for the refusals (`_guard_clean`), not for a red check. The driver only does what today's
  session does, and changing `publish` is out of scope (non-goal: no new escalation texts).
- **The driver runs `finish`** (A5). The `done` end keeps the stdout of `complete` (the report) and the archive path
  that `finish` printed (`state archived to <path>`).
- **Early ends count as in spec 200** (A8, AC-216.6). `starts` in `state.driver` counts the starts since the last
  planned end. `drive` sets `starts = 1` for a new run id, or after a dead driver whose progress file (same pid) holds an
  end. Otherwise it sets `starts = previous + 1`. Above `MAX_STARTS = 2`, `drive` escalates instead of spawning. `wait`
  prints `ENDED:` for a dead driver without an end while `starts < 2`, and escalates otherwise. Both escalate with cause
  `environment` and the text `system ship driver ended twice in phase <phase>; log <log>`.
- **Resume uses only today's verbs** (AC-216.9). A run from today's flow has no `driver` key. Its first loop turn is
  `next --json`. Running repos give `wait`, and `next --wait` records the repos that finished (`repo result`). It
  restarts only dead sessions (`check_session`), so the driver adds no resume logic of its own.
- **The switch is read only by `drive`** (A9, AC-216.10). `CPLAT_SYSTEM_DRIVER=0` prints the off line before any other
  check. Any other value, or none, means on. Today's loop rules move word for word to
  `plugins/system/references/ship-loop.md`. `ship.md` reads it only after the off line, so the instructions read at the
  start shrink.
- **A person's answer to a held repo goes through the switch-off path.** The driver never asks (AC-216.2: resume or
  hold), and the session runs no `repo resume` with the driver on (AC-216.7). So a run whose repos wait for the person's
  answer would escalate again on every driver resume. `ship.md` therefore says: when the person wants to answer the
  questions an `ESCALATED:` listed, resume with `cplat system ship start <spec>` and then
  `CPLAT_SYSTEM_DRIVER=0 cplat system ship drive`, and follow `ship-loop.md`, whose `answer` rule asks and resumes. This
  is today's attended path (AC-186.12), unchanged.
- **The gate holds the owner on `system ship wait`** (AC-216.8). With `state.driver` set, `next_step` names
  `cplat system ship wait`. `_mark` adds the driver's step count, so a driver step is progress next to the repo states
  and clone commits it counts today. `gate` calls `waits.live(repo, session)`: a mark of another session, the driver's
  included, no longer lets the owner stop, while the owner's own wait still does (AC-202.1).
- ADR: "A system ship's mechanical loop runs in `cplat`", which amends ADR-082 (`cplat` counts the repo `TIMEOUT:`
  results) and ADR-086 (the driver starts the repo sessions). Its Consequences state the kill rule of AC-216.12. Task t4
  creates it with `cplat adr add`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/appship_driver.py` | `drive` (start, reuse, refusals, switch), the loop, the progress file, the seams `spawn`/`alive`/`run_step` | new |
| `scripts/cplat/appship_wait.py` | `system ship wait`: step lines, the result table below | new |
| `scripts/cplat/appship.py` | subcommands `drive [--loop]` and `wait [--timeout]`; the docstring | changed |
| `scripts/cplat/appship_proc.py` | `alive(pid, marker=…)`; `spawn` removes `CPLAT_SYSTEM_DRIVER_RUN` | changed |
| `scripts/cplat/waits.py` | `running`: the driver's session label | changed |
| `scripts/cplat/waitdetach.py` | `("system", "ship", "wait")` in `WAIT_COMMANDS` (spec 202: detached under `cplat headless`) | changed |
| `scripts/cplat/appship_state.py` | `next_step` with a driver, `_mark` with driver steps, `gate` filters waits by session | changed |
| `plugins/system/commands/ship.md`, `plugins/system/references/ship-loop.md` | session rules with the driver; today's loop for the switch | changed / new |

## Contract

### `cplat system ship drive` (AC-216.1, AC-216.10)

Run in the gitops repo (`--repo DIR`). The checks, in order:

| Condition | stdout | exit | effect |
|---|---|---|---|
| `CPLAT_SYSTEM_DRIVER` is `0` | `driver: off (CPLAT_SYSTEM_DRIVER=0); run phase repos in this session` | 0 | nothing |
| no state | `no system ship run in this repo; start one with /system:ship <spec>` | 1 | nothing |
| escalated | `phase <phase>: the run is escalated; resume it with /system:ship <spec>` | 1 | nothing |
| phase `plan` | `phase plan: plan the product first (/system:plan <spec>), then cplat system ship phase publish` | 1 | nothing |
| phase `done` | `phase done: the run is finished; cplat system ship finish` | 1 | nothing |
| a live driver of this run | `driver: pid <pid>, log <path>` then `next: cplat system ship wait` | 0 | nothing |
| `starts` would exceed 2 | the `ESCALATED:` block (below) | 1 | run escalated, cause `environment` |
| otherwise | `driver: pid <pid>, log <path>` then `next: cplat system ship wait` | 0 | spawned; `state.driver` written |

The phase, liveness and spawn steps run under the state lock, so two `drive` calls start one process. A failed spawn
(`OSError`) raises `PlatformError("cannot start the system ship driver: <error>")`, exit 1.

### The driver loop (`drive --loop`, AC-216.2 to AC-216.5)

Each step is logged as `=== HH:MM:SS cplat system ship <argv>`, then its stdout and stderr, then `=== exit <code>`. The
progress file gets the step `{at, argv, code: null}` before the step runs, and `code`, `line` (the first non-empty
output line) and `ended` after it.

```
loop:
  st = load_state(gitops)
  if no st or st.escalated or st.phase == "done": end()        # nothing left; wait reads the state
  if a gitops-app repo is running: end_entry(id, clone)
  phase publish:  r = step(publish); r.code == 0 → continue; else end_stopped(red line or first line of r)
  phase complete: complete_steps(phase_already_set=True)
  phase repos:    act(json(step(next --json)))

act(a):
  start:    for s in a.start: r = step(repo start s.id)
              r.code != 0 and "preflight failed:" in r → go on
              r.code != 0 and "has uncommitted changes" in r → end_stopped(that line)
              r.code != 0 otherwise → end() unless the run or that repo is now escalated (then go on)
            any s.entry → end_entry(entry id, its clone); else loop
  wait:     timeouts = 0
            repeat: r = step(next --wait --json)
              r.code == 0: action = json(r.out); a WAIT: line on stderr or action "wait" → timeouts = 0, again; else act(action)
              r.code == 2: timeouts += 1; at 3 → step(escalate '<that TIMEOUT line>' --cause environment); end()
              other → end()
  answer:   q = a.answer.questions
            a.answer.cause == "decision" and q and every q.suggested →
                step(repo resume <id> --answer '<q1.text>: <q1.suggested>; <q2.text>: <q2.suggested>…')    # A6
            else step(repo hold <id>)
            loop
  escalate: step(escalate '<reason of the first escalated repo in plan order>')   # no --cause: the repo's cause stays
            end()
  land:     twos = 0
            repeat: r = step(land)
              0 → complete_steps(); 1 → end(); 3 (WAIT:) → again
              2 → twos += 1; at 3 → step(escalate '<that TIMEOUT line>' --cause environment); end(); else again
  complete: complete_steps()
complete_steps(phase_already_set=False):
  unless phase_already_set: step(phase complete) (≠0 → end())
  r = step(complete); r.code != 0 → end()
  f = step(finish); end_done(report = r.out lines, archive = path from "state archived to <path>")
```

`end()` writes no end record. The wait then reads the state: escalated, or `ENDED:`. Every other `end_*` writes the end
record and exits 0.

### The progress file `<git dir>/cplat-app-ship-driver.json`

```json
{"spec": "<spec id>", "run_id": "<run id>", "pid": 4242, "log": "<path>", "started": "<iso>",
 "steps": [{"at": "<iso>", "argv": ["next", "--wait", "--json"], "code": 0, "line": "action: start", "ended": "<iso>"}],
 "end": null | {"kind": "entry", "id": "<repo id>", "worktree": "<path>", "at": "<iso>"}
            | {"kind": "stopped", "line": "<the rule's line>", "at": "<iso>"}
            | {"kind": "done", "report": ["<line>", …], "archive": "<path>", "at": "<iso>"}}
```

The driver replaces the file at its start (its own pid, no steps) and rewrites it after each step. While a state with
`driver` exists, a file whose `pid` is not `state.driver.pid` is ignored: no steps yet, no end. Without a state (after
`finish`), the file is read as it is.

### `cplat system ship wait [--timeout T]` (AC-216.6)

Default `T = 540`. It polls every 5 s (`waits.now`/`waits.sleep`), with a fixed deadline, and returns by `T + 10` s at the
latest. For each step that ended since the call began, it prints one line:
`HH:MM:SS driver: cplat system ship <words up to the first option> -> exit <code>`. Reasons and answers are left out.
For `escalate` only the verb is printed. Each poll checks the following in order; the first match is the single result:

| # | Condition | Exit | Output |
|---|---|---|---|
| 0 | a state without `driver`; or no state and no progress file with a `done` end | 1 | `no driver recorded for this system ship run; start it with cplat system ship drive` (at once) |
| 1 | progress file end `done` | 0 | `DONE: product ship <spec> is done`, then the `report` lines verbatim, then `archive: <path>` |
| 2 | end `stopped` | 1 | `STOPPED: <line>` |
| 3 | state escalated | 1 | the `ESCALATED:` block |
| 4 | end `entry` | 0 | `ENTRY: <id> in <worktree>`, then `next: build it as references/ship-entry.md says, then cplat system ship drive` |
| 5 | `alive(pid)` is false, no end, `starts < 2` | 1 | `ENDED: driver ended in phase <phase>; log <path>`, then `next: cplat system ship drive` |
| 6 | `alive(pid)` is false, no end, `starts >= 2` | 1 | escalate (cause `environment`, text above), then the `ESCALATED:` block |
| 7 | deadline, with a step started or ended, or a change in `_mark(st)["phase"]`, during the call | 0 | `WAIT: driver still going, progress in the last <T>s; run the same wait again` |
| 8 | deadline, nothing changed | 2 | `TIMEOUT: system ship <spec> in phase <phase>, no driver step for <waits.duration(now − last step at)>; log <path>` |

The `ESCALATED:` block (`appship_wait.escalated_lines(st)`):

```
ESCALATED: product ship <spec>: <st.escalated> (cause <st.cause or unknown>)
<repo id>: question: <text> (suggested: <s> | no suggestion)      # one line per question of each escalated repo
<appship_report.state_table(st) lines>
log: <driver log>
resume it with /system:ship <spec>
```

The wait runs inside `waits.running("cplat system ship wait", gitops)`, so the owner's stop passes while it runs
(AC-202.1). Under `cplat headless` it detaches like the other waits (spec 202).

### Stop hook (AC-216.8)

`appship_state.next_step(st)`, when `st.driver` is set and the phase is not `done`:
`` `cplat system ship wait`, then act on its result as /system:ship says ``. `_mark(st)["phase"]` gets
` driver <n>`, where n is the number of ended steps in the progress file (pid matched). `gate` passes the hook's
session to `waits.live`. Ownership, the two-stop escalation and the non-owner silence are unchanged.

### `status --json`

The state already holds `driver`. `status --json` adds `driver_progress`: the progress file, or `null`.

## Prompt rules (t4)

`ship.md`, after phase `plan`: `cplat system ship phase publish`, `cplat system ship drive`.

- A `driver: off` line: read `${CLAUDE_PLUGIN_ROOT}/references/ship-loop.md` and follow it.
- Otherwise run `cplat system ship wait` and act on the result:
  - `WAIT:` or `TIMEOUT:`: run the same wait again. After three `TIMEOUT:` in a row (a `WAIT:` resets the count), run
    `cplat system ship escalate '<the TIMEOUT line>' --cause environment`.
  - `ENTRY:`: build the entry with `ship-entry.md`, then run `drive`.
  - The first `ENDED:`: run `drive`.
  - `DONE:`: print the report.
  - `ESCALATED:` or `STOPPED:`: print the result.
  - After `DONE:`, `ESCALATED:` and `STOPPED:`, the hand-over.
- The verbs that only the driver runs are listed once, with their reason: the driver applies those rules, and a second
  actor would race it on the state.
- The attended answer sentence (Decisions).

`ship-loop.md` holds today's Phase `publish`, Phase `repos` and Phase `complete` text. Their register entries move to
`docs/rules/plugins/system/references/ship-loop.yml`, keeping their ids, classes and sources. The prompts in total stay
within `baseline.prompt_bytes`, and `ship.md` ends shorter than before this change (AC-216.7).

## Data

- `cplat-app-ship.json`: new key `driver` (`{pid, log, started, run_id, starts}`).
- New file `<git dir>/cplat-app-ship-driver.json` (above). Never committed. Each new driver replaces it at its start.
