# ADR-084: A spec decides by default and asks only what it may not decide

**Status:** Accepted (2026-11-07, spec 149)
**Revises:** [ADR-026](026-feature-specs.md) decision 6 ("the product-manager returns open questions instead of guessing")

## Context

ADR-026 made the product-manager return every decision as an open question, with a suggested answer, because a subagent
cannot ask the user. In journeys 3 to 5 (2026-11-06, [docs/PERFORMANCE.md](../PERFORMANCE.md)) the user answered 56
questions; all 56 took the suggested answer. Each round of questions costs a person's attention and an agent turn that
re-reads its context, and an unattended run that meets a question stops: in the run store of the 14 days before
2026-11-07, `decision` is the most frequent escalation cause (31 of 75). An AI-native process keeps the person on the
loop: they set the direction and approve the result, they do not confirm every default.

## Decision

1. **The product-manager decides by default.** A decision with a sensible default (a limit, a format, an order, a status
   code, a wording, a small scope call) is taken, written into the criteria and listed in the spec's new `## Assumptions`
   section as `- **A<n>** <decision> (other option: <…>; affects AC-…)`.
2. **Open questions are a fixed list:** security, access or secrets; money (paid services, quotas, cost limits); deleting,
   migrating or exposing existing data; a request so ambiguous that the default may build the wrong feature.
3. **The approval is the review of the assumptions.** `/component:spec` and `/system:spec` show them with the criteria and
   ask once: approve with these assumptions, change one (an amendment), or review the file first. `cplat spec approve`
   still refuses a spec with an open question; assumptions never block it.
4. **A changed assumption is struck through, never deleted**, so `cplat` can count how many assumptions were revised (the
   quality signal of this decision: it should stay near zero). `cplat spec list --json` and the "How this was built"
   block report both counts.

## Consequences

- A spec with only defaults reaches approval in one question instead of three or four rounds.
- The user sees every default before anything is built, in one list; a wrong default costs an amendment before the plan,
  not a stop during the build.
- Specs written before this decision have no `## Assumptions` section; nothing changes for them.
