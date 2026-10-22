---
spec_id: 078-one-image-tag-format
spec_hash: 95189c46747d
summary: sha-<40> everywhere a pin is written; sha-<7> accepted for one release
tasks:
- id: t1
  title: Service CI pushes and dispatches sha-<40>
  files: [templates/service-go/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/service-python/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml]
  covers: [AC-078.1]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: pin-dev, pin.py and promote accept and write the full sha
  files: [templates/gitops-app/.github/workflows/pin-dev.yml, templates/gitops-app/scripts/pin.py, scripts/cplat/promote.py, tests/cplat/test_tags_and_wait.py]
  covers: [AC-078.2]
  parallel_safe: false
  depends_on: []
  done: true
- id: t3
  title: ADR-030 and docs
  files: [docs/adr/030-image-tags-are-the-full-commit-sha.md, docs/adr/README.md, plugins/svc/agents/deployment.md, plugins/svc-go/agents/deployment.md, plugins/svc-java/agents/deployment.md, plugins/web/agents/deployment.md, docs/HOW-IT-WORKS.md, docs/USER-JOURNEY.md]
  covers: [AC-078.3]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — Service CI pushes and dispatches sha-<40>

**Files:** templates/service-go/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/service-python/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml
**Covers:** AC-078.1

## t2 — pin-dev, pin.py and promote accept and write the full sha

**Files:** templates/gitops-app/.github/workflows/pin-dev.yml, templates/gitops-app/scripts/pin.py, scripts/cplat/promote.py, tests/cplat/test_tags_and_wait.py
**Covers:** AC-078.2

## t3 — ADR-030 and docs

**Files:** docs/adr/030-image-tags-are-the-full-commit-sha.md, docs/adr/README.md, plugins/svc/agents/deployment.md, plugins/svc-go/agents/deployment.md, plugins/svc-java/agents/deployment.md, plugins/web/agents/deployment.md, docs/HOW-IT-WORKS.md, docs/USER-JOURNEY.md
**Covers:** AC-078.3
