# Design — 136 The whole journey fits a time budget

## Decisions

- **A journey is one run record of kind `journey`** (spec 087). It is started, fed and ended through
  `cplat platform runs journey …`, by hand or by the coordinator that follows the fixed script. A journey spans several
  repos and sessions, so its pointer is not the per-checkout `cplat-run.json` but one machine-wide file
  `<runs state dir>/journey.json`. Only one journey is open at a time. ADR:
  [ADR-081](../../adr/081-a-journey-is-measured-in-stages-of-working-time.md).
- **The script states the stages, cplat does the arithmetic.** A stage is opened and closed with
  `journey stage <id> start|end`. Every event takes `--at <ISO time>`, so a journey reconstructed afterwards from
  transcripts and Actions runs (as on 2026-11-05) is recorded with the same command.
- **Waits are intervals of the journey, not of a stage.** A person wait or an external wait is recorded once
  (`journey wait person|external start|end`, or `add --minutes M` afterwards). A stage's waits are the overlap of the
  journey's waits with the stage's span, so a wait that falls into two overlapping stages counts in both, and once in their
  part.
- **External waits are also recorded on their own.** `core.run` already waits out GitHub's rate limit (spec 137). While a
  journey is open it adds that wait as an external wait, best effort and silently. Runner queues and the image registry
  are recorded by the script with `journey wait external`.
- **The time model** (contract below) is the one the spec gives: working = wall clock − person-wait; a part and the journey
  are spans (critical path), not sums. The journey is the span over all its stages, the same formula as a part, so a
  pause between two parts counts as working time unless it is recorded as a person wait (a platform fix, a restart).
- **PRs and extra rounds are named by the script.** `journey pr <url>` counts a PR for a stage (default: the open stage that
  started last); `journey round <kind> --cause <cause>` records an extra round. No GitHub call is made.
- **The report lives with the benchmarks.** `cplat platform runs report --benchmarks` adds a journey section and the JSON
  key `journey`; the existing keys and their values are unchanged.
