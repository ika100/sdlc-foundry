# Design — 210 The dispatcher budgets by plan limits or by cost

## Decisions

- **One gate decides every start.** The new module `dispatch_gate.py` holds the reasons not to start (steering, the
  plan, the cost caps, unknown usage) in one fixed order. Both `run_cycle`/`evaluate` and `status` call it, so the
  `no starts:` line, the held reasons of `plan` and the `status` lines cannot drift. Today `dispatch_cycle._why_not` and
  `dispatch_view.starts_doc` each have their own copy of this logic (AC-210.2, AC-210.6).
- **The plan's usage is machine-wide state, not repo state.** Readings, the booked-token tape and the last usage limit
  are kept under `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/usage/`, because one subscription serves every repo
  of the machine. The USD and token ledgers stay per repo in `state.json`, because the caps are per repo policy (non-goal:
  several machines).
- **The sensor is a copied stdlib script.** `cplat dispatch sensor install` copies `scripts/cplat/usage_sensor.py` to
  `usage/sensor.py` and points `statusLine` at it. The plugin cache path holds the version and goes away on update.
  A status line also cannot rely on the plugin's `bin` on its PATH. The script imports nothing from cplat, and
  `usage_readings.py` imports its file functions, so there is one writer of the format (AC-210.5).
- **The estimate uses a time-stamped tape.** The per-day ledger cannot tell how many tokens were booked between two
  readings. Every booking (`book`, `book_agent`) also appends `{at, tokens}` to `usage/booked.jsonl`. The tape keeps 8
  days (AC-210.7).
- **Limit messages are recorded by the run that sees them.** `headless` and `supervisor` already detect the limit
  (spec 184). On a hit that has a message, they write `usage/limit.json`. A manual `cplat headless` run on the machine
  therefore holds the dispatcher too, because it hits the same subscription. A silent short session, which
  `usagelimit.detect` also counts as a hit, records nothing, because it carries no limit message (AC-210.8).
- **Budget holds turn ready candidates into held ones.** Under a budget or pace hold, every ready candidate that would
  have taken a slot shows `held: <text>` with reason `budget`, both in `plan` and in `last_cycle.held` (so in `status`).
  Pause and drain keep the old behaviour (ready, queued), because AC-202.7 is unchanged (AC-210.2, AC-210.6).
- **Filler units are two new unit kinds, `task` and `draft`, beside `fix` and `ship`.** A `task` runs its command
  through the hidden verb `cplat dispatch task <unit>`, so `dispatch_units.alive` recognises its process and a result
  file is written. A `draft` runs `cplat headless "/component:spec …"`. It is done once its branch has an open pull
  request. The dispatcher never lands it (AC-210.9).
- **Draft units run one at a time and release the retro issue's claim when they end.** A draft spec tracks the retro
  issue, and `cplat spec new --tracks N` claims it for the draft's branch. A second draft running at the same time would
  be refused by that claim. When a draft unit ends (done or escalated), the dispatcher releases the claim, so the next
  draft can claim it.
- **A retro draft is never self-approved.** `dispatch_ready.judge` holds a draft spec as `needs-approval` (detail
  `a retro draft: approve it yourself`) when it tracks an issue titled `Weekly retro YYYY-Www`, or when its branch is
  recorded in `state.filler.drafted`, even with `gates.approve_specs: self` (AC-210.9).
- **`guard` stays a valid key.** AC-210.1 lists the keys without `guard.loop_calls`/`guard.loop_minutes` (spec 202).
  Refusing `guard` would break every policy that sets it, and the spec does not ask to remove it.
- Departs from AC-210.3 "while a unit's usage is unknown": an unknown unit holds starts only on the local day its
  usage was first found unknown (the AC-167.10 rule, kept). An escalated unit whose usage never becomes known would
  otherwise stop the dispatcher for good. Within one day the behaviour is exactly the criterion's.
