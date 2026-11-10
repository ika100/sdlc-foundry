# ADR-097: Tests wait for events, never for a fixed time

**Status:** Accepted (2026-11-10, spec 178)
**Builds on:** [ADR-094](094-a-build-runs-each-coder-on-its-own-tests-and-new-tests-under-load.md) (new tests run under load)

## Context

The dispatcher's land and unit acceptance tests (spec 167) passed on a laptop and failed on the slower CI runner: they
waited for processes and threads with fixed sleeps, so a slower machine read a state before it existed. Every seam
between `cplat`, git, `gh` and a session is tested with spawned fake programs, so the same race sits in every test that
starts a process or a thread.

## Decision

- A test in `tests/cplat` waits for a process, a thread or a file through `tests/cplat/waiting.py` (`wait_for`,
  `wait_file`, `wait_process`, `wait_gone`), which polls an event with a timeout that grows with `TEST_FAKE_DELAY`.
  Time-dependent behaviour of `cplat` runs on a fake clock (the module's `sleep` / `now` replaced).
- `scripts/check-test-sleeps.py` fails `devbox run quality`, `ci-local.sh` and CI on every real sleep in `tests/cplat`,
  one line per occurrence with the file, the line and the fix. The only exemption is a sleep inside the source of a fake
  program that stands in for a slow process, marked on its line with `fake-delay: <reason>`; `waiting.py` itself is
  the one place that polls.
- `TEST_FAKE_DELAY=<seconds>` makes every fake program written through `waiting.fake_prelude` sleep that long at start;
  a suite run with `TEST_FAKE_DELAY=2` is the slow-runner rehearsal.

## Consequences

- A slower runner changes how long a test takes, not whether it passes.
- A new fake program uses `waiting.fake_prelude`; one that does not is not slowed by the rehearsal.
- The check sees `time.sleep`, `asyncio.sleep`, a `sleep` imported from them and `sleep` in fake program text; a wait
  disguised another way (`Event().wait(n)` on an event nobody sets) is left to review.

## Not included

- The e2e cluster test and the template tests: their waits stay as they are.
- A nightly stress job in CI: the 10-run stress gate runs while a spec that adds such tests is built.
