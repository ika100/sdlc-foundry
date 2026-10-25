# Design — 099 Token usage and cost are measured per run

## Decisions

- **Transcripts are the only source, read at run end by cplat** (`runs_usage`). A run started inside a Claude Code
  session *claims* it through `$CLAUDE_CODE_SESSION_ID`. `headless` and `benchmark` *own* the sessions they launch.
  Claims live in a local ledger, never in the store. ADR: [035](../../adr/035-token-usage-from-session-transcripts.md).
- **The transcript files are found by session id**, not by cwd slug: `<projects>/*/<session>.jsonl` (glob one level).
  `<projects>` is `$CLAUDE_CONFIG_DIR/projects`, defaulting to `~/.claude/projects` (`runs_usage.projects_root()`, which
  tests replace). Only `benchmark` uses a project directory, found from its clone path (cwd slug: absolute real path
  with `/` and `.` replaced by `-`).
- **Failed calls keep the breakdown sums exact.** A `<synthetic>` call counts in `calls` and `failed_calls`. In
  `by_model` it goes in the bucket `(failed)`, which is not a model, has `cost_usd: 0`, and never makes a cost
  `unknown` (AC-099.6). That way the sums of `by_phase`, `by_role` and `by_model` each equal `totals` (AC-099.1).
- **Split shares are fractions.** A shared main-session call adds `1/n` to calls, tokens and cost in each of the `n`
  runs (AC-099.14). Values are integers when whole, otherwise rounded to 6 decimals.
- **Gates are recorded by the orchestrator**, through `cplat runs gate`, at the points where `/svc:build` already
  decides them. `finish` fills a missing gate with `not run` for `ship` and `build` (AC-099.12).
- **The benchmark refuses a moved sample repo.** If the sample repo's `main` is not at the pinned revision, the
  benchmark stops unless it is given `--reset-first`. That way it never quietly wipes other work in the sdlc-test repo
  (the e2e round uses it too).
- **Benchmark runs go through `cplat headless`, in process**, in a fresh clone of the sample repo. Every record started
  under it carries `benchmark_of: <benchmark run_id>`. The report leaves out records of kind `benchmark` and records
  with `benchmark_of`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/transcripts.py` | read one session (main + subagents) into `Call`s; dedupe by message id; count malformed lines; no knowledge of runs | new |
| `scripts/cplat/prices.json` | price table (data) | new |
| `scripts/cplat/usage_cost.py` | load the price table, price one model's counts, build buckets and a usage section from attributed calls | new |
| `scripts/cplat/runs_usage.py` | sources ledger, attribution (window, phase, role, shared split), 10 s budget, `for_run`, `for_session` | new |
| `scripts/cplat/runs_usage_report.py` | pure: `usage` key of `runs report`, `--benchmarks` aggregate, text rendering of one usage section | new |
| `scripts/cplat/runs_usage_cli.py` | `cplat runs usage` | new |
| `scripts/cplat/runs_bench.py`, `scripts/cplat/benchmark/` | `cplat runs benchmark`, fixed tasks, sample reset | new |
| `scripts/cplat/runs.py` | register claim at `start`, collect usage and default gates at `finish`, `benchmark_of`, `gate` / `usage` / `benchmark` subcommands, `report --benchmarks` | changed |
| `scripts/cplat/runs_report.py` | `aggregate` adds `usage`; `render_text` appends its lines | changed |
| `scripts/cplat/headless.py` | `--session-id <uuid>` per launched session, registered as an owned source | changed |
| `plugins/svc/commands/build.md` | `cplat runs gate ...` calls | changed |

## Contract

### Transcript reading (`transcripts.py`)

```python
@dataclass(frozen=True)
class Call:
    key: str            # message.id; the line's uuid when the message has no id
    at: datetime        # timestamp of the FIRST line with this key (UTC, aware)
    model: str          # message.model of the LAST line; sanitized (below)
    failed: bool        # model == "<synthetic>"
    input: int; output: int; cache_read: int; cache_write: int   # LAST line's usage (AC-099.2)
    agent: str | None   # None = main session; else the subagent file id ("agent-<id>")
    role: str           # "main" for main-session calls; agentType for subagent calls; "unknown" if missing/invalid
    cwd: str | None     # first "cwd" seen in that file (used for subagent attribution only; never stored)

@dataclass
class Session:
    session_id: str
    calls: list[Call]
    found: bool               # the main transcript exists
    malformed: int            # complete lines that are not a JSON object
    problems: list[str]       # e.g. "subagent agent-ab12 unreadable"

