---
spec_id: 131-runs-that-finish-on-their-own
shape: platform
spec_hash: e560eb57e900
summary: "cplat headless runs an unattended /component:ship or /component:build as one fresh session per unit (plan, red tests, each task, verification, land) with checkpoints detected from the committed feature branch (units.py, supervisor.py); a preflight grants the run allowlist per session through --allowedTools/--disallowedTools and fails before anything is spent (preflight.py); budgets scale with T and C in per-spec ledger parts, a one-time verification grace, and the subagent cost is never a partial sum; /system:ship gets the preflight and the scaled parts; the runs report measures AC-131.18; ADR-075/076/077, plugin unit mode, docs"
tasks:
  - id: t1
    title: units.py — unit list, completion rules, checkpoints, validity, 5.5 derivation, status rows, unit gate, stalls
    files: [scripts/cplat/units.py, scripts/cplat/runs.py]
    covers: [AC-131.1, AC-131.2, AC-131.3, AC-131.5, AC-131.7, AC-131.19]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: preflight.py — run allowlist, refused rules, settings-layer matcher, five checks; pr_open honours CPLAT_RUN_ALLOWLIST
    files: [scripts/cplat/preflight.py, scripts/cplat/pr_open.py]
    covers: [AC-131.8, AC-131.9, AC-131.10, AC-131.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: budget.py — plan formula, per-spec parts, rescale, limits line with T and C, $0 rule, incomplete cost is unknown
    files: [scripts/cplat/budget.py, tests/cplat/test_budget.py]
    covers: [AC-131.12, AC-131.13, AC-131.14, AC-131.17]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: runs_usage and transcripts — an incomplete read is cost_complete false; parse cache for unchanged transcripts
    files: [scripts/cplat/runs_usage.py, scripts/cplat/transcripts.py]
    covers: [AC-131.17]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: budget.py — the verification grace (grant, extended limits, grace used, end), budget section fields
    files: [scripts/cplat/budget.py]
    covers: [AC-131.15, AC-131.16]
    parallel_safe: true
    depends_on: [t1, t3]
    done: true
  - id: t6
    title: ship.py — unit gate, units in status, ship unit, rescale on phase build, grace-aware phase check, archive units
    files: [scripts/cplat/ship.py]
    covers: [AC-131.2, AC-131.7, AC-131.14, AC-131.15, AC-131.19]
    parallel_safe: true
    depends_on: [t1, t3, t5]
    done: true
  - id: t7
    title: supervisor.py — the unit loop, summary lines, stall escalation, rescale and grace at unit boundaries
    files: [scripts/cplat/supervisor.py]
    covers: [AC-131.1, AC-131.3, AC-131.4, AC-131.5, AC-131.6, AC-131.14, AC-131.15, AC-131.19]
    parallel_safe: true
    depends_on: [t1, t3, t5]
    done: true
  - id: t8
    title: headless.py — unit mode dispatch, preflight before the first session, per-session grants, defaults, preflight record
    files: [scripts/cplat/headless.py, tests/cplat/test_headless.py, tests/cplat/test_headless_126.py, tests/cplat/test_headless_model.py]
    covers: [AC-131.4, AC-131.6, AC-131.8, AC-131.9, AC-131.10, AC-131.11, AC-131.12]
    parallel_safe: false
    depends_on: [t2, t7]
    done: true
  - id: t9
    title: system ship — placeholder budget parts per plan repo, preflight at repo start
    files: [scripts/cplat/appship_state.py, scripts/cplat/appship_sched.py]
    covers: [AC-131.8, AC-131.11, AC-131.13]
    parallel_safe: true
    depends_on: [t2, t3]
    done: true
  - id: t10
    title: runs report — the Unattended ships (spec 131) section
    files: [scripts/cplat/runs_report.py]
    covers: [AC-131.18]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t11
    title: plugins — unit-mode reference, ship and build unit mode, system ship preflight note, Stop hook, version bumps
    files: [plugins/component/references/unit-mode.md, plugins/component/commands/ship.md, plugins/component/commands/build.md, plugins/system/commands/ship.md, plugins/shared/hooks/hooks.json, plugins/component/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-131.1, AC-131.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t12
    title: docs — AGENTS.md, unattended-delivery.md, ADR amendment lines, changelog, measurements.md for AC-131.18
    files: [docs/AGENTS.md, docs/unattended-delivery.md, docs/adr/028-unattended-delivery-without-branch-protection.md, docs/adr/037-cplat-bundles-honour-the-allowlist.md, docs/adr/043-one-budget-per-run-tree.md, docs/adr/070-the-stop-hook-holds-only-the-owning-session-until-it-stops-progressing.md, docs/CHANGELOG.md, docs/specs/131-runs-that-finish-on-their-own/measurements.md]
    covers: [AC-131.18]
    parallel_safe: true
    depends_on: []
    done: true
human_steps:
  - "AC-131.18, seven days after the release that ships spec 131: run the commands in docs/specs/131-runs-that-finish-on-their-own/measurements.md (cplat platform runs report --since 7, its Unattended ships section), fill its table, and open an issue for any line marked MISSED."
---

# Plan — 131 Runs that finish on their own

[design.md](design.md) is the contract that every task and test follows. The ADRs are written with this plan, and their
rows are already in `docs/adr/README.md`:
[ADR-075](../../adr/075-an-unattended-ship-runs-one-session-per-unit-saved-at-checkpoints.md) (units),
[ADR-076](../../adr/076-an-unattended-run-gets-its-permissions-per-session-from-a-checked-run-allowlist.md) (run allowlist)
and [ADR-077](../../adr/077-budgets-scale-with-the-plan-and-verification-gets-one-grace.md) (scaled budgets and grace). t12
adds the "Amended by" lines to the ADRs they amend.

**Levels:**

| Level | Tasks |
|---|---|
| 1 | t1, t2, t3, t4, t10, t11, t12 |
| 2 | t5, t9 |
| 3 | t6, t7 |
| 4 | t8 |

Each hot file has one owner per level. `scripts/cplat/budget.py` belongs to t3 and then to t5. `scripts/cplat/ship.py`
belongs only to t6, and `scripts/cplat/headless.py` only to t8. `supervisor.py` (t7) uses `headless.run_once`,
`headless.last_message` and `headless.log_dir` as they are today, and gets the claude command from a callable. t8 then
calls `supervisor.drive`, which is why t8 depends on t7. t8 is not parallel-safe because it changes the CLI defaults that
existing headless tests encode.

**Acceptance tests.** The testers write them first, one criterion id per test, in these files:

- `tests/cplat/test_units_131.py`
- `test_supervisor_131.py`
- `test_preflight_131.py`
- `test_headless_131.py`
- `test_budget_131.py`
- `test_usage_cost_131.py`
- `test_ship_units_131.py`
- `test_appship_131.py`
- `test_runs_report_131.py`
- `test_docs_131.py`

How they test:

- The supervisor is driven with a fake `claude` (`CPLAT_CLAUDE`, a script that reads `CPLAT_UNIT` and makes that unit's
  commits).
- `gh` is faked with PATH stubs.
- The settings layers are faked through `preflight.layers`.
- The transcripts are fixture JSONL files under a fake `CLAUDE_CONFIG_DIR/projects`, with a `<session>/subagents/`
  directory.
- The spec 128 example (T=8, C=14 → $29, 250, 74, 6) is a fixed case.
- AC-131.18 is tested on fixture run records: the report section and the `--json` values.

Existing tests that encode replaced behaviour are updated by the task that changes the code they test, and those test
files are in that task's `files`. Examples: `/component:ship` under headless as one resuming session, and
`--max-runs 6` as the default.

## t1 — units.py

**Files:** scripts/cplat/units.py, scripts/cplat/runs.py
**Covers:** AC-131.1, AC-131.2, AC-131.3, AC-131.5, AC-131.7, AC-131.19
**Goal:** One module knows the units of an unattended run, when each one is done, and what the run state says about them.

**Implementation notes:**
- Public API: `unit_ids`, `prepare`, `next_open`, `detect`, `start_session`, `end_session` (returns the ending: checkpoint
  with its commit, or no checkpoint with the stall count), `escalate`, `rows`, `describe_lines`, `gate`,
  `only_verification_left`, `next_step`, `feature_head` and `STALL_LIMIT = 2`. Ids, order and file schema follow design
  § Units.
- Completion rules follow the design table and read only committed trees (`git show B:<path>`). `red-tests` runs
  `cplat spec trace` the way `ship.build_red` does (same interpreter and script path). `land` for `build` asks `gh pr list`
  through a module-level `gh` function that tests replace.
- Task order: `spec.topo_levels` levels, with the plan order inside a level (not the sorted ids).
- Validity: `git merge-base --is-ancestor`. Once there is a `merge_sha`, or the ship phase is `deploy` or `done`, nothing
  before `land` is re-checked.
- Derivation exactly as in the design table, `derived: "5.5"`. Read the ship state with `ship.load_state` (read only;
  import `ship` lazily to avoid a cycle).
- `gate(repo, unit, hook_input)` follows design § Stop hook in a unit session. It returns `None` or the block dict, saves
  `hold`, and never escalates.
- Writes are atomic (`runs._atomic_write`) under `runs._locked()`. A broken or unreadable file is treated as missing and
  recreated by `prepare`.
- `runs.py`: in the `end` CLI with `--outcome escalated`, when `CPLAT_UNIT` is set, also call `units.escalate(repo,
  reason, cause)`. This never raises, and nothing else in `runs.py` changes.

**Done when:** the unit tests of `test_units_131.py` pass:

- order with dependencies (AC-131.1);
- each completion rule, with uncommitted work not counting;
- a checkpoint dropped when its commit leaves the branch (AC-131.3);
- stalls reset by a new commit and counted otherwise (AC-131.5);
- status rows (AC-131.7);
- derivation per phase (AC-131.19);
- every row of the gate table (AC-131.2).

## t2 — preflight.py and pr_open

**Files:** scripts/cplat/preflight.py, scripts/cplat/pr_open.py
**Covers:** AC-131.8, AC-131.9, AC-131.10, AC-131.11
**Goal:** The run allowlist, the refused rules and the five checks exist as one testable module, and `cplat pr open` honours
the per-run grant.

**Implementation notes:**
- `run_allowlist(command, branches)`, `refused_rules(default_branch)`, `default_branch(repo)`, `layers(repo)`,
  `matches(rule, command)`, `check(repo, command, specs, targets=None) -> Failure | None`, `check_repo(clone, slug) ->
  Failure | None`, and `env(allowlist) -> {"CPLAT_RUN_ALLOWLIST": json}`. Rules, order and texts are exactly as in
  design § Run allowlist and preflight.
- `Failure(category, detail)` has `line()`, which returns `preflight failed: <category>: <detail>`, and `reason()`, which
  returns `preflight failed: <category>`.
- The matcher is a glob over the whole command, where `*` spans spaces. `Bash(<p>:*)` is a prefix match, and `Bash` or
  `Bash(*)` matches everything. Other tools never match.
- The checks run in the design order and stop at the first failure. `git` and `gh` go through module-level functions
  that tests replace. Use a 30 s timeout per call. A missing `gh` binary is `gh-auth`.
- Nothing is written anywhere: no settings file, no temp file in the repo (AC-131.9).
- No rule from `refused_rules` may be equal to a rule of `run_allowlist`, and a refused rule must never match a
  representative command of the allowlist. The module asserts both at import.
- `pr_open.pr_allowed`: add the rules of `CPLAT_RUN_ALLOWLIST` (a JSON array; an invalid value is ignored) to `allow`,
  before the deny and ask test.

**Done when:** the `test_preflight_131.py` tests pass:

- the allowlist per command (AC-131.8);
- the refused rules and that none is in the allowlist, plus `feature/x-fix` not refused (AC-131.10);
- every category with its line and detail (AC-131.11);
- byte-identical settings files after a passing and a failing check (AC-131.9);
- the `pr open` test with the env grant.

The existing `test_pr_open.py` stays green.

## t3 — budget scaling

**Files:** scripts/cplat/budget.py, tests/cplat/test_budget.py
**Covers:** AC-131.12, AC-131.13, AC-131.14, AC-131.17
**Goal:** The default limits follow the plan of each spec in the run, they are raised when a plan appears, and the cost
is never reported lower than it is.

**Implementation notes:**
- `plan_limits(T, C, floors)` and `plan_size(repo, spec_id) -> (T, C) | None`. `plan_size` returns `None` without a plan
  that passes `spec.check_plan`.
- Ledger `parts`, `fixed` and `grace: null` (t5 fills `grace`). `open_root` builds the parts from `spec_refs`/`ships` as
  in design § Budgets, and the options go into `fixed`. A continued ledger is rescaled on open.
- `rescale(run_id, repo, spec_ids)` and `add_parts(run_id, parts)` raise and never lower. Each raise is recorded in
  `changes` with its `reason`. Neither raises an error.
- `limits_line` gets the `(plan: …)` bracket of the design.
- The $0 rule: a headless root with `invocations` 0 and no usage source costs `0` in `used_of` and in `on_finish`.
- `_cost_of`: `cost_complete` false means `unknown`, whatever the number of calls.
- `section()` gets `parts` (`{key: {"T", "C"}}`).
- `test_budget.py`: update only the tests that assert the old multiplication for a spec with a plan, or a cost from an
  incomplete read.

**Done when:**

- The `test_budget_131.py` tests for AC-131.13 pass: the spec 128 case, floors for small plans, an option replacing a
  limit, two specs summed, settings floors.
- So do the AC-131.14 tests (raised at the plan, never lowered, `changes` entry, limits line with T and C), the AC-131.12
  $0 test and the AC-131.17 `unknown` test.
- `test_budget.py` is green.

## t4 — complete usage reads

**Files:** scripts/cplat/runs_usage.py, scripts/cplat/transcripts.py
**Covers:** AC-131.17
**Goal:** A budget check counts every subagent's cost, or says `unknown`.

**Implementation notes:**
- `for_run` sets `totals.cost_complete = False` whenever `incomplete` names any of these:
  - a transcript that was not found or could not be read;
  - a subagent it could not read;
  - the time budget;
  - an error.

  It keeps the price-table reason. Malformed lines alone do not count.
- `transcripts`: a parse cache per file under `runs.state_dir()/usage/cache/` (import `runs` lazily), keyed by path, size
  and `mtime_ns`. It stores the parsed calls and the malformed count. A file whose key matches is not parsed again and
  does not count against the deadline. A file still being written (last line without a newline) is never cached.
- The cache is best effort: an unreadable or corrupt cache entry is parsed again, never an error.
- `read_session` keeps its signature. The cache is an implementation detail that tests may point at a temp `state_dir`.

**Done when:** the `test_usage_cost_131.py` tests pass:

- a main transcript plus coder, tester and reviewer subagent files give the full sum through `cplat budget show --json`;
- a read stopped by the deadline gives `unknown`;
- an unreadable subagent file gives `unknown`;
- a second read of unchanged files parses nothing.

The existing `test_runs_usage*.py` tests stay green.

## t5 — verification grace

**Files:** scripts/cplat/budget.py
**Covers:** AC-131.15, AC-131.16
**Goal:** A run that has done all its tasks is verified within one bounded grace instead of escalating.

**Implementation notes:**
- `check(run_id, point, repo=None)` follows design § Grace, steps 1 to 5. It calls `units.only_verification_left(repo)`
  (lazy import). The grant prints `budget grace: verification` once.
- Grace amounts: minutes `max(30, 0.2·L)`, invocations `max(10, ceil(0.2·L))`, cost `max(3, round(0.2·L, 2))`, reruns
  `ceil(0.2·L)`. A limit that is `off` gets no grace.
- `end_grace(run_id)` sets `state` to `ended`. `stop()` returns `budget exhausted: <limit> (grace used)` when the grace
  was used.
- `section()` adds `grace`, and on a stop `verification_left`.
- `_gate` (the PreToolUse hook) passes `repo` to `check`. `allow_rerun` ignores the grace.
- The grace never touches `stages`, `attempts` or `decisions` (AC-102.8).

**Done when:** the AC-131.15 and AC-131.16 tests pass:

- the grant with its line and section, once only;
- no grace for an earlier unit or for land;
- the floors;
- the `(grace used)` reason;
- `budget resume` decisions unchanged during a grace.

## t6 — ship.py

**Files:** scripts/cplat/ship.py
**Covers:** AC-131.2, AC-131.7, AC-131.14, AC-131.15, AC-131.19
**Goal:** The ship commands know the units: the hook ends a unit session at its checkpoint, the status lists the units,
and phase changes rescale the budget and end the grace.

**Implementation notes:**
- `gate`: when `CPLAT_UNIT` is set, return `units.gate(repo, unit, hook_input)` before loading the owner logic. This also
  happens without a ship state. Without `CPLAT_UNIT` nothing changes.
- `describe` and `status --json`: the units block and `units` list of design § Units. They appear only when a units file
  for the spec exists. `status` without a ship state but with a units file prints the build units, with exit 0.
- New subcommand `unit [--json]`, as in the design.
- `set_phase`:
  - `build` calls `budget.rescale(st["run_id"], repo, [st["spec"]])` before the safe-point check;
  - the check becomes `budget.check(rid, "phase end", repo=repo)`;
  - `pr` calls `budget.end_grace(rid)` after the check.
- `finish` also archives `cplat-units.json` as `cplat-units-<spec>-<ts>.json`, when the file exists.
- Module docstring: the `unit` line.

**Done when:** the `test_ship_units_131.py` tests pass:

- the gate cases with `CPLAT_UNIT` (AC-131.2);
- status text and JSON with units (AC-131.7) and for a derived 5.5 run (AC-131.19);
- the rescale on `phase build` (AC-131.14);
- the grace ended on `phase pr` (AC-131.15).

`test_ship*.py` and `test_ship_gate_126.py` stay green.

## t7 — supervisor.py

**Files:** scripts/cplat/supervisor.py
**Covers:** AC-131.1, AC-131.3, AC-131.4, AC-131.5, AC-131.6, AC-131.14, AC-131.15, AC-131.19
**Goal:** The supervisor runs the units one session at a time until the run is done, escalated or out of budget.

**Implementation notes:**
- `drive(repo, command, specs, prompt, make_cmd, extra_env, rid, ns, log, state) -> int`, following the loop of design
  § Supervisor:
  - `make_cmd(prompt) -> list[str]` returns the claude command for a prompt, with the grants of t8 in it;
  - the supervisor appends a fresh `--session-id` for each session;
  - `ns` carries `max_runs`, `max_minutes`, `quiet` and `no_wait` (`None` means no cap);
  - `state` is headless's dict (`sessions`, `result`, `code`, `cause`).
- Session env: set `CPLAT_UNIT=<unit>` and every key of `extra_env` (`CPLAT_RUN_ALLOWLIST`) in `os.environ` for the
  duration of the `headless.run_once` call, and restore them afterwards. `run_once` already passes `os.environ` plus
  `CPLAT_SESSION_ID` and `CPLAT_RUN_PARENT`. Import `headless` lazily, since t8 makes `headless` import this module.
- Register every session with `runs_usage.register(rid, mode="own", session=sid)`, as the legacy loop does.
- Summary log: one line per session, in the format of the design. The last message comes from the session's log section
  (`headless.last_message`).
- Budget:
  - `budget.check(rid, "session", repo=repo)` before each session;
  - a stop goes through `ship.budget_stop` when a ship state exists, else `budget.stop` and `budget.snapshot`;
  - `rescale` after the `plan` checkpoint, and the limits line printed when it changed;
  - `end_grace` after the `verification` checkpoint.
- Stall: at `units.STALL_LIMIT`, escalate with `no progress: unit <u> after 2 sessions without a commit`. The cause is
  `ship.no_progress_cause`, as in the design. For `ship`, call `ship.escalate`. For `build`, call `units.escalate`.
  `state["cause"]` is set for the headless record.
- `--max-runs`/`--max-minutes` apply only when given. The quiet window works as in the legacy loop.
- After the `land` checkpoint of a ship: `ship.finish(repo)` and `shipped <spec>[ (<deployed> in dev)]`. For a build:
  `finished`. Several specs run in prompt order.
- Escalated inside a session (ship state or units file) → `needs you: …`, with nothing more started.

**Done when:** the `test_supervisor_131.py` tests pass with a fake `claude`:

- 3 tasks give 7 sessions with unit prompts and 7 summary lines (AC-131.1);
- a session ended early resumes the same unit, and a checkpointed unit never runs again unless its commit is gone
  (AC-131.3);
- a restart continues at the first open unit, with ledger usage carried on (AC-131.4);
- two sessions without a commit escalate with the reason and the AC-126.7 cause, and committing sessions do not
  (AC-131.5);
- more units than 6 run without `--max-runs`, and `--max-runs` caps them (AC-131.6);
- the limits are raised after the plan unit (AC-131.14);
- the grace starts verification and never land (AC-131.15);
- a 5.5 state resumes without a question (AC-131.19).

## t8 — headless.py

**Files:** scripts/cplat/headless.py, tests/cplat/test_headless.py, tests/cplat/test_headless_126.py, tests/cplat/test_headless_model.py
**Covers:** AC-131.4, AC-131.6, AC-131.8, AC-131.9, AC-131.10, AC-131.11, AC-131.12
**Goal:** `cplat headless` checks and grants permissions before anything runs, and hands covered ship and build prompts to
the supervisor.

**Implementation notes:**
- Covered commands: the prompt's first word is `/component:ship`, `/component:build` or `/system:ship`. Unit mode: the
  first two, with at least one spec ref (`budget.spec_refs`). Everything else keeps today's flow unchanged (no
  preflight, no grants).
- Remove the early `.claude/settings.json` `PlatformError`. Order for a covered command:
  1. `runs.start`;
  2. `budget.open_root`;
  3. limits line;
  4. the run allowlist output;
  5. `preflight.check`;
  6. sessions.

  For `/system:ship`, the targets are the plan's repos (design § Targets).
- A failed preflight follows the design exactly: the line, the summary line, record `escalated` with cause `environment`
  and `stop_reason: "preflight"`, and exit 1. `stop_of` maps `preflight failed`.
- `claude_cmd(prompt, model, plugin_dirs, allow=None, deny=None)` appends `--allowedTools <rule>…` and
  `--disallowedTools <rule>…` (one argument per rule). `--dry-run` prints the command and the allowlist block.
- The legacy loop of `/system:ship` also gets the grants. It sets `CPLAT_RUN_ALLOWLIST` the same way the supervisor does
  (in `os.environ` around `run_once`). Unit mode passes `lambda p: claude_cmd(p, model, dirs, allow, deny)` and
  `preflight.env(allow)` to `supervisor.drive`.
- Defaults: `--max-runs` and `--max-minutes` default to `None`. The legacy loop uses 6 and 240 when they are `None`, and
  unit mode uses no cap.
- `finally` record: keep the existing outcome mapping. Add the preflight escalation and the stall cause from
  `state["cause"]` (also for `no progress: unit …`).
- Module docstring: unit mode, the run allowlist and the new defaults.
- Update the listed existing tests where they assume one resuming session for `/component:ship`, the missing-settings
  `PlatformError`, or the exact `claude_cmd` list. Their stubs get a passing preflight (`preflight.layers` and `gh`
  faked).

**Done when:** the `test_headless_131.py` tests pass:

- the printed allowlist and the `--allowedTools`/`--disallowedTools` arguments on every session (AC-131.8, AC-131.10);
- byte-identical settings files (AC-131.9);
- each preflight category, with no session, exit 1 and the record (AC-131.11);
- 0 invocations, $0, and no branch, commit or PR after a failed preflight (AC-131.12);
- the `--max-runs` default (AC-131.6);
- the restart (AC-131.4).

The listed existing headless tests are green.

## t9 — system ship

**Files:** scripts/cplat/appship_state.py, scripts/cplat/appship_sched.py
**Covers:** AC-131.8, AC-131.11, AC-131.13
**Goal:** A product ship gets one budget part per repo and checks each repo's permissions before it starts it.

**Implementation notes:**
- `appship_state._open_budget`: keep `open_root` for a root product ship. Then call `budget.add_parts(st["run_id"], {"<org>/<repo id>:*": F})` for every repo of the plan, in both cases (root and child under headless). The repo ships' own `phase build` rescale (t6) replaces each placeholder with its plan part.
- `appship_sched.start_repo`: after the clone exists, run `preflight.check_repo(path, "<org>/<repo id>")`. On a failure,
  record the repo `escalated` with the reason `preflight failed: <category>` and the cause `environment` (the existing
  repo-escalate path). Then raise `PlatformError(failure.line())`, so the CLI prints it and exits 1. The gitops entry
  (`entry: true`) is not checked here, because it is the gitops repo itself, which headless already checked.
- Nothing else in the product ship changes.

**Done when:** the `test_appship_131.py` tests pass:

- the product ledger's parts, summed, and raised when a repo's plan appears (AC-131.13);
- a repo with an `ask` rule on `git push` or without push access is escalated at `repo start`, with the line and cause
  `environment`, and its ship not started (AC-131.11);
- the session allowlist covers `feature/*` (AC-131.8).

`test_appship_097.py` and the gate tests stay green.

## t10 — runs report section

**Files:** scripts/cplat/runs_report.py
**Covers:** AC-131.18
**Goal:** The weekly report says whether unattended ships now finish.

**Implementation notes:**
- `aggregate_unattended(kept) -> dict` with `runs`, `done`, `done_pct`, `spend_total`, `spend_bad`, `spend_bad_pct`,
  `unknown_cost`, `approval_escalations`, `verification_budget_stops`, and an `ok` flag per target. The definitions are
  in design § Success measure. The approval escalation uses `escalation_rules.classify`.
- `render_text` gets the section lines of the design after the existing summary. The JSON output gets
  `unattended_ships`.
- With zero runs the section says `runs: 0` and no target lines are marked. Never divide by zero.

**Done when:** the `test_runs_report_131.py` tests pass on fixture records (done and escalated headless ships, an
approval escalation, a budget stop with `verification_left`, unknown cost). `test_runs_report*.py` stays green.

## t11 — plugins

**Files:** plugins/component/references/unit-mode.md, plugins/component/commands/ship.md, plugins/component/commands/build.md, plugins/system/commands/ship.md, plugins/shared/hooks/hooks.json, plugins/component/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-131.1, AC-131.2
**Goal:** A unit session knows it does one unit and stops at its checkpoint. The Stop hook reaches unit sessions.

**Implementation notes:**
- `references/unit-mode.md` holds the rules for each unit, and is the only place they are written:
  - `plan`: follow plan.md unattended, commit `plan.md`, and in a ship `cplat component ship phase build`;
  - `red-tests`: build Phases 0 and 1;
  - `task:<id>`: build Phase 2 for that one task as a sequential task (no worktree probe, no parallel batch),
    `task-done` and its commit;
  - `verification`: build Phases 2.5 to 6, and in a ship `ship phase pr`;
  - `land`: ship phases `pr`, `land` and `deploy` without `ship finish`, or build Phase 7.

  It also says:
  - check with `cplat component ship unit`, then stop at once;
  - never start another unit;
  - commit what is done before every stop;
  - escalate as the command says.
- `ship.md` and `build.md`: the `--unit <unit>` argument (set only by `cplat headless`). When it is present, read
  `${CLAUDE_PLUGIN_ROOT}/references/unit-mode.md` and follow only that unit. Without it the flow is unchanged.
- `ship.md` and `build.md`: one line on the run allowlist. Unattended sessions are granted the feature branch, `commit -s`,
  push without force and `gh pr create`. Force pushes, pushes to the default branch and merges outside
  `cplat component ship land` are refused.
- `system/commands/ship.md`: `cplat system ship repo start` may fail with `preflight failed: <category>: …`. The repo is
  then escalated, so print the line and stop for that repo.
- `hooks.json` Stop command for `cplat component ship gate`: it runs when `cplat-ship.json` exists or `$CPLAT_UNIT` is
  set. The product-ship hook is unchanged.
- Version bumps, from the values in the files at build time, in `plugin.json` and `marketplace.json` alike: `component`
  minor, `shared` minor, `system` patch.

**Done when:**

- `devbox run validate`, the version-match loop of `devbox run quality` and `scripts/shapes.py check` pass.
- The AC-131.1 and AC-131.2 doc tests pass: both commands name `--unit` and the reference, the reference names every unit,
  and the hook condition names `CPLAT_UNIT`.

## t12 — docs

**Files:** docs/AGENTS.md, docs/unattended-delivery.md, docs/adr/028-unattended-delivery-without-branch-protection.md, docs/adr/037-cplat-bundles-honour-the-allowlist.md, docs/adr/043-one-budget-per-run-tree.md, docs/adr/070-the-stop-hook-holds-only-the-owning-session-until-it-stops-progressing.md, docs/CHANGELOG.md, docs/specs/131-runs-that-finish-on-their-own/measurements.md
**Covers:** AC-131.18
**Goal:** The docs describe unit runs, the run allowlist and the scaled budgets, and the post-release measurement is
ready to run.

**Implementation notes:**
- `AGENTS.md` (headless and Stop hook sections) and `unattended-delivery.md`: units and checkpoints, the unit hold, the
  2-session stall rule, the preflight categories with what to do for each, the run allowlist, the formula and the grace.
  Link ADR-075, ADR-076 and ADR-077.
- Add one `**Amended by:**` line to each ADR it amends:
  - ADR-028 → ADR-075;
  - ADR-070 → ADR-075 (unit sessions);
  - ADR-037 → ADR-076;
  - ADR-043 → ADR-077.
- `CHANGELOG.md` `[Unreleased]`: a paragraph **Runs that finish on their own** (spec 131, ADR-075/076/077). It names the
  unit sessions, the preflight and its categories, the scaled budgets with the spec 128 example, the grace, and the
  subagent cost fix. It adds the plugin versions of t11 to the **Plugins** line. Action: none, because runs in flight
  resume by themselves. Not breaking.
- `measurements.md`: the AC-131.18 checks as commands with an empty result table, in the style of spec 126's sheet:
  - `cplat platform runs report --since 7` and its four lines;
  - the release date to count from.

**Done when:** `python3 scripts/check-links.py` and `scripts/shapes.py check` pass, and the AC-131.18 doc test passes
(`measurements.md` exists with the report command and the four targets).
