---
spec_id: 102-runs-stay-within-a-budget-and-stop
spec_hash: c23ce0359a7d
summary: One budget per run tree in a local ledger (defaults ×ships, --budget, off), checked at safe points (session,
  subagent hook, CI rerun, phase end, repo ship start), stop escalates with cause decision; no-progress attempts,
  recovery snapshot, verified stages for resume
tasks:
  - id: t1
    title: budget.py — ledger, defaults and multiplier, --budget parsing, root_of, usage (peek cost), check, stop section
    files: [scripts/cplat/budget.py, scripts/cplat/runs_usage.py, scripts/cplat/settings.py]
    covers: [AC-102.1, AC-102.2, AC-102.4, AC-102.5, AC-102.6]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: Safe points — headless sessions, ship start and set_phase, CI reruns (ship land, pr wait), app-ship, runs begin
    files: [scripts/cplat/headless.py, scripts/cplat/ship.py, scripts/cplat/pr.py, scripts/cplat/appship.py,
      scripts/cplat/appship_sched.py, scripts/cplat/runs.py]
    covers: [AC-102.2, AC-102.3, AC-102.7, AC-102.8]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: cplat budget CLI (show, gate --invocation) and the shared plugin's PreToolUse hook on Task|Agent
    files: [scripts/cplat/budget.py, scripts/cplat/cplat.py, plugins/shared/hooks/hooks.json]
    covers: [AC-102.1, AC-102.3]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t4
    title: No-progress attempts (normalised errors) in ship land and `cplat budget attempt`
    files: [scripts/cplat/budget.py, scripts/cplat/ship.py]
    covers: [AC-102.9]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t5
    title: Recovery snapshot on escalation, budget stop and no-progress stop
    files: [scripts/cplat/budget.py, scripts/cplat/ship.py]
    covers: [AC-102.10]
    parallel_safe: false
    depends_on: [t4]
    done: true
  - id: t6
    title: Verified stages (`budget stage`, `runs gate`) and `cplat budget resume`; build.md and build-resume.md use them
    files: [scripts/cplat/budget.py, scripts/cplat/runs.py, plugins/svc/commands/build.md,
      plugins/svc/references/build-resume.md]
    covers: [AC-102.11, AC-102.12]
    parallel_safe: false
    depends_on: [t5]
    done: true
  - id: t7
    title: Docs — unattended-delivery.md budgets section, shared README, ADR index, CHANGELOG, plugin versions
    files: [docs/unattended-delivery.md, plugins/shared/README.md, docs/adr/README.md, docs/CHANGELOG.md]
    covers: [AC-102.1, AC-102.7]
    parallel_safe: false
    depends_on: [t6]
    done: false
---

# Plan — 102 Runs stay within a budget and stop repeating failures

Design: [design.md](design.md). Red tests first (`tests/cplat/test_budget.py`, plus updates to the headless, ship and
pr wait tests), then t1–t6 in order, one coder, then docs and the reviewer.
