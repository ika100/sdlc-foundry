# ADR-103: Prompt tests check structure not wording

**Status:** Accepted (2026-11-12)

## Context

About 67 test files checked that an exact sentence occurs in a plugin prompt. Such a test proves only that the wording
stayed, not that an agent still behaves correctly (the eval gate of spec 151 proves behaviour), and it breaks with every
prompt change: specs 168, 171 and 172 each restored or re-pinned phrases several times. Spec 168 also capped the total
prompt size at a byte baseline in the rule register; the prompts were 7 bytes under it and nothing offered a sanctioned
way to raise it.

## Decision

Prompt tests check the targets a prompt points to; a literal is pinned only as a marked interface; the prompt byte baseline rises only through the gated rules rebaseline.

- `cplat platform rules check` resolves every link, heading anchor, plugin-root path, `cplat <noun> <verb>` name and
  slash command a prompt names, and fails on one that does not exist.
- A string literal of at least 4 words in a test under `tests/` that occurs verbatim in a prompt fails the check unless
  the line or the line above carries `# interface: <reason>` (3 or more words): a literal that code depends on.
- `cplat platform rules rebaseline --reason "<why>"` raises `baseline.prompt_bytes` only when the eval gate passes for
  a clean tree, and records the raise in `baseline.history`; `cplat platform pr-check` (rule `rules-baseline`) refuses a
  raise without a matching entry.

## Consequences

- A prompt can be reworded without rewriting unrelated tests; a test that needs a prompt to point somewhere asserts that
  through `tests/cplat/structure.py`.
- Agent behaviour is proven by the eval gate only; a test no longer proves that a sentence stayed.
- New sentence pins cannot grow back unmarked, and every marked one names why code depends on it.
- The baseline rises in the open: each raise has its date, size, reason and benchmark run ids in the register.
- A later change keeps each rewritten test's criterion id, so traceability does not drop.
