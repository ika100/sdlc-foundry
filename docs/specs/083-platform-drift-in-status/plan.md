---
spec_id: 083-platform-drift-in-status
spec_hash: 97dca08a0e58
summary: a platform column in /shared:status
tasks:
- id: t1
  title: Platform column
  files: [scripts/cplat/status.py, tests/cplat/test_drift.py]
  covers: [AC-083.1]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — Platform column

**Files:** scripts/cplat/status.py, tests/cplat/test_drift.py
**Covers:** AC-083.1
