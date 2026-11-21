---
spec_id: 213-library-releases-publish-their-package
shape: platform
spec_hash: 184adcfdfde2
summary: "Library shapes declare publish.registry in shapes.yml; the tag-only publish job runs scripts/publish.sh (build, version check, GitHub release upload); shapes.py checks it; ADR-125 records the convention"
tasks:
  - id: t1
    title: "Registry field and contract check"
    files: [shapes.yml, scripts/shapes.py]
    covers: [AC-213.1, AC-213.2]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "library-python publish script, recipe, CI job and guide"
    files: [templates/library-python/scripts/publish.sh, templates/library-python/devbox.json, templates/library-python/.github/workflows/ci.yml, templates/library-python/CLAUDE.md]
    covers: [AC-213.3, AC-213.4, AC-213.5, AC-213.7]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "Platform CI smoke, ADR, docs, tests and changelog"
    files: [.github/workflows/ci.yml, docs/adr/125-library-releases-publish-to-github-on-the-tag.md, docs/adr/README.md, docs/adr/015-shape-registry-as-code.md, docs/templates.md, tests/cplat/test_213_library_publish.py]
    covers: [AC-213.1, AC-213.2, AC-213.3, AC-213.4, AC-213.5, AC-213.6, AC-213.7, AC-213.8]
    parallel_safe: false
    depends_on: [t2]
    done: true
---

# Plan — 213 Library releases publish their package

The contract is [design.md](design.md).

## t1 — Registry field and contract check

**Files:** shapes.yml, scripts/shapes.py
**Covers:** AC-213.1, AC-213.2
**Goal:** `shapes.py check` requires and checks `publish` on library shapes and their templates.

## t2 — library-python publish script, recipe, CI job and guide

**Files:** templates/library-python/scripts/publish.sh, devbox.json, .github/workflows/ci.yml, CLAUDE.md
**Covers:** AC-213.3, AC-213.4, AC-213.5, AC-213.7
**Goal:** a tag publishes the wheel and source archive to the GitHub release; a version mismatch fails first.

## t3 — Platform CI smoke, ADR, docs, tests and changelog

**Files:** .github/workflows/ci.yml, docs/adr/125-…, docs/adr/README.md, docs/adr/015-…, docs/templates.md, tests/cplat/test_213_library_publish.py
**Covers:** every criterion.
