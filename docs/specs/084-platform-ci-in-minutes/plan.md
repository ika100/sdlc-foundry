---
spec_id: 084-platform-ci-in-minutes
spec_hash: 453be283bb7c
summary: pytest-xdist; fail-fast false and Maven retries in the smoke matrices
tasks:
- id: t1
  title: Parallel tests
  files: [scripts/ci-local.sh]
  covers: [AC-084.1]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: Matrices and Maven
  files: [.github/workflows/ci.yml]
  covers: [AC-084.1, AC-084.2]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — Parallel tests

**Files:** scripts/ci-local.sh
**Covers:** AC-084.1

## t2 — Matrices and Maven

**Files:** .github/workflows/ci.yml
**Covers:** AC-084.1, AC-084.2