def find(session_id: str, root: Path) -> Path | None          # <root>/*/<session_id>.jsonl
def read_session(session_id: str, root: Path, *, deadline: Callable[[], bool]) -> Session
def read_project_dir(path: Path, *, since: datetime, deadline) -> list[Session]   # every *.jsonl modified at/after since
def cwd_slug(path: Path) -> str                                 # realpath, "/" and "." -> "-"
```

- Token fields: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` of
  `message.usage`; a missing one is 0. Only lines with `type == "assistant"` and a `message.usage` dict are calls.
- A final line without a trailing newline is still being written and is skipped silently. It is not malformed.
- Main-file lines with `isSidechain: true` (older layout) count as a subagent with role `unknown`.
- Subagents: `<session dir>/subagents/agent-*.jsonl`. The role is `agentType` from the matching `.meta.json`. Its
  `description` is never read into any structure.
- Sanitizing: a model or role that does not match `^[A-Za-z0-9._:@/-]{1,80}$` becomes `unknown` (AC-099.9).
- `deadline()` is checked at least every 1000 lines and before each file. When it is true, reading stops and the
  `Session` holds what was read so far.

### Price table (`prices.json`)

```json
{"taken": "2026-10-25", "source": "https://www.anthropic.com/pricing", "unit": "USD per million tokens",
 "models": {"claude-opus-4-5": {"input": 5.0, "cache_write": 6.25, "cache_read": 0.5, "output": 25.0}}}
```

`cache_write` is the 5-minute cache write price. The lookup tries the exact model id first, then the longest key `k`
for which the id starts with `k + "-"` (so `claude-sonnet-4-5-20250929` matches `claude-sonnet-4-5`).

### Costing (`usage_cost.py`)

```python
def load_prices(path: Path = DEFAULT) -> Prices            # Prices(taken: str, models: dict[str, dict[str, float]])
def model_cost(prices, model, input, output, cache_read, cache_write) -> float | None   # None = unpriced
def section(items: Iterable[Attributed], prices) -> dict    # totals / by_phase / by_role / by_model
# Attributed = (call: Call, share: float, phase: str | None, role: str); phase None -> omitted by for_session
```

Cost = (input·p_in + cache_write·p_cw + cache_read·p_cr + output·p_out) / 1e6 × share.

### The `usage` section (in the 087 record)

```json
"usage": {
  "sessions": ["<session uuid>"],
  "price_table": "2026-10-25",
  "incomplete": null,
  "totals":   {"calls": 12, "failed_calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
               "cost_usd": 1.234567, "cost_complete": true, "models_without_price": []},
  "by_phase": {"<phase name>": B, "unphased": B},
  "by_role":  {"main": B, "main (shared)": B, "svc:coder": B, "unknown": B},
  "by_model": {"<model id>": B, "(failed)": B}
}
```

`B` = `{"calls", "failed_calls", "input", "output", "cache_read", "cache_write", "cost_usd"}`. Only buckets with at
least one call appear.

- `cost_usd`: in a `by_model` bucket of an unpriced model, `"unknown"`. Everywhere else it is the sum of the known
  costs (a number). `(failed)` is always `0`. `totals.cost_complete` is false iff `models_without_price` is non-empty.
  That list is sorted and holds no duplicates (AC-099.7).
- `incomplete`: `null`, or the reasons joined by `"; "`, from: `transcript not found: <session>`, `<n> malformed
  lines`, `subagent <agent-id> unreadable`, `time budget of 10 s used up`, `error: <ExceptionType>` (AC-099.8).
- Invariant (AC-099.1): for every field of `B`, the sums over `by_phase`, over `by_role` and over `by_model` equal
  `totals`, within 1e-6. For `cost_usd`, compare the known parts.
- The record never holds anything else from the transcripts (AC-099.9). `runs._scrub` keeps `usage.sessions` verbatim.
- The `usage` key is added to `runs.RESERVED`. A record with no source has no `usage` key.

### Gates and benchmark fields (in the 087 record)

```json
"gates": {"acceptance": "passed" | "failed" | "not run", "security": "passed" | "failed" | "not run"}
"benchmark_of": "<benchmark run_id>"
"benchmark": {"workflow": "quick-task" | "build" | "ship", "task_version": 1, "sample_repo": "ika100/todo-api",
              "sample_rev": "<40 hex>", "reset": "done" | "failed" | "not run", "reset_note": "<short text or null>"}
```

`gates` is written for kinds `ship` and `build` only. The last `cplat runs gate` call for a gate wins.
`benchmark_of` is copied from `$CPLAT_BENCHMARK` at `start`, and is added to `runs._IDENTIFIERS`.

### Sources ledger (`runs_usage`)

`<runs.state_dir()>/usage/sources.json`: a list of entries, written under `runs._locked()`.

