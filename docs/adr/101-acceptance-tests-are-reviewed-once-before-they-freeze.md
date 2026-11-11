# ADR-101: Acceptance tests are reviewed once against their criteria and the contract before they freeze

**Status:** Accepted (2026-11-10, spec 179)
**Builds on:** [ADR-026](026-feature-specs.md) (failing acceptance tests first), spec 165 (a test problem does not stop an
unattended run), spec 169 (the acceptance tests freeze when the red-tests step ends)

## Context

The acceptance tests freeze when the red-tests step ends: from then on `cplat spec test-diff` flags every change, and
only the person may approve one that is not formatting, a lint suppression, a tightening or a test helper. In the last
round the tester's own tests contradicted their spec or design six times: a fixture whose data contradicts the test's
assertion, an asserted message the contract never defines, an expected text the specified behaviour cannot produce.
Each was found only after the freeze, by a coder who could not make the test pass, and each became a stop or an
approval for the person, although nothing about it was the person's decision: the criterion and the contract already
said what the test had to check.

## Decision

1. **The red-tests step ends with one review of the tests.** After the tester's tests trace and fail for the right
   reason, the reviewer agent, in a test-review mode, compares each acceptance test with its criterion and the design's
   contract and reports each contradiction (test, criterion id, what contradicts). It reads only; it never changes a
   test, because the tester owns them.
2. **Findings go to the tester exactly once.** The tester changes only the tests named; the review never runs a second
   time, so a build pays at most one extra review and one extra tester round. A finding the tester does not resolve
   does not block: it is listed for the person in `verification.md` and in the PR's "How this was built" block.
3. **The tests freeze at a marker commit.** `cplat component build reviewed <spec>` commits
   `test(<number>): reviewed acceptance tests for <spec id>` (empty, its body lists the unresolved findings). The
   red-tests unit is done only when this commit exists, so a session that ends early never skips the review, and the
   freeze point (`RED`, the unit's checkpoint) is the commit after the tester's round.

## Consequences

- Contradictions between a test and its own spec are fixed by the agents before any coder works against them; the
  person sees only what the tester could not resolve, and sees it in the PR rather than as a stop.
- Every build has one more reviewer invocation in the red-tests step (inside the build's budget), and at most one more
  tester round.
- Builds that were in their red-tests step when this ships repeat only the review: the tests already trace, so Phase 1
  goes straight to the review and the marker commit.
- The review checks consistency with the criterion and the contract, not test quality in general; a test that is
  merely looser than its criterion is still found in verification and tightened there (spec 165).
