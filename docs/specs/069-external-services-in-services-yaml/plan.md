---
spec_id: 069-external-services-in-services-yaml
spec_hash: bbb5c84d5ee2
summary: external entries render as an overlay over a kustomize package or an Argo Application for a chart; pins stay in the overlay kustomization
tasks:
- id: t1
  title: render.py external entries
  files: [templates/gitops-app/scripts/render.py, tests/cplat/test_gitops.py]
  covers: [AC-069.1, AC-069.2, AC-069.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: pin.py re-renders external charts
  files: [templates/gitops-app/scripts/pin.py, tests/cplat/test_gitops.py]
  covers: [AC-069.3]
  parallel_safe: false
  depends_on: [t1]
  done: true
- id: t3
  title: ADR-029 and docs
  files: [docs/adr/029-external-services.md, docs/adr/README.md, templates/gitops-app/CLAUDE.md.jinja]
  covers: [AC-069.1]
  parallel_safe: false
  depends_on: [t1]
  done: true
---

## t1 — render.py external entries

**Files:** templates/gitops-app/scripts/render.py, tests/cplat/test_gitops.py
**Covers:** AC-069.1, AC-069.2, AC-069.4

## t2 — pin.py re-renders external charts

**Files:** templates/gitops-app/scripts/pin.py, tests/cplat/test_gitops.py
**Covers:** AC-069.3

## t3 — ADR-029 and docs

**Files:** docs/adr/029-external-services.md, docs/adr/README.md, templates/gitops-app/CLAUDE.md.jinja
**Covers:** AC-069.1
