---
spec_id: 075-devbox-run-ci-is-the-ci-gate
spec_hash: d5202109c919
summary: a ci recipe per template, required by the shape contract, run by ship pr and /svc:build
tasks:
- id: t1
  title: ci recipe and shape contract
  files: [scripts/shapes.py]
  covers: [AC-075.1]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: ship pr runs devbox run ci
  files: [scripts/cplat/ship.py]
  covers: [AC-075.2]
  parallel_safe: false
  depends_on: []
  done: true
- id: t3
  title: /svc:build and /svc:ship
  files: [plugins/svc/commands/build.md, plugins/svc/commands/ship.md]
  covers: [AC-075.3]
  parallel_safe: true
  depends_on: []
  done: true
---

## t1 — ci recipe and shape contract

**Covers:** AC-075.1 — the recipes, the shape contract and the /svc:build gate landed first as #108; this spec adds secrets-baseline to the contract and the test

## t2 — ship pr runs devbox run ci

**Covers:** AC-075.2

## t3 — /svc:build and /svc:ship

**Covers:** AC-075.3
