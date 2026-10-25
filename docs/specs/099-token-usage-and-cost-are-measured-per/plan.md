---
spec_id: 099-token-usage-and-cost-are-measured-per
spec_hash: e51ac22a7f79
summary: usage section (totals, by_phase/role/model, estimated cost) in the 087 run record from local session
  transcripts; gates in ship/build records; cplat runs usage, cplat runs gate, cplat runs benchmark, report usage and
  --benchmarks
tasks:
- id: t1
  title: Transcript reader (calls per session and subagent, deduped, malformed counted)
  files: [scripts/cplat/transcripts.py]
  covers: [AC-099.2, AC-099.4, AC-099.6, AC-099.8, AC-099.9]
  parallel_safe: true
  depends_on: []
- id: t2
  title: Price table and costing / section builder
  files: [scripts/cplat/prices.json, scripts/cplat/usage_cost.py]
  covers: [AC-099.1, AC-099.6, AC-099.7]
  parallel_safe: true
  depends_on: []
- id: t3
  title: Usage attribution per run (sources ledger, window, phase, role, shared split, 10 s budget)
  files: [scripts/cplat/runs_usage.py]
  covers: [AC-099.1, AC-099.3, AC-099.4, AC-099.8, AC-099.9, AC-099.14]
  parallel_safe: true
  depends_on: [t1, t2]
- id: t4
  title: Usage in runs report, the --benchmarks aggregate, text rendering of one usage section
  files: [scripts/cplat/runs_usage_report.py, scripts/cplat/runs_report.py]
  covers: [AC-099.7, AC-099.10, AC-099.11, AC-099.12, AC-099.13]
  parallel_safe: true
  depends_on: []
- id: t5
  title: cplat runs usage (run id or session)
  files: [scripts/cplat/runs_usage_cli.py]
  covers: [AC-099.9, AC-099.10]
  parallel_safe: true
  depends_on: [t3, t4]
- id: t6
  title: cplat runs benchmark (fixed tasks, sample clone, reset)
  files: [scripts/cplat/runs_bench.py, scripts/cplat/benchmark/tasks.json, scripts/cplat/benchmark/spec-900.md]
  covers: [AC-099.13, AC-099.15]
  parallel_safe: true
  depends_on: [t3]
- id: t7
  title: headless names its sessions and owns them as usage sources
  files: [scripts/cplat/headless.py]
  covers: [AC-099.1, AC-099.8]
  parallel_safe: true
  depends_on: [t3]
- id: t8
  title: Wire usage, gates and benchmark marking into runs start/finish and the runs CLI
  files: [scripts/cplat/runs.py, scripts/cplat/cplat.py]
  covers: [AC-099.1, AC-099.3, AC-099.8, AC-099.9, AC-099.10, AC-099.11, AC-099.12, AC-099.13, AC-099.14]
  parallel_safe: false
  depends_on: [t3, t4, t5, t6]
