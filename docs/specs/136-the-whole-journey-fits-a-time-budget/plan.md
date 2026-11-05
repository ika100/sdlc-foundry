---
spec_id: 136-the-whole-journey-fits-a-time-budget
shape: platform
spec_hash: 49217098fed8
summary: "A journey is one run record of kind journey, fed by `cplat platform runs journey begin|stage|wait|pr|round|show|end` (runs_journey.py): 15 stages with budgets, waits as intervals of the journey, working = wall − person-wait, parts and the journey as spans with their overlap; core.run notes GitHub rate-limit waits as external waits; `cplat platform runs report --benchmarks` gets the journey medians per platform version and coordinator model, the previous version and the overrun ranking (runs_journey_report.py, key `journey`); ADR-081; AC-136.11 withdrawn and moved to spec 144"
tasks:
  - id: t1
    title: runs_journey.py — stage table, time model, pointer, recording API and the `runs journey` CLI; runs.py dispatch
    files: [scripts/cplat/runs_journey.py, scripts/cplat/runs.py]
    covers: [AC-136.1, AC-136.2, AC-136.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: core.run — a rate-limit wait is an external wait of the open journey
    files: [scripts/cplat/core.py]
    covers: [AC-136.3]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: runs_journey_report.py — journey medians, previous version, ranking, text; `journey` key in report --benchmarks
    files: [scripts/cplat/runs_journey_report.py, scripts/cplat/runs_usage_report.py]
    covers: [AC-136.8]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: docs — runs command, ADR-081 and its index row, changelog fragment, platform plugin bump
    files: [plugins/platform/commands/runs.md, docs/adr/081-a-journey-is-measured-in-stages-of-working-time.md, docs/adr/README.md, docs/changelog.d/136-journey-measurement.added.md, plugins/platform/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-136.1, AC-136.8]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 136 The whole journey fits a time budget

[design.md](design.md) is the contract. [ADR-081](../../adr/081-a-journey-is-measured-in-stages-of-working-time.md) records
the time model.

**Levels:**

| Level | Tasks |
|---|---|
| 1 | t1, t4 |
| 2 | t2, t3 |

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

## AC-136.11 (moved)

Withdrawn on 2026-11-05 by the user's decision and moved to spec 144 (one gitops PR per environment for a system
ship); design § AC-136.11 keeps the measurement it starts from.

## Acceptance tests

Written first, one criterion id per test name, in `tests/cplat/test_136_journey_record.py` (AC-136.1–3, through the CLI
with a fake clock and `--at`) and `tests/cplat/test_136_journey_report.py` (AC-136.8, through `runs.main(["report",
"--benchmarks", ...])` on an in-memory store, as `test_runs_usage_bench.py` does).
