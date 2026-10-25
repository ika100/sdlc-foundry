---
spec_id: 104-generated-repos-build-and-observe
spec_hash: d3141701497f
summary: Strict lockfile installs in the service-python and web-nextjs Dockerfiles (template-owned), one metrics
  middleware with route templates and an unmatched label, errors counted, /metrics not recorded, observability off
  leaves no metrics code, and platform plus template tests in the existing CI jobs
tasks:
  - id: t1
    title: Strict installs in both Dockerfiles; Dockerfile stays out of _skip_if_exists
    files: [templates/service-python/Dockerfile, templates/web-nextjs/Dockerfile.jinja]
    covers: [AC-104.1, AC-104.2, AC-104.3]
    parallel_safe: true
    depends_on: []
    done: false
  - id: t2
    title: MetricsMiddleware (route template, unmatched, 500 + error type, /metrics skipped), /ping count removed
    files: ["templates/service-python/src/{{ module_name }}/metrics.py", "templates/service-python/src/{{ module_name }}/main.py",
      templates/service-python/tests/test_metrics.py]
    covers: [AC-104.4, AC-104.5, AC-104.6, AC-104.7, AC-104.8]
    parallel_safe: true
    depends_on: []
    done: false
  - id: t3
    title: Observability off excludes metrics.py, the middleware, /metrics and prometheus-client
    files: [templates/service-python/copier.yml, "templates/service-python/src/{{ module_name }}/main.py"]
    covers: [AC-104.9]
    parallel_safe: false
    depends_on: [t2]
    done: false
  - id: t4
    title: Platform tests and the lockfile-mismatch steps in the template smoke CI jobs; CHANGELOG migration note
    files: [tests/cplat/test_generated_repos.py, .github/workflows/ci.yml, docs/CHANGELOG.md]
    covers: [AC-104.10]
    parallel_safe: false
    depends_on: [t1, t3]
    done: false
---

# Plan — 104 Generated repos build and observe reliably

Design: [design.md](design.md). Red tests first (`tests/cplat/test_generated_repos.py` and the template's
`tests/test_metrics.py`), then t1–t4, one coder, reviewer.
