# ADR-091: Agent rules carry their reason in the prompt and their class in a checked register

**Status:** Accepted (2026-11-09, spec 168)
**Builds on:** [ADR-085](085-prompt-changes-pass-the-benchmark-before-a-release.md) (the eval gate),
[ADR-039](039-weekly-retro-evidence-checked-proposals.md) (the weekly retro)

## Context

Agents read every sentence of a plugin prompt as a rule. Rules were added after each incident, often with only an issue
number as their reason, and written as condition lists that never cover every case. Nobody could tell which rules
still held, so none was removed, and the few rules that must never be bent drowned among the others.

## Decision

1. **Every rule sentence is classified** as `hard`, `practice`, `experience` or `not a rule` in the rule register
   `docs/rules/`: one entry file per prompt file, plus `register.yml` with the byte baseline and the table of distinct
   hard rules. A rule sentence is one with "never", "always", "must", "do not", "don't", "only", "unless" or "except".
   The register lives outside `plugins/`, so agents never load it and a register change never changes the plugin tree
   the benchmark ran.
2. **The reason stays in the prompt sentence** (`so that`, `because`, `since`, `otherwise`, at least 3 words besides
   references). A practice states its purpose instead of a condition list; only a hard rule may keep a condition.
3. **Hard rules are few, marked and enforced:** at most 20 distinct ones, each marked `**Hard rule:**` in the prompt,
   each naming the `cplat` command or CI job that enforces it or marked an intentional prose rule with the reason no
   tool can. Every agent and command prompt states once that a hard rule is never departed from and that a practice
   may be, with the departure named in the report.
4. **`cplat platform rules check` enforces 1 to 3 in CI**, and the prompts may not grow past the bytes they had before
   the first sweep.
5. **Rules retire through evidence:** the weekly retro proposes at most 3 entries per week (a rule now enforced by a
   tool, or an incident rule whose issue is closed and whose cause stopped occurring); a change that retires or removes
   entries passes the eval gate in `cplat platform pr-check`, and the retired entry keeps the date, the reason and the
   benchmark run ids.

## Consequences

- Adding a rule costs a register entry and a reason; the check refuses a bare rule or a condition list.
- The prompts can only shrink below the baseline, so a new rule has to pay for its bytes.
- Rewording a prompt means updating the quoted text of its entries (stable ids keep the history).
- Retiring a rule costs the two benchmark runs a release needs anyway.
- Giving a prose-only hard rule a real enforcement is a follow-up spec per rule.
