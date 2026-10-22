---
spec_id: 080-lean-build-and-headless
spec_hash: 0d4ed5ccce2e
summary: Phase 3 = devbox run ci first; headless stops after two idle sessions
tasks:
- id: t1
  title: build.md Phase 3
  files: [plugins/svc/commands/build.md, tests/cplat/test_ci_gates.py]
  covers: [AC-080.1]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: headless progress key
  files: [scripts/cplat/headless.py, tests/cplat/test_headless.py]
  covers: [AC-080.2]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — build.md Phase 3

**Files:** plugins/svc/commands/build.md, tests/cplat/test_ci_gates.py
**Covers:** AC-080.1

## t2 — headless progress key

**Files:** scripts/cplat/headless.py, tests/cplat/test_headless.py
**Covers:** AC-080.2
