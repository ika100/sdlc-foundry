# ADR-134: Codebase-Memory MCP is not adopted

**Status:** Accepted (2026-11-27, spec 107 candidate 1)

## Context

Spec 107 candidate 1 was Codebase-Memory MCP, a code and knowledge graph meant to cut the tokens agents spend finding code.
It was tried by hand on 2026-11-20, outside the benchmark harness of AC-107.2.

The transcript analysis came first. Exploration was about 28 % of a journey's repo-session tokens. 75 % of the reads were
repeats, mostly platform prompts and spec documents, not code. The estimated gain of any graph was 4–6 % of tokens.

The trial used codebase-memory-mcp v0.12.1:
- It indexed this repo in 5 s (34k nodes).
- Section nodes hold only the heading, not the body.
- Criterion ids are not nodes.
- Callers miss callable references and monkeypatched names.
- Its 17 tool schemas cost about 5.6k tokens per turn (about 2.5k with `--tool-profile=scout`).

## Decision

**Reject** (AC-107.6). The live A/B (issues #862, #863; arms: none, graph with a hint, graph with an explicit instruction;
Opus, headless):
- **Graph with a hint:** its tools stayed deferred and were never used.
- **Graph with an explicit instruction:** it used them twice in two runs and cost more, +19k tokens of first-turn context.
- **Noise:** the same setup varied 0.84 M vs 0.59 M tokens, far more than the expected effect of about 5 %.

The run ids were not recorded in the run store, so AC-107.10 is not met for this record. The figures come from the session
transcripts of 2026-11-20.

## Consequences

- No MCP server is added to the platform or the templates.
- Lookups here are mostly text searches, so a cheaper token win is slicing the prompts per step, without a graph.
- A new proposal needs a new signal, for example agents asking symbol or caller questions that text search answers badly.
