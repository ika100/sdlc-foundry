---
spec_id: 066-unattended-runs-stop-only-when-done
spec_hash: f8a350f43d25
summary: A Stop hook in the shared plugin runs `cplat ship gate` only when a ship state file exists
tasks:
- id: t1
  title: cplat ship gate
  files: [scripts/cplat/ship.py, tests/cplat/test_ship.py]
  covers: [AC-066.1, AC-066.2]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: Stop hook in the shared plugin
  files: [plugins/shared/hooks/hooks.json, tests/cplat/test_ship.py]
  covers: [AC-066.3]
  parallel_safe: false
  depends_on: [t1]
  done: true
---

## t1 — cplat ship gate

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship.py
**Covers:** AC-066.1, AC-066.2

## t2 — Stop hook in the shared plugin

**Files:** plugins/shared/hooks/hooks.json, tests/cplat/test_ship.py
**Covers:** AC-066.3
