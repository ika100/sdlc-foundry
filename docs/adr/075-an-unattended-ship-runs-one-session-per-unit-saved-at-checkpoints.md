# ADR-075: An unattended ship or build runs as one session per unit, each saved at a checkpoint

**Status:** Accepted (2026-11-03)
**Amends:** [ADR-028](028-unattended-delivery-without-branch-protection.md) (decision 4: headless sessions each resume the whole run), [ADR-070](070-the-stop-hook-holds-only-the-owning-session-until-it-stops-progressing.md) (unit sessions are held only until their unit's checkpoint and never escalated by the hook); spec 131

## Context

From 2026-10-24 to 2026-10-31, 16 of 52 `ship` runs finished. About half of the estimated agent spend went to runs that
ended escalated or failed. The top cause was the run's shape, not the code. A ship was one long session that the Stop hook
held until it gave up or stopped making progress. `cplat headless` (spec 070) resumed a stopped run in a fresh session,
but each session tried to finish the whole remaining run. One hard step used up the context, the stops and the budget of
everything after it, and a session that ended lost all its unsaved progress.

## Decision

1. **A run is a list of units.** An unattended `/component:ship` or `/component:build` under `cplat headless` is the list
   `plan`, `red-tests`, one `task:<id>` per task in dependency order, `verification` and `land`. The supervisor
   (`cplat headless`) starts one fresh `claude -p` session per unit, one after the other. The session's prompt names the
   unit (`--unit <unit>`). Task units run one after the other and never in parallel worktrees.
2. **A checkpoint is detected, not declared.** A unit is done when fixed rules on the committed tree of the feature branch
   (and the ship state for `verification` and `land`) say so. The unit and the commit it ended on are recorded in
   `<git dir>/cplat-units.json`, per worktree as in ADR-051. A checkpoint stops counting once its commit is no longer on
   the feature branch. A unit that is already complete is skipped.
3. **The Stop hook ends a unit session at its checkpoint.** While its unit is open, it holds the session only as long as
   each stop brings a new commit. The hook never escalates a unit session.
4. **The supervisor counts sessions per unit.** Two sessions in a row that end without the checkpoint and without a new
   commit escalate the run as `no progress: unit <unit> after 2 sessions without a commit`, with the cause rule of
   ADR-070. Sessions that add commits are bounded only by the budget. `--max-runs` caps sessions only when it is given.
5. **Runs in flight from 5.5 continue.** A ship run without units gets them derived from its phase and the plan's `done`
   flags. Nothing is asked.

## Consequences

- A session that ends, fails or fills its context loses at most one unit, and the next session starts from the last
  checkpoint.
- Each unit session pays the start-up cost of reading the command again. The scaled budget of ADR-077 bounds this.
- Uncommitted work never counts as progress or as a checkpoint, so unit sessions must commit what they finish.
- Attended runs keep one session and parallel worktrees, and the ADR-070 stop rule still applies to them.

## Not included

- Per-unit sessions for `/system:ship` in the repos it drives (a follow-up spec), and parallel task units.
- A supervisor anywhere but on the user's machine.
