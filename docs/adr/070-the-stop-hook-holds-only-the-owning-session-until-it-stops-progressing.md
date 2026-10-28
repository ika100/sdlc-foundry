# ADR-070: The Stop hook holds only the run's owning session, and only while it makes progress

**Status:** Accepted (2026-10-28)
**Amends:** [ADR-028](028-unattended-delivery-without-branch-protection.md) (decision 3: "or after 8 blocked stops"), spec 088 (AC-088.18: the `environment` cause of a stuck-run escalation); spec 126

## Context

The Stop hook of ADR-028 kept every session in a checkout with an unfinished ship run going, and let go only after 8 blocked stops,
recording the cause `environment`. In the week of 2026-10-21, 14 of 32 escalated ships ended this way (10 from the hook, 4 from the
headless "no progress" rule), and escalated ships cost more than delivered ones. Three things were wrong:

- A count of stops says nothing about whether the session is getting anywhere: a stuck model spent six more turns, and a working one
  could be stopped at the eighth.
- The run state is per checkout, not per session, so a research session or a second session in the same checkout was held on a run it
  never started (a stale run of an already merged spec).
- The cause `environment` sent the weekly retro to the wrong owner: usually the model could not get further, a code or a decision
  problem.

## Decision

1. **A run has an owner.** The session that starts or resumes a run (`cplat component ship start`, `cplat system ship start`, including
   the sessions `cplat headless` starts) is recorded in the run state as `owner` (Claude Code's `CLAUDE_CODE_SESSION_ID`, or
   `CPLAT_SESSION_ID` that `cplat headless` exports). The latest start or resume wins.
2. **Only the owner is held.** The hook compares the Stop input's `session_id` with `owner`. Any other session stops silently and
   changes nothing. A run without an owner (state written before this ADR, or started outside Claude Code) never holds a session; the hook
   prints one line saying how to resume it.
3. **Progress, not a count, decides.** A stop of the owner shows progress when the feature branch has a new commit or the run's phase
   changed since the previous blocked stop (the first stop after a start or resume always does). Progress resets the count; two stops in a
   row without progress end the run as an escalation `no progress: …`. There is no cap on stops that show progress; the run budget of
   spec 102 bounds them.
4. **A fixed rule names the cause of a no-progress escalation** (from the hook or from `cplat headless`): the AC-088.16 rule matching
   the session's last message, else `code` when tests, criteria or a required PR check are red, else `decision`. Never `environment` by
   default, never `platform`, never `unknown`.

## Consequences

- Escalations from a stuck run come after two wasted turns instead of eight, and the retro's cause counts point at the code or the
  decision that stopped the run.
- Parallel sessions and worktrees sharing a run state no longer interfere; a run started before this change has to be resumed once
  (`/component:ship <spec>`) before the hook holds a session for it again.
- A session started outside Claude Code 2.1.132 or later (no `CLAUDE_CODE_SESSION_ID`) is never held; `cplat headless` covers unattended
  runs through `CPLAT_SESSION_ID`.
- Uncommitted edits do not count as progress: a model that edits but never commits escalates after two stops. That is intended, a ship
  run commits each finished task.

## Not included

- Deciding progress or cause with a model; both come from fixed rules.
- Any change to the run budget (spec 102), its equivalent-failure stop (AC-102.9) or the 3-fix-round escalation of `cplat ship`.