- **An agent call with no reported cost** is priced from its `usage` with the price table. With no usage either, it
  books `AGENT_CEILING` tokens (200 000) at the model's input price. If the model has no price, it uses the highest
  input price in the table. An agent call therefore never makes the usage unknown.
- **ADR needed (not yet created):** the decision "the dispatcher budgets in the unit the user pays: plan percentages
  from a status line sensor, or US dollars from the price table" outlives this feature. Create it with
  `cplat adr add dispatcher-budget-units --decision "The dispatcher budgets in plan percentages (status line sensor) or USD (price table), never in raw tokens"`.
  The architect session had no shell, so the ADR file does not exist yet.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `dispatch_policy.py` | new keys, validation, defaults, `filler_match` | changed |
| `usage_sensor.py` | stdlib only: parse status line input, write a reading, run the earlier status line command | new |
| `usage_readings.py` | read readings, append/sum the booked tape, record/read the usage limit | new |
| `dispatch_sensor.py` | `sensor install` / `sensor remove`: edit the user's Claude settings | new |
| `usagelimit.py` | `Hit.message` (the limit line, None for a silent session) | changed |
| `headless.py`, `supervisor.py` | record a limit hit; result file gains `cost_usd` | changed |
| `dispatch_agent.py` | `ask` returns tokens, cost and model; results carry `cost_usd`, `model` | changed |
| `dispatch_budget.py` | USD per unit and per agent call, USD ledger, month sums, tape bookings, USD history hint, budget needs | changed |
| `dispatch_pace.py` | plan mode: windows from readings or estimate, calibration, limit hold, bands, filler window | new |
| `dispatch_gate.py` | the one ordered decision: hold, max running, filler, `plan`/`cost` documents, needs | new |
| `dispatch_filler.py` | filler candidates: filler-only split, `filler_tasks`, retro proposals, per-window counters | new |
| `dispatch_units.py` | `task` and `draft` unit kinds: start, classify, finish, escalate; `run_task` | changed |
| `dispatch_backlog.py` | `title` in `PR_FIELDS` | changed |
| `dispatch_ready.py` | the retro-draft hold | changed |
| `dispatch_cycle.py` | gate, band cap, budget-held verdicts, filler scheduling, needs | changed |
| `dispatch_view.py` | `plan`/`cost`/`hints`/`warnings` in `plan` and `status`, text lines | changed |
| `dispatch.py` | verbs `sensor install|remove`, hidden `task <unit>`; `start`/`resume` policy check | changed |

## Contract

### Policy (`.platform/dispatch.yml`) — AC-210.1

```yaml
slots: 1..10                       # default 1
budget:
  mode: cost | plan                # default cost
  usd_per_day: <number > 0>        # no default
  usd_per_month: <number > 0>      # no default
  tokens_per_day: <int >= 1>       # deprecated, no default
  per_unit: {minutes|invocations|reruns|cost: <number > 0> | off}
  plan:                            # only with mode: plan
    weekly_target: 0.50..1.00      # default 0.92
    window_stop: 0.50..1.00        # default 0.80
    filler_only: [label:<name> | priority:P0|P1|P2, ...]   # default [priority:P2, label:enhancement]; [] allowed
    filler_tasks: [{name: <non-empty, unique>, command: <non-empty>}, ...]   # default []
    filler_drafts: true | false    # default true
sources, ready, priority, gates.approve_specs, gates.merge, serialize, guard   # unchanged
```

Errors are `PlatformError`, printed as `ERROR: .platform/dispatch.yml: <key>: <message>`, exit 1, and are the same on
every `cplat dispatch` verb that reads the policy:

