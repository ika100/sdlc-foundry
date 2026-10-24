---
spec_id: 089-agent-quality-is-measured-per-agent-and
spec_hash: 773376832bcd
summary: agents / replans / agent_metrics sections in the 087 run record, cplat runs agent recording CLI, in-code recording
  in ship land and spec test-diff, cplat runs report --agents [--by-version]
tasks:
- id: t1
  title: Run record hooks for agent metrics and the report flags
  files: [scripts/cplat/runs.py, scripts/cplat/cplat.py]
  covers: [AC-089.1, AC-089.10, AC-089.11, AC-089.12]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: Agent metric recording (runs_agents) and the cplat runs agent CLI
  files: [scripts/cplat/runs_agents.py]
  covers: [AC-089.1, AC-089.2, AC-089.3, AC-089.4, AC-089.5, AC-089.6, AC-089.7, AC-089.8, AC-089.9, AC-089.10, AC-089.14]
  parallel_safe: true
  depends_on: [t1]
  done: true
- id: t3
  title: Agent report aggregation and rendering
  files: [scripts/cplat/runs_report.py]
  covers: [AC-089.9, AC-089.11, AC-089.12, AC-089.13, AC-089.14]
  parallel_safe: true
  depends_on: []
- id: t4
  title: ship land records red-CI rounds against the coder
  files: [scripts/cplat/ship.py]
  covers: [AC-089.5, AC-089.10]
  parallel_safe: true
  depends_on: [t2]
  done: true
- id: t5
  title: spec test-diff records refused test diffs
  files: [scripts/cplat/spec.py]
  covers: [AC-089.7, AC-089.10]
  parallel_safe: true
  depends_on: [t2]
- id: t6
  title: Build, ship and app-build prompts record agent signals
  files: [plugins/svc/commands/build.md, plugins/svc/commands/ship.md, plugins/app/commands/build.md]
  covers: [AC-089.1, AC-089.2, AC-089.3, AC-089.4, AC-089.6, AC-089.7, AC-089.8]
  parallel_safe: true
  depends_on: []
- id: t7
  title: Docs for agent metrics
  files: [docs/CHANGELOG.md, docs/unattended-delivery.md, docs/AGENTS.md]
  covers: []
  parallel_safe: true
  depends_on: []
---

The contract for every task is [design.md](design.md): the record sections, event kinds, the `runs_agents` API, the
`cplat runs agent` CLI and the report JSON/text. Recording never changes a run's outcome, exit code or stdout. Every
new call into `runs` / `runs_agents` from other modules is wrapped or never raises. Specs 090 and 094 build on this
contract, so field names and values are exactly as written there.

## t1 — Run record hooks for agent metrics and the report flags

**Files:** scripts/cplat/runs.py, scripts/cplat/cplat.py
**Covers:** AC-089.1, AC-089.10, AC-089.11, AC-089.12
**Goal:** the generic hooks `runs_agents` builds on (`mutate`, `current_run`, `mark_incomplete` and its merge in
`finish`), the redaction exemption, section initialisation in `runs begin build`, delegation of `cplat runs agent`,
and the `report --agents` flags. All as in design.md "Python API — runs.py (additions)".

**Implementation notes:**
- `mutate(run_id, change) -> "ok" | "none" | "error"`: same lock and read/write as `_mutate`, but it reports the
  outcome. `_mutate` may become a thin wrapper around it.
- `current_run(repo_dir)`: the pointer's `run_id` if `active()` finds it, else `attach_point(repo_dir)`. It never
  raises.
- `mark_incomplete(run_id, section, problem)`: plain append (`open(..., "a")`, no lock) of one JSON line to
  `active/<run_id>.incomplete.jsonl`, then `mutate` to set `complete: false` and add the problem (unique, ≤ 10). It
  never raises.
- `finish`: merge the `.incomplete.jsonl` lines before `_scrub`, create the section when it is missing, and delete the
  file with the active file.
