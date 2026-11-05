---
spec_id: 136-the-whole-journey-fits-a-time-budget
shape: platform
spec_hash: bb6c73369c48
summary: "A journey is one run record of kind journey, fed by `cplat platform runs journey begin|stage|wait|pr|round|show|end` (runs_journey.py): 15 stages with budgets, waits as intervals of the journey, working = wall − person-wait, parts and the journey as spans with their overlap; core.run notes GitHub rate-limit waits as external waits; `cplat platform runs report --benchmarks` gets the journey medians per platform version and coordinator model, the previous version and the overrun ranking (runs_journey_report.py, key `journey`); ADR-081; AC-136.11 measured and planned as t6, not built"
tasks:
  - id: t1
    title: runs_journey.py — stage table, time model, pointer, recording API and the `runs journey` CLI; runs.py dispatch
    files: [scripts/cplat/runs_journey.py, scripts/cplat/runs.py]
    covers: [AC-136.1, AC-136.2, AC-136.3]
    parallel_safe: true
    depends_on: []
    done: false
  - id: t2
    title: core.run — a rate-limit wait is an external wait of the open journey
    files: [scripts/cplat/core.py]
    covers: [AC-136.3]
    parallel_safe: true
    depends_on: [t1]
    done: false
  - id: t3
    title: runs_journey_report.py — journey medians, previous version, ranking, text; `journey` key in report --benchmarks
    files: [scripts/cplat/runs_journey_report.py, scripts/cplat/runs_usage_report.py]
    covers: [AC-136.8]
    parallel_safe: true
    depends_on: [t1]
    done: false
  - id: t4
    title: docs — runs command, ADR-081 and its index row, changelog fragment, platform plugin bump
    files: [plugins/platform/commands/runs.md, docs/adr/081-a-journey-is-measured-in-stages-of-working-time.md, docs/adr/README.md, docs/changelog.d/136-journey-measurement.added.md, plugins/platform/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-136.1, AC-136.8]
    parallel_safe: true
    depends_on: []
    done: false
  - id: t6
    title: one gitops PR per environment per spec (deferred, see design § AC-136.11)
    files: [scripts/cplat/appship_sched.py, scripts/cplat/appship.py, scripts/cplat/ship.py, scripts/cplat/staging_deploy.py, scripts/cplat/systemset.py, templates/gitops-app/.github/workflows/pin-dev.yml, plugins/system/commands/ship.md]
    covers: [AC-136.11]
    parallel_safe: false
    depends_on: []
    done: false
---

# Plan — 136 The whole journey fits a time budget

[design.md](design.md) is the contract. [ADR-081](../../adr/081-a-journey-is-measured-in-stages-of-working-time.md) records
the time model.

**Levels:**

| Level | Tasks |
|---|---|
| 1 | t1, t4 |
| 2 | t2, t3 |
| — | t6 (open, not built in this build) |

## t1 — the journey record

`runs_journey.py` holds `STAGES` (id, part, budget) and `PARTS`, the pure `compute(raw, now)` of design § Time model, the
pointer `<state dir>/journey.json`, and the verbs of design § CLI. The raw state lives in the active record under
`journey_raw` (stages with start, end, PR URLs and rounds; waits); `end` replaces it with the computed `journey` section
through `runs.finish(..., fields=...)`. `runs.main` dispatches `journey` as it does `benchmark`.

## t2 — rate-limit waits

`core.run` records the start of each rate-limit sleep and after it calls `runs_journey.note_external_wait`. The import is
lazy and inside `try`, so `core` keeps working without a journey and `runs_journey` may import `core`.

## t3 — the report

`runs_journey_report.aggregate(kept)` and `render_lines(agg)`, called from `runs_usage_report.aggregate_benchmarks` (key
`journey`, after the existing keys) and `render_benchmarks_text` (lines after the benchmark lines).

## t4 — docs

`/platform:runs` names the journey commands; ADR-081 with its README row; the changelog fragment; platform plugin
1.5.1 → 1.6.0 in `plugin.json` and `marketplace.json` (a command text changed and gained a feature).

## t6 — one gitops PR per environment (open)

Not built in this build; design § AC-136.11 has the measurement and what it needs: the entry PR held until the last
component merged, `pin-dev` pushing onto `compose/<spec>` during a system ship, the component ship's deploy phase ending
at the pin, the system ship landing the entry and running every dev smoke; for part 3 the command of #427 and `system set`
with several settings of one environment. It needs its own design pass with spec 143 and #474, which change the same files.

## Acceptance tests

Written first, one criterion id per test name, in `tests/cplat/test_136_journey_record.py` (AC-136.1–3, through the CLI
with a fake clock and `--at`) and `tests/cplat/test_136_journey_report.py` (AC-136.8, through `runs.main(["report",
"--benchmarks", ...])` on an in-memory store, as `test_runs_usage_bench.py` does). AC-136.11 gets no test in this build.