- id: t9
  title: /svc:build records the acceptance and security gates; plugin version bump
  files: [plugins/svc/commands/build.md, plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
  covers: [AC-099.12]
  parallel_safe: true
  depends_on: []
- id: t10
  title: Docs (changelog, unattended-delivery guide, ADR index)
  files: [docs/CHANGELOG.md, docs/unattended-delivery.md, docs/adr/README.md]
  covers: [AC-099.10, AC-099.11, AC-099.13]
  parallel_safe: true
  depends_on: []
human_steps:
- Check that Claude Code is 2.1.132 or later on the machines that run deliveries (`claude --version`); older versions do not set CLAUDE_CODE_SESSION_ID, so their runs record no usage.
- Before the first `cplat runs benchmark`, make sure ika100/todo-api main is at the revision pinned in scripts/cplat/benchmark/tasks.json (or run once with --reset-first), and that nobody else needs that repo's main to move during benchmarks.
---

# Plan — 099 Token usage and cost are measured per run

The binding contract is in [design.md](design.md). Each task below names the design section it implements, so a
coder only has to read that section.

## t1 — Transcript reader

**Files:** scripts/cplat/transcripts.py
**Covers:** AC-099.2, AC-099.4, AC-099.6, AC-099.8, AC-099.9
**Goal:** a small pure-I/O module that turns one session id (or one project directory) into a list of `Call`s. It
knows nothing about runs, prices or phases. Contract: design.md "Transcript reading".

**Implementation notes:**
- `find(session_id, root)` globs `root/*/<session_id>.jsonl` (exactly one level). The subagents are in
  `<that dir>/<session_id>/subagents/agent-*.jsonl`, with `agent-*.meta.json` next to them. Read only `agentType`.
- Read line by line. Skip a final line without `\n`. Count every other line that is not a JSON object as malformed.
  A call is `type == "assistant"` with a `message.usage` dict.
- Dedupe by `message.id` within a file (fallback: the line `uuid`). Take tokens and model from the last line and `at`
  from the first line. `failed = model == "<synthetic>"`.
- Sanitize model and role with `^[A-Za-z0-9._:@/-]{1,80}$`, else `unknown`. Never keep text from `message.content`,
  tool fields or the description.
- `deadline` callable checked every 1000 lines and before each file. `cwd_slug(path)` is for the benchmark.
- An unreadable subagent file or meta file goes in `problems` (role `unknown` for an unreadable meta).

**Done when:** the acceptance tests for AC-099.2 and the reader parts of AC-099.4/.6/.8/.9 pass. Unit tests cover the
unterminated last line and the old `isSidechain` layout.

## t2 — Price table and costing

**Files:** scripts/cplat/prices.json, scripts/cplat/usage_cost.py
**Covers:** AC-099.1, AC-099.6, AC-099.7
**Goal:** the price table and the one function that turns attributed calls into the `totals` / `by_phase` / `by_role`
/ `by_model` part of the usage section. Contract: design.md "Price table", "Costing", "The usage section".

**Implementation notes:**
- `prices.json`: Anthropic list prices on the day you write it (anthropic.com/pricing), for the current Opus, Sonnet
  and Haiku models and for every model id in the local transcripts (`message.model` under `~/.claude/projects`). Use
  the 5-minute cache-write price. Set `taken` to that date.
- Lookup: exact id, else the longest key `k` with `id.startswith(k + "-")`.
- `section(items, prices)` takes `(call, share, phase, role)` tuples. `phase=None` everywhere means "no by_phase key"
  (for `--session`). Failed calls go in the `by_model["(failed)"]` bucket at cost 0. An unpriced model's `by_model`
  cost is `"unknown"`, and the known sum appears everywhere else.
- Numbers are integers when whole, else rounded to 6 decimals. Only buckets with calls appear.
- `totals.cost_complete` and `models_without_price` (sorted, unique).

**Done when:** the sum invariant (AC-099.1) holds in unit tests with fractional shares, and the acceptance tests for
AC-099.6 and AC-099.7 that use `usage_cost` directly pass.

## t3 — Usage attribution per run

**Files:** scripts/cplat/runs_usage.py
**Covers:** AC-099.1, AC-099.3, AC-099.4, AC-099.8, AC-099.9, AC-099.14
**Goal:** `register`, `for_run`, `for_session` and `projects_root` as in design.md "Sources ledger". This module
decides which calls of which sessions belong to a run, with which share, phase and role. It then calls
`usage_cost.section` and adds `sessions`, `price_table` and `incomplete`.

**Implementation notes:**
- Ledger at `runs.state_dir()/usage/sources.json`, changed only under `runs._locked()`. Import `runs` lazily inside
  functions (`runs` imports this module lazily too). Prune entries that ended more than 2 days ago.
- `register` never raises. `for_run` never raises: an exception becomes `incomplete: "error: <Type>"`, with the counts
  so far. A run with no ledger entry returns `None`.
- Use the attribution pseudocode exactly. A live claim is `ended_at is None` and `runs.active(run_id)` is not None. A
  dead one (no active record) is ignored. The finishing run uses its own `ended_at`. Then it sets `ended_at` on its
  entries.
- Phase lookup: the deepest phase that holds the call (ties: the latest started), else `unphased`.
- Budget: `runs.monotonic()`, 10 s, passed to the reader as `deadline`.
- `for_session(id)`: all calls of the session and its subagents, no window and no phases, share 1. Raises
  `LookupError` when `transcripts.find` finds nothing.
- `projects_root()`: `$CLAUDE_CONFIG_DIR/projects`, else `~/.claude/projects`.

**Done when:** the acceptance tests for AC-099.3, AC-099.4, AC-099.8 and AC-099.14 that call `runs_usage` pass. A
unit test shows two overlapping claims of one session that together hold every call once.

## t4 — Usage in the report, benchmarks aggregate, rendering

**Files:** scripts/cplat/runs_usage_report.py, scripts/cplat/runs_report.py
**Covers:** AC-099.7, AC-099.10, AC-099.11, AC-099.12, AC-099.13
**Goal:** pure functions over records and usage sections. Contract: design.md "CLI", the `runs report`,
`--benchmarks` and `runs usage` text parts.

**Implementation notes:**
- `aggregate_usage(records) -> dict`: the `usage` key (kinds → delivered / failed / escalated / abandoned /
  gate_failed groups + `no_usage`). Leave out kind `benchmark` and any record with `benchmark_of`. A gate is failed
  when any `gates` value is `"failed"`.
- `render_usage_lines(agg_usage) -> list[str]`: the report lines, with the estimate and price-date labels.
- `aggregate_benchmarks(records, *, since_days, repo, store, now, malformed) -> dict` and `render_benchmarks_text`.
  Reuse `runs_report.select` for the window.
- `render_section(header, usage, *, phases: bool) -> str`: the `runs usage` text with the "output (as reported)"
  column, the lower-bound line, `unknown` costs and the cost-incomplete line.
- `runs_report.py`: `aggregate` adds `"usage": runs_usage_report.aggregate_usage(kept)`, and `render_text` appends
  `render_usage_lines`. Change no existing key or line.

**Done when:** the acceptance tests for AC-099.11 and the `--benchmarks` part of AC-099.13 pass at the
`runs_report` / `runs_usage_report` level. The existing `test_runs_report*.py` tests stay green.

## t5 — cplat runs usage

**Files:** scripts/cplat/runs_usage_cli.py
**Covers:** AC-099.9, AC-099.10
**Goal:** `main(argv) -> int` for `cplat runs usage <run_id> | --session <id> [--json]`, as in design.md "CLI".

**Implementation notes:**
- Look up the record: first `runs._safe_buffer()`, then (if `runs.configured_repo()`) `runs.open_store(slug).read([day,
  day+1])`, where the day comes from the run id prefix, parsed with `runs_report.parse`. The last line with the run id
  wins.
- Raise the three `PlatformError` messages of the design, verbatim.
- `--json` prints one `json.dumps` document and nothing else on stdout. Text goes through
  `runs_usage_report.render_section`.
- `--session`: `runs_usage.for_session`. `LookupError` becomes the `PlatformError`.

**Done when:** the acceptance tests for AC-099.10 pass, and AC-099.9's check on the printed output passes.

## t6 — cplat runs benchmark

**Files:** scripts/cplat/runs_bench.py, scripts/cplat/benchmark/tasks.json, scripts/cplat/benchmark/spec-900.md
**Covers:** AC-099.13, AC-099.15
**Goal:** `main(argv) -> int` that follows the 9 steps of design.md "runs benchmark".

**Implementation notes:**
- `tasks.json`: sample `ika100/todo-api`; `rev` = the current `main` sha (`gh api repos/ika100/todo-api/commits/main
  -q .sha`). The quick-task prompt is one fixed small fix in that repo, touching one file with no new dependency.
  `spec-900.md` is one fixed small spec in spec format (status `approved`, 2 criteria, no gitops change). Read the
  sample repo before choosing both.
- Every git/gh call goes through one module-level `run(cmd, cwd=None) -> (code, out, err)` that tests replace.
  `headless.main` is called in process; tests replace it too.
- Order matters for AC-099.13: no record before the reachability and pinned-revision checks pass. Once `runs.start`
  has run, the record is always finished (try/finally), including when the reset fails (AC-099.15).
- Register the usage source with `mode="own"` and `project_dir=runs_usage.projects_root() /
  transcripts.cwd_slug(clone)`.
- Set and restore `CPLAT_RUN_PARENT` and `CPLAT_BENCHMARK` around the headless call.

**Done when:** the acceptance tests for AC-099.13 (record fields, the no-record failures) and AC-099.15 (reset noted,
reset failure exits non-zero and the record is still written) pass with `run` and `headless.main` replaced.

## t7 — headless names its sessions

**Files:** scripts/cplat/headless.py
**Covers:** AC-099.1, AC-099.8
**Goal:** each launched `claude -p` session gets `--session-id <uuid4>`, registered as an owned usage source of the
headless run, so the headless record carries usage.

**Implementation notes:**
- In `_drive`, per session: `sid = str(uuid.uuid4())`, run `cmd + ["--session-id", sid]`, then
  `runs_usage.register(rid, mode="own", session=sid)` before `run_once`. Keep `claude_cmd` and `--dry-run` output
  unchanged.
- Registration failures never change the headless result.

**Done when:** a unit test with a fake `claude` sees a distinct `--session-id` per session, and the headless record
has a `usage` section counting those sessions' calls.

## t8 — Wire it into runs.py and the CLI

**Files:** scripts/cplat/runs.py, scripts/cplat/cplat.py
**Covers:** AC-099.1, AC-099.3, AC-099.8, AC-099.9, AC-099.10, AC-099.11, AC-099.12, AC-099.13, AC-099.14
**Goal:** the record gains `usage`, `gates` and `benchmark_of`, and `cplat runs` gains `usage`, `gate`, `benchmark`
and `report --benchmarks`. Contract: design.md "The usage section", "Gates and benchmark fields", "Sources ledger",
"CLI".

**Implementation notes:**
- `RESERVED += {"usage"}`; `_IDENTIFIERS += {"benchmark_of"}`. `_scrub` keeps `("usage", "sessions")` values
  verbatim.
- `start`: copy `$CPLAT_BENCHMARK` to `benchmark_of`. If `$CLAUDE_CODE_SESSION_ID` is set and the kind is not
  `headless` or `benchmark`, call `runs_usage.register(rid, mode="claim", session=..., started_at=rec["started_at"],
  dir=<git toplevel of cwd or cwd>)`. Lazy import, in a try block.
- `finish`: take `now` first. Read a copy of the active record and close its open phases at `now`. Call
  `runs_usage.for_run(copy, ended_at=now)` outside the lock, and only then start the 20 s flush clock. Under the lock,
  use the same `now`, set `rec["usage"]` when it is not None, and for kinds `ship` / `build` fill missing
  `gates.acceptance` / `gates.security` with `"not run"`. Outcome, exit code and stdout stay as they are.
- `main`: `argv[:1] == ["usage"]` → `runs_usage_cli.main`; `["benchmark"]` → `runs_bench.main` (like `agent`).
  Add the `gate` subparser (choices; `--dir`) and handle it in `_recording_command` like `phase`. Add
  `report --benchmarks` (with `--agents` it raises `PlatformError`), which prints
  `runs_usage_report.aggregate_benchmarks` / `render_benchmarks_text`.
- Update the docstrings in `runs.py` and the `runs` line in `cplat.py`.

**Done when:** the end-to-end acceptance tests through `runs.start` / `runs.finish` / `runs.main` pass for AC-099.1,
.3, .8 (outcome and output unchanged, at most 10 s), .9, .10, .11, .12 and .14. `tests/cplat/test_runs*.py` stay
green.

## t9 — /svc:build records the gates

**Files:** plugins/svc/commands/build.md, plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-099.12
**Goal:** the orchestrator states each gate's result where it is decided.

**Implementation notes:**
- Phase 2: when every acceptance test passes, run `cplat runs gate acceptance passed`. Before escalating because they
  still fail after the fix rounds, run `cplat runs gate acceptance failed`.
- Phase 3: when `devbox run ci` is green, run `cplat runs gate security passed`. When the security gate stays red
  (escalation, or a HIGH finding documented while the build goes on), run `cplat runs gate security failed`.
- Bump the svc plugin minor version in both `plugin.json` and `marketplace.json`.

**Done when:** `devbox run validate` passes and the build.md lines name both gates at the points above.

## t10 — Docs

**Files:** docs/CHANGELOG.md, docs/unattended-delivery.md, docs/adr/README.md
**Covers:** AC-099.10, AC-099.11, AC-099.13
**Goal:** users can find and read the new numbers.

**Implementation notes:**
- CHANGELOG `Unreleased`: the usage section, `cplat runs usage`, `runs gate`, `runs benchmark`, `report --benchmarks`.
  Say that costs are estimates and that Claude Code 2.1.132 or later is needed.
- unattended-delivery.md, next to the run-record and report section: what `usage` holds; that output is "as
  reported" and output cost is a lower bound; delivered vs. gate-failed; how to run a benchmark and what the reset
  does to ika100/todo-api.
- ADR index row: `| [035](../../adr/035-token-usage-from-session-transcripts.md) | Token usage is measured from the local
  session transcripts: sessions claimed via CLAUDE_CODE_SESSION_ID, shared calls split evenly, costs estimated from a
  price table in the repo |`.

**Done when:** `devbox run validate` passes (Markdown links included).
