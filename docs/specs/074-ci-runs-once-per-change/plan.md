---
spec_id: 074-ci-runs-once-per-change
spec_hash: d7e2caf4441a
summary: push triggers only main and tags; the runner guide recommends a persistent dind volume
tasks:
- id: t1
  title: CI push triggers
  files: [templates/gitops-app/.github/workflows/ci.yml, templates/library-python/.github/workflows/ci.yml,
    templates/service-python/.github/workflows/ci.yml, templates/service-go/.github/workflows/ci.yml,
    templates/service-java/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml]
  covers: [AC-074.1]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: Runner guide
  files: [docs/self-hosted-runners.md]
  covers: [AC-074.2]
  parallel_safe: true
  depends_on: []
  done: true
---

## t1 — CI push triggers

**Covers:** AC-074.1

## t2 — Runner guide

**Covers:** AC-074.2
