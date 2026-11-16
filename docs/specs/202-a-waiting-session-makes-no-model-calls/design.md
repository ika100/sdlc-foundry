# Design — 202 A waiting session makes no model calls

## Decisions

- **A waiting session stops (AC-202.1, A1).** Every Stop gate (`ship.gate`, `units.gate`, `ship_handoff.gate`,
  `appship_state.gate`) lets the owning session stop while one of its `cplat` waits runs (`waits.live`, ADR-093's marks) and
  answers with one `systemMessage` line. The stop gate's counter (`stop_gate` / the handoff file's `gate`) is not written at
  all, so the count is exactly what it was before the wait. The block of ADR-093 and its `wait_line` go. ADR: to be created
  with `cplat adr add a-waiting-session-stops-and-its-wait-outlives-it` (supersedes ADR-093's "blocks the stop").
- **Under `cplat headless` every `cplat` wait runs detached from its session (AC-202.3, A2).** `claude -p` ends its
  background shells when it exits, so a wait the session started would die with it. `cplat.main` therefore re-runs a wait
  command, when `CPLAT_HEADLESS` is set, as a child in its own process group (`start_new_session`) that writes its output
  and result into the checkout's git dir; the calling process only streams the child's output and exits with its code.
  Detaching at the CLI entry (before any work) keeps every wait unchanged (non-goal: what a wait does) and cannot run a
  wait's side effects twice; detaching inside `waits.running` would. Outside `cplat headless` nothing is detached: an
  interactive Claude Code session keeps its background task and wakes on its end (AC-202.2).
- **The next session learns the result at its start (AC-202.3).** A `SessionStart` hook of the shared plugin runs
  `cplat waits handover`, which prints each ended detached wait of the checkout (exit code, last 20 lines) or `ended without
  a result`, and removes it. This reaches every kind of session (ship, build, fix, system ship) without changing their
  prompts; `cplat headless` prints the same line in its own output.
- **`cplat headless` holds before every session (AC-202.3).** Before it starts a session (also the first one of a restarted
  or resumed run) it waits, polling local files every 5 s and making no model call, while a detached wait of the checkout is
  alive. 120 minutes after the hold began, it stops the wait's process group and escalates with cause `environment`.
- **A session that ended while its wait ran is neither a stop without progress nor a usage-limit pause (AC-202.3).** Such a
  session is short and often silent, which spec 184's detector would read as a usage limit.
- **The loop guard reads the session's transcript (AC-202.4, A3).** `cplat headless` passes `--session-id`, so the
  transcript `<CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session>.jsonl` (ADR-035, `transcripts.find`) is known. Reading it
  keeps `--output-format text`, the log and `last_message` unchanged; switching to `stream-json` would change all three. The
  guard polls every 2 s while `run_once` waits on the process (now `Popen` instead of `subprocess.run`).
- **`<m>` in the reason is the configured window `loop_minutes`**, not the measured span, so the reason is the same for the
  same threshold; `<n>` is the number of idle calls counted (normally `loop_calls`).
- **`<phase>` in the reason:** the ship run's phase when a ship state is open; else the unit (`CPLAT_UNIT`) of a
  `/component:build` run; else the command's last word (`fix` for `/component:fix`).
- **Pause reaches the session through its Stop hook (AC-202.7, A8).** The dispatcher's existing stop flag
  (`<git dir>/cplat-dispatch-stop`, AC-167.11) is read by `ship.gate` and `units.gate` before anything else: the session may
  stop, nothing is counted. `cplat headless` already starts no session once the flag is set. A turn that runs tools is never
  interrupted, because only a stop attempt reads the flag.
- **The dispatcher passes the effective guard to every unit:** `headless_cmd` always adds `--loop-guard <calls>/<minutes>`
  (the defaults too), so a unit's guard never depends on how `cplat headless` defaults.
- **`status` keeps `phase: "paused"` in JSON** (AC-167.11's tests and readers) and adds the paused unit's real phase and last
  checkpoint in a new `paused_at` field; escalated units of today get a new `escalated` list (they hold no slot).
- **`cplat needs` escalation items gain `cause`** (the run record's `escalation.cause`), so AC-202.6's entry names it.
- **Departs from spec 178's AC-178.8 variant "the Stop hook must block the stop without counting it" (AC-171.8):** spec 202
  replaces AC-171.8, so the seam variant now asserts the AC-202.1 behaviour (the stop is let through and not counted); spec
  178's Changelog records it, as spec 171's does.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/stopgate.py` | `check` returns `waiting` without writing the count; `waiting_message`, `pause_requested` | changed |
| `scripts/cplat/ship.py`, `units.py`, `ship_handoff.py`, `appship_state.py` | the gates let a waiting or paused session stop | changed |
| `scripts/cplat/waitdetach.py` | wait commands, the detached child, its record and result, `hold`, `handover` | new |
| `scripts/cplat/cplat.py` | detach wait commands under `CPLAT_HEADLESS`; plumbing `waits` | changed |
| `scripts/cplat/loopguard.py` | `parse`, `Guard`: idle calls and progress of one session | new |
| `scripts/cplat/headless.py`, `supervisor.py` | `--loop-guard`, the hold, the guard in `run_once`, the new stop reasons | changed |
| `scripts/cplat/dispatch_policy.py`, `dispatch_units.py`, `dispatch_view.py`, `dispatch.py` | `guard.*`, `--loop-guard`, status | changed |
| `scripts/cplat/needs.py` | `cause` on escalation items | changed |
| `plugins/shared/hooks/hooks.json` | `SessionStart`: `cplat waits handover` | changed |
| `plugins/component/commands/ship.md`, `references/unit-mode.md` | a session may stop while its background wait runs and acts on its result | changed |

## Contract

### Stop hook answers (AC-202.1, AC-202.7)

Checked in this order by the gate of the owning session; each answer lets the session stop, writes no counter and
escalates nothing.

| Case | Gate | Answer (`{"systemMessage": …}`, one line) |
|---|---|---|
| dispatcher stop flag set in the checkout | `ship.gate`, `units.gate` | `ship <spec>: paused by cplat dispatch in phase <phase>; cplat dispatch resume continues it` (a build unit: `build <spec>: paused by cplat dispatch in unit <unit>; …`) |
| a wait of this session runs (`waits.live(repo, session)`) | `ship.gate`, `units.gate` (ship) | `ship <spec>: waiting for <command>[, <command>…] in phase <phase>` |
| same | `units.gate` (build) | `build <spec>: waiting for <command>[, …] in unit <unit>` |
| same | `ship_handoff.gate`, `appship_state.gate` | `ship <spec>: waiting for <command>[, …] in phase <phase>` |

`<command>` is the mark's command (`cplat component ship land`, `cplat pr wait 7 --merge`, …), oldest first. A running
background agent keeps its existing answer (`waiting for <n> background agent(s)`). With no wait and no flag, stops count as
in AC-126.4/AC-126.5. `stopgate.check(st, session, mark, running=0, waiting=None) -> Verdict` returns
`Verdict("waiting", <unchanged count>, "<commands>")` and leaves `st["stop_gate"]` untouched; `stopgate.wait_line` is removed;
`stopgate.waiting_message(label: str, waiting: list[str], where: str) -> dict` builds the line;
`stopgate.pause_requested(repo: Path) -> bool` reads `dispatch_state.stop_path(repo)`.

### Detached waits (AC-202.3)

Wait commands (argv after `cplat`, prefix match): `pr wait`, `component ship land`, `component ship wait`,
`system ship next` with `--wait`, `system wait`, `cluster wait`, `dispatch wait`, `component release wait`,
`component release gates` (`waitdetach.WAIT_COMMANDS`; a test asserts that every caller of `waits.record`/`waits.running` is
listed). Detached only when `CPLAT_HEADLESS` is set, `CPLAT_WAIT_CHILD` is not, and the working directory is in a git
checkout; otherwise the command runs in place as today.

Files, in `<git dir>/cplat-waits/detached/` (not matched by `waits.live`'s `cplat-waits/*.json`):

- `<id>.json` `{"id": str, "pid": int, "command": "cplat <argv>", "argv": [str], "session": str|null, "log": str, "started_at": ISO}`
  (written by the calling process right after the child starts; `pid` is the child, the leader of its process group).
- `<id>.log`: the child's stdout and stderr.
- `<id>.result.json` `{"id": str, "command": str, "code": int, "tail": [str] (last 20 non-empty lines), "ended_at": ISO}`
  (written by the child in `cplat.main`'s `finally`, `CPLAT_WAIT_CHILD=<id>` in its environment).

The calling process streams `<id>.log` to its stdout until the child ends, then exits with `code`; a child that ended
without a result: prints `wait <command> ended without a result`, exit 1. A live detached wait with the same `argv` in the
checkout is joined (its log streamed from the start) instead of starting a second one. Killing the calling process never
stops the child.

`waitdetach.alive(repo) -> list[Detached]`, `waitdetach.ended(repo) -> list[Ended]` (with `code`/`tail`, or `result: None`
when the child is gone without a result file), `waitdetach.stop(d)` (SIGTERM to the group, SIGKILL after 10 s),
`waitdetach.hold(repo, *, limit_min=120, poll=5, clock, sleep) -> Hold(done: bool, command: str|None)`.

### `cplat waits handover [--repo-dir DIR]` (AC-202.3)

Run by the shared plugin's `SessionStart` hook only when `<git dir>/cplat-waits/detached/` exists. For each ended detached
wait, oldest first, prints

```
wait <command> ended: exit <code> at <HH:MM:SS>; its last lines:
  <line>            (up to 20)
```

or `wait <command> ended without a result`, then removes its three files. A live one prints
`wait <command> is still running (pid <pid>)` and is kept. Nothing to report: no output. Always exit 0.

### `cplat headless` (AC-202.3, AC-202.4, AC-202.5, AC-202.7)

- `--loop-guard <calls>/<minutes>`: `calls` an integer 3..100, `minutes` an integer 1..60; default `10/5`. A bad value is
  refused before anything starts (no slot, no run record): `ERROR: --loop-guard: <value> is not allowed (allowed:
  <calls>/<minutes>, calls an integer 3..100, minutes an integer 1..60)`, exit 1.
- Before each session, while `waitdetach.alive(repo)` is not empty: prints once
  `waiting for <command> (pid <pid>, since <HH:MM:SS>): no session starts until it ends`; when it ends:
  `wait <command> ended: exit <code>` or `wait <command> ended without a result`; the next session starts within 30 s.
  After 120 min: stops it, escalates the ship run (or the units file) with cause `environment` and the reason
  `wait <command> still running after 120 min`, result line `HEADLESS <repo>: wait <command> still running after 120 min`,
  exit 1; the dispatch result has `cause: "environment"`, `stop_reason: "escalated"`.
- A session that ended while a detached wait of the checkout was alive: no stall (`units.end_session(..., paused=True)`), no
  `no progress` check of the legacy loop, no usage-limit pause.
- Loop guard trip: the session gets SIGTERM, SIGKILL after 10 s; the ship run (else the units file) escalates with cause
  `platform` and the reason

  ```
  looping: <n> model calls in <loop_minutes> min without progress in phase <phase>; last message: <≤200 chars, redacted>
  ```

  (`; last message: …` only when there is one; `stopgate.excerpt` of the transcript's last assistant text). No new session;
  `HEADLESS <repo>: looping: …`, exit 1; run record and dispatch result `stop_reason: "escalated"`, `cause: "platform"`.
- `stop_of`: a result starting `looping:` or `wait ` … `still running after` → `("escalated", "escalated")`.

### Loop guard rules (`loopguard.py`, AC-202.4)

`parse(text) -> (calls, minutes)`; `DEFAULT = (10, 5)`; `Guard(calls, minutes, repo, session_id, phase)`;
`Guard.observe(now) -> str | None` (the reason once tripped, then sticky). Each poll reads the transcript from its last
offset and groups assistant lines by `message.id`:

- a **call** is one main-chain message id (`isSidechain` lines and the `subagents/` files never count as idle);
- an **idle call** is a call none of whose lines holds a `tool_use` block, judged 3 s after its last line (so a text block
  followed by its `tool_use` is never idle);
- **progress** is a call with `tool_use`, a growing subagent transcript, or a change of the mark
  `(git HEAD of the checkout, ship phase, unit statuses of the units file)`;
- the guard trips when the idle calls after the last progress that started within the last `minutes` number `calls` or more.

No transcript yet (or none at all, e.g. a fake `claude`): no calls, never trips.

### `.platform/dispatch.yml` `guard` (AC-202.5)

```yaml
guard:
  loop_calls: 10      # an integer 3..100
  loop_minutes: 5     # an integer 1..60
```

Defaults are listed in `DEFAULTS` and `DEFAULTED_KEYS` (`guard.loop_calls`, `guard.loop_minutes`). Refusals, by every
`cplat dispatch` command (they all load the policy): `.platform/dispatch.yml: guard.loop_calls: 2 is not allowed (allowed: an
integer 3..100)`, `.platform/dispatch.yml: guard.<key>: unknown key (allowed: loop_calls, loop_minutes)`. `plan` text:
`  guard.loop_calls: 10 (default)`; `plan --json`: `policy.values.guard = {"loop_calls": 10, "loop_minutes": 5}`, both in
`policy.defaulted` when not given. `headless_cmd` adds `--loop-guard <calls>/<minutes>` before the prompt.

### `cplat dispatch status [--json]` (AC-202.6, AC-202.7)

- A paused unit's row keeps `"phase": "paused"` and adds `"paused_at": {"phase": <ship phase or unit id or null>,
  "checkpoint": <sha of the last done unit or null>}`; text: `paused (phase <phase>, checkpoint <sha7 or ->)` in the phase column.
- New top-level `"escalated": [{"unit", "item", "kind", "label", "cause", "reason", "ended_at", "log"}]`: units ended
  `escalated` or `stuck` today (`ds.today()`); `label` is `escalated: looping` when the reason starts with `looping:`, else
  `escalated: <cause>`. Text after the slots: `escalated today (<n>):` and per unit `  <unit>  <item>  <label>  <reason, one line>`.
- `cplat dispatch pause` prints `paused: nothing new starts; running units stop at their next stop`.

### `cplat needs --json` / `cplat dispatch inbox` (AC-202.6)

An `escalation` item gains `"cause": <escalation.cause or null>`; the text of `inbox` shows `(cause <cause>)` after the reason.

## Data

No new store. New files only under the checkout's git dir (`cplat-waits/detached/`); `.platform/dispatch.yml` gains the
optional `guard` mapping.
