# ADR-079: A PR shows how it was built, generated from the run records

**Status:** Accepted (2026-11-03, spec 133)

## Context

A build PR says what was built and verified, not how the agent loop got there: user decisions, hand-backs and fix rounds, accepted
deviations, sequential fallback, budget and wall time were scattered across commits, `verification.md` and the orchestrator's prose
(#338). The run already records most of it locally (ADR-032 run records, spec 089 agent events, ADR-043 budget ledger). Contributors
are asked how a PR was produced (#326); the platform's own PRs should show it in a form a reviewer can check.

## Decision

1. **`cplat` writes it, not the orchestrator.** `cplat platform runs report --pr <run-id>` renders a "How this was built" block from
   the run's records and files; `cplat pr open` appends it to the body when the checkout has a current run. The model never writes or
   edits the block.
2. **Only what was recorded.** Facts come from the run record, the runs it resumes, the budget ledger and the spec's
   `verification.md`; anything missing reads `not recorded`. No prompts, no message flow, no diffs.
3. **Local records.** The block is built on the machine that ran the build, from the active record or the local buffer, so it works
   without a run store.
4. **Redacted and bounded.** Every value goes through the run records' redaction; lists are capped.
5. **Never blocks a PR.** A failure to build the block leaves the body unchanged and adds one `note:` line.
6. **New facts are recorded, not inferred.** What the block needs and no record holds (the sequential fallback; later user-approved
   test changes, #324) gets its own recording call or section.

## Consequences

- Reviewers see decisions, hand-backs and accepted deviations in one collapsed block in every repo built by the platform.
- Adding a fact to the block means recording it first; the block's contract is in spec 133's design.md.
- Rerunning `cplat pr open` replaces the block (marker comments), so it stays current.