```json
{"run_id": "...", "mode": "claim" | "own", "session": "<uuid>" | null, "project_dir": "<abs path>" | null,
 "dir": "<abs path the run was started in>", "started_at": "<iso>", "ended_at": "<iso>" | null}
```

```python
def register(run_id, *, mode, session=None, project_dir=None, started_at=None, dir=None) -> None   # never raises
def for_run(rec: dict, *, ended_at: str, budget_s: float = 10.0) -> dict | None   # never raises; sets the entries' ended_at
def for_session(session_id: str) -> dict          # LookupError("no transcript for session <id> on this machine")
def projects_root() -> Path
```

- `runs.start` registers `mode=claim` for `$CLAUDE_CODE_SESSION_ID` (with `dir` = git toplevel of the cwd, else the
  cwd), except for kinds `headless` and `benchmark`. An attached `begin` starts nothing and registers nothing.
- An entry with `ended_at: null` whose active record no longer exists is ignored. Entries that ended more than 2 days
  ago are pruned on every write.

Attribution in `for_run` (window `W = [rec.started_at, ended_at]`, inclusive):

```
own source (session or project_dir): every call of its sessions with at in W
                                     role = "main" for main calls, else the call's role; share 1
claim source, session S:
  claims(S) = ledger entries with mode=claim and session=S (live ones: end = +inf)
  main call c with at in W:  n = |{k in claims(S) : k.start <= c.at <= k.end}|
                             share = 1/n; role = "main" if n == 1 else "main (shared)"
  subagent A: first = min(at of its calls); cand = {k in claims(S): k.start <= first <= k.end}
              owner = the k in cand whose dir is the longest path prefix of A.cwd;
                      else the latest k.start (ties: highest run_id)
              owner == this run -> each call of A with at <= ended_at, share 1, role = A's role
phase of a call = the deepest phase (most ":") with started_at <= at <= ended_at, ties -> latest started;
                  none -> "unphased"   (AC-099.3; phases are taken as closed at ended_at)
```

The budget is measured with `runs.monotonic()`. When it runs out, the section holds what was counted, plus
`time budget of 10 s used up`. `runs.finish` computes `now` first, collects usage *outside* the lock from a copy of
the active record, then writes the record with that same `now`. The 20 s flush budget starts after collection.

### CLI

```
cplat runs usage <run_id> [--json]
cplat runs usage --session <session_id> [--json]
cplat runs gate <acceptance|security> <passed|failed> [--dir D]
cplat runs benchmark <quick-task|build|ship> [--reset-first]
cplat runs report --benchmarks [--json] [--since DAYS]
```

**`runs usage <run_id>`.** It looks up the record in the local buffer, then in the store files for the run id's date
and the day after (the run id starts with `YYYYMMDDTHHMMSSZ`). Text output:

```
Usage of run <run_id> (<kind>, <outcome>); estimate from the price table of <date>[; incomplete: <reason>]
<label>            calls  failed  input  output (as reported)  cache read  cache write  cost USD (est.)
total              ...
By phase:  one row per bucket
By role:   one row per bucket
By model:  one row per bucket ("unknown" for an unpriced model's cost)
Output cost is a lower bound: output tokens are taken as the transcripts report them.
[Cost incomplete: no price for <m1>, <m2>.]
```

`--session <id>` prints the same with the header `Usage of session <id> (this machine)` and no "By phase" block.
`--json` prints exactly one document and nothing else on stdout:
`{"run_id", "kind", "outcome", "usage": {...}}` or `{"session": "<id>", "usage": {sessions, price_table, incomplete,
totals, by_role, by_model}}`. Errors raise `PlatformError` (non-zero exit), one message each:

- `run <id> not found in the run store <slug> or the local buffer` (without a store: `... in the local buffer (no run
  store configured)`);
- `run <id> has no usage section (recorded before spec 099, or started outside a Claude Code session)`;
- `no transcript for session <id> on this machine`.

**`runs gate`.** It sets `gates.<gate>` on the current run (the same pointer resolution as `cplat runs phase`). It
prints nothing and never fails a command.

**`runs report`** (AC-099.11). `aggregate` adds this key and leaves the others unchanged:

```json
"usage": {"price_tables": ["2026-10-25"],
          "kinds": {"ship": {"delivered": G, "failed": G, "escalated": G, "abandoned": G, "gate_failed": G,
                             "no_usage": 2}}}
```

