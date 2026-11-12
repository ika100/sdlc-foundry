# ADR-108: Test time is bounded

**Status:** Accepted (2026-11-12)

## Context

Spec 184's verification hung for 2.5 hours. Sixteen older cplat tests used a silent fast fake `claude` and slept through the
usage-limit pause of AC-184.2, so `test-fast` never ended and nothing said which test was waiting.

## Decision

The cplat suite stops a test after 120 s or when its real sleeps pass 1 s, and cplat quiet test-fast gives up after 9 min in every shape, naming the tests still running

- 120 s per test (setup, call or teardown) through the pinned `pytest-timeout`; the failure names the test id, the limit and the stack.
- A 1 s real-sleep budget per test: the sleep that would cross it fails and does not sleep, and says to wait for an event or a file, or
  to use the fake clock.
- 9 min per `cplat quiet test-fast` run: it stops every process it started, prints `FAILED (gave up after 9 min)` and
  `still running: <test id>` lines and exits 124, without a flaky rerun. An injected progress plugin names the running tests.

## Consequences

- A hang becomes one short red run instead of hours, and the output names the culprit.
- No per-test override of the limits: a test that needs longer is split or made event-driven.
- A repo whose pytest ignores `PYTHONPATH` does not load the progress plugin and sees no test names; the 9 min give-up still applies.
