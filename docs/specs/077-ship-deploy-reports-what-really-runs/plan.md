---
spec_id: 077-ship-deploy-reports-what-really-runs
spec_hash: 8c1ed0f9936a
summary: deploy watches the service's main CI and the pin-dev run, waits for Argo to run the merged image; GITOPS_TOKEN preflight
tasks:
- id: t1
  title: Deploy watches main CI and the pin-dev run (RunWatch); Argo image and revision checks
  files: [scripts/cplat/ship.py, tests/cplat/test_ship_checks.py, tests/cplat/test_ship.py]
  covers: [AC-077.1, AC-077.2, AC-077.3]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: pin-dev run-name; GITOPS_TOKEN preflight in ship start and doctor; template warning
  files: [templates/gitops-app/.github/workflows/pin-dev.yml, scripts/cplat/doctor.py, templates/service-go/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/service-python/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml]
  covers: [AC-077.1, AC-077.4]
  parallel_safe: false
  depends_on: []
  done: true
- id: t3
  title: /svc:ship describes it
  files: [plugins/svc/commands/ship.md]
  covers: [AC-077.3]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — Deploy watches main CI and the pin-dev run (RunWatch); Argo image and revision checks

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship_checks.py, tests/cplat/test_ship.py
**Covers:** AC-077.1, AC-077.2, AC-077.3

## t2 — pin-dev run-name; GITOPS_TOKEN preflight in ship start and doctor; template warning

**Files:** templates/gitops-app/.github/workflows/pin-dev.yml, scripts/cplat/doctor.py, templates/service-go/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/service-python/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml
**Covers:** AC-077.1, AC-077.4

## t3 — /svc:ship describes it

**Files:** plugins/svc/commands/ship.md
**Covers:** AC-077.3
