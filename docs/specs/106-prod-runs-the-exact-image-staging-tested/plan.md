---
spec_id: 106-prod-runs-the-exact-image-staging-tested
spec_hash: b8986ae0a732
summary: promote staging→prod compares the GHCR digests of the staging sha-<40> tag and the release tag (all services
  first, refusal on mismatch, missing tag, failed lookup or unidentifiable tag), dry-run shows both, an override with a
  reason, --no-verify notice; release CI re-tags the tested sha image instead of rebuilding
tasks:
  - id: t1
    title: registry.digests with pagination (extends spec 105's registry.py)
    files: [scripts/cplat/registry.py]
    covers: [AC-106.4, AC-106.5]
    parallel_safe: false
    depends_on: []
    done: false
  - id: t2
    title: promote — digest check for staging→prod, all services first, dry-run output, override, --no-verify notice, PR body and evidence line
    files: [scripts/cplat/promote.py, scripts/cplat/evidence.py]
    covers: [AC-106.1, AC-106.2, AC-106.3, AC-106.4, AC-106.5, AC-106.6, AC-106.7, AC-106.8, AC-106.9, AC-106.11]
    parallel_safe: false
    depends_on: [t1]
    done: false
  - id: t3
    title: release-image job re-tags sha-<40> in the four image templates (no rebuild on v*.*.* tags)
    files: [templates/service-python/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml,
      templates/service-go/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml]
    covers: [AC-106.10]
    parallel_safe: true
    depends_on: []
    done: false
  - id: t4
    title: Docs — /gitops:promote command text, unattended-delivery.md, CHANGELOG
    files: [plugins/gitops/commands/promote.md, docs/unattended-delivery.md, docs/CHANGELOG.md]
    covers: [AC-106.12]
    parallel_safe: false
    depends_on: [t2, t3]
    done: false
---

# Plan — 106 Prod runs the exact image staging tested

Design: [design.md](design.md). Starts after spec 105 (registry.py) is on main. Red tests first
(`tests/cplat/test_promote_digest.py`), then t1–t4, one coder, reviewer.
