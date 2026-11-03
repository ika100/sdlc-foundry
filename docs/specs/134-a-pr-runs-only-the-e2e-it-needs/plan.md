---
spec_id: 134-a-pr-runs-only-the-e2e-it-needs
shape: platform
spec_hash: 9898c0b51c6d
summary: "scripts/e2e-scope.py decides whether a pull request needs the cluster e2e (template, Dockerfile, e2e files, the cplat modules the e2e scripts call and import, closed over every import, or a release heading); e2e.yml gets a decide job and runs the e2e as three parallel parts on a pull request (E2E_PART guards in run.sh) and as one job nightly; e2e-upgrade decides on the pull request's base; CONTRIBUTING, ADR-080, changelog"
tasks:
  - id: t1
    title: scripts/e2e-scope.py (exercised set, trigger rule, release heading, --list, --base) and its tests with the 40-PR fixture
    files: [scripts/e2e-scope.py, tests/cplat/test_e2e_scope_134.py, tests/cplat/fixtures/e2e_scope_134_prs.json]
    covers: [AC-134.2, AC-134.3, AC-134.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: E2E_PART guards in tests/e2e/run.sh (core, scaling, backups, all) with skip lines and the early refusal of an unknown part
    files: [tests/e2e/run.sh, tests/cplat/test_e2e_parts_134.py]
    covers: [AC-134.5, AC-134.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: e2e.yml decide job and the part matrix; e2e-upgrade.yml decides on the pull request's base; the workflow tests
    files: [.github/workflows/e2e.yml, .github/workflows/e2e-upgrade.yml, tests/cplat/test_e2e_workflows_134.py, tests/cplat/test_upgrade_121_ops.py]
    covers: [AC-134.1, AC-134.4, AC-134.6]
    parallel_safe: false
    depends_on: [t1, t2]
    done: true
  - id: t4
    title: CONTRIBUTING CI section, ADR-080 and its index row, changelog entry
    files: [CONTRIBUTING.md, docs/adr/080-a-pull-request-runs-only-the-e2e-it-needs.md, docs/adr/README.md, docs/CHANGELOG.md, tests/cplat/test_e2e_docs_134.py]
    covers: [AC-134.9]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 134 A pull request runs only the e2e it needs, and that e2e runs in parallel parts

t1 and t2 are independent; t3 wires them into the workflows; t4 documents. AC-134.7 (the measured wall time) is proven by this pull
request's own e2e run and recorded in verification.md; its test checks the structure that makes it possible (the two longest scenarios
in different parts, neither in core).
