---
spec_id: 107-open-source-tools-are-adopted-on
spec_hash: bce40e66898d
summary: Benchmark arms (local sample-repo modifications applied before a run and removed by the reset), arm in the
  record and report, a recall check for test selection; then baseline and per-candidate trials of 5 runs each in the
  agreed order, one ADR per tool and an evaluations index
tasks:
  - id: t1
    title: Benchmark arms — arms/*.json, --arm applied after prepare, record benchmark.arm, report key, refusals
    files: [scripts/cplat/runs_bench.py, scripts/cplat/runs_usage_report.py, scripts/cplat/benchmark/arms/testmon.json,
      scripts/cplat/benchmark/arms/pytest-impact.json, scripts/cplat/benchmark/arms/semgrep.json,
      scripts/cplat/benchmark/arms/trivy.json, scripts/cplat/benchmark/arms/codebase-memory.json]
    covers: [AC-107.2, AC-107.9, AC-107.10]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: --recall — full suite after the session, a deselected failing test fails the arm's record
    files: [scripts/cplat/runs_bench.py]
    covers: [AC-107.3]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: Evaluation index and ADR record format (docs/evaluations.md, ADR index rows)
    files: [docs/evaluations.md, docs/adr/README.md]
    covers: [AC-107.6, AC-107.7, AC-107.8, AC-107.11]
    parallel_safe: true
    depends_on: []
    done: false
  - id: t4
    title: Baseline (5 build + 5 quick-task) and the change-aware test trials (testmon, pytest-impact) with records
    files: [docs/evaluations.md, docs/adr/045-evaluate-pytest-testmon.md, docs/adr/046-evaluate-pytest-impact.md]
    covers: [AC-107.1, AC-107.2, AC-107.3, AC-107.6, AC-107.7, AC-107.10]
    parallel_safe: false
    depends_on: [t1, t2, t3]
    done: false
  - id: t5
    title: Semgrep and Trivy trials with records
    files: [docs/evaluations.md, docs/adr/047-evaluate-semgrep.md, docs/adr/048-evaluate-trivy.md]
    covers: [AC-107.3, AC-107.4, AC-107.6]
    parallel_safe: false
    depends_on: [t4]
    done: false
  - id: t6
    title: Codebase-Memory MCP trial (or defer) and the tracing gap review with records
    files: [docs/evaluations.md, docs/adr/049-evaluate-codebase-memory-mcp.md, docs/adr/050-evaluate-llm-tracing.md]
    covers: [AC-107.3, AC-107.5, AC-107.6]
    parallel_safe: false
    depends_on: [t5]
    done: false
---

# Plan — 107 Open-source tools are adopted on measured value

Design: [design.md](design.md). Red tests for t1–t2 first (`tests/cplat/test_bench_arms.py`), then the code, then
the trials (each benchmark run is a real headless session against `ika100/todo-api`).
