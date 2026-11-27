---
spec_id: 222-the-ux-step-is-measured-on-website-plans
shape: platform
spec_hash: aff3f3e63c08
summary: "an opt-in ux-plan benchmark on system-ship's web clone, the eval gate asks for it on web/UX changes, the UX word rule tuned on real website specs"
tasks:
  - id: t1
    title: "Acceptance tests and the labelled cases"
    files: [tests/cplat/test_222_ux_measured.py, tests/cplat/fixtures/ux_cases.json]
    covers: [AC-222.1, AC-222.2, AC-222.3, AC-222.4, AC-222.5, AC-222.6, AC-222.7, AC-222.8, AC-222.9, AC-222.10, AC-222.11]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "The ux-plan workflow: task, spec 902, sample and clone, result check"
    files: [scripts/cplat/benchmark/tasks.json, scripts/cplat/benchmark/spec-902.md, scripts/cplat/runs_bench.py, scripts/cplat/benchmark/README.md]
    covers: [AC-222.1, AC-222.2, AC-222.3, AC-222.4, AC-222.5, AC-222.11]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: "The eval gate selects ux-plan for web prompt and UX step changes"
    files: [scripts/cplat/evalgate.py]
    covers: [AC-222.6, AC-222.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: "The tuned UX rule and its help"
    files: [scripts/cplat/spec_ux.py]
    covers: [AC-222.8, AC-222.9, AC-222.10, AC-222.11]
    parallel_safe: true
    depends_on: [t1]
    done: true
---

# Plan — 222 The UX step is measured on website plans

See [design.md](design.md). One PR: tests first (t1), then the benchmark (t2), the gate (t3) and the rule (t4), which touch separate files.
