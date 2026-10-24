---
spec_id: 087-every-run-is-recorded-in-a-private-run
spec_hash: f83113c9dfda
summary: runs.py record API with a local buffer, a private GitHub run store (one file per run, one commit per flush), cplat runs init/flush/report, recording in ship, pr wait, build, headless and doctor
tasks:
- id: t1
  title: Record API, local buffer, flush and the cplat runs CLI
  files: [scripts/cplat/runs.py, scripts/cplat/cplat.py, tests/cplat/conftest.py]
  covers: [AC-087.5, AC-087.6, AC-087.7, AC-087.8, AC-087.9, AC-087.10, AC-087.15, AC-087.19, AC-087.20, AC-087.21, AC-087.22, AC-087.23]
  parallel_safe: true
  depends_on: []
- id: t2
  title: GitHub run store transport over gh api
  files: [scripts/cplat/runs_store.py]
  covers: [AC-087.8, AC-087.9, AC-087.20]
  parallel_safe: true
  depends_on: []
  done: true
- id: t3
  title: Report aggregation and rendering
  files: [scripts/cplat/runs_report.py]
  covers: [AC-087.14, AC-087.17, AC-087.18]
  parallel_safe: true
  depends_on: []
- id: t4
  title: Ship and pr wait record their runs
  files: [scripts/cplat/ship.py, scripts/cplat/pr.py]
  covers: [AC-087.1, AC-087.3, AC-087.4, AC-087.5, AC-087.16]
  parallel_safe: true
  depends_on: [t1, t2]
- id: t5
  title: Headless records; build and ship commands call cplat runs
  files: [scripts/cplat/headless.py, plugins/svc/commands/build.md, plugins/svc/commands/ship.md]
  covers: [AC-087.5, AC-087.6]
  parallel_safe: true
  depends_on: [t1, t2]
- id: t6
  title: Doctor run store check
  files: [scripts/cplat/doctor.py]
  covers: [AC-087.11]
  parallel_safe: true
  depends_on: [t1, t2]
- id: t7
  title: Docs for the run store
  files: [docs/CHANGELOG.md, docs/unattended-delivery.md, plugins/shared/README.md, plugins/svc/README.md]
  covers: []
  parallel_safe: true
  depends_on: []
---

The contract for every task is [design.md](design.md). ADR: [032](../../adr/032-private-run-store.md). Recording must
never change a run's outcome, exit code or stdout: every call into `runs` from other modules is either a mutator
(never raises) or `runs.finish` (never raises, at most one stderr line).

## t1 — Record API, local buffer, flush and the cplat runs CLI

**Files:** scripts/cplat/runs.py, scripts/cplat/cplat.py, tests/cplat/conftest.py
**Covers:** AC-087.5, AC-087.6, AC-087.7, AC-087.8, AC-087.9, AC-087.10, AC-087.15, AC-087.19, AC-087.20, AC-087.21, AC-087.22, AC-087.23
**Goal:** the `runs` module exactly as in design.md "Python API": start / link_parent / attach_point, the in-place
mutators, `finish`, `flush`, `store_status`, `init`, and the `cplat runs` subcommands. It talks to the store only through
`open_store(slug)`, which returns a `runs_store.Store` (t2), and renders reports through `runs_report` (t3).

**Implementation notes:**
- State dir, `active/<run_id>.json`, `buffer.jsonl`, `filings.jsonl`, all under an `fcntl` lock. Write files atomically
  (temp file + `os.replace`).
- `run_id` = `%Y%m%dT%H%M%SZ` of `utcnow()` + `-` + `secrets.token_hex(4)`. Timestamps are `%Y-%m-%dT%H:%M:%SZ`.
- Phase levels by `:` count, as in the contract. `event` upserts by `id` with `dict.update`.
- `finish`: close phases, set fields, coerce the cause and the outcome, redact every non-identifier string with
  `feedback.redact` and cut it to 500 chars, add the line to the buffer (cap 1000, oldest by `ended_at`/`at` dropped),
  remove the active file, then `flush(budget=remaining)`. The warning line is in the exact format of the contract, on
  stderr. Everything sits in `try/except Exception`.
- `flush`: visibility first (not private → nothing written). Then each pending filing once (`FILERS[name]`, else
  `importlib.import_module(name).retry_filing`), only while at least half the budget is left. Then the buffer in
  `ended_at`/`at` order, 200 per `Store.put`, each written batch removed by key. Per-call deadline as in the contract.
- `begin` / `phase` / `end` with the pointer `<git common dir>/cplat-run.json`. They always exit 0.
- `init`: `visibility()` → `StoreMissing` → `create_private()`. Public → `PlatformError` and nothing changes. Print
  `export CPLAT_RUNS_REPO=<slug>   # add this to your shell profile`.
- `report`: config check, then `store.visibility()` (`StoreError` → unreachable error), then `store.read(days)`, then
  `runs_report.parse/aggregate`, then text, or `json.dumps(agg, indent=2)` alone on stdout for `--json`.
