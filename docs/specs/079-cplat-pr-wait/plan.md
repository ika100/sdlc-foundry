---
spec_id: 079-cplat-pr-wait
spec_hash: ae3a1680d95c
summary: cplat pr wait on the shared CheckWatch, which reruns transient failures once
tasks:
- id: t1
  title: Transient rerun in CheckWatch
  files: [scripts/cplat/ship.py]
  covers: [AC-079.2, AC-079.3]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: cplat pr wait
  files: [scripts/cplat/pr.py, scripts/cplat/cplat.py, tests/cplat/test_tags_and_wait.py, CLAUDE.md]
  covers: [AC-079.1]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — Transient rerun in CheckWatch

**Files:** scripts/cplat/ship.py
**Covers:** AC-079.2, AC-079.3

## t2 — cplat pr wait

**Files:** scripts/cplat/pr.py, scripts/cplat/cplat.py, tests/cplat/test_tags_and_wait.py, CLAUDE.md
**Covers:** AC-079.1
