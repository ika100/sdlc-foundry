# ADR-110: Generated repos bound test time

**Status:** Accepted (2026-11-13)

## Context

Journey 13's hung API test cost about 9 of 112.6 minutes. Spec 185 bounded test time in the platform's own suite
([ADR-108](108-test-time-is-bounded.md)) and left generated repos out. Their build files (`pyproject.toml`, `pom.xml`) are
project-owned, so a limit written there would not reach existing repos through `/platform:update`.

## Decision

Generated Python and Java repos fail a test after 120 s and Go repos stop a test package after 5 min, set by the platform-owned
`scripts/gate.sh` through environment variables; a repo's own limit wins. The mechanisms:

- **pytest:** a stdlib-only plugin, `scripts/pytest_limit/platform_test_limit.py` (SIGALRM per test), loaded through
  `PYTEST_ADDOPTS=-p platform_test_limit` and `PYTHONPATH`. No `pytest-timeout` dependency, because `pyproject.toml` is project-owned.
- **Maven:** `MAVEN_ARGS=-Djunit.jupiter.execution.timeout.default=120s`. The default `SAME_THREAD` mode interrupts the test.
  `SEPARATE_THREAD` would also stop code that ignores interrupts, but it runs the body in another thread and breaks Spring's
  thread-bound test transactions.
- **Go:** `GOFLAGS=-timeout=5m`.

Each is skipped where the repo sets its own limit.

## Consequences

- No build file changes, so `/platform:update` carries the limits without touching project-owned files.
- A Java test that ignores interrupts still waits for `cplat quiet`'s 9 minutes.
- Extends [ADR-108](108-test-time-is-bounded.md).