- `cplat.py`: `"runs": "runs"` in `COMMANDS`, and the docstring line
  `cplat.py runs init|flush|report|begin|phase|end ...   private run records (spec 087, ADR-032)`.
- `conftest.py`: an autouse fixture that sets `CPLAT_RUNS_DIR` to a per-test tmp dir and unsets `CPLAT_RUNS_REPO` and
  `CPLAT_RUN_PARENT`, so no test touches the user's buffer or GitHub.

**Done when:** together with t2 and t3, the acceptance tests for AC-087.7–.10, .15, .19–.23, the API part of AC-087.5/.6
(`cplat runs begin/phase/end`, `link_parent`) and the CLI part of AC-087.14/.17/.18 pass, and the full
`tests/cplat` suite is green (no existing test writes outside its tmp dir).

## t2 — GitHub run store transport over gh api

**Files:** scripts/cplat/runs_store.py
**Covers:** AC-087.8, AC-087.9, AC-087.20
**Goal:** `StoreError` / `StoreMissing` / `StoreUnreachable`, the `Store` protocol, `GitHubStore` and `record_path`,
exactly as in design.md "Transport". Every subprocess call goes through `runs_store.gh`, so tests can fake GitHub.

**Implementation notes:**
- `gh(args, input=, timeout=)` returns `(code, out, err)`. A timeout or a missing `gh` is `(124 | 127, "", reason)`.
  It never raises.
- `visibility`: `gh api repos/{slug}`. 404 → `StoreMissing`. Any other non-zero exit → `StoreUnreachable(<last stderr line>)`.
  `visibility` comes from the JSON (fallback `private: true/false`), and `default_branch` is cached.
- `put`: the 5-call Git Data sequence with `--input -` JSON bodies. Retry from the ref read on a 409/422 ref update, at
  most 3 attempts. An empty repo (ref 404/409) gets one Contents-API `README.md` first.
- `read`: GraphQL with ≤ 40 day aliases per query; `null` directories are skipped; returns `(path, text)`.
- `create_private`: `gh repo create {slug} --private --add-readme --description ...`. Non-zero → `StoreUnreachable`.
- `record_path`: `runs/YYYY/MM/DD/<run_id>.json`, with the date from `ended_at`. A follow-up's date comes from `at`,
  and its name is `<run_id>.filed.<sha1(signature)[:12]>.json`.

**Done when:** with a fake `runs_store.gh`, a write whose ref update fails once as "not a fast forward" retries and
lands every file; the same files written twice produce identical paths and content; a public or 404 repo raises the
right error. Together with t1, the AC-087.8, .9 and .20 tests pass.

## t3 — Report aggregation and rendering

**Files:** scripts/cplat/runs_report.py
**Covers:** AC-087.14, AC-087.17, AC-087.18
**Goal:** `parse`, `aggregate` and `render_text` as in design.md "Report": pure functions with no I/O, tolerant of old
schemas, unknown kinds and fields, and malformed lines.

**Implementation notes:**
- `parse` splits the texts into lines and skips blank ones. A line that does not parse to a dict counts as malformed.
  A line with `"followup"` is a follow-up.
- `aggregate`: window filter on `ended_at`, `--repo` filter, dedupe by `run_id`, follow-ups merged by
  `(run_id, signature)`, `"unknown"` for anything missing.
- Median (`statistics.median`) and nearest-rank p90 per phase name. Top 10 reasons by count, then by text.
- The JSON keys are exactly `window, runs, phases, causes, escalations, reruns, filed, buffered`. `filed` always has
  `new, +1, suppressed, pending`.
- `render_text` uses the line layout of the contract (it states the malformed count and the buffered count).

**Done when:** the acceptance tests for AC-087.14, .17 and .18 pass (through `cplat runs report` once t1 and t2 are in).

## t4 — Ship and pr wait record their runs

**Files:** scripts/cplat/ship.py, scripts/cplat/pr.py
**Covers:** AC-087.1, AC-087.3, AC-087.4, AC-087.5, AC-087.16
**Goal:** a ship run gets a `run_id`, its phases, CI rounds and reruns, and exactly one end record (`done`,
`escalated` with the cause, or `abandoned`). A resumed escalated run is a new run with `resumes`. `cplat pr wait`
records a `pr-wait` run, or counts toward the ship run it runs inside. See design.md "Integration points".

**Implementation notes:**
- `_ensure_run` and `_record` are called from `save_state` (wrapped). `recorded` makes the end record happen once.
- `start`:
  - The same spec, escalated → `runs.start(..., resumes=old)`.
  - Another spec, unfinished, unescalated, with `take_over` → `runs.finish(old, "abandoned")`. Without the flag, it
    raises with the extended hint.
  - It always calls `runs.link_parent`.
- `escalate(repo, reason, cause="unknown")` and the CLI `--cause` (choices from `runs.CAUSES`). The gate giving up
  stays `cause` unknown.
