---
spec_id: 076-ship-carries-the-gitops-changes-of-a-spec
spec_hash: 1d2778686a96
summary: gitops tasks in plan.md, opened as draft PRs by cplat ship gitops, merged by land and deploy in order
tasks:
- id: t1
  title: Validate gitops tasks and human_steps
  files: [scripts/cplat/spec.py]
  covers: [AC-076.1]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: cplat ship gitops prepare/pr, merges in land and deploy, health of every app, human steps
  files: [scripts/cplat/ship.py, tests/cplat/test_ship_checks.py]
  covers: [AC-076.2, AC-076.3, AC-076.4, AC-076.5]
  parallel_safe: false
  depends_on: []
  done: true
- id: t3
  title: Architect, /svc:plan and plan reference
  files: [plugins/svc/agents/architect.md, plugins/svc/commands/plan.md, plugins/svc/skills/spec-format/references/plan.md,
    plugins/svc/commands/ship.md]
  covers: [AC-076.6]
  parallel_safe: true
  depends_on: []
  done: true
---

## t1 — Validate gitops tasks and human_steps

**Covers:** AC-076.1

## t2 — cplat ship gitops prepare/pr, merges in land and deploy

**Covers:** AC-076.2, AC-076.3, AC-076.4, AC-076.5

## t3 — Architect, /svc:plan and plan reference

**Covers:** AC-076.6
