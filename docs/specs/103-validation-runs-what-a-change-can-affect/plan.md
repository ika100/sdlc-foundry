---
spec_id: 103-validation-runs-what-a-change-can-affect
spec_hash: 987e235a8022
summary: cplat validate plans each check as run, reused or skipped by deterministic rules (full, mandatory categories,
  docs-only, mapped, no rule), reuses local evidence for identical inputs, records a validation section with misses;
  build and ship fix rounds use it, the final gate stays full
tasks:
  - id: t1
    title: shapes.yml validation keys (selector, mandatory globs per shape) and their registry check
    files: [shapes.yml, scripts/shapes.py]
    covers: [AC-103.3]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: validate.py planner — diff, checks from devbox.json, rules full/mandatory/docs-only/mapped/no rule, risk adds only
    files: [scripts/cplat/validate.py, scripts/cplat/cplat.py]
    covers: [AC-103.1, AC-103.2, AC-103.3, AC-103.4, AC-103.5, AC-103.9]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: Local evidence and reuse, validate run, validation section and misses (validate final, ship.run_ci)
    files: [scripts/cplat/validate.py, scripts/cplat/ship.py, scripts/cplat/runs.py, scripts/cplat/runs_report.py]
    covers: [AC-103.6, AC-103.7, AC-103.8, AC-103.10]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: build and ship fix rounds call cplat validate run; final gate stays cplat quiet ci
    files: [plugins/svc/commands/build.md, plugins/svc/commands/ship.md, plugins/svc/references/ship-land-red.md]
    covers: [AC-103.8]
    parallel_safe: false
    depends_on: [t3]
    done: true
  - id: t5
    title: runs benchmark --compare-validation
    files: [scripts/cplat/runs_bench.py, scripts/cplat/runs_usage_report.py]
    covers: [AC-103.11]
    parallel_safe: false
    depends_on: [t3]
    done: true
  - id: t6
    title: Docs — unattended-delivery.md, svc README, ADR index, CHANGELOG
    files: [docs/unattended-delivery.md, plugins/svc/README.md, docs/adr/README.md, docs/CHANGELOG.md]
    covers: [AC-103.9]
    parallel_safe: false
    depends_on: [t4, t5]
    done: false
---

# Plan — 103 Validation runs what a change can affect

Design: [design.md](design.md). Red tests first (`tests/cplat/test_validate.py`), then t1–t5, one coder, docs, reviewer.