| Case | Message after `<key>: ` |
|---|---|
| unknown key | `unknown key (allowed: <comma list>)` (`budget` allows `mode, usd_per_day, usd_per_month, tokens_per_day, per_unit, plan`; `budget.plan` allows `weekly_target, window_stop, filler_only, filler_tasks, filler_drafts`; a `filler_tasks` entry allows `name, command`) |
| bad value | `<value> is not allowed (allowed: <description>)`, e.g. `budget.mode: tokens is not allowed (allowed: cost, plan)`, `budget.plan.weekly_target: 0.3 is not allowed (allowed: a number 0.50..1.00)` |
| `budget.plan` or a `budget.plan.*` key in mode cost | `budget.plan.<k>: needs budget.mode: plan` (the key is the first one given, `budget.plan` itself when it is empty) |
| duplicate `filler_tasks` name | `budget.plan.filler_tasks: <name> is not allowed (allowed: unique names)` |

`start` and `resume` (`require_budget=True`): in mode cost with neither `usd_per_day` nor `tokens_per_day`:
`ERROR: .platform/dispatch.yml: budget.usd_per_day is required in mode cost (or the deprecated budget.tokens_per_day)`,
hint `set a daily limit in US dollars (see docs/dispatch.md); cplat dispatch plan shows the cost of the last 7 days`,
exit 1, nothing started. Without the file: unchanged (`no .platform/dispatch.yml in <repo>`).

`Policy.values["budget"]` is
`{"mode", "usd_per_day", "usd_per_month", "tokens_per_day", "per_unit", "plan"}`. `plan` is the filled mapping in mode
plan and `None` in mode cost. The leaves that are not given are `None`. `Policy.defaulted` adds `budget.mode` and, in
mode plan, `budget.plan.<k>` for each default taken. `Policy.unset` is `["budget.usd_per_day"]` in mode cost without
it, else `[]`.

