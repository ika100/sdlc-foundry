---
spec_id: 067-ship-an-approved-spec-to-dev
spec_hash: fbb62faf4ba1
summary: /svc:ship orchestrates plan and build; cplat ship keeps the state and opens, lands and deploys
tasks:
- id: t1
  title: 'cplat ship: state, pr, land, deploy'
  files: [scripts/cplat/ship.py, scripts/cplat/cplat.py, tests/cplat/test_ship.py]
  covers: [AC-067.1, AC-067.2, AC-067.3, AC-067.4, AC-067.5]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: /svc:ship command and docs
  files: [plugins/svc/commands/ship.md, docs/AGENTS.md, plugins/svc/README.md]
  covers: [AC-067.3]
  parallel_safe: false
  depends_on: [t1]
  done: true
---

## t1 — cplat ship: state, pr, land, deploy

**Files:** scripts/cplat/ship.py, scripts/cplat/cplat.py, tests/cplat/test_ship.py
**Covers:** AC-067.1, AC-067.2, AC-067.3, AC-067.4, AC-067.5

## t2 — /svc:ship command and docs

**Files:** plugins/svc/commands/ship.md, docs/AGENTS.md, plugins/svc/README.md
**Covers:** AC-067.3