`G` = `{"runs", "tokens", "tokens_median", "cost_usd", "cost_usd_median", "cost_incomplete"}`. A run's tokens are
input + output + cache_read + cache_write of its `totals`. Medians are `null` for an empty group. `cost_incomplete`
counts the group's runs with `cost_complete: false`. Delivered means outcome `done` and no gate `failed`; gate-failed
means outcome `done` with a gate `failed`. `no_usage` counts the kind's records without `usage`, whatever their
outcome. Records of kind `benchmark` or with `benchmark_of` are left out. The text report appends one line per kind
after the existing ones, under a heading that says "estimate, prices of <dates>; output as reported, output cost is a
lower bound".

**`runs report --benchmarks`** (AC-099.13). It cannot be combined with `--agents`: that raises `PlatformError`.
`--json` prints:

```json
{"window": {...as in the report...},
 "benchmarks": {"<workflow>": {"<platform_version>": {"runs": 3, "tokens_median": 0, "cost_usd_median": 0.0,
                                                    "outcomes": {"done": 2, "failed": 1}}}}}
```

Only records of kind `benchmark` count. The text output has one row per workflow and version, and labels the cost as
an estimate.

**`runs benchmark <workflow>`** (AC-099.13, AC-099.15). The steps:

1. An unknown workflow is an argparse error (exit 2, the valid choices are named). No record is written.
2. Load `scripts/cplat/benchmark/tasks.json`:
   ```json
   {"version": 1, "sample": {"repo": "ika100/todo-api", "rev": "<40 hex>"},
    "workflows": {"quick-task": {"task_version": 1, "prompt": "/svc:quick-task <fixed fix>", "max_runs": 1, "max_minutes": 30},
                  "build": {"task_version": 1, "spec_file": "spec-900.md", "spec_id": "900-<slug>", "prompt": "/svc:build 900", "max_runs": 2, "max_minutes": 120},
                  "ship":  {"task_version": 1, "spec_file": "spec-900.md", "spec_id": "900-<slug>", "prompt": "/svc:ship 900", "max_runs": 4, "max_minutes": 240}}}
   ```
3. `git ls-remote https://github.com/<repo> refs/heads/main`. On failure, raise `PlatformError("sample repo <repo>
   cannot be reached: <reason>")` and write no record. If `main` is not at `rev`: without `--reset-first`, raise
   `PlatformError("sample repo <repo>: main is at <x>, not the pinned <rev>", hint="cplat runs benchmark <wf>
   --reset-first")`, with no record. With `--reset-first`, reset (step 7) first. If that reset fails, raise and
   write no record.
4. Clone into `<state_dir>/benchmark/<workflow>-<UTC stamp>` and check out `rev` as local `main`. For `build` and
   `ship`, copy `benchmark/<spec_file>` to `docs/specs/<spec_id>/spec.md` and commit it locally.
5. `rid = runs.start("benchmark", repo=<repo>, mode="headless")`, then `runs_usage.register(rid, mode="own",
   project_dir=<projects_root>/<cwd_slug(clone)>)`, then phase `benchmark:run`.
6. With `CPLAT_RUN_PARENT=rid` and `CPLAT_BENCHMARK=rid` set in `os.environ` (restored afterwards), call
   `headless.main(["--repo", clone, "--max-runs", n, "--max-minutes", m, prompt])`. Exit 0 → outcome `done`;
   anything else, or an exception, → `failed`.
7. Phase `benchmark:reset`. Reset the sample repo for every workflow: close its open PRs and delete their branches;
   delete the remote branches other than `main`; delete the tags that are not ancestors of `rev`, with their GitHub
   releases; `git push --force <url> <rev>:refs/heads/main`; then check that `ls-remote` shows `rev`. Every step is
   run through one replaceable `run(cmd, cwd) -> (code, out, err)`.
8. `runs.finish(rid, outcome, fields={"benchmark": {...}})`. If the reset failed, raise `PlatformError("reset of
   sample repo <repo> failed: <reason>; the benchmark record was written")` afterwards (non-zero exit).
9. On success, print one line: `benchmark <wf> v<task_version> on <repo>@<rev[:7]>: <outcome>, <tokens> tokens,
   est. USD <cost> (prices of <date>); reset <status>`.

## Risks

- `$CLAUDE_CODE_SESSION_ID` needs Claude Code 2.1.132 or later. Without it, a run has no usage section and counts as
  "no usage data". It never fails.
- Subagent attribution by cwd and start time is a heuristic. Two runs in the same directory, started in the same
  second, by the same session, cannot be told apart. The later-started run gets the subagent.
- A subagent still running when its run ends is counted only up to `ended_at`.
- Large transcripts: every complete line is parsed with `json.loads`. Files modified before the run started are
  skipped (for `project_dir` sources). The 10 s budget is the backstop.
- The ship benchmark deploys to the sample's dev through `ika100/todo`. That gitops entry is not reset: dev keeps the
  benchmark's image until the next deploy.
