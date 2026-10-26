# ADR-052 — Shared renders and round-robin shards for the platform test suite

**Status:** accepted (2026-10-26, spec 112)

## Context

The `tests/cplat` suite rendered the same templates again in hundreds of fixtures (about 1.2 s per render against
0.04 s for a copy), and its single CI job was the critical path of every pull request and every fix round. Faster CI
must not mean fewer tests or weaker isolation, and the suite must still run with one plain `pytest` command locally.

## Decision

- A test that needs a rendered repo as its starting point gets it from the session-scoped shared-render cache
  (`tests/cplat/shared_render.py`: fixtures `new_service` and `shared_renders`): one build per key per test process,
  a private copy per test, nothing kept beyond the run. A test whose subject is the render itself renders from the
  template.
- In CI the suite runs in 4 shards: test `k` of the sorted node ids goes to shard `k % 4 + 1`. No file lists and no
  stored durations. Every run checks from the shards' reports that each collected test ran in exactly one shard
  (`scripts/check-shards.py`), and `ci-success` requires that check.

## Consequences

- New fixtures that start from a render use `new_service` (or `shared_renders.copy` for other builds); a fixture
  calling `newsvc.main` directly is a review finding unless the render is the subject of the test.
- Tests must not depend on order or on another test's files; the shard split changes whenever a test is added.
- A broken template fails every dependent test at setup with the render's error, once per worker.
- Local runs are unchanged: without `--shard` the plugin does nothing.
