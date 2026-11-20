# ADR-121: Red tests fail for the missing behaviour before they freeze

**Status:** Accepted (2026-11-20, spec 205)

## Context

[ADR-101](101-acceptance-tests-are-reviewed-once-before-they-freeze.md) reviews the acceptance tests once before they
freeze, but the review only reads them. A test can be red for the wrong reason (a helper that raises, a missing import in
the test code) and still freeze. The build then finds out only when the coder reports it, and the frozen test can no
longer be corrected without a test-diff record. The week-46 retro counted 63 stops on such cases; spec 157's
`make_repo` helper (a `mkdir` without parents) is the clearest one. `cplat spec test-diff` also refused edits that change
no assertion, such as a comment, a docstring or a static import, so each of them needed a record.

## Decision

A red acceptance test freezes only when it fails for the missing behaviour; edits that change no assertion pass test-diff without a record

- `cplat quiet test-fast --red -- <test files>` runs the tests once and classes each red pytest test as `missing
  behaviour`, `test error` or `passes`. `cplat component build tests <id> --red` prints the exact command for the
  spec's trace.
- `cplat component build reviewed` freezes the tests only after that check exited 0 on their current content, in pytest
  repos. The build sends `test error` and `passes` lines back to the tester and escalates with cause `code` after 2
  rounds.
- After the freeze, a test that raises in test code goes to the tester as a harness fix, recorded with `--tighten`.
- `cplat spec test-diff` passes an edit whose only differences are comments, Python docstrings and imports, or TS/JS, Go
  and Java static imports, prints `no assertion changed: <kinds>` and records nothing.

## Consequences

- A broken test stops the run in Phase 1, where it costs one tester round, not in a coder's round later.
- Go, Java and Vitest repos keep the orchestrator's judgement of a wrong failure: the red check classes pytest tests
  only.
- Each Phase 1 round runs the tests once more.
- A later change to test-diff must keep every directive comment (suppressions stay with spec 160's check) and every
  other edit refused.
