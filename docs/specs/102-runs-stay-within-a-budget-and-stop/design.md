# Design — 102 Runs stay within a budget and stop repeating failures

## Decisions

- **One ledger per run tree, outside the run records.** Run records (spec 087) are written once at `finish`, and a
  resumed run is a new record (`resumes`), so they cannot carry usage across a resume. The budget lives in a small
  local ledger, `runs.state_dir()/budgets/<key>.json`, keyed by the work it covers: `<repo slug or dir>:<spec or
  prompt>` of the root run. A new root for the same work while the ledger is not `done` continues it (AC-102.6); a
  tree that ends `done` closes the ledger, so the next run of that work starts fresh. ADR:
  [043](../../adr/043-one-budget-per-run-tree.md).
- **The root owns the budget, children find it through `parent`.** Roots are the runs with no parent: `cplat
  headless`, `cplat app-ship` (the `product-ship` record), a `cplat ship start` by hand, and a `cplat runs begin
  build` by hand. `budget.root_of(run_id)` follows `parent` through the active records (`runs.active`). A child never
  opens a ledger of its own (AC-102.2), so `ship start` under headless or under a product ship, and a build attached
  to a ship (`runs.current`), all count against the root's ledger.
- **Defaults** (AC-102.1): per ship `minutes=180, invocations=60, reruns=6, cost=15`. The root multiplies them by the
  number of ships it covers: headless by the spec numbers in its prompt (`/svc:ship 102 103` → 2, at least 1), the
  product ship by the repos in its plan. `settings.py` may override the per-ship defaults (`budget:` in
  `.platform-settings.yml` or the user file, same precedence as `coordinator_model`). A root takes
  `--budget KEY=VALUE` (repeatable; key `minutes|invocations|reruns|cost`, value a number or `off`), which replaces
  that limit after multiplying. A changed limit on a continued ledger is appended to `changes` (AC-102.6).
- **Usage is measured where it happens.**
  - minutes: `carried.minutes` (earlier trees of the ledger) + wall clock since the current root started.
  - invocations: a counter. `headless` adds 1 per session, a root started in an interactive session adds 1, and the
    shared plugin's new `PreToolUse` hook on `Task|Agent` runs `cplat budget gate --invocation`, which adds 1 per
    subagent and refuses it (exit 2, the reason on stderr) when the budget is used up.
  - reruns: a counter. Every place that reruns CI (`ship.CheckWatch`, `cplat pr wait`) asks
    `budget.allow_rerun(run_id)` first; a refusal is a stop instead of the rerun.
  - cost: the sum over the tree's active records of `runs_usage.for_run(rec, ended_at=now, peek=True)` (a new
    `peek` that does not mark claims ended). `cost_complete` false or a missing price makes it `unknown`; then the cost
    limit is not checked and the other three are (AC-102.5). Cost is read only at safe points, never per call.
- **Safe points** (AC-102.3) are the places code already passes: before each headless session, the
  `PreToolUse` hook before a subagent, before a CI rerun, `ship.set_phase` (the end of a phase), and before the
  product ship starts a repo ship. `budget.check(run_id, point)` returns `None` or the exhausted limit. Nothing is
  killed: a running session or CI run finishes, the next start is refused.
- **A stop** writes the `budget` section (`limits`, `used`, `limit`, `phase`, `point`) into the stopping run's record
  and the root's (AC-102.4), then escalates the run the usual way with cause `decision` and reason
  `budget exhausted: <limit>`: `ship.escalate` for a ship, the product ship's own escalation, and for headless the
  result line `budget exhausted: <limit>`, which `stop_of` maps to stop reason `budget`, outcome `escalated`, exit 1
  (AC-102.7). Gates not reached stay `not run` (the existing `runs.finish` fill, AC-102.8); the outcome is never
  `done`.
- **No progress** (AC-102.9): `budget.attempt(repo, stage, error, failing)` appends the attempt to the ship state (or
  the ledger without a ship) and returns the stop reason when the last 3 attempts of that stage are equivalent with no
  progress between them. Normalisation removes ISO timestamps, clock times, absolute and relative paths, hex ids of 7+
  characters, UUIDs, `line N`/`:N` numbers and collapses whitespace. Progress is fewer failing checks, or a check of
  the previous attempt's failing set that passes now. Callers: `ship.land` (stage `ci`, error = failing check names +
  their log tail) and `cplat budget attempt <stage> --failing N [--names a,b] --error-file F` for build's fix loop
  (exit 3 with the reason on a stop). The 3-fix-round rule of `cplat ship` and the two-idle-session stop of headless
  stay as they are.
- **Recovery snapshot** (AC-102.10): `budget.snapshot(repo, stage, excerpt, criteria)` writes
  `<git common dir>/cplat-recovery.json` on every escalation through `ship.escalate`, on a budget stop and on a
  no-progress stop: stage, excerpt (last 40 lines, `feedback.redact`), changed files (`git diff --name-only` against
  the merge base with the default branch, plus the working tree), the `AC-<NNN>.<n>` ids in the excerpt and in the
  changed test files, and the attempts of that stage. No prompts, no full logs; nothing reads it into a run record or
  the store.
- **Verified stages** (AC-102.11, AC-102.12): `cplat runs gate <gate> <result>` and the new
  `cplat budget stage <name> passed|failed` record `{result, head, inputs}` in the ship state's `stages` (or the
  ledger), where `inputs` hashes `git status --porcelain` plus the uncommitted diff. `cplat budget resume` prints, per
  stage of build and ship (`acceptance`, `quality`, `tests`, `security`, `verify`, `image`, `ci`), `skip` only for a
  passed result on the current HEAD and inputs, otherwise `run` with the reason (`missing`, `failed`, `skipped`,
  `stale`, `unreadable`), and the snapshot's stage and excerpt first. `build-resume.md` and ship's resume step use it.
- **Commands stay thin.** `build.md` calls `cplat budget attempt` in its fix loop and `cplat budget resume` on resume;
  `ship.md` needs no new step (its safe points are in cplat). `cplat budget show` prints limits, usage and the root.

## Contract

```
cplat budget show [--json]                         limits, used, root run, ledger key ("no budget" outside a run)
cplat budget gate [--invocation]                   exit 0 allowed, 2 refused (stderr: budget exhausted: <limit>)
cplat budget attempt <stage> --failing N [--names a,b] (--error-file F | --error TEXT)   exit 0, or 3 + reason
cplat budget stage <name> passed|failed            record a verified stage result for HEAD + inputs
cplat budget resume [--json]                       skip/run per stage, the snapshot first
--budget KEY=VALUE  on: cplat headless, cplat ship start, cplat app-ship start, cplat runs begin
```

Ledger (`budgets/<sha1 of key>.json`):
`{"key", "limits": {minutes, invocations, reruns, cost}, "carried": {minutes, invocations, reruns, cost},
"used": {invocations, reruns}, "roots": [run_id...], "started_at", "changes": [{at, limit, from, to}], "state":
"open"|"stopped"|"done", "attempts": {stage: [...]}, "stages": {name: {...}}}` (`off` is stored as `null`).

Record section `budget`: `{"limits", "used", "limit", "phase", "point"}`; `used.cost` is a number or `"unknown"`.
