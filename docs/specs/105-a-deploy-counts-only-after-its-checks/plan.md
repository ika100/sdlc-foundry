---
spec_id: 105-a-deploy-counts-only-after-its-checks
spec_hash: 34a1ca298aca
summary: Smoke records the image digest the cluster runs, staging promotion and the prod evidence compare digests,
  smoke failures are classed environment or application with retries per class, not-run never promotes, replays
  re-smoke a changed digest, and the deploy gate is one documented, tested table
tasks:
  - id: t1
    title: registry.py (GHCR digest of a tag via gh api) and cluster.running_digest (kubectl imageID)
    files: [scripts/cplat/registry.py, scripts/cplat/cluster.py]
    covers: [AC-105.1, AC-105.2]
    parallel_safe: false
    depends_on: []
    done: false
  - id: t2
    title: Smoke records the digest; staging promotion and promote evidence compare digests; not-run never promotes
    files: [scripts/cplat/ship.py, scripts/cplat/smoke.py, scripts/cplat/staging_deploy.py, scripts/cplat/promote.py]
    covers: [AC-105.1, AC-105.2, AC-105.3, AC-105.6]
    parallel_safe: false
    depends_on: [t1]
    done: false
  - id: t3
    title: Failure classes, environment retries (3 × 30 s), escalation cause environment without an issue
    files: [scripts/cplat/smoke.py, scripts/cplat/ship.py]
    covers: [AC-105.4, AC-105.5]
    parallel_safe: false
    depends_on: [t2]
    done: false
  - id: t4
    title: Replays re-smoke unless the record holds a pass for the same digest
    files: [scripts/cplat/ship.py]
    covers: [AC-105.7]
    parallel_safe: false
    depends_on: [t3]
    done: false
  - id: t5
    title: Deploy gate table in unattended-delivery.md and its test; CHANGELOG
    files: [docs/unattended-delivery.md, tests/cplat/test_deploy_gate_table.py, docs/CHANGELOG.md]
    covers: [AC-105.8]
    parallel_safe: false
    depends_on: [t4]
    done: false
---

# Plan — 105 A deploy counts only after its checks pass

Design: [design.md](design.md). Red tests first (`tests/cplat/test_deploy_checks.py`), then t1–t5, one coder, reviewer.
