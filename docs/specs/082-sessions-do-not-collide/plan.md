---
spec_id: 082-sessions-do-not-collide
spec_hash: a5382cd9ffeb
summary: claim.py used by spec new and ship start; spec-required check in the platform CI
tasks:
- id: t1
  title: Claims
  files: [scripts/cplat/claim.py, tests/cplat/test_claims.py, tests/cplat/conftest.py, plugins/svc/commands/spec.md]
  covers: [AC-082.1]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: Spec required in platform PRs
  files: [scripts/check-spec-required.py]
  covers: [AC-082.2]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — Claims

**Files:** scripts/cplat/claim.py, tests/cplat/test_claims.py, tests/cplat/conftest.py, plugins/svc/commands/spec.md
**Covers:** AC-082.1

## t2 — Spec required in platform PRs

**Files:** scripts/check-spec-required.py
**Covers:** AC-082.2
