---
spec_id: 202-a-waiting-session-makes-no-model-calls
shape: platform
spec_hash: 5cbaedb2de55
summary: "A session waiting for its cplat wait may stop (no model calls); under cplat headless waits run detached, headless holds until they end and the next session gets their result; a transcript-based loop guard escalates idle sessions; pause reaches a session at its next stop"
tasks:
  - id: t1
    title: "Stop gates let a waiting or paused session stop without counting"
    files: [scripts/cplat/stopgate.py, scripts/cplat/ship.py, scripts/cplat/units.py, scripts/cplat/ship_handoff.py, scripts/cplat/appship_state.py, tests/cplat/test_171_stop_hook.py, tests/cplat/test_178_seam.py, tests/cplat/seam178_world.py, tests/cplat/test_200_gate.py, docs/specs/178-one-way-to-land-and-tests-that-do-not/spec.md]
    covers: [AC-202.1, AC-202.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "Detached waits under cplat headless and `cplat waits handover`"
    files: [scripts/cplat/waitdetach.py, scripts/cplat/cplat.py, plugins/shared/hooks/hooks.json]
    covers: [AC-202.2, AC-202.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: "Loop guard: idle calls and progress of one session from its transcript"
    files: [scripts/cplat/loopguard.py]
    covers: [AC-202.4, AC-202.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: "Dispatcher: guard policy keys, --loop-guard per unit, escalated and paused units in status, cause in needs"
    files: [scripts/cplat/dispatch_policy.py, scripts/cplat/dispatch_units.py, scripts/cplat/dispatch_view.py, scripts/cplat/dispatch.py, scripts/cplat/needs.py, tests/cplat/test_167_policy_plan.py]
    covers: [AC-202.5, AC-202.6, AC-202.7]
    parallel_safe: true
    depends_on: []
  - id: t6
    title: "Ship and unit instructions: stop while a background wait runs, act on its result"
    files: [plugins/component/commands/ship.md, plugins/component/references/unit-mode.md, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/references/unit-mode.yml]
    covers: [AC-202.2]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: "cplat headless: --loop-guard, hold for detached waits, guard in run_once, new stop reasons"
    files: [scripts/cplat/headless.py, scripts/cplat/supervisor.py]
    covers: [AC-202.3, AC-202.4, AC-202.5, AC-202.6, AC-202.7]
    parallel_safe: true
    depends_on: [t2, t3]
  - id: t7
    title: "Docs, ADR, changelog fragment and plugin versions"
    files: [docs/dispatch.md, docs/unattended-delivery.md, docs/adr/README.md, docs/changelog.d/750-waiting-session-makes-no-model-calls.fixed.md, .claude-plugin/marketplace.json, plugins/shared/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json]
    covers: [AC-202.1, AC-202.5]
    parallel_safe: true
    depends_on: [t4, t5]
---

# Plan — 202 A waiting session makes no model calls

The contract (hook lines, files, flags, policy keys, status and needs fields) is in [design.md](design.md). Level 1: t1, t2,
t3, t5, t6 at once; level 2: t4; level 3: t7.

## t1 — Stop gates let a waiting or paused session stop without counting

**Files:** scripts/cplat/stopgate.py, scripts/cplat/ship.py, scripts/cplat/units.py, scripts/cplat/ship_handoff.py, scripts/cplat/appship_state.py, tests/cplat/test_171_stop_hook.py, tests/cplat/test_178_seam.py, tests/cplat/seam178_world.py, tests/cplat/test_200_gate.py, docs/specs/178-one-way-to-land-and-tests-that-do-not/spec.md
**Covers:** AC-202.1, AC-202.7
**Goal:** the owning session of an unfinished ship run stops while one of its `cplat` waits runs, with the one-line
`systemMessage` of the design, and nothing is counted; a session whose checkout carries the dispatcher's stop flag stops at its
next stop attempt.

**Implementation notes:**
- `stopgate.check`: with `waiting`, return `Verdict("waiting", <prev count>, ", ".join(waiting))` and leave `st["stop_gate"]`
  as it is (do not write it); remove `wait_line`; add `waiting_message(label, waiting, where)` and `pause_requested(repo)`
  (`dispatch_state.stop_path(repo).exists()`, never raises).
- `ship.gate`: `pause_requested` first (before the `CPLAT_UNIT` branch too, so `units.gate` gets it; or check it in both), then
  the verdict; a `waiting` verdict returns the message and does not call `save_state`.
- `units.gate`: pause line, then the waiting line (`ship …` in a ship, `build … in unit <unit>` in a build); no hold written.
- `ship_handoff.gate` and `appship_state.gate`: a running wait lets the session stop with the line; the handoff file's `gate`
  and the system ship's `stop_gate` stay untouched.
- Existing tests that pin the AC-171.8 block move to the AC-202.1 behaviour: `test_171_stop_hook.py` (block, `waiting:` line,
  `wait_line`), `test_200_gate.py` (handoff block), and the AC-178.8 seam variant in `test_178_seam.py`/`seam178_world.py`
  (one stop let through, none blocked, count 0). The tests of marks, liveness and session filtering stay as they are.
- Add `- 2026-11-15 AC-178.8 variant "stops while its land waits" follows AC-202.1 (spec 202): the stop is let through, not counted (#750)`
  to the Changelog of spec 178's `spec.md` (design Decisions).

**Done when:** the AC-202.1 tests (including the 2026-11-14 replay: one stop, no blocked stop while a 60 s background
`ship land` runs) and the hook part of AC-202.7 (a looping fake session ends at its next stop after the pause) pass, and
`test_126*`, `test_171*`, `test_178*`, `test_200*` are green.

## t2 — Detached waits under cplat headless and `cplat waits handover`

**Files:** scripts/cplat/waitdetach.py, scripts/cplat/cplat.py, plugins/shared/hooks/hooks.json
**Covers:** AC-202.2, AC-202.3
**Goal:** a `cplat` wait started inside a `cplat headless` session survives the session's end, records its exit code and last
20 lines, and the next session of the checkout sees that result at its start.

**Implementation notes:**
- `waitdetach.py`: `WAIT_COMMANDS`, `wanted(argv)`, `front(argv) -> int` (start `[sys.executable, cplat.py, *argv]` with
  `start_new_session=True`, `CPLAT_WAIT_CHILD=<id>`, stdout/stderr to `<id>.log`; write `<id>.json`; stream the log; exit with
  the result's code; join a live wait with the same argv), `finish_child(id, code)` (write `<id>.result.json` from the log's
  tail), `alive`, `ended`, `stop`, `hold`, `handover_lines`, `main(argv)` for `cplat waits handover [--repo-dir DIR]`.
- `cplat.main`: before `_resolve`'s module runs, `if waitdetach.wanted(argv): return waitdetach.front(argv)`; when
  `CPLAT_WAIT_CHILD` is set, call `finish_child` in a `finally` with the exit code (also for `PlatformError` and crashes).
  Add `"waits": "waitdetach"` to `PLUMBING` and a docstring line.
- A test asserts every module calling `waits.record`/`waits.running` maps to a `WAIT_COMMANDS` entry (guards the list).
- `hooks.json` `SessionStart`: a second hook,
  `d="$(git rev-parse --git-dir 2>/dev/null)"; [ -n "$d" ] && [ -d "$d/cplat-waits/detached" ] || exit 0; exec "${CLAUDE_PLUGIN_ROOT}/bin/cplat" waits handover`,
  timeout 30.
- `hold(repo, limit_min=120, poll=5, clock=, sleep=)`: returns as soon as nothing is alive; at the limit stops the group and
  returns `Hold(done=False, command=…)`; `clock`/`sleep` are the seams tests replace.

**Done when:** the AC-202.3 tests on detach, result, `ended without a result`, handover output and the 120-minute stop pass
through `waitdetach` (the headless side follows in t4); a wait run outside `CPLAT_HEADLESS` behaves exactly as before.

## t3 — Loop guard: idle calls and progress of one session from its transcript

**Files:** scripts/cplat/loopguard.py
**Covers:** AC-202.4, AC-202.5
**Goal:** a pure, testable judge of "idle calls without progress" for one session, with the threshold parser.

**Implementation notes:**
- `DEFAULT = (10, 5)`, `CALLS = (3, 100)`, `MINUTES = (1, 60)`; `parse(text) -> (calls, minutes)` raising `PlatformError`
  with the design's message.
- `Guard(calls, minutes, repo, session_id, phase: Callable[[], str])`; `observe(now) -> str | None`; finds the transcript with
  `transcripts.find(session_id, runs_usage.projects_root())`, reads from its last offset (only complete lines), groups by
  `message.id`, applies the 3-second idle rule, the subagent and mark progress rules of the design.
- `mark(repo)`: `(git HEAD, ship phase, unit statuses)` from `ship.load_state` and `units.rows`, never raises.
- `reason(n)`: `looping: <n> model calls in <minutes> min without progress in phase <phase>` plus `; last message: <excerpt>`
  from `stopgate.last_message({"transcript_path": …})` and `stopgate.excerpt`.

**Done when:** unit tests of the guard with written transcripts pass: 10 one-line calls 1.5 s apart trip at the 10th; tool
calls every call for 15 min never trip; a commit or phase change resets the count; `parse` accepts `3/1` and `100/60` and
refuses `2/5`, `10/0`, `10/61`, `x`.

## t5 — Dispatcher: guard policy keys, --loop-guard per unit, escalated and paused units in status, cause in needs

**Files:** scripts/cplat/dispatch_policy.py, scripts/cplat/dispatch_units.py, scripts/cplat/dispatch_view.py, scripts/cplat/dispatch.py, scripts/cplat/needs.py, tests/cplat/test_167_policy_plan.py
**Covers:** AC-202.5, AC-202.6, AC-202.7
**Goal:** the policy carries `guard.loop_calls`/`guard.loop_minutes`, every unit's headless gets them, and status, inbox and
needs show a looping escalation and a paused unit as the design says.

**Implementation notes:**
- `dispatch_policy`: `guard` in `DEFAULTS` and `DEFAULTED_KEYS`; `_validate` with `_mapping("guard", …)` and `_int` ranges.
- `dispatch_units.headless_cmd`: `--loop-guard <calls>/<minutes>` after the budget args, before the prompt.
- `dispatch_view`: `_flat` lists `guard.*` leaves; `status_doc` adds `paused_at` to paused rows (ship phase from the
  worktree's ship state or the next open unit; last done unit's commit from `units.rows(worktree)`) and the `escalated` list
  of today; `render_status` prints both.
- `dispatch.py` `_pause` line: `running units stop at their next stop`.
- `needs._escalations`: `"cause"` on each item; `render` shows `(cause <cause>)`.
- `test_167_policy_plan.py` line 83: the expected default mapping gains `"guard": {"loop_calls": 10, "loop_minutes": 5}`.
- The day's budget needs no change: `_end` books the unit's tokens from the result file headless writes (AC-167.10).

**Done when:** the AC-202.5 dispatcher tests (plan shows defaults marked, bad values and keys refused by every dispatch
command, `--loop-guard` in the unit's command), the AC-202.6 tests (claim released, `needs-decision`, inbox/needs entry with
cause `platform`, status `escalated: looping`, report counts it, tokens booked) and the status part of AC-202.7 pass, with
`test_167*` and `test_176*` green.

## t6 — Ship and unit instructions: stop while a background wait runs, act on its result

**Files:** plugins/component/commands/ship.md, plugins/component/references/unit-mode.md, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/references/unit-mode.yml
**Covers:** AC-202.2
**Goal:** the session knows that it may end its turn while its background `cplat` wait runs, and that the next turn (the
wait's notification, or the `wait … ended` lines at the start of the next headless session) carries the result it acts on.

**Implementation notes:**
- `ship.md` line "**The Stop hook holds the session until the run is finished**; …": add that a stop while a `cplat` wait of
  this session runs is let through, and that its result (notification or the session's start lines) decides the next step as
  the phase says; reword so the file does not grow, since `cplat platform rules check` refuses prompts past the recorded size.
- `unit-mode.md` "Rules for every unit": one bullet: `wait <command> ended: …` lines at the start are the result of the wait
  the previous session started; act on them as your unit's phase says, never start the wait again for them.
- Register each new rule with its reason and source `spec 202` in the two `.yml` files; `cplat platform rules check` passes.

**Done when:** `cplat platform rules check` passes with the total prompt bytes at or below the baseline, and the AC-202.2
tests that read the instructions (if any) pass.

## t4 — cplat headless: --loop-guard, hold for detached waits, guard in run_once, new stop reasons

**Files:** scripts/cplat/headless.py, scripts/cplat/supervisor.py
**Covers:** AC-202.3, AC-202.4, AC-202.5, AC-202.6, AC-202.7
**Goal:** `cplat headless` makes no model call while a wait runs, starts the next session within 30 s of its end, exempts
such session ends from the no-progress and usage-limit rules, and stops and escalates a looping session.

**Implementation notes:**
- `--loop-guard` parsed with `loopguard.parse` right after `parse_args` (before the slot, the run record and any print), so
  a bad value starts nothing.
- `run_once(..., guard=None)`: `Popen` (same args, env, log, timeout); poll every 2 s, `guard.observe`; on a trip SIGTERM,
  SIGKILL after 10 s, return `LOOPED = 125`; the timeout path keeps returning 124.
- Both loops (`_drive`, `supervisor.drive`): after the pause check and before the budget checks, `waitdetach.hold`; print the
  design's lines; a limit hit escalates (`ship.escalate` when a ship state is open, else `units.escalate`) with cause
  `environment`, sets `state["cause"]`, ends with exit 1.
- After a session: `waited = bool(waitdetach.alive(repo))` (taken right when the process ended); `waited` → no usage-limit
  hit, `units.end_session(..., paused=True)`, and the legacy `key == last` check skipped.
- A guard trip: escalate with cause `platform` and the guard's reason, `state["cause"] = "platform"`, end with the reason as
  the result, exit 1, no new session.
- `stop_of`: `looping:` and `wait … still running after` → `("escalated", "escalated")`; the `finally` block passes
  `state["cause"]` as the escalation cause for both, so the run record and the dispatch result carry `platform`/`environment`
  (the platform cause files the deduplicated issue of spec 088).
- Phase for the reason: open ship state's phase, else `CPLAT_UNIT`/the unit, else the command's last word.

**Done when:** the AC-202.3 headless tests (no session while a 60 s detached wait runs, next session within 30 s naming the
result, no stall counted, 120-minute escalation, `ended without a result`), AC-202.4 (fake session looping every 1.5 s ends
after its 10th idle call, exit 1, `looping:` reason with cause `platform`; a tool-running fake runs 15 min untouched),
AC-202.5 (`--loop-guard` used and refused) and the headless part of AC-202.7 (no further session after the pause) pass, with
`test_*headless*`, `test_budget*`, `test_184*` and `test_178_seam.py` green.

## t7 — Docs, ADR, changelog fragment and plugin versions

**Files:** docs/dispatch.md, docs/unattended-delivery.md, docs/adr/README.md, docs/changelog.d/750-waiting-session-makes-no-model-calls.fixed.md, .claude-plugin/marketplace.json, plugins/shared/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json
**Covers:** AC-202.1, AC-202.5
**Goal:** the person can read the new behaviour and the `guard` keys, the decision is recorded, and the changed plugins
ship as new versions.

**Implementation notes:**
- Unless the orchestrator already created it, run
  `cplat adr add a-waiting-session-stops-and-its-wait-outlives-it --decision "A session may stop while its cplat wait runs; under cplat headless the wait runs detached, headless holds the next session until it ends and a loop guard escalates idle sessions"`
  (it writes the ADR file and its `docs/adr/README.md` row); fill in Status (supersedes ADR-093's blocking of the stop),
  Context (#750), Decision and Consequences from design.md.
- `docs/dispatch.md`: the `guard` keys with ranges and defaults, `escalated: looping`, what pause does now.
- `docs/unattended-delivery.md`: a waiting session stops; headless holds; the loop guard and `--loop-guard`.
- Fragment `750-waiting-session-makes-no-model-calls.fixed.md`: bold summary ending `(#750).`, then what was wrong and what
  happens now; "Update the plugins (`/plugin marketplace update`)".
- Versions: `shared` 1.4.0 → 1.5.0 (new SessionStart hook), `component` 1.21.0 → 1.22.0 (instructions), in both
  `plugin.json` and `marketplace.json`.

**Done when:** `devbox run validate`, the Markdown link check, `scripts/check-docs.py` and
`cplat platform pr-check --title "fix(headless): a waiting session makes no model calls" --body-file <body>` pass.
