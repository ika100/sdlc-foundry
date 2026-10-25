# ADR-044 — Change-aware validation in the inner loop only, decided by rules in code

**Status:** accepted (2026-10-25, spec 103)

## Context

A build or ship reruns the whole test suite and the security scan on every fix round, even when a change touches one
module or only documentation. On larger repos this is most of a fix round's time and a large share of its tokens
(test output read back by agents). Skipping checks is risky: a missed failure costs more than a saved run.

## Decision

- Selection applies only to the inner loop (build after coders, fix rounds). The final gate before a PR is marked
  ready or landed, and the PR's CI, always run the full `devbox run ci`.
- A deterministic planner (`cplat validate`) decides per check `run`, `reused` or `skipped` with a named rule.
  Mandatory categories (dependencies, Dockerfile, CI, secrets/auth, specs, acceptance tests, and per shape API,
  migrations, manifests, routes, build config) force the full suite and the security scan. Anything not covered by a
  rule runs everything. A model's risk estimate can only add checks.
- Mapping comes from what the repo already declares: plan task `files` → `covers` → criterion-tagged tests, and the
  component's own unit tests by name. No dependency graph.
- Passed results are reused only for byte-identical inputs and only on the machine that produced them.
- Every skip or reuse that the final gate later contradicts is counted as a miss for its rule, so a bad rule is
  visible in `cplat runs report`.

## Consequences

- Shapes without a test selector (Java, Go, gitops-app) run everything in the loop, as before.
- The final gate's cost is unchanged; the saving is in fix rounds only.