- `finish`: an unrecorded state → `abandoned`.
- `CheckWatch` and `RunWatch` take `run_id=None`. `runs.rerun` is called at the stale, stuck (queued cancel + rerun)
  and transient rerun points, with `check` = the run's check names, sorted and joined by `, `. `RunWatch`'s rerun uses
  `pin-dev`. `wait_checks` calls `runs.ci_round` once per green or red return. `land`, `merge_gitops` and `deploy`
  pass `st.get("run_id")`.
- `pr.wait`: `attach_point` or its own `pr-wait` run. Green, merged or already merged → `done`. Red, a timeout or any
  `PlatformError` → `failed`, re-raised. The exit code is unchanged.
- Without a store configured, every existing test of `test_ship.py`, `test_ship_checks.py`, `test_tags_and_wait.py`,
  `test_claims.py` and `test_gitops.py` behaves exactly as before. Only stderr may get the one warning line.

**Done when:** the acceptance tests for AC-087.1, .3, .4, .16 and the `pr wait` part of AC-087.5 pass, and the
existing ship, pr-wait and gitops tests stay green.

## t5 — Headless records; build and ship commands call cplat runs

**Files:** scripts/cplat/headless.py, plugins/svc/commands/build.md, plugins/svc/commands/ship.md
**Covers:** AC-087.5, AC-087.6
**Goal:** one `headless` record per invocation (redacted command, sessions, stop reason, the ship runs it drove). Its
sessions run with `CPLAT_RUN_PARENT`. `/svc:build` records a `build` run, or attaches to the ship run.

**Implementation notes:**
- `headless.main`: `runs.start("headless", mode="headless")` after the argument checks, never for `--dry-run`.
  `run_once` adds `CPLAT_RUN_PARENT=<rid>` to the session env. Every exit path goes through one
  `runs.finish(rid, outcome, fields={"command", "sessions", "stop_reason"})` (stop-reason table in design.md). An
  exception is recorded as `error`/`failed` and re-raised. The exit codes `EXIT_DONE`, `EXIT_STOPPED` and
  `EXIT_QUIET` are unchanged.
- `build.md`:
  - Phase 0: `cplat runs begin build --spec <id>`.
  - Start of Phases 1–7: `cplat runs phase build:tests|implement|qa|verify|image|close|pr`.
  - Final Report: `cplat runs end --outcome done`.
  - Each "stop and show the user" rule: `cplat runs end --outcome escalated --reason '<why>'`.
  - One sentence: inside `/svc:ship` these calls attach to the ship run.
- `ship.md`: `cplat ship escalate '<reason>' [--cause platform|code|decision|environment]` in Escalate, and that a
  missing cause is recorded as `unknown`. `--take-over` also ends another spec's unfinished run (recorded `abandoned`),
  only on the user's word. Finish: the run record is written when the run reaches `done` or escalates, and a warning
  line about a buffered record is not an error.

**Done when:** the acceptance tests for AC-087.6 pass (the "ship records carry `mode` `headless`" part also needs t4),
the build part of AC-087.5 passes through `cplat runs begin/phase/end`, and `test_headless.py` stays green.

## t6 — Doctor run store check

**Files:** scripts/cplat/doctor.py
**Covers:** AC-087.11
**Goal:** `check_run_store()` maps `runs.store_status()` to one `run store` check, as in design.md, and is part of `run_checks`.

**Implementation notes:**
- `unset` → warn with fix `cplat runs init <owner/name>`.
- `public` → fail.
- `unreachable` → warn naming the repo.
- Buffered or pending > 0 → warn with both counts and fix `cplat runs flush`.
- Otherwise ok naming the repo.
- `store_status` uses a 10 s timeout. An exception inside it becomes `warn`, never `fail`.

**Done when:** the acceptance tests for AC-087.11 pass, and `test_update_doctor.py` stays green (no store configured
gives a warn, and doctor's exit code is unchanged).

## t7 — Docs for the run store

**Files:** docs/CHANGELOG.md, docs/unattended-delivery.md, plugins/shared/README.md, plugins/svc/README.md
**Covers:** none (documentation)
**Goal:** users learn how to set up and read the run store.

**Implementation notes:**
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feature (087): every run is recorded in a private run
  store.** It covers `cplat runs init <owner/name>`, `CPLAT_RUNS_REPO`, the local buffer (1000), `cplat runs flush`,
  `cplat runs report [--json]`, the doctor check and ADR-032. Only this task edits the CHANGELOG.
- `docs/unattended-delivery.md`: a "Run records" section covering setup (`cplat runs init`, the env line in the shell
  profile that Claude sessions read), what a record holds and never holds, offline behaviour, `report` and `flush`.
- `plugins/shared/README.md` and `plugins/svc/README.md`: one line each where `cplat ship` / `pr wait` / `headless`
  are described: runs are recorded (spec 087), see `cplat runs report`.
- No plugin or marketplace version bumps.

**Done when:** `devbox run validate` and the Markdown link check (`scripts/` link checker in `ci-local`) pass.
