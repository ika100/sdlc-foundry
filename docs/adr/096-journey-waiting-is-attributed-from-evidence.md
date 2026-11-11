# ADR-096: A journey's waiting is attributed from evidence, and a child session's work is agent time

**Status:** Proposed (2026-11-10, spec 181)
**Builds on:** [ADR-081](081-a-journey-is-measured-in-stages-of-working-time.md) (a journey is measured in stages)

## Context

The performance record ranks where a journey's wall clock goes, and the next round picks its target from that ranking. The
measurement (`scripts/journey/measure.py`) read only the coordinator's transcript and named a wait after the command that was
running: the coordinator's `cplat system ship next --wait` counted as "deploys" while the headless repo sessions of the
system ship (spec 155) were building. Journey 10 reported 91 of 138 minutes as waiting, 38.7 of them in one step where the
repo sessions were working. The script also sat outside `cplat`, so it could neither read the run records nor be tested.

## Decision

- The measurement is a `cplat` verb, `cplat platform runs journey measure` (modules `journey_timeline`, `journey_sources`,
  `journey_measure`); `scripts/journey/measure.py` only forwards to it.
- Each minute is counted once, in this order: a person; agents, when any thread works (the coordinator's sessions and their
  subagents, then the children: the repo sessions found through the system ship's run records and their subagents); waiting.
  A thread works inside its transcript's span unless a wait call is open in it or it only waits on a subagent.
- A wait call is a closed list of commands. Some carry a kind (`pr wait` → CI, `system wait` and `component ship deploy` →
  deploy and Argo, `instance promote` → promotion, `resource restore|backup` and `system restore` → restore and backup,
  `cluster wait` and cluster set-up → cluster, `instance verify` → smoke); the others (`system ship next --wait`, the lands,
  `component ship wait`, `gh run watch`, sleep loops) mark the thread as waiting but never set a kind.
- A waiting minute takes its kind from evidence, first match wins: an open repo session without a transcript
  (`no_transcript`); a kinded wait call or a run-store wait record or ship `deploy` phase; a GitHub Actions run of a journey
  repo, queued or running (CI); else `unattributed`.
- With `--journey <run_id>` the per-stage split is written as a follow-up line of kind `journey_split` on the journey record
  (the record itself is written once and never changed); `runs report --benchmarks` shows its medians.

## Consequences

- Waiting shrinks to the minutes in which nothing of ours works, and an `unattributed` share shows where evidence is missing
  instead of hiding it in a guessed kind.
- Journeys measured before this ADR are not comparable in their waiting columns; journeys 9 and 10 get a corrected note, 1–8
  keep their rows.
- A new wait verb in `cplat` has to be added to the list in `journey_timeline`, or its minutes count as agent work.
- A wait run in the background (`run_in_background`) is not seen as a wait call; the platform's prompts run waits in the
  foreground.
