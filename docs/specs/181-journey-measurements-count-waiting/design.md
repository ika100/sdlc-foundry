# Design — 181 Journey measurements count waiting correctly

## Decisions

- **The measurement moves into `cplat`** as `cplat platform runs journey measure`: it has to read run records (store and
  local buffer), find transcripts by session id (`transcripts.find`), write a follow-up line, and be tested under
  `tests/cplat`. `scripts/journey/measure.py` keeps its path and arguments and only forwards to it. ADR:
  [docs/adr/096-journey-waiting-is-attributed-from-evidence.md](../../adr/096-journey-waiting-is-attributed-from-evidence.md).
- **Exact interval arithmetic, not 5-second sampling**: the split is computed over the elementary segments between all
  interval endpoints, so person + agents + waiting equals the wall clock exactly before rounding (AC-181.2). JSON values are
  rounded to 2 decimals, text to 1.
- **The record's split is per stage** of the journey record (spec 136), computed over each stage's own `started_at`..`ended_at`
  (and each part's and the total's span): the report's rows are stages, and the stage spans are already in the record. The
  driver's steps file only drives the printed per-step table.
- **The split reaches the report as a follow-up line**, not by rewriting the record: a record is written once (spec 087).
  The follow-up mechanism already exists for `filed`; `journey_split` is a second follow-up kind (A5).
- **A transcript-less repo session's span is its run record's span** (`started_at`..`ended_at` of the record whose
  `usage.sessions` lists it): the record does not carry per-session times.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/journey_timeline.py` | pure: transcript → `Thread`, wait-call table, the split of one span | new |
| `scripts/cplat/journey_sources.py` | I/O: run records, system ship tree, child sessions, Actions runs, record evidence | new |
| `scripts/cplat/journey_measure.py` | the `measure` verb: steps, tokens, questions, GitHub counts, text and JSON, `--journey` | new |
| `scripts/cplat/runs_journey.py` | dispatches `measure` to `journey_measure.main` | changed |
| `scripts/journey/measure.py` | forwards its argv to `journey_measure.main` | changed |
| `scripts/cplat/runs.py` | `followup()`; `_report` passes follow-ups to the benchmarks report | changed |
| `scripts/cplat/runs_store.py` | `record_path` names a follow-up by its kind | changed |
| `scripts/cplat/runs_journey_report.py`, `runs_usage_report.py` | split medians per stage, new columns | changed |

## Contract

### CLI

```
cplat platform runs journey measure <session>[,<session>...] <start> <end> <owner/repo>... \
    [--steps FILE] [--json] [--journey RUN_ID] [--records FILE]
