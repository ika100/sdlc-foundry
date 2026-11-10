# ADR-094: A build runs each coder on its own tests and the new tests under load before the pull request

**Status:** Accepted (2026-11-10, spec 172)
**Builds on:** [ADR-026](026-feature-specs.md) (failing acceptance tests first), spec 165 (the single flake rerun of
`cplat quiet test-fast`), spec 169 (the acceptance tests freeze when the red-tests step ends)

## Context

Every coder of a parallel batch ran the whole `test-fast` suite, because `cplat quiet` took no arguments: 13 coders at
once overloaded the machine and the orchestrator fell back to raw `pytest` calls. New acceptance tests that passed in
one quiet run failed about one run in five under the load of a CI runner, so the first sign of a flaky harness was a red
CI round after the pull request was open. Both problems come from the same gap: the build had no way to run a chosen
set of tests, alone or several times at once.

## Decision

1. **`test-fast` is the one devbox script that takes arguments**, after `--`, passed to the shape's test runner
   unchanged (`cplat quiet test-fast -- <args>`). Every other script keeps refusing arguments, so that the gates CI runs
   stay exactly the recipes in `devbox.json`.
2. **A coder runs only its task's tests**: the acceptance test files of its `covers` criteria plus the test files in its
   `files`, in the form its shape's runner selects them (`cplat component build tests <spec> <task>` prints the command).
   The whole suite runs once when every task is merged (build 2.5) and in Phase 3 (`cplat quiet ci`).
3. **Before Phase 3 the build runs the spec's acceptance tests and the tests the build added or changed several times at
   once** (`cplat quiet test-fast --repeat 3 -- <tests>`). A test that fails under load and passes alone is *flaky under
   load*: the command exits 3, never 0, and the tester fixes the harness (fixtures, helpers, fakes, process clean-up)
   without touching an assertion or a frozen acceptance test file; after two rounds the build escalates. Only named tests
   repeat, never the whole suite, `test`, `ci` or the e2e tests.

## Consequences

- Parallel batches cost one suite run per build instead of one per coder; a coder never needs a raw test command.
- A flaky harness is fixed by the agent that wrote it, before CI sees it; the price is three parallel runs of the new
  tests per build (seconds to a few minutes) and up to two tester rounds.
- In service-java the parallel Maven runs would share `target/`, so the load run is skipped there and named in the build
  report; giving each run its own build directory is a follow-up.
- Gitops shapes, whose `test-fast` renders manifests and runs no test runner, keep the whole `test-fast` for coders and
  have no load run.
