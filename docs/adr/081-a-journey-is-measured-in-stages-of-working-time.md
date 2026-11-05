# ADR-081: A journey is measured in stages of working time

**Status:** Accepted (2026-11-05, spec 136)

## Context

The demo journey (empty folder → feature in dev → database and web UI → staging, release, prod with backups) took 240 and
234 minutes in the two journeys measured on 2026-11-05, against a budget of 60. The numbers were reconstructed by hand
from transcripts and Actions runs. Run records (ADR-032) and benchmarks (ADR-035) measure one run at a time, not a
journey across several repos and sessions, and they do not separate the time spent waiting for a person from the time the
platform takes.

## Decision

1. **One run record of kind `journey` per journey.** It is fed by `cplat platform runs journey …` (begin, stage start and
   end, waits, PRs, extra rounds, end), by hand or by the coordinator following the fixed script. Its pointer is
   machine-wide (`<runs state dir>/journey.json`), because a journey spans repos and sessions. Every event takes `--at`,
   so a journey reconstructed afterwards is recorded the same way.
2. **Working time is wall clock minus person-wait.** Person waits (a question, an approval, a decision shown until it is
   answered) are excluded from the budgets and reported on their own. External waits (rate limits, runner queues, the
   registry) count as working time and are also reported on their own. A minute that is both is a person minute.
3. **Waits belong to the journey, stages overlap.** A wait is one interval; a stage's waits are its overlap with the
   stage. A part and the journey are spans from their first stage start to their last stage end (the critical path),
   never the sum of their stages; the record keeps the sum and the overlap beside them.
4. **A stage that never ran is `not run`**, with null times, never 0 minutes.
5. **The comparison is the benchmark report.** `cplat platform runs report --benchmarks` shows the median per stage, part
   and journey per platform version and coordinator model over done runs, the previous version beside it, and ranks the
   stages by overrun. An overrun warns; it never fails a run, CI or a release.

## Consequences

- A release can show whether the journey got faster, and the next fix goes to the stage that loses the most minutes.
- The stage list and budgets are code (`runs_journey.STAGES`); changing them is a spec change and a new task version.
- What the script does not record (a PR, a round, a wait) is missing from the record; cplat adds only GitHub rate-limit
  waits on its own.