- **AC-136.11 moved to spec 144.** The user withdrew it from this spec on 2026-11-05. The measurement below (journey 2)
  is where spec 144 starts: the extra dev PRs come from the per-component `pin-dev` dispatch and the gitops entry landing
  first.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/runs_journey.py` | the stage table and budgets, the time model (`compute`), the pointer, the recording API (`begin`, `stage`, `wait`, `pr`, `round`, `end`, `note_external_wait`) and the CLI `cplat platform runs journey` | new |
| `scripts/cplat/runs_journey_report.py` | the journey aggregation of `report --benchmarks` (medians per platform version and coordinator model, previous version, ranking) and its text | new |
| `scripts/cplat/runs.py` | dispatch `runs journey …`; usage line | changed |
| `scripts/cplat/runs_usage_report.py` | `aggregate_benchmarks` adds `journey`, `render_benchmarks_text` appends the journey section | changed |
| `scripts/cplat/core.py` | a rate-limit wait inside `run` is noted as an external wait of the open journey | changed |
| `plugins/platform/commands/runs.md` | names the journey commands | changed |

## Contract

### Stages and budgets

Ids are `<part>.<stage>`, in this order (the order of the spec's table):

| Id | Budget (min) | Id | Budget (min) | Id | Budget (min) |
|---|---|---|---|---|---|
| `1.scaffold` | 2 | `2.scaffold` | 2 | `3.env-settings` | 2 |
| `1.cluster` | 2 | `2.spec` | 5 | `3.staging-prod` | 8 |
| `1.spec` | 3 | `2.plan` | 3 | | |
| `1.plan` | 2 | `2.build` | 12 | | |
| `1.build` | 10 | `2.pr-ci` | 3 | | |
| `1.pr-ci` | 3 | `2.deploy-dev` | 2 | | |
| `1.deploy-dev` | 2 | | | | |

Part budgets: 1 → 20, 2 → 30, 3 → 10. Journey: budget 60, interim 90, stretch 50.

### CLI

```
cplat platform runs journey begin [--task-version N] [--model M] [--repo OWNER/NAME] [--at T]
cplat platform runs journey stage <id> start|end [--at T]
cplat platform runs journey wait person|external start [--reason R] [--at T]
cplat platform runs journey wait person|external end [--at T]
cplat platform runs journey wait person|external add --minutes M [--at T] [--reason R]   (T = the wait's start; default now − M)
cplat platform runs journey pr <url> [--stage <id>] [--at T]
cplat platform runs journey round <kind> --cause <cause> [--stage <id>] [--note N] [--at T]
cplat platform runs journey show [--json]
cplat platform runs journey end --outcome done|failed|escalated|abandoned [--reason R] [--at T]
```

- `begin` refuses while a journey is open (hint: `journey end --outcome abandoned`). It prints `journey <run_id>`.
  `--task-version` defaults to 1, `--model` to `unknown`. A `begin --at` (a journey reconstructed afterwards) claims no Claude Code session for the
  record's usage (spec 099); a live `begin` does.
- Every other verb refuses without an open journey (hint: `journey begin`). An unknown stage id, a `stage end` of a
  stage that never started, a second open wait of the same kind, or a `wait end` without an open wait is refused with the
  reason; nothing is changed.
- `stage start` of a started stage keeps its first start; `stage end` sets the end to the latest end.
- `round` kinds: `fix-round`, `ci-rerun`, `escalation`, `resumed-session`, `reworked-spec`, `reworked-plan`. Causes: the
  run-record causes `platform`, `code`, `decision`, `environment`, `unknown`.
- `pr` and `round` without `--stage` go to the open stage that started last; with no open stage they are refused.
- `show` prints the stage table computed now (open stages, shown as `open`, and waits end at now); `--json` prints the
  `journey` section.
- `end` closes open waits and stages at its time (`--at`, else now), computes the section, writes it to the record with
  `runs.finish` and removes the pointer. Its outcome is the record's outcome; the record's own `ended_at` is the time the
  command ran.
- Times are UTC; `--at` takes `YYYY-MM-DDTHH:MM[:SS]Z` (or with an offset).

### The record

The finished record (kind `journey`) carries `journey`:

```json
{"schema": 1, "task_version": 1, "coordinator_model": "opus",
 "stages": [{"id": "1.scaffold", "part": 1, "status": "done", "started_at": "…", "ended_at": "…",
             "wall_minutes": 3.0, "working_minutes": 3.0, "person_wait_minutes": 0.0, "external_wait_minutes": 0.0,
             "budget_minutes": 2, "prs": 1, "pr_urls": ["…"],
             "extra_rounds": [{"kind": "ci-rerun", "cause": "environment", "note": "…"}]}, …],
 "parts": [{"part": 1, "status": "done", "started_at": "…", "ended_at": "…", "wall_minutes": …, "working_minutes": …,
            "person_wait_minutes": …, "external_wait_minutes": …, "budget_minutes": 20, "prs": …, "extra_rounds": …,
            "stages_sum_minutes": …, "overlap_minutes": …}, …],
 "total": {"status": "done", …the same fields…, "budget_minutes": 60, "interim_minutes": 90, "stretch_minutes": 50},
 "waits": [{"kind": "person", "started_at": "…", "ended_at": "…", "reason": "…"}, …]}
```

- `stages` holds all 15 stages in table order. `status`: `done` (ended), `stopped` (started, not ended when the journey
  ended: its end is the journey's end) or `not run`. A `not run` stage has `null` for `started_at`, `ended_at` and every
  `*_minutes` field and `0` PRs; never 0 minutes.
- `parts` holds parts 1–3; a part without any stage run is `not run` with `null` times. `extra_rounds` of a part and of
  `total` is the count; of a stage, the list.
- Minutes are floats rounded to one decimal.

### Time model

For an interval set `P` (the union of person waits) and `E` (the union of external waits):

- stage `[s, e]`: wall = `e − s`; person = `|P ∩ [s, e]|`; external = `|(E − P) ∩ [s, e]|`; working = wall − person.
  A minute in a person wait and an external wait at once is a person minute only.
- part (and `total`): span `[min s, max e]` over its stages that ran; wall, person, external and working as for a stage
  over the span. `stages_sum_minutes` = Σ stage working; `overlap_minutes` = Σ stage working − `|U − P|`, where `U` is the
  union of the stage spans. With no gap between the stages, part working = Σ stage working − overlap (AC-136.2).
- PRs: a stage counts its distinct URLs; a part and `total` the sum.

### Report (`cplat platform runs report --benchmarks`)

Records: kind `journey`, inside the report window (`runs_report.select`). Groups: (`platform_version`,
`journey.coordinator_model`). JSON key `journey`, one entry per group keyed `"<version> (<model>)"`:

```json
{"platform_version": "5.9.1", "coordinator_model": "opus", "runs": 3, "done": 2, "outcomes": {"done": 2, "failed": 1},
 "previous_version": "5.9.0",
 "stages": [{"id": "2.build", "part": 2, "runs": 2, "working_median": 16.0, "wall_median": 18.5, "budget_minutes": 12,
             "overrun_minutes": 4.0, "person_wait_median": 0.0, "external_wait_median": 1.0, "prs_median": 1,
             "previous": {"working_median": 18.0, "wall_median": 20.0}}, …],
 "parts": [{"part": 1, …the same fields…}, …],
 "total": {…the same fields…}}
```

- Medians are over the group's `done` runs, per stage over those where the stage ran. A stage or part that ran in no done
  run has `runs` 0 and `null` medians.
- `overrun_minutes` = `max(0, working_median − budget)`. `stages` is sorted by `working_median − budget`, largest first;
  stages without a median come last in table order.
- `previous_version` is the highest platform version below this one (numeric compare of the dotted parts) that has done
  journey runs with the same coordinator model; `previous` holds its medians for the same stage, part or total (`null`
  when there is none).
- Text: one block per group after the benchmark lines, newest platform version first, header `Journey <version> (<model>): <runs> run(s), <done> done`,
  then a table with columns stage, working, wall, budget, over, person, external, PRs, `prev <version>` (working / wall),
  the stages in ranking order, then parts 1–3 and `journey`. A group without done runs says `no done run`. No journey
  records: `Journey: none`.

### The rate-limit hook

`core.run`, after each rate-limit sleep, calls `runs_journey.note_external_wait(seconds, kind)` (imported lazily, any
exception swallowed). It appends an external wait from now − `seconds` to now, reason `GitHub rate limit (<kind>)`, to the
open journey, if any. It never prints and never changes the result of `run`.

## AC-136.11 — measured, moved to spec 144

Journey 2 (`ika100-demo/taskboard2-gitops`, 2026-11-05), gitops PRs for the part 2 system spec 002: #10 spec, #11 spec and
plan, **#12 the compose entry (postgres, web wiring), #13 pin-dev api, #14 pin-dev web**, #15 done. Dev got three PRs
where AC-136.11 allows one. Part 3 environment settings: #16 staging host, #17 prod host, #18 observability (by hand),
#23 backups bucket: four PRs.

Where they come from:

1. `appship_sched` starts the gitops entry first (plan order), and `appship entry land` merges it before any component
   repo starts, so the resources exist when the components' dev smoke runs.
2. Each component's CI dispatches `pin-dev` after its merge to main; the gitops-app's `pin-dev.yml` opens and merges one
   PR per component. The component ship's deploy phase finds that run by name (spec 077) and runs the dev smoke.
3. `system set --env` takes one environment per call; observability and backups have no command (#427).

What one PR per environment needs: the entry PR stays open until the last component of the plan has merged; `pin-dev`
pushes its pin onto the open `compose/<spec>` branch instead of opening a PR while a system ship of that component runs;
the component ship under a system ship ends its deploy phase at "pinned on compose/<spec>"; the system ship lands the
entry after the last pin and runs every dev smoke; a red component holds the dev deploy of the others. For part 3, the
command of #427 plus `system set` taking several settings of one environment. That touches the system ship's order, the
component ship's deploy phase, `pin-dev.yml` in every rendered gitops-app and the dev smoke: the files of spec 143 and
#474, so it is its own spec (144).
