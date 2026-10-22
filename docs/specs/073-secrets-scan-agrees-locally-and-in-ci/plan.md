---
spec_id: 073-secrets-scan-agrees-locally-and-in-ci
spec_hash: 7c8a4706b876
summary: pinned scanners, baselines with the standard filters and no gibberish, a secrets-baseline recipe
tasks:
- id: t1
  title: Pin scanners and add the secrets-baseline recipe
  files: [templates/gitops-app/devbox.json, templates/library-python/devbox.json, templates/service-python/devbox.json,
    templates/service-go/devbox.json.jinja, templates/service-java/devbox.json.jinja, templates/web-nextjs/devbox.json.jinja]
  covers: [AC-073.1, AC-073.3]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: Regenerate the template baselines
  files: [templates/gitops-app/.secrets.baseline.json, templates/library-python/.secrets.baseline.json,
    templates/service-python/.secrets.baseline.json, templates/service-go/.secrets.baseline.json,
    templates/service-java/.secrets.baseline.json, templates/web-nextjs/.secrets.baseline.json]
  covers: [AC-073.2]
  parallel_safe: true
  depends_on: []
  done: true
- id: t3
  title: CLAUDE.md and the security agent point to secrets-baseline
  files: [templates/gitops-app/CLAUDE.md.jinja, templates/library-python/CLAUDE.md, templates/service-python/CLAUDE.md,
    templates/service-go/CLAUDE.md.jinja, templates/service-java/CLAUDE.md.jinja, templates/web-nextjs/CLAUDE.md.jinja,
    plugins/shared/agents/security.md, tests/cplat/test_ci_gates.py]
  covers: [AC-073.3]
  parallel_safe: false
  depends_on: [t1]
  done: true
---

## t1 — Pin scanners and add the secrets-baseline recipe

**Covers:** AC-073.1, AC-073.3

## t2 — Regenerate the template baselines

**Covers:** AC-073.2

## t3 — CLAUDE.md and the security agent point to secrets-baseline

**Covers:** AC-073.3
