---
spec_id: 070-headless-runs-resume-until-finished
spec_hash: 567e93847322
summary: cplat headless loops claude -p sessions while the ship state is unfinished
tasks:
- id: t1
  title: cplat headless
  files: [scripts/cplat/headless.py, scripts/cplat/cplat.py, tests/cplat/test_headless.py]
  covers: [AC-070.5, AC-070.2, AC-070.3, AC-070.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: Unattended runs guide
  files: [docs/ADOPTING.md, docs/unattended-delivery.md]
  covers: [AC-070.5]
  parallel_safe: false
  depends_on: [t1]
  done: true
---

## t1 — cplat headless

**Files:** scripts/cplat/headless.py, scripts/cplat/cplat.py, tests/cplat/test_headless.py
**Covers:** AC-070.5, AC-070.2, AC-070.3, AC-070.4

## t2 — Unattended runs guide

**Files:** docs/ADOPTING.md, docs/unattended-delivery.md
**Covers:** AC-070.5
