---
spec_id: 081-gates-that-can-fail
spec_hash: ab0e817b046c
summary: gate tools pinned and bumped; gates.py checks in doctor and adopt
tasks:
- id: t1
  title: Pin gate tools; bump them weekly
  files: [templates/gitops-app/devbox.json, templates/library-python/devbox.json, templates/service-python/devbox.json, templates/service-go/devbox.json.jinja, templates/service-java/devbox.json.jinja, scripts/bump_template_pins.py]
  covers: [AC-081.1]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: gates.py in doctor
  files: [scripts/cplat/gates.py, tests/cplat/test_gates.py]
  covers: [AC-081.2]
  parallel_safe: false
  depends_on: []
  done: true
- id: t3
  title: adopt reports CI gaps
  files: [scripts/cplat/adopt.py]
  covers: [AC-081.3]
  parallel_safe: false
  depends_on: []
  done: true
---

## t1 — Pin gate tools; bump them weekly

**Files:** templates/gitops-app/devbox.json, templates/library-python/devbox.json, templates/service-python/devbox.json, templates/service-go/devbox.json.jinja, templates/service-java/devbox.json.jinja, scripts/bump_template_pins.py
**Covers:** AC-081.1

## t2 — gates.py in doctor

**Files:** scripts/cplat/gates.py, tests/cplat/test_gates.py
**Covers:** AC-081.2

## t3 — adopt reports CI gaps

**Files:** scripts/cplat/adopt.py
**Covers:** AC-081.3