`filler_match(policy, labels) -> bool`: false in mode cost. True when any rule matches. `label:<name>` matches a label
case-insensitively. `priority:P<n>` matches when `priority.most_urgent(lowercased labels)` is `P<n>`. The labels are
`Verdict.labels` (own labels, a spec's priority, the labels of its tracked issues).

### Usage files (machine-wide) — AC-210.5, AC-210.7, AC-210.8

Directory `U = ${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/usage/`. Every write is atomic (temp file + rename) under
`U/usage.lock` (`fcntl.flock`), except the tape, which is appended with `O_APPEND`.

`U/readings.json`:

```json
{"schema": 1,
 "five_hour": {"last": {"at": 1763460000, "used": 83.0, "resets_at": 1763466300},
               "history": [{"at": 1763456400, "used": 80.0, "resets_at": 1763466300}, ...]},
 "seven_day": {"last": {...} | null, "history": [...]}}
```

`at` and `resets_at` are Unix epoch seconds, and `used` is 0–100 as given. A reading of a window always replaces
`last`. It is appended to `history` when `used` or `resets_at` differs from the last history entry, or when that entry
is 10 minutes or more older. History older than 7 days is dropped on each write. A window missing from the input, or
one without both `used_percentage` and `resets_at`, is left as it was.

`U/booked.jsonl`: one line `{"at": <epoch float>, "tokens": <int>}` per booking with tokens > 0. Lines older than 8 days
are dropped when the file is rewritten, which happens at most once per local day.

`U/limit.json`: `{"at": <epoch>, "until": <epoch>, "reset_known": true|false, "message": "<the limit line, ≤ 300 chars>"}`.
`until` is the parsed reset, or `at + 3600` without one. A new hit replaces the file only when its `until` is later.

`U/sensor.json` (install record): `{"installed_at": "<ISO>", "settings": "<abs path>", "previous": <the earlier statusLine value or null>, "command": "<installed command>"}`.

`U/sensor.py`: the copy of `usage_sensor.py`.

### Sensor — AC-210.5

`cplat dispatch sensor install [--json]`:
- Settings file: `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json` (created as `{}` when missing; a file that is not a
  JSON object: exit 1, file named, nothing written).
- It copies `usage_sensor.py` to `U/sensor.py`. The command is `<python3> <U/sensor.py>`, shell-quoted, where `<python3>`
  is `shutil.which("python3")`, else `sys.executable`.
- The new `statusLine` is `{**previous_without_type_and_command, "type": "command", "command": <command>}`, so
  `padding` and `refreshInterval` are kept. `sensor.json` records `previous` (null when there was none).
- It is idempotent: when `statusLine.command` already is the sensor command, only `sensor.py` is refreshed, and the
  recorded `previous` is kept.
- It prints `sensor installed: <settings path> (earlier status line kept: <command>)` or
  `sensor installed: <settings path>`. Exit 0.

`cplat dispatch sensor remove`:
- When `statusLine.command` is the sensor command, it restores `previous` (or deletes `statusLine` when `previous` is
  null) and prints `sensor removed: <settings path>`.
- When the status line is something else, it leaves it alone and prints
  `sensor removed: the status line was changed since the install; left unchanged`.
- It deletes `sensor.json` and `sensor.py`. Without a `sensor.json` it prints `no sensor installed`. Exit 0 in every case.

`U/sensor.py` (run by Claude Code with the status line JSON on stdin):
1. Read stdin whole. Parse it. For each window `w` in `five_hour`, `seven_day` with numeric
   `rate_limits.w.used_percentage` and `rate_limits.w.resets_at`, record a reading at
   `now = float(os.environ.get("CPLAT_SENSOR_NOW") or time.time())`. Any error is swallowed: the status line never breaks.
2. When `sensor.json.previous.command` exists, run it with `sh -c`, the same stdin bytes, the current directory and
   environment, and a 10 s timeout. Write its stdout bytes unchanged to stdout. Exit 0.
3. With no earlier command, print `5h <n> % · 7d <n> %` from the last readings (`?` for a missing window).

### Plan state (`dispatch_pace.pace`) — AC-210.6 to AC-210.9

`pace(policy, now, booked=usage_readings) -> Pace`, with `now` = `dispatch_state.now()`:

```
Pace(source: "reading"|"estimate"|"limit"|"unknown", read_at: ISO|None,
     five_hour: Window, seven_day: Window, filler: bool,
     hold: (why_not, text) | None, max_running: int | None, limit_until: ISO | None)
Window(used: float|None, resets_at: ISO|None, stale: bool, estimated: bool)
```

Per window `w`:
1. `last` = the newest reading. With none, `used` is None.
2. If `last` is 30 minutes old or less and `now < resets_at`, then `used = last.used`.
3. Otherwise (stale, or the reset has passed) the window is estimated. `base_used = 0` and `since = resets_at` when
   `now ≥ resets_at`. For `five_hour` the new `resets_at` is `since + 5 h`, and for `seven_day` it is `since + 7 d`,
   stepped until it lies in the future. Otherwise `base_used = last.used` and `since = last.at`. Then
   `used = base_used + tape_sum(since, now) / tpp(w)`.
4. `tpp(w)` is the median, over consecutive history pairs `(a, b)` of `w` from the last 7 days with
   `|a.resets_at − b.resets_at| ≤ 60`, `b.used > a.used` and `tape_sum(a.at, b.at) > 0`, of
   `tape_sum(a.at, b.at) / (b.used − a.used)`. With no such pair it is None, and the estimated window has `used` None.

   Example (AC-210.7): 40 % at 10:00, 42 % at 11:00, 20 M between → 10 M per point. 15 M after 11:00 → 43.5 %.

`tape_sum(t0, t1)` is the sum of the tape tokens with `t0 < at ≤ t1`.

The decision runs in this order. The first that applies sets `hold`. `text` is what follows `held: ` / `no starts: `:

| # | Condition | why_not | text |
|---|---|---|---|
| 1 | `limit.json.until > now` | `usage limit` | `usage limit until <t>` |
| 2 | either window `used` None | `plan usage unknown` | `plan usage unknown (install the sensor and open an interactive session)` |
| 3 | `five_hour.used ≥ window_stop × 100` | `plan window` | `plan-window <u> % ≥ <s> %` |
| 4 | `seven_day.used ≥ weekly_target × 100` | `weekly target reached` | `weekly target reached` |
| 5 | `seven_day.used > pace` | `ahead of weekly pace` | `ahead of weekly pace (<u> % used, pace <p> %)` |

- `pace = weekly_target × elapsed × 100`, where `elapsed = clamp((now − (resets_at − 7 d)) / 7 d, 0, 1)`.
- `max_running` is 1 when `pace − used ≤ 5`, else None (the slots count). It is None under a hold.
- `filler` is true when `seven_day.resets_at − now ≤ 24 h` and none of rows 1 to 5 holds.
- `source` is `limit` under row 1, else `unknown` under row 2, else `estimate` when a window was estimated, else
  `reading`. `read_at` is the older of the two windows' `last.at` (ISO local), or None.
- Numbers in text use `f"{round(x, 1):g}"`: 83 → `83`, 43.5 → `43.5`. `<t>` is `%H:%M` when the time falls on
  today's local date, else `<Mon> %H:%M` (English weekday abbreviation).

### The gate (`dispatch_gate.gate`) — AC-210.2 to AC-210.8

`gate(slug, policy, state, usage, *, now=None) -> Gate`, where `usage` is `dispatch_budget.Usage`:

```
Gate(why_not: str|None, text: str|None, max_running: int|None, filler: bool,
     plan: dict|None, cost: dict, needs: list[dict], hints: list[str], warnings: list[str])
```

The order is: `paused` → `drain` → (mode plan) the `Pace` hold → `daily budget reached` (USD) → `monthly budget reached`
→ `daily budget reached` (tokens) → `usage unknown`.

| why_not | text |
|---|---|
| `paused` / `drain` | `paused` / `drain` (unchanged) |
| `daily budget reached` (USD) | `daily budget reached: $<used> of $<limit>` |
| `monthly budget reached` | `monthly budget reached: $<used> of $<limit>` |
| `daily budget reached` (tokens) | `daily budget reached: <used> of <limit> tokens` |
| `usage unknown` | `usage unknown: <unit>, <unit>` |

- In mode plan the USD and token caps apply only when set (A12).
- `usage unknown` applies when a set cap needs a value that is unknown: USD caps need `usage.unknown_usd`, the token cap
  and mode plan need `usage.unknown` (tokens).
- USD amounts in text and JSON are rounded to 2 decimals and printed as `$1.20`.

`Gate.plan` is the `plan` JSON object below (null in mode cost). `Gate.cost` is always the `cost` object.

`Gate.needs` holds one `budget` need per period, with the shape of today's need
(`kind: "budget"`, `stage: "Build"`, `object.type: "dispatch"`, `since` kept per id in `state.budget_since`):

| Hold | id | reason | command |
|---|---|---|---|
| USD daily | `budget:<slug>:<YYYY-MM-DD>` | `daily cost budget reached: $<u> of $<l>` | `raise budget.usd_per_day in .platform/dispatch.yml (starts continue after midnight)` |
| USD monthly | `budget:<slug>:<YYYY-MM>` | `monthly cost budget reached: $<u> of $<l>` | `raise budget.usd_per_month in .platform/dispatch.yml (starts continue on the 1st)` |
| tokens daily | `budget:<slug>:<YYYY-MM-DD>` | `daily token budget reached: <u> of <l> tokens` (unchanged) | unchanged |
| plan usage unknown | `budget:<slug>:<YYYY-MM-DD>` | `plan usage unknown: no current reading of the subscription's limits` | `cplat dispatch sensor install, then open an interactive Claude Code session` |

The need is listed only while its condition holds. When two needs share a day id, the first in this table wins.

Hints (AC-210.10, at most one, from `usage_readings`):
- Mode cost and any history entry from the last 7 days:
  `hint: subscription usage readings found; budget.mode: plan paces by your plan's limits`.
- Mode plan, `ANTHROPIC_API_KEY` set and non-empty, and no reading at all:
  `hint: an API key and no subscription readings; budget.mode: cost caps spending in USD`.

Warnings (AC-210.4): with `budget.tokens_per_day` set:
`budget.tokens_per_day is deprecated: set budget.usd_per_day (cost today: $<n>)`.

### `plan --json` and `status --json` — AC-210.2

New top-level keys in both documents (`schema` stays 1, existing keys stay):

```json
"plan": null | {"source": "reading"|"estimate"|"limit"|"unknown", "read_at": "<ISO local>"|null,
                "five_hour": {"used": 83.0|null, "resets_at": "<ISO local>"|null, "stop": 80.0},
                "seven_day": {"used": 41.0|null, "resets_at": "<ISO local>"|null, "pace": 46.0|null, "target": 92.0},
                "filler": false, "hold": "<text>"|null, "max_running": 1|null, "limit_until": "<ISO local>"|null},
"cost": {"day": "2026-11-18", "used_usd": 1.2, "limit_usd": 5.0|null,
         "month_used_usd": 30.4, "month_limit_usd": 100.0|null},
"hints": ["hint: ..."],
"warnings": ["budget.tokens_per_day is deprecated: ..."]
```

- `starts` becomes `{"allowed": bool, "why_not": <why_not or null>, "text": <text or null>}`.
- `policy.usage_hint` entries become `{"day", "tokens", "usd"}`. `usd` is the sum of `usage.totals.cost_usd` of the
  top-level run records of that day, or null when a record has `cost_complete: false` or the store cannot be read.
- A candidate row gains `"filler": true|false`.
- A candidate held by the gate has `verdict: "held"`, `reason: "budget"` and `detail: <gate text>`.
- A filler-only candidate outside the filler window has `reason: "filler only"` and `detail: null`.

Text lines, after the policy block and before `tokens today` in `plan`, and after `escalated today` in `status`:
- Mode plan:
  `plan usage: 5h 83 % (stop 80 %, resets 15:45) · week 41 % (pace 46 %, target 92 %, resets Mon 00:00) · <age>`.
  `<age>` is `reading 4 min old`, `estimate from a reading 52 min old`, or `usage limit until 15:45`. A window with
  `used` null shows `5h ?`. With source `unknown`, the line is
  `plan usage: unknown (install the sensor and open an interactive session)`.
- Mode cost, or any USD cap set: `cost today: $1.20 of $5.00`, followed by ` · this month: $30.40 of $100.00` when
  `usd_per_month` is set. Without `usd_per_day` the line reads `cost today: $1.20 (no USD limit set)`.
- Each warning, then each hint, on its own line.
- The policy block shows `budget.usd_per_day: unset (required by start and resume in mode cost) — last 7 days: 2026-11-12 $1.20 2026-11-13 $? …`
  in mode cost without it. The old `tokens_per_day` unset line goes away: the key prints as `unset (deprecated)` when None.
- A candidate verdict under reason `budget` renders `held: <detail>`, and under `filler only` renders
  `held: filler only`.
- A filler start renders `slot <n> (filler)`. When the window is open, `plan` adds the line `filler: true`.

### Filler — AC-210.9

`dispatch_filler.candidates(repo, slug, policy, snap, state, pace, verdicts) -> (filler_only: [Verdict], extra: [Candidate])`:
- In mode plan, ready verdicts that match `filler_match` are taken out of the regular order. Outside the filler window
  they become held (`filler only`). Inside it, they come first in the filler list, in priority order.
- The weekly window id is `pace.seven_day.resets_at`. `state.filler = {"window": <id>, "tasks": {<name>: <unit>}, "drafts": [<unit>, …], "drafted": {"retro-<N>-<rank>": {"unit", "branch", "pr"}}}`.
  `tasks` and `drafts` are reset when `window` changes. `drafted` is kept for good.
- Tasks: each `filler_tasks` entry whose name is not in `state.filler.tasks` gives a candidate with
  `key "task-<slug of name>"`, `item "task:<name>"`, `kind "task"` and `text <command>`.
- Drafts: only when `filler_drafts` is true, fewer than 3 entries are in `state.filler.drafts`, and no draft unit is
  running. The latest issue labelled `retro` whose title matches `^Weekly retro \d{4}-W\d{2}$` is read with
  `gh issue list -R <slug> --label retro --state all --limit 10 --json number,title,body,createdAt` (newest
  `createdAt`). Its `## Proposed specs` section is parsed: an item line `^(\d+)\. \*\*(.+?)\*\* \((P\d)\)` (rank,
  title, priority) and its line `` `/component:spec (.+)` `` (the request). A proposal is answered when any of these
  holds:
  - `drafted` has `retro-<N>-<rank>`;
  - a spec of `origin/main` (any status) or of an open spec-draft pull request tracks `N` and has the same title
    (case and punctuation ignored);
  - an open pull request's title contains the proposal title (case ignored).

  Each unanswered proposal gives a candidate with `key "retro-<N>-<rank>"`, `item "retro#<N>.<rank>"`, `kind "draft"`
  and `text "/component:spec <request> #<N>"`. Only one draft candidate is offered per cycle.
- The read of the retro issue happens only in the filler window, with `filler_drafts` true and a free slot left. A
  failed read lands in `unavailable` as `retro`.

Scheduling in `_schedule`: the regular ready candidates first (unchanged). Then, only when `gate.filler`, no regular
candidate is ready, no hold applies and a slot is free, the filler list fills the free slots in order: filler-only
verdicts, then tasks, then drafts. No agent call is made for `task` or `draft`.

Units (`dispatch_units`):
- `task`:
  - The worktree is `git worktree add --detach <path> origin/main`, there is no claim, and `branch` is None.
  - The process is `python cplat.py dispatch task <unit> --repo <repo>`, detached, with the unit's log.
  - `run_task` runs `sh -c <command>` in the worktree, with a timeout of `per_unit.minutes` when numeric, else 240 min.
  - It writes the result file `{unit, ended_at, outcome: "done"|"escalated", result: "exit <n>"|"timed out after <m> min", stop_reason, tokens: 0, cost_usd: 0.0}`.
  - Classify: `done` → done, `escalated` → escalate (no issue: held in state), no result and no process → restart, as
    for other kinds.
  - `alive` also accepts a command line that contains `dispatch task`.
- `draft`:
  - The worktree is detached at `origin/main`, there is no claim by the dispatcher, and the command is
    `cplat headless --repo <wt> "<text>"`.
  - Classify after the process ends: read the worktree's branch (`git rev-parse --abbrev-ref HEAD`). If it is
    `feature/<id>` with an open pull request (`unit_pr`), the unit is done with that PR, which is never landed.
    Otherwise it is escalated (`the draft run ended without a pull request: <result>`, cause `decision`), with no label
    on any issue.
  - On both ends, `claim.release(repo, [N], "retro draft <unit> ended (cplat dispatch)")`, and `state.filler.drafted`
    records `{unit, branch, pr}`.
- The start line reads `started <unit> (<kind>, single, slot <n>) (filler): <command>  log: <log>`.

## Data

- `state.json` (per repo):
  - `ledger[day]` gains `usd: {<unit>: <float>}` and `agent_usd: <float>`.
  - New keys `counted_usd: {<unit>: <float>}`, `unknown_usd: {<unit>: <day>}` and `filler` (above).
  - `budget_since` is now keyed by need id (the old day keys stay valid).
- Result file `cplat-dispatch-result.json` gains `cost_usd: <float|null>` (headless: `run_cost(rid)` =
  `usage.totals.cost_usd` when `cost_complete` and not incomplete, else null).
- `dispatch_budget.Usage` gains `usd: float`, `month_usd: float` and `unknown_usd: list[str]`.
