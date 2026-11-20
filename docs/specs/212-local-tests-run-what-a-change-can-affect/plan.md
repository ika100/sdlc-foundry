---
spec_id: 212-local-tests-run-what-a-change-can-affect
shape: platform
spec_hash: 8894c02a208e
summary: "A traced full run records which repo files each cplat test file touches; test-fast and ci-local run only the test files a change can reach, and everything when that cannot be told; CI unchanged"
tasks:
  - id: t1
    title: "The recorder, the cplat child record and the recording plugin"
    files: [scripts/cplat/depstrace.py, scripts/cplat/cplat.py, tests/cplat/depsmap.py, tests/cplat/conftest.py, tests/cplat/shared_render.py]
    covers: [AC-212.2, AC-212.6, AC-212.7]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "The selector and the recipes"
    files: [scripts/testselect.py, devbox.json, scripts/ci-local.sh]
    covers: [AC-212.1, AC-212.3, AC-212.4, AC-212.5, AC-212.6]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "Tests, measurements, ADR, guides and changelog"
    files: [tests/cplat/test_212_select.py, tests/cplat/support_212.py, docs/adr/123-local-test-runs-select-by-recorded-dependencies.md, docs/adr/README.md, CONTRIBUTING.md, CLAUDE.md, docs/changelog.d/881-local-tests-select.added.md]
    covers: [AC-212.1, AC-212.2, AC-212.3, AC-212.4, AC-212.5, AC-212.6, AC-212.7, AC-212.8, AC-212.9]
    parallel_safe: false
    depends_on: [t2]
    done: true
---

# Plan — 212 Local tests run what a change can affect

The contract is [design.md](design.md). t1 records, t2 selects from what t1 records, t3 proves both and measures AC-212.8
and AC-212.9 on the real suite (numbers in the pull request and verification.md).

## t1 — The recorder, the cplat child record and the recording plugin

**Files:** scripts/cplat/depstrace.py, scripts/cplat/cplat.py, tests/cplat/depsmap.py, tests/cplat/conftest.py, tests/cplat/shared_render.py
**Covers:** AC-212.2, AC-212.6, AC-212.7
**Goal:** a full run with `--deps-record PATH` writes the map of the design's contract; without it nothing changes.

## t2 — The selector and the recipes

**Files:** scripts/testselect.py, devbox.json, scripts/ci-local.sh
**Covers:** AC-212.1, AC-212.3, AC-212.4, AC-212.5, AC-212.6
**Goal:** `test-fast` without arguments and `ci-local.sh` run the selection; `--full` and `devbox run test` run everything.

## t3 — Tests, measurements, ADR, guides and changelog

**Files:** tests/cplat/test_212_select.py, tests/cplat/support_212.py, docs/adr/123-…, docs/adr/README.md, CONTRIBUTING.md, CLAUDE.md, the changelog fragment
**Covers:** every criterion; AC-212.8 and AC-212.9 are measurements recorded in the pull request.
