---
spec_id: 071-adopt-an-existing-repo
spec_hash: 88a29e4361ec
summary: cplat adopt renders the template to a scratch dir and copies only what is missing
tasks:
- id: t1
  title: cplat adopt
  files: [scripts/cplat/adopt.py, scripts/cplat/cplat.py, tests/cplat/test_adopt.py]
  covers: [AC-071.1, AC-071.2, AC-071.3, AC-071.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: Adoption guide
  files: [docs/ADOPTING.md]
  covers: [AC-071.3]
  parallel_safe: false
  depends_on: [t1]
  done: true
---

## t1 — cplat adopt

**Files:** scripts/cplat/adopt.py, scripts/cplat/cplat.py, tests/cplat/test_adopt.py
**Covers:** AC-071.1, AC-071.2, AC-071.3, AC-071.4

## t2 — Adoption guide

**Files:** docs/ADOPTING.md
**Covers:** AC-071.3
