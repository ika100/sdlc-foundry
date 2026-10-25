# ADR-035 — Token usage is measured from the local session transcripts

**Status:** accepted (2026-10-25, spec 099)

## Context

The run records of spec 087 (ADR-032) say how long a run took, not what it consumed. The cost-reduction work after
spec 099 (#141, #142, #144) needs a baseline. The user is on a subscription, so there is no per-run invoice. The
only per-call source is the transcript Claude Code writes on the local machine:
`~/.claude/projects/<cwd-slug>/<session>.jsonl`, with each subagent in
`<session>/subagents/agent-<id>.jsonl` and its `agent-<id>.meta.json` holding `agentType`. Each assistant line holds
`message.id`, `message.model` and `message.usage`. A streamed message repeats over several lines with the same
`message.id`. One main session can drive several runs at once (`/app:ship`, a fleet), and a run does not know which
session it is part of unless it is told.

## Decision

- **Source.** Usage comes only from the local transcripts, read at run end by `cplat` (module `runs_usage`). Nothing
  else is called, and nothing from the transcripts is kept except counts, model ids, agent types, phase names, run
  and session ids and timestamps. Prompts, tool input and output, file contents and subagent descriptions are read
  past and never kept.
- **Which session.** A run started inside a Claude Code session *claims* that session through
  `$CLAUDE_CODE_SESSION_ID` (set in the Bash tool environment since Claude Code 2.1.132). Runs that launch their own
  sessions (`headless` with `claude -p --session-id <uuid>`, `benchmark` with its own clone directory) *own* them.
  The claims are kept in a local ledger next to the active records (`<state dir>/usage/sources.json`), never in the
  store.
- **Shared sessions.** A subagent counts in exactly one run: the claiming run whose window holds its first call,
  picked by its working directory, then by the latest-started run. A main-session call that falls inside the windows
  of `n` claiming runs counts `1/n` in each, under the role `main (shared)`. Every call of a session is counted once
  across all records.
- **Cost.** Costs are estimates from a price table kept in the platform repo (`scripts/cplat/prices.json`: USD per
  million tokens for input, cache write, cache read and output, plus the date the prices were taken). An unpriced model
  costs `unknown`, never 0. The table is updated by hand.
- **Never in the way.** Collection has a 10 s budget, runs outside the record lock, and never changes a run's
  outcome, exit code or output. What it could not read is stated in `usage.incomplete`.

## Consequences

- Every run record of a run started in a Claude Code session gains a `usage` section. Runs started outside one (a
  plain terminal) carry none and are counted as "no usage data" in the report.
- Usage measures only this machine: a run whose sessions ran elsewhere has no usage.
- Output tokens are taken as the transcripts report them. The transcripts under-report them, so output cost is a lower
  bound and is labelled that way.
- A change in the transcript layout breaks the measurement, not the run. It shows up as `incomplete` reasons.
- New models need a row in the price table. Until then their cost is `unknown` and the totals say `cost_complete:
  false`.

## Not included

- Budgets and their enforcement (#144), and any change that lowers token use.
- Reconciling the estimates with an invoice.
