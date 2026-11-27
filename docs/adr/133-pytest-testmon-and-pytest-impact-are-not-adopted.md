# ADR-133: pytest-testmon and pytest-impact are not adopted

**Status:** Accepted (2026-11-27, spec 107 candidate 2)

## Context

Spec 107 evaluates open-source tools on measured value, one decision record per candidate. Candidate 2 was change-aware test
selection with pytest-testmon or pytest-impact (#142). Before its trial ran, the platform built the selection itself
(spec 212, [ADR-123](123-local-test-runs-select-by-recorded-dependencies.md), merged 2026-11-20). Both tools select by the
Python code a test executes. In this repo about half of the test files run cplat as a subprocess, and many read prompts,
templates and docs. Coverage-based selection misses those dependencies, so the native selection records them too.

## Decision

**Reject** (AC-107.6). The native selection of ADR-123 covers the need, so neither tool enters the platform or the
templates. No benchmark trial was run for the tools themselves (AC-107.2 is not met for this record). The native selection's
own figures (spec 212, 2026-11-20) are the evidence:
- Recording costs about 2.6 % extra on a full run.
- The median module reaches 11.8 % of the test files.
- 3 mutation checks found no missed test.
- The baseline was a 7 min 41 s full local run of 12,409 tests.

## Consequences

- No extra test dependency in the platform repo or the generated repos.
- A later proposal to adopt either tool needs a gap that ADR-123 leaves open, for example selection in the generated repos'
  own test runs, and a trial under AC-107.2.