python3 scripts/journey/measure.py <same arguments>          # forwards, same output and exit code
```

- `<session>`: a coordinator transcript path without `.jsonl` (`~/.claude/projects/<dir>/<id>`), as today; its subagents are
  `<session>/subagents/*.jsonl`. `<start>`, `<end>`: ISO times, UTC. Repos: the journey's demo repos.
- `--steps FILE`: lines `<ISO time UTC>\t<label>`; a step ends where the next starts, the last at `<end>`; steps are clipped
  to `<start>`..`<end>`.
- `--records FILE`: JSON lines of run records (and follow-ups) to use **instead of** the run store and the local buffer
  (re-measuring saved journeys; tests). Without it: the local buffer (`runs._read_buffer()`) plus, when `CPLAT_RUNS_REPO` is
  set and reachable, the store's days from `<start>` − 1 day to `<end>` + 1 day; duplicates by `run_id` are dropped.
- `--journey RUN_ID`: also compute the per-stage split of that journey record and write it as a follow-up (§ Follow-up).
- Exit 0 after a measurement, including with warnings (AC-181.4). Exit 1 (`PlatformError`, one `ERROR:` line) for a time
  that does not parse, a coordinator transcript that does not exist, or a `--journey` record not found in the record sources.
- **Warnings** go to stderr, one line each, and into `warnings` in the JSON:
  - `WARNING: repo <owner/repo>: session <session-id> has no transcript on this machine; its minutes count as "repo session, no transcript"` (AC-181.4; `<owner/repo>` is the record's `repo`, `?` when absent)
  - `WARNING: no system ship run record overlaps the journey; repo sessions are not counted` (only when no record source
    has a `product-ship` record in the window)

### Threads and wait calls (`journey_timeline`)

A **thread** is one transcript file. Its **span** is its first to its last timestamped event, clipped to the measured span.
Threads are **coordinator** (each `<session>` and its subagents) or **child** (each repo session and its subagents).

A Bash `tool_use` whose `command` matches a row below is a **wait call** from the `tool_use` to its `tool_result`
(word-bounded match anywhere in the command; first row wins):

| Command | Kind |
|---|---|
| `cplat pr wait` | `ci` |
| `cplat system wait`, `cplat component ship deploy` | `deploy` |
| `cplat instance promote` | `promotion` |
| `cplat resource restore`, `cplat resource backup`, `cplat system restore` | `restore` |
| `cplat cluster wait`, `cplat cluster new`, `cplat cluster add`, `devbox run cluster-up` | `cluster` |
| `cplat instance verify` | `smoke` |
| `cplat system ship next … --wait`, `cplat system ship land`, `cplat component ship wait`, `cplat component ship land`, `cplat component release wait`, `cplat spec land`, `cplat dispatch wait`, `gh run watch`, `gh pr checks … --watch`, a loop (`sleep N`, `until `, `while true`) around `gh ` or `cplat ` | none (a wait without a kind) |

`command_wait(cmd: str) -> str | None` returns the kind, `"wait"` for a row without a kind, `None` for anything else.

A thread **works** at time t when t is in its span and none of: a wait call of the thread is open; an `Agent`/`Task` call
is open and no other tool call is (its subagent thread decides); t is in a person interval (coordinator main threads).
Any other tool call (files, tests, `git`, other `cplat` verbs) and the time between tool calls is work.

**Person intervals** (coordinator main threads only, unchanged from today): from the last assistant event to a typed user
prompt (string content, not meta, not starting with `<`), and every open `AskUserQuestion` call.

### Classification of one instant (AC-181.2, AC-181.3, AC-181.4)

First match wins:

1. `person`: a person interval is open.
2. agents: some thread works; `coordinator` if a coordinator thread works, else `children`.
3. `no_transcript`: the span of a repo session without a transcript is open.
4. the first of `ci`, `deploy`, `promotion`, `restore`, `cluster`, `smoke` that is open as a kinded wait call in any thread
   or as record evidence (below). A `system ship next --wait` never gives a kind.
5. `ci`: a GitHub Actions run of a journey repo is queued or running (`createdAt` ≤ t < `updatedAt`, A2).
6. `unattributed`.

**Record evidence** (`journey_sources`), records overlapping the span that belong to the system ship tree or whose `repo` is
a journey repo: kind `pr-wait` → `ci`; kind `verify` → `smoke`; kind `wait` → `command_wait("cplat " + wait.command)` when
that is a kind; a phase named `deploy` of a `ship` record → `deploy`; each over its `started_at`..`ended_at`.

### Children (AC-181.1, AC-181.4)

- **System ship runs**: records of kind `product-ship` overlapping the window whose `usage.sessions` contains a coordinator
  session id or whose `repo` is a journey repo.
- **Tree**: every record reachable from them through `parent` (child → parent) or `ships` (parent → child), any depth.
- **Repo sessions**: every id in `usage.sessions` of a tree record that is not a coordinator session, with the record's `repo`
  and span. Found with `transcripts.find(id, runs_usage.projects_root())`; its subagents are `<dir>/<id>/subagents/*.jsonl`.
  Not found → one warning, and the record's span (clipped) joins the `no_transcript` spans.

### The split object

Used for the whole window, each step, the step total and each stage/part/total in the follow-up. All values are minutes.

```json
{"wall_min": 40.0, "person_min": 0.0,
 "agents_min": 30.0, "agents": {"coordinator": 2.0, "children": 28.0},
 "waiting_min": 10.0,
 "waiting": {"ci": 3.0, "deploy": 5.0, "promotion": 0.0, "restore": 0.0, "cluster": 0.0, "smoke": 0.0,
             "unattributed": 2.0, "no_transcript": 0.0}}
```

`wall_min` = span end − start. `agents_min` = coordinator + children; `waiting_min` = sum of `waiting`. Rounded to 2
decimals; `person_min + agents_min + waiting_min` is within 0.1 of `wall_min` (AC-181.2). Every key is always present.

### JSON output (`--json`, AC-181.5)

```json
{"window": {"started_at": "2026-11-10T08:00:00Z", "ended_at": "2026-11-10T10:18:00Z"},
 "wall": {"<split object>": "…", "subagents": 16, "repo_sessions": 14, "inputs": 13},
 "tokens": {"api_calls": 0, "input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "total": 0, "output_by_model": {}},
 "questions": {"questions": 7, "rounds": 7},
 "github": {"merged_prs": 27, "runs": 155, "failed_runs": 1, "run_min": 134, "queue_min": 5, "ci_active_min": 52},
 "warnings": [],
 "steps": [{"step": "One spec for the whole system", "started_at": "…", "ended_at": "…", "<split object>": "…",
            "tokens": 0, "api_calls": 0}],
 "steps_total": {"<split object>": "…", "tokens": 0, "api_calls": 0},
 "journey": {"run_id": "…", "written": true}}
```

`wall` is the split object of the window plus the three counts (its keys merged in). `tokens`, `questions` and `github`
keep today's meaning (tokens and questions over the coordinator threads). `steps` and `steps_total` only with `--steps`;
`steps_total` is the split of first step start..`<end>` (the sum of the rows). `journey` only with `--journey`; `written` is
false when the follow-up stayed in the local buffer.

### Text output (AC-181.5)

The four header lines of today (wall clock, tokens, GitHub, questions), the wall-clock line showing person, agents
(coordinator / children) and waiting per kind. With `--steps`, a table with one row per step and a `total` row:

```
step                              wall  person  agents  coord  child     CI  deploy  promo  restore  cluster  smoke  unattr  no-tr  tokens
One spec for the whole system     52.3     0.4    41.0    3.1   37.9    4.0     2.5    0.0      0.0      0.0    0.0     4.4    0.0   9.1 M
total                            138.0     4.1    …
```

Labels: `CI`, `deploy` (deploy and Argo), `promo` (promotion), `restore` (restore and backup), `cluster`, `smoke`, `unattr`
(unattributed), `no-tr` (repo session, no transcript). Minutes with 1 decimal; the step label cut to 32 characters.

### Follow-up (`runs.followup`, AC-181.6)

```python
def followup(run_id: str, kind: str, data: dict) -> str | None:
    """Buffer {"schema": 1, "followup": kind, "signature": kind, "run_id": run_id, "at": <now>, **data} and flush.
    Returns the warning line when it stays buffered (as finish does), else None. Never raises."""
```

`runs_store.record_path` of a follow-up becomes `runs/<at day>/<run_id>.<followup>.<sha1(signature)[:12]>.json` — unchanged
for `filed`. A re-measurement writes the same signature again; readers take the latest `at`.

The journey follow-up (`kind = "journey_split"`):

```json
{"schema": 1, "followup": "journey_split", "signature": "journey_split", "run_id": "<journey run_id>", "at": "…",
 "split": {"stages": {"2.spec": {"<split object>": "…"}}, "parts": {"2": {"<split object>": "…"}},
           "total": {"<split object>": "…"}}}
```

Stages without both `started_at` and `ended_at` in the record's `journey.stages` are left out; parts and the total likewise.

### Report (`cplat platform runs report --benchmarks`, AC-181.6)

`runs._report` passes the parsed follow-ups to `runs_usage_report.aggregate_benchmarks(..., followups=follows)`, which passes
them to `runs_journey_report.aggregate(kept, followups)`. Per journey record the latest `journey_split` follow-up (by `at`)
supplies the split of each stage, part and the total. Each row (stage, part, journey) gains:

```json
{"split_runs": 2, "agents_median": 41.0, "waiting_median": {"ci": 4.0, "deploy": 2.5, "promotion": 0, "restore": 0,
  "cluster": 0, "smoke": 0, "unattributed": 4.4, "no_transcript": 0}}
```

Medians over the done runs whose follow-up has that row; with none, `agents_median` is `null` and every `waiting_median`
value is `null`. Text: the columns `agents CI deploy promo restore cluster smoke unattr no-tr` after `PRs` and before the
`prev` column, `–` (en dash) for `null`; every other column and line stays as it is. The JSON keys of today are unchanged.
