---
spec_id: 065-merges-wait-for-green-ci-without-branch
spec_hash: a72aba2db709
summary: pin-dev runs the gitops CI as a reusable workflow on the pin branch and merges only on green; new-service names what still guards merges
tasks:
- id: t1
  title: Callable gitops CI and a pin-dev that merges after it
  files: [templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/.github/workflows/pin-dev.yml, tests/cplat/test_gitops.py]
  covers: [AC-065.1, AC-065.2, AC-065.3]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: new-service reports the free-plan fallback
  files: [scripts/cplat/newsvc.py, tests/cplat/test_newsvc.py]
  covers: [AC-065.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t3
  title: cplat ship land merges only on green
  files: [scripts/cplat/ship.py, tests/cplat/test_ship.py]
  covers: [AC-065.5]
  parallel_safe: true
  depends_on: []
  done: true
---

## t1 — Callable gitops CI and a pin-dev that merges after it

**Files:** templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/.github/workflows/pin-dev.yml, tests/cplat/test_gitops.py
**Covers:** AC-065.1, AC-065.2, AC-065.3

## t2 — new-service reports the free-plan fallback

**Files:** scripts/cplat/newsvc.py, tests/cplat/test_newsvc.py
**Covers:** AC-065.4

## t3 — cplat ship land merges only on green

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship.py
**Covers:** AC-065.5
