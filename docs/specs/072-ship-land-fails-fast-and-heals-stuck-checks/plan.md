---
spec_id: 072-ship-land-fails-fast-and-heals-stuck-checks
spec_hash: a3e6924cd2b2
summary: a CheckWatch per PR reports conclusions, ends on the first red check and heals stale or stuck runs once
tasks:
- id: t1
  title: CheckWatch in ship land and ship deploy
  files: [scripts/cplat/ship.py, tests/cplat/test_ship_checks.py]
  covers: [AC-072.1, AC-072.2, AC-072.3, AC-072.4, AC-072.5]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: /svc:ship describes the new land and deploy
  files: [plugins/svc/commands/ship.md]
  covers: [AC-072.1, AC-072.3]
  parallel_safe: false
  depends_on: [t1]
  done: true
---

## t1 — CheckWatch in ship land and ship deploy

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship_checks.py
**Covers:** AC-072.1, AC-072.2, AC-072.3, AC-072.4, AC-072.5

## t2 — /svc:ship describes the new land and deploy

**Files:** plugins/svc/commands/ship.md
**Covers:** AC-072.1, AC-072.3