- `_scrub`: exempt `("agents", "events", "spec")` and `("replans", "spec")`.
- `begin`, for kind `build` (own or attached): `import runs_agents; runs_agents.init(rid)` inside the existing
  try.
- `main`: `argv[:1] == ["agent"]` → `runs_agents.main(argv[1:])`. It always returns 0.
- `report`: add `--agents`, `--by-version`, `--agent NAME`, `--shape SHAPE`. The three without `--agents` →
  `PlatformError` as in the contract. With `--agents`: the same config / visibility / read as today, then
  `runs_report.parse`, `runs_report.aggregate_agents(...)`, then `json.dumps(agg, indent=2)` alone on stdout, or
  `render_agents_text`.
- Module docstring and `cplat.py` docstring: `cplat.py runs init|flush|report|begin|phase|end|agent ...   private run
  records and agent metrics (specs 087, 089)`.

**Done when:** the AC-089.10 tests pass, including the case where the active record cannot be written and the
finished record still has `agent_metrics.complete == false`. Together with t2 and t3, the AC-089.1 test of an
escalated Phase-0 build (empty `agents`) and the CLI parts of AC-089.11/.12 pass. `tests/cplat/test_runs*.py` stay
green.

## t2 — Agent metric recording (runs_agents) and the cplat runs agent CLI

**Files:** scripts/cplat/runs_agents.py
**Covers:** AC-089.1, AC-089.2, AC-089.3, AC-089.4, AC-089.5, AC-089.6, AC-089.7, AC-089.8, AC-089.9, AC-089.10, AC-089.14
**Goal:** the `agents`, `replans` and `agent_metrics` sections exactly as in design.md, every recording function, and
`cplat runs agent <event>` (always exit 0, nothing on stdout).

**Implementation notes:**
- `identity(repo, role, model_id)`:
  - Resolve the role through `shapecmd.route(repo)["agents"]`. An exception means shape `none`, with `shared:` for
    quality and security and `svc:` otherwise. A full name with `:` is kept.
  - `model` comes from the agent file's frontmatter `model:` under `core.PLATFORM_ROOT/plugins/<plugin>/agents/<role>.md`,
    else `unknown`.
- One private `_change(run_id, fn)` around `runs.mutate`. It does the following in this order:
  - init the sections when they are missing;
  - run `fn(rec)`;
  - mark the metrics measured;
  - recompute `counts` of every entry from its events and `measured` (null for unmeasured, role keys only).

  `"error"` → `runs.mark_incomplete(run_id, "agent_metrics", "write failed: ...")`.
- Entry key `agent|shape|model`; `_entry(rec, identity)` creates the entry or returns the existing one, and sets
  `model_id` when one is given.
- Event ids are `<kind>:<n>`, numbered across the whole section. Natural-key upserts as in the contract (out-of-plan,
  finding, tester, refused-test-diff).
- `merged`:
  - `git diff --name-only <since>..HEAD`;
  - the task's `files` from `spec.find(repo, rec["spec"]).plan[0]["tasks"]`, matched exactly, by `fnmatch` glob or by
    directory prefix;
  - `helpers` are excepted;
  - ensure both the architect and the coder entry.
- `conflict`: `paths` from `git diff --name-only --diff-filter=U` when none are given. `with_task` is the `done` task
  with the largest file overlap (later task on a tie, else null). `author` is copied from the architect entry.
  `outcome` must be in `CONFLICT_OUTCOMES`. `conflict_outcome` updates the task's latest conflict. `replan` adds the
  event and the `replans` entry, links the latest conflict and sets that conflict to `re-planned`.
- `findings`:
  - parse the criteria table of `docs/specs/<spec>/verification.md` (rows whose first cell is `AC-…`; verdict cell
    lowercased; `not met` / `partial`);
  - deviations are an AC id → the covering tasks, or a task id → that task;
  - `pass` is `first` for cycle 1, else `after fix`;
  - it also marks `fix_rounds` measured.
- Validate every enum (`FIX_CAUSES`, `SEVERITIES`, `TESTER_REASONS`, `CONFLICT_OUTCOMES`, `by`) in code. A bad value
  → `mark_incomplete("malformed: …")` and no event.
