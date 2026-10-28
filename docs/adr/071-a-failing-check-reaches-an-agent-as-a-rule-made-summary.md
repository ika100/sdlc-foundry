# ADR-071: A failing check reaches an agent as a summary made by fixed rules, the full log stays on disk

**Status:** Accepted (2026-10-28, spec 108)
**Amends:** spec 100 (AC-100.12: the failure output of `cplat quiet`), spec 102 (AC-102.9/AC-102.10: where the normalized message and
the snapshot excerpt come from)

## Context

A fix round hands a failure to an agent. Until now that was the last 40 lines of a `cplat quiet` log, or the last 60 lines of each
failed CI job, and the agent instructions said to read the log. Agents read whole logs, with progress bars, passing tests, library stack
frames and repeated warnings, in every round. The parts a fix needs (which check, which test or `file:line`, the error, a few lines
around it) can be read out of the tools' output by fixed rules. Spec 102 already normalizes errors to detect repeated failures, but from
the raw tail, so two runs that fail the same way but print different noise look different.

## Decision

1. **One summarizer, `scripts/cplat/failsum/`, no model.** Every place that hands a failure to an agent (`cplat quiet`, `cplat validate
   run`, the `devbox run ci` before a ship push, the red checks of `cplat component ship land`, `cplat pr wait` and the product ship's
   gitops PRs) renders the failure through it. It has one parser per tool output format, a fixed render with fixed limits (20 entries
   per check, 10 excerpt lines per entry, 80 lines in total, excerpts shortened before entries, a failing check never dropped) and is
   deterministic: the same log gives the same bytes.
2. **Unknown output falls back to today.** A check no parser reads is shown as `format: unknown` with its last 40 lines. Supporting a new
   tool is adding a parser; nothing else changes.
3. **The log stays local and is opened on demand.** Every summary names the log path (a CI check's log is saved next to the `cplat quiet`
   logs first). Instructions tell agents to open it only when the summary is not enough. Neither summary nor log goes to the run store.
4. **The summary is the failure of record.** Spec 102's no-progress signature is computed from the summary's normalized messages, and the
   recovery snapshot's excerpt is the summary. `cplat quiet` leaves the summary next to the log (`<log>.summary.json`) so `cplat budget
   attempt --error-file <log>` uses the same text.
5. **On by default, off per project or per call.** `failure_summary: off` in `.platform-settings.yml`, or `cplat quiet --raw`, restore the
   old output and say so.

## Consequences

- Fix rounds read a few dozen lines instead of whole logs; the benchmark task of spec 108 measures it against the old output.
- Equivalent failures are detected on what failed, not on the noise around it, so the no-progress stop sees through changing output.
- Each template tool format is code to maintain: a tool upgrade that changes its output degrades that check to `format: unknown` (today's
  output), never to a silent omission. Parser tests carry sample logs of each format.
- A tool's output in a new shape needs a parser before its summaries are useful; until then it behaves as before.

## Not included

- Summaries of successful output (spec 100 keeps one line), summaries made by a model, or dropping a failing check to save lines.
- Deploy-phase CI on main (`ship.run_logs`): not a fix round; it keeps its log tails.
