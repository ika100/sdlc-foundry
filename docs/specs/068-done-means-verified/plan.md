---
spec_id: 068-done-means-verified
spec_hash: 5d6fb01184f2
summary: set-status done checks verification.md; --unverified records an exception; next step shows /svc:verify
tasks:
- id: t1
  title: Verification gate in cplat spec
  files: [scripts/cplat/spec.py, tests/cplat/test_spec.py]
  covers: [AC-068.1, AC-068.2, AC-068.3]
  parallel_safe: true
  depends_on: []
  done: true
---

## t1 — Verification gate in cplat spec

**Files:** scripts/cplat/spec.py, tests/cplat/test_spec.py
**Covers:** AC-068.1, AC-068.2, AC-068.3