- `main`: an argparse parser whose `error()` raises instead of exiting. Every subcommand has `--dir`. The run is
  `runs.current_run(Path(dir))`. Wrap everything. When a call marked the run incomplete, print the one stderr
  `WARNING:` line from the contract. It returns 0.

**Done when:** the acceptance tests pass for these criteria and parts:
- AC-089.1–.4, .6 and .8, through `cplat runs agent …` on a temp git repo with a spec, a plan and a
  `verification.md`;
- AC-089.14;
- the record side of AC-089.9 (`null` counts, `measured`);
- the CLI side of AC-089.10 (malformed or unparsable calls exit 0 and flag the record).

## t3 — Agent report aggregation and rendering

**Files:** scripts/cplat/runs_report.py
**Covers:** AC-089.9, AC-089.11, AC-089.12, AC-089.13, AC-089.14
**Goal:** the pure functions `select`, `aggregate_agents` and `render_agents_text`, as in design.md "Report". They are
tolerant of pre-089 records, missing sections and malformed entries.

**Implementation notes:**
- Factor 087's window, repo filter and `run_id` dedupe out of `aggregate` into `select(records, since_days=, repo=,
  now=)`. `aggregate` must give byte-identical output for the 087 tests.
- Rows keyed `(agent, shape, model[, platform_version])`. The `--agent` (full name, or role without `:`) and
  `--shape` filters apply.
- Per metric, average over the row's records whose `agent_metrics.measured` holds it, computed from `events`. No
  measured run → `avg: null` and null per-cause values. Round to 3 decimals.
- `rework`, `few_runs` (< 5), `incomplete_runs` and `resolved_share` as in the contract. Sort by rework descending,
  then key. With `by_version`, groups go by their maximum rework and versions ascend by `core.vtuple`.
- `top_causes`:
  - labels and path patterns as in the contract;
  - top 3 by count, then label;
  - the example `run_id` is the latest record;
  - labels, agent, shape, model and model_ids go through `feedback.redact` and are cut to 200 characters.
- `render_agents_text`: the exact line layout of the contract. Averages print with 2 decimals, `null` prints `n/a`,
  and `few runs` is marked.

**Done when:** the acceptance tests for AC-089.11, .12, .13, .14 (report columns and the resolved share) and the
report side of AC-089.9 pass, and the 087 report tests stay green.

## t4 — ship land records red-CI rounds against the coder

**Files:** scripts/cplat/ship.py
**Covers:** AC-089.5, AC-089.10
**Goal:** `cplat ship land` counts every red PR CI round against the shape's coder, with the first failed check as the
cause. A green conclusion marks the metric measured. Reruns are never counted.

**Implementation notes:**
- In `land`, right after `wait_checks(...)` returns, inside `try/except Exception: pass`, call
  `runs_agents.red_ci(st.get("run_id"), repo, [c["name"] for c in failed] if status == "red" else [])`.
- No recording in `merge_gitops`, `deploy` or `pr wait`. Nothing changes in the return values, the stdout or
  `fix_rounds`.

**Done when:** the AC-089.5 tests pass. A red round gives one `red-ci` event in the `svc:coder` (routed) entry of the
ship record, and no quality or security entry. A stuck or transient rerun followed by green gives no `red-ci` event
and `red_ci` measured. `test_ship*.py`, `test_tags_and_wait.py` and `test_runs*.py` stay green.

## t5 — spec test-diff records refused test diffs

**Files:** scripts/cplat/spec.py
**Covers:** AC-089.7, AC-089.10
**Goal:** `cplat spec test-diff <base> [files] [--by coder|quality] [--task T]` records each refused file against the
agent named by `--by` (default coder) in the current run. A passing run marks the metric measured.

**Implementation notes:**
- Add `--by` (default `coder`, no argparse `choices`) and `--task`.
- After printing the existing output: `runs_agents.refused_test_diff(runs.current_run(root), root, [(f, why) for f,
  (ok, why) in result.items() if not ok], by=ns.by, task=ns.task)` in `try/except Exception: pass`.
- `test_diff()` itself stays pure. Its output and the exit code (0/1) are unchanged.

**Done when:** the AC-089.7 tests pass, and `test_spec*.py` stays green (test-diff without a run behaves as before).

## t6 — Build, ship and app-build prompts record agent signals

**Files:** plugins/svc/commands/build.md, plugins/svc/commands/ship.md, plugins/app/commands/build.md
**Covers:** AC-089.1, AC-089.2, AC-089.3, AC-089.4, AC-089.6, AC-089.7, AC-089.8
**Goal:** the build orchestrator calls `cplat runs agent …` at every point of design.md "Build prompt calls". Each call
is one line next to the action it records. Recording never stops the build.

**Implementation notes:**
- `build.md` Phase 0 gets one rule: after every subagent spawn, `cplat runs agent spawned <role>` (plus
  `--model-id <id>` when known). These calls never fail the build, and a `WARNING: agent metric not recorded` line is
  not an error.
- Phase 1: after the trace and red checks, one `cplat runs agent tester` call with `--untraced` for each id sent back
  and `--wrong-failure` for each test sent back (no ids → still call it).
- Phase 2.4:
  - before each merge or sequential coder, `PRE=$(git rev-parse HEAD)`;
  - on a conflict, `cplat runs agent conflict <task>` before `git merge --abort`;
  - after a clean merge, or a sequential commit, `cplat runs agent merged <task> --since $PRE [--helper <path>]` (the
    helpers the coder reported);
  - `cplat spec test-diff $RED --task <task>`;
  - every hand-back gets `cplat runs agent fix-round lint/type|test --task <task>`.
- Phase 2.5: `fix-round test --task <task>`. Phase 3: tests red → coder `fix-round ci`, and `test-diff $RED --by
  quality` when the quality agent changed files in that round. Phase 4: after each reviewer pass,
  `cplat runs agent findings --cycle <n> [--deviation <id>]` for the deviations it judged not acceptable; each NOT MET
  sent to a coder → `fix-round verification --task <task>`.
- `ship.md`:
  - Phase `plan`: `cplat runs agent spawned architect` after the architect returns.
  - Phase `pr`: a red `devbox run ci` handed to the coder → `fix-round ci`.
  - Phase `land`: one sentence saying RED rounds are recorded by `cplat ship land` itself, so there is no call.
- `app/commands/build.md`: the repo agent instructions say the per-repo `/svc:build` records its run and agent
  metrics (spec 089) as usual.
- Keep the existing text of `test_spec_agents.py` assertions intact (only add lines).

**Done when:** the prompt-text parts of the acceptance tests for these criteria pass, and `test_spec_agents.py` stays
green: build.md names `cplat runs agent spawned`, `tester`, `merged … --since`, `conflict`, `fix-round`, `findings` and
`test-diff … --task`.

## t7 — Docs for agent metrics

**Files:** docs/CHANGELOG.md, docs/unattended-delivery.md, docs/AGENTS.md
**Covers:** none (documentation)
**Goal:** users learn what is measured per agent and how to read it.

**Implementation notes:**
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feat (089): agent quality is measured per agent, shape and
  model.** It names the build record's `agents` / `replans` sections, `cplat runs report --agents [--by-version]
  [--agent] [--shape] [--json]`, "not measured" shown as `n/a`, and that recording never stops a build. Only this task
  edits the CHANGELOG.
- `docs/unattended-delivery.md`: an "Agent metrics" subsection under "Run records":
  - what each metric counts and against which agent;
  - when a metric is "not measured";
  - the `few runs` mark;
  - comparing releases with `--by-version`;
  - incomplete metrics.
- `docs/AGENTS.md`: under "Parallel implementation via git worktrees", one paragraph: merge conflicts, out-of-plan files
  and hand-backs are recorded per agent (spec 089), with a pointer to `cplat runs report --agents`.
- No plugin or marketplace version bumps.

**Done when:** `devbox run validate` and the Markdown link check pass.
