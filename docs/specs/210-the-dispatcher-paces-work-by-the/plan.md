---
spec_id: 210-the-dispatcher-paces-work-by-the
shape: platform
spec_hash: e7d75da9c63a
summary: The dispatcher budgets in USD (mode cost, default) or by the subscription's 5-hour and weekly percentages from a status line sensor (mode plan), with a filler queue before the weekly reset
tasks:
  - id: t1
    title: Policy keys budget.mode, usd caps and budget.plan with validation and filler matching
    files: [scripts/cplat/dispatch_policy.py, tests/cplat/test_167_policy_plan.py, tests/cplat/test_dispatch_view.py]
    covers: [AC-210.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Usage store, status line sensor and sensor install/remove verbs
    files: [scripts/cplat/usage_sensor.py, scripts/cplat/usage_readings.py, scripts/cplat/dispatch_sensor.py, scripts/cplat/dispatch.py]
    covers: [AC-210.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Record usage-limit hits and the run's USD cost in headless and supervisor
    files: [scripts/cplat/usagelimit.py, scripts/cplat/headless.py, scripts/cplat/supervisor.py]
    covers: [AC-210.3, AC-210.8]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t4
    title: USD ledger per unit and agent call, month sums, booked-token tape, USD history hint
    files: [scripts/cplat/dispatch_budget.py, scripts/cplat/dispatch_agent.py]
    covers: [AC-210.2, AC-210.3, AC-210.4]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t5
    title: Plan-mode pace (readings, estimate, calibration, limit hold, bands, filler window)
    files: [scripts/cplat/dispatch_pace.py]
    covers: [AC-210.6, AC-210.7, AC-210.8, AC-210.9]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t6
    title: One ordered start gate with plan and cost documents, needs, hints and warnings
    files: [scripts/cplat/dispatch_gate.py]
    covers: [AC-210.3, AC-210.4, AC-210.6, AC-210.7, AC-210.8, AC-210.10]
    parallel_safe: true
    depends_on: [t1, t4, t5]
    done: true
  - id: t7
    title: Filler candidates (filler-only split, filler tasks, retro proposals) and the retro-draft hold
    files: [scripts/cplat/dispatch_filler.py, scripts/cplat/dispatch_backlog.py, scripts/cplat/dispatch_ready.py]
    covers: [AC-210.9]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t8
    title: Task and draft unit kinds and the hidden dispatch task verb
    files: [scripts/cplat/dispatch_units.py, scripts/cplat/dispatch.py]
    covers: [AC-210.9]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t9
    title: plan and status show the plan or cost line, held reasons, hints and warnings
    files: [scripts/cplat/dispatch_view.py, tests/cplat/test_dispatch_view.py]
    covers: [AC-210.2, AC-210.4, AC-210.10]
    parallel_safe: true
    depends_on: [t6]
    done: true
  - id: t10
    title: The cycle applies the gate, the pace band and the filler queue
    files: [scripts/cplat/dispatch_cycle.py]
    covers: [AC-210.2, AC-210.3, AC-210.4, AC-210.6, AC-210.7, AC-210.8, AC-210.9, AC-210.10]
    parallel_safe: false
    depends_on: [t6, t7, t8, t9]
    done: true
  - id: t11
    title: Document the two budget modes, the sensor and the filler queue; changelog fragment
    files: [docs/dispatch.md, docs/changelog.d/210-dispatcher-budgets-by-plan-or-cost.added.md]
    covers: [AC-210.1, AC-210.5]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 210 The dispatcher budgets by plan limits or by cost

The contract (policy keys and errors, usage files, sensor, pace rules, gate order, JSON and text, filler and the new
unit kinds) is in [design.md](design.md). Read it before any task. No agent prompt, command, plugin or template
changes, so there is no plugin version bump and no rules-register entry. Every new module has a docstring header in
the style of `dispatch_budget.py` (what it exports, one line each). All dispatcher clocks go through
`dispatch_state.now()`. Usage files go through `usage_readings` (never written by hand elsewhere).

Levels: t1, t2, t11 → t3, t4, t5, t7, t8 → t6 → t9 → t10.

## t1 — Policy keys budget.mode, usd caps and budget.plan with validation and filler matching

**Files:** scripts/cplat/dispatch_policy.py, tests/cplat/test_167_policy_plan.py, tests/cplat/test_dispatch_view.py
**Covers:** AC-210.1
**Goal:** the policy file accepts and validates the new keys exactly as design.md "Policy" states. `start` and `resume`
refuse mode cost without a daily limit, naming `budget.usd_per_day`.

**Implementation notes:**
- `DEFAULTS["budget"]` becomes `{"mode": "cost", "usd_per_day": None, "usd_per_month": None, "tokens_per_day": None, "per_unit": {}, "plan": None}`.
  `PLAN_DEFAULTS = {"weekly_target": 0.92, "window_stop": 0.80, "filler_only": ["priority:P2", "label:enhancement"], "filler_tasks": [], "filler_drafts": True}`
  is filled in only in mode plan.
- Add `_usd(key, v)`: a finite number > 0, not bool. Add `_share(key, v)`: a number 0.50..1.00. Add `_filler_only`:
  `label:<name>` or `priority:P0|P1|P2`, empty list allowed. Add `_filler_tasks`: a list of mappings with keys
  `name, command`, both non-empty strings, names unique. `filler_drafts` is a bool.
- In mode cost, a `budget.plan` key fails with `<key>: needs budget.mode: plan` (the first `budget.plan.<k>` given, or
  `budget.plan` itself).
- `DEFAULTED_KEYS` gains `budget.mode`. In mode plan, `defaulted` also lists `budget.plan.<k>` for each default taken
  (compute it in `load`, not as a static tuple). `_given` must treat a `None` USD value like a missing one, as it does
  for `tokens_per_day`.
- `unset` is `["budget.usd_per_day"]` in mode cost when that key is None, else `[]`.
- `require_budget` refuses only mode cost with neither `usd_per_day` nor `tokens_per_day`, with the exact message and
  hint of the design. The message names both keys, so the old check for `budget.tokens_per_day` in the error still
  holds.
- Add `USD_DAY_KEY`, `USD_MONTH_KEY`, `MODE_KEY` constants. Add `mode(policy) -> str`, which reads
  `values["budget"].get("mode", "cost")`, so hand-built `Policy` objects in tests work. Add
  `filler_match(policy, labels) -> bool` as the design states (use `priority.most_urgent`).
- Tests that pin AC-167.1/AC-167.2 behaviour now replaced by AC-210.1/AC-210.2: in `test_167_policy_plan.py`, the
  `unset` assertions become `["budget.usd_per_day"]`, including the file case that sets only `tokens_per_day`. In
  `test_dispatch_view.py`, the `unset` assertion changes the same way. Mark each changed line `# replaced by AC-210.2`.
  Change nothing else in those files.

**Done when:** the acceptance tests for AC-210.1 that exercise validation and the `start`/`resume` refusal pass. The
existing `test_167_*`, `test_dispatch_*` and `test_202_dispatch.py` stay green.

## t2 — Usage store, status line sensor and sensor install/remove verbs

**Files:** scripts/cplat/usage_sensor.py, scripts/cplat/usage_readings.py, scripts/cplat/dispatch_sensor.py, scripts/cplat/dispatch.py
**Covers:** AC-210.5
**Goal:** `cplat dispatch sensor install` makes every interactive session record the subscription's two windows. An
earlier status line keeps printing exactly what it printed, and `sensor remove` restores it.

**Implementation notes:**
- `usage_sensor.py` imports only the stdlib. It holds:
  - `usage_dir()`, `lock()`, `write_json_atomic()` and `record(payload: dict, now: float)`: the readings rules of the
    design (last, history on change or after 10 min, 7-day trim, a window missing from the input left alone);
  - `main()`: read stdin, record (`CPLAT_SENSOR_NOW` overrides the time), chain the earlier command from `sensor.json`
    (`sh -c`, same stdin bytes, 10 s timeout, stdout bytes written unchanged), else print the short `5h … · 7d …`
    line. It swallows every error and exits 0.
- `usage_readings.py` imports `usage_sensor` for the paths, lock and atomic write. It exports `readings()`,
  `append_booked(tokens, at=None)`, `booked_between(t0, t1)`, `record_limit(until, reset_known, message, at=None)`,
  `limit()` and `any_reading_since(epoch)`. The tape keeps 8 days and is rewritten at most once per local day. Every
  reader returns empty values on a missing or broken file and never raises.
- `dispatch_sensor.py`: `install()` and `remove()` as the design states. The settings path is
  `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`. Write the settings back with `indent=2` and the other keys
  untouched, and copy the sensor with `shutil.copyfile`.
- `dispatch.py`: add a `sensor` verb with a positional `action` (`install` | `remove`). It needs no policy file and no
  git repo (`--repo` accepted and ignored). Add one line to the module docstring.

**Done when:** the acceptance tests for AC-210.5 pass. They feed fixture status line inputs to the installed command,
with `HOME`, `XDG_STATE_HOME` and `CLAUDE_CONFIG_DIR` in a temp dir, and need no network. `plan` showing the reading is
checked in t9/t10. The existing `test_dispatch_*` tests stay green.

## t3 — Record usage-limit hits and the run's USD cost in headless and supervisor

**Files:** scripts/cplat/usagelimit.py, scripts/cplat/headless.py, scripts/cplat/supervisor.py
**Covers:** AC-210.3, AC-210.8
**Goal:** every limit message a run sees reaches `usage/limit.json`, and the dispatcher's result file carries the run's
USD cost.

**Implementation notes:**
- `usagelimit.Hit` gains `message: str | None = None`. `detect` sets it to the last line when `_MESSAGE` matched, and
  leaves it None for a silent short session.
- Add `usagelimit.record(hit, ended)`: when `hit.message`, call
  `usage_readings.record_limit(until=hit.reset or ended + 60 min, reset_known=hit.reset is not None, message=hit.message[:300])`.
  It never raises. Call it in `headless._drive` and `supervisor.drive` right after a hit is accepted (before the pause
  sleep).
- `headless.run_cost(rid)`, next to `run_tokens`, returns `totals.cost_usd` when the section is complete and
  `cost_complete` is true, else None. Write `cost_usd` into the dispatch result record next to `tokens`, on both paths
  (the exception path and the `finally` path).

**Done when:** a module-level test shows that a limit message with and without a reset time writes `limit.json` with
the right `until`, that a silent session writes nothing, and that the result file has `cost_usd`. The existing
`test_headless_131.py`, `test_184_*` and `test_supervisor*` tests stay green. AC-210.8 passes end to end after t10.

## t4 — USD ledger per unit and agent call, month sums, booked-token tape, USD history hint

**Files:** scripts/cplat/dispatch_budget.py, scripts/cplat/dispatch_agent.py
**Covers:** AC-210.2, AC-210.3, AC-210.4
**Goal:** the dispatcher knows, per repo, the USD spent today and this month by its units and agent calls. Every token
it books is also on the machine-wide tape.

**Implementation notes:**
- Refactor `_peek` into `_peek_section(run_id)`, and add `unit_usage(unit, result) -> (tokens|None, usd|None)`:
  - a running unit gives tokens and USD from the same section;
  - an ended unit gives `result.tokens`/`result.cost_usd`, else the unit file's, else the record's
    `usage.totals.cost_usd` when `cost_complete`.
  `unit_tokens` stays as a thin wrapper.
- `book` books the growth of tokens (as now) and of USD (`counted_usd`, `ledger[day].usd`) in one pass. It marks
  `unknown_usd[unit] = day` like `unknown`, and appends the total token growth of the pass to the tape
  (`usage_readings.append_booked`).
- `Usage` gains `usd`, `month_usd` (the ledger days of the local month) and `unknown_usd`. `usage_today` fills them too.
- `book_agent(slug, tokens, cost_usd=None, model=None)`: it keeps the old positional call working, books
  `agent_usd`, and appends the tokens to the tape. The cost is `cost_usd` when given, else priced from tokens (as
  input) with the price table. With no tokens either, it uses the ceiling rule of the design.
- `dispatch_agent.ask` returns `(text, tokens, cost_usd, model)`. `cost_usd` is the answer's `total_cost_usd` when it
  is numeric. `premise`/`mode` results gain `cost_usd` and `model` (0.0 for a cached answer).
- `history_hint` entries gain `usd` (the sum of `usage.totals.cost_usd`, or None when a record has
  `cost_complete: false`).
- Remove `budget_need`, `reached` and `limit_of` from `__all__` only if nothing else uses them. `dispatch_cycle` and
  `dispatch_view` still call them until t9/t10, so keep them working.
- Read policy values with `.get` so the hand-built `Policy(values={"budget": {...}})` of `test_dispatch_budget.py`
  keeps working.

**Done when:** module-level tests of USD booking (unit growth, agent call with/without `total_cost_usd`, an unpriced
model marked unknown, month sum across days) pass, and `test_dispatch_budget.py` and `test_dispatch_agent.py` stay
green.

## t5 — Plan-mode pace (readings, estimate, calibration, limit hold, bands, filler window)

**Files:** scripts/cplat/dispatch_pace.py
**Covers:** AC-210.6, AC-210.7, AC-210.8, AC-210.9
**Goal:** a pure decision from the usage files and the policy: the windows, their source, the hold, the band and
whether the filler window is open.

**Implementation notes:**
- `pace(policy, now: datetime, readings=None, tape=None, limit=None) -> Pace`, with `Pace` and `Window` dataclasses as
  in design.md. The three inputs default to `usage_readings.readings()`, `usage_readings.booked_between` and
  `usage_readings.limit()`, so tests can pass fixtures.
- Implement exactly the window steps 1 to 4, the decision table rows 1 to 5, `max_running`, `filler`, `source`,
  `read_at` and the number and time formats of the design. Stale means older than 30 minutes.
- Add `fmt_pct(x)` and `fmt_when(dt, now)`, which t6 and t9 use.
- Add `doc(pace, policy) -> dict`, the `plan` JSON object of the design. `stop` and `target` are percentages.
- No I/O beyond the three defaults, and no import of dispatcher modules except `dispatch_policy` and `usage_readings`.

**Done when:** module-level tests reproduce the examples of AC-210.6 (83/79 % window, 50/43/30/92 % week at 50 %
elapsed), AC-210.7 (43.5 %, reset passed counts from 0 %, no calibration gives unknown) and AC-210.8 (limit with and
without reset time, a lower later reading does not lift it).

## t6 — One ordered start gate with plan and cost documents, needs, hints and warnings

**Files:** scripts/cplat/dispatch_gate.py
**Covers:** AC-210.3, AC-210.4, AC-210.6, AC-210.7, AC-210.8, AC-210.10
**Goal:** a single function that every caller asks whether starts are allowed, how many may run, whether the filler
window is open, and what `plan`/`status` print about the budget.

**Implementation notes:**
- `gate(slug, policy, state, usage, *, now=None) -> Gate` in the order of the design. In mode plan it calls
  `dispatch_pace.pace` once.
- `cost_doc(usage, policy)`: the `cost` object, with amounts rounded to 2 decimals.
- `needs`: the table of the design. The `since` of each id is kept in `state.budget_since[id]` through
  `dispatch_state.update` (the old day keys stay valid).
- `hints`: through `usage_readings.any_reading_since(now − 7 d)` and `os.environ.get("ANTHROPIC_API_KEY")`.
  `warnings`: the `tokens_per_day` text.
- Text constants for every `why_not` and text in one place, which t9 and t10 import.

**Done when:** module-level tests cover the order (pause before plan, plan before USD caps, USD daily before monthly
before tokens), each need id, both hints and the warning. AC-210.3/4/6/7/8/10 pass end to end after t10.

## t7 — Filler candidates (filler-only split, filler tasks, retro proposals) and the retro-draft hold

**Files:** scripts/cplat/dispatch_filler.py, scripts/cplat/dispatch_backlog.py, scripts/cplat/dispatch_ready.py
**Covers:** AC-210.9
**Goal:** the cycle can ask which filler work exists right now, and a retro draft can never be self-approved.

**Implementation notes:**
- `dispatch_filler.split(policy, ready_verdicts, filler_open) -> (regular, filler_only, held)`. Outside the window a
  matching verdict is held with reason `filler only`, detail None.
- `dispatch_filler.extra(repo, slug, policy, snap, state, window_id, *, want_drafts: bool) -> list[Candidate]`: the
  tasks, then at most one draft candidate, as the design states. `window_rollover(slug, window_id)` resets `tasks` and
  `drafts` when the window changes.
- Parse the retro body with the two regexes of the design. Tolerate a missing section (no proposals) and a gh failure
  (raise `PlatformError`, which the cycle records as `unavailable["retro"]`).
- "Answered" checks:
  - `state.filler.drafted`;
  - `snap.specs` and `snap.drafts` (tracks `N` and the same normalised title);
  - one `git grep -l -E "^tracks:.*\b<N>\b" origin/main -- 'docs/specs/*/spec.md'`, then the titles of those files
    (covers done specs);
  - open PR titles.
- `dispatch_backlog.PR_FIELDS` gains `title`.
- `dispatch_ready.judge`: a draft spec candidate that tracks an open issue titled `^Weekly retro \d{4}-W\d{2}$`, or
  whose `feature/<id>` branch is in `state.filler.drafted`, is held `needs-approval` with detail
  `a retro draft: approve it yourself`, before `_approval`.

**Done when:** module-level tests cover the split inside and outside the window, task once per window, the draft limit
of 3, answered proposals skipped, and the retro-draft hold with `gates.approve_specs: self`. `test_dispatch_ready.py`,
`test_dispatch_backlog.py` and `test_167_ready_order.py` stay green.

## t8 — Task and draft unit kinds and the hidden dispatch task verb

**Files:** scripts/cplat/dispatch_units.py, scripts/cplat/dispatch.py
**Covers:** AC-210.9
**Goal:** a filler candidate can be started, observed and ended like any unit, without ever being landed.

**Implementation notes:**
- `start`, for `task` and `draft`:
  - no claim, and a detached worktree at `origin/main` (`git worktree add --detach`);
  - `branch` None, `tracks` [];
  - unit fields `command` (task), and `retro_issue` and `request` (draft);
  - the run section `dispatch.kind` is the kind;
  - the start line ends in `(filler)`.
- `headless_cmd`: a draft runs `cplat headless --repo <wt> [--budget …] --loop-guard … "<text>"`. Add
  `task_cmd(unit, repo)` = `[python, cplat.py, "dispatch", "task", <unit>, "--repo", <repo>]`, and use it in `spawn`
  for kind `task`.
- `run_task(repo, slug, unit_id) -> int`: run `sh -c` in the worktree with the timeout of the design, and write the
  result file (`tokens: 0`, `cost_usd: 0.0`). `alive` also accepts `dispatch task` in the command line.
- `_classify`: `task` → done/escalate from the result; `draft` → the branch and PR rule of the design. Never
  `Obs("land")` for either.
- `finish_done`/`escalate` for a draft: release the claim of `retro_issue`, and record `state.filler.drafted["retro-<N>-<rank>"]`.
  Nothing is labelled.
- `restart` for a task and a draft: the same as fix/ship, but with no stash for a task.
- `cleanup`: skip `git branch -D` when `branch` is None.
- `dispatch.py`: a hidden `task <unit>` verb (like `land`) that calls `run_task`.

**Done when:** module-level tests with the seams `spawn`, `gh` and `alive` show:
- a task unit that ends with exit 0 is done, and one that ends with exit 3 is escalated and held;
- a draft whose branch has an open PR is done, the PR is not merged, and the claim is released;
- a draft without a PR is escalated with no issue label.

`test_dispatch_units.py`, `test_167_units.py` and `test_202_dispatch.py` stay green.

## t9 — plan and status show the plan or cost line, held reasons, hints and warnings

**Files:** scripts/cplat/dispatch_view.py, tests/cplat/test_dispatch_view.py
**Covers:** AC-210.2, AC-210.4, AC-210.10
**Goal:** `plan --json`, `status --json` and their text carry `plan`, `cost`, `hints`, `warnings` and the new `starts`
exactly as design.md "plan --json and status --json" states.

**Implementation notes:**
- `plan_doc(..., gate=None)` and `status_doc(...)`: when `gate` is None, compute it with `dispatch_gate.gate(slug,
  policy, st, dispatch_budget.usage_today(slug))`. This keeps `dispatch_cycle.evaluate` working before t10. Add
  `plan`, `cost`, `hints` and `warnings`. `starts_doc` takes the gate (`allowed`, `why_not`, `text`).
- `policy_doc`: `usage_hint` entries with `usd`.
- `_flat` lists the budget leaves `budget.mode`, `budget.usd_per_day`, `budget.usd_per_month`, `budget.tokens_per_day`
  and `budget.per_unit`, and, in mode plan, the `budget.plan.<k>` leaves.
- `render_plan`:
  - the `usd_per_day` unset line with the USD 7-day hint;
  - `tokens_per_day` None prints `unset (deprecated)`;
  - the plan or cost line, then warnings, then hints, then `filler: true` when open;
  - a candidate with reason `budget` renders `held: <detail>`, `filler only` renders `held: filler only`, and a filler
    slot renders `slot <n> (filler)`.
- `render_status`: the same plan or cost line, warnings and hints after `escalated today`. The held rows of reason
  `budget` render the same way.
- `test_dispatch_view.py`: update the unset-line text assertion to the new `budget.usd_per_day` line
  (`# replaced by AC-210.2`), and nothing else.

**Done when:** the acceptance tests for AC-210.2 (the JSON keys and text lines with a fixture reading or ledger),
AC-210.4 (the warning) and AC-210.10 (both hints, the policy file unchanged) pass. The other `test_dispatch_view.py`,
`test_167_policy_plan.py` and `test_167_steering.py` tests stay green.

## t10 — The cycle applies the gate, the pace band and the filler queue

**Files:** scripts/cplat/dispatch_cycle.py
**Covers:** AC-210.2, AC-210.3, AC-210.4, AC-210.6, AC-210.7, AC-210.8, AC-210.9, AC-210.10
**Goal:** `start` and `plan` decide with the gate: budget holds stop starts and agent calls, the pace band caps the
running units, and filler work takes free slots in the filler window.

**Implementation notes:**
- Replace `_why_not` and `_reached` with `dispatch_gate.gate`:
  - once before the loop;
  - again after each agent call (a USD or token cap reached by the call stops the next start, as `_reached` does now);
  - `free = free_numbers(running, min(effective_slots, gate.max_running or slots))`.
- Under a gate hold other than `paused`/`drain`, each ready candidate becomes `held` with reason `budget` and detail
  `gate.text`. It goes into `CycleResult.held`/`last_cycle.held`. No agent call is made.
- `_judge`: after ordering, call `dispatch_filler.split` with `gate.filler`. Verdicts held as `filler only` join the
  held list.
- After the regular loop, only when `gate.filler`, no regular candidate is ready, no hold applies and a slot is free:
  - call `dispatch_filler.window_rollover`;
  - take the filler-only verdicts, then `dispatch_filler.extra(...)` (with `want_drafts` when a slot is still free);
  - start each with `du.start` (no premise or mode call);
  - add the candidate rows with `filler: true`;
  - record task names and draft units in `state.filler`.
- `_candidate_doc` gains `filler`. `evaluate` passes the same gate to `dispatch_view.plan_doc(gate=…)`.
- Needs: `dispatch_notify.write_needs(slug, gate.needs + new_needs, …)` replaces the single `budget_need`.
- The `no starts:` line prints `gate.text`.
- Update the module docstring (the reasons not to start now come from `dispatch_gate`).

**Done when:** the acceptance tests for AC-210.2 to AC-210.4 and AC-210.6 to AC-210.10 pass in the dispatcher world,
with fixture usage files and no network. All `test_167_*`, `test_dispatch_*`, `test_202_dispatch.py`,
`test_184_slots.py` and `test_176_task.py` stay green, apart from lines that pin replaced criteria (AC-167.1, AC-167.2,
AC-167.10). Change such a line only if it fails, and mark it `# replaced by AC-210.<n>`.

## t11 — Document the two budget modes, the sensor and the filler queue; changelog fragment

**Files:** docs/dispatch.md, docs/changelog.d/210-dispatcher-budgets-by-plan-or-cost.added.md
**Covers:** AC-210.1, AC-210.5
**Goal:** users can choose a mode, install the sensor and read the new lines.

**Implementation notes:**
- `docs/dispatch.md`:
  - the steps and the example policy use `budget.usd_per_day`;
  - the key table lists every key of AC-210.1 with its default, and marks `tokens_per_day` deprecated;
  - the "Budget" section explains mode cost (daily/monthly USD, priced from the price table) and mode plan (the 92 %
    weekly target, the 80 % window stop, the pace bands, a stale reading estimated after 30 min, limit messages hold
    until reset, usage credits never spent);
  - a new "Plan usage sensor" section covers `cplat dispatch sensor install|remove`, that readings come only from
    interactive sessions, and the earlier status line kept;
  - a new "Filler work" section covers the last 24 h, filler-only, `filler_tasks` once per week, at most 3 retro drafts
    that stay open for you.
  - No spec numbers in the guide.
- The fragment follows the style of the existing ones: a bold one-sentence summary ending in `(spec 210).`, then why
  (a token cap tracks neither money nor a subscription) and what changes for an existing policy (`tokens_per_day`
  still works, with a warning).

**Done when:** `devbox run quality` passes (link check, `check-docs.py`, `release-check.py rows`).
