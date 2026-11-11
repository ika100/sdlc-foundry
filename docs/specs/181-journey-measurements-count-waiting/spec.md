---
spec_id: 181-journey-measurements-count-waiting
title: Journey measurements count waiting correctly
status: done
priority: P1
shape: platform
---

# 181 — Journey measurements count waiting correctly

## Problem

The journey measurement says where the wall clock goes, and the next round picks its target from it. Journey 10 (5.17.0)
took 138 minutes, and the measurement reported 91 of them as waiting (deploys and Argo 48, CI 25, promotions and
restores 17), 44 as agents and 4 as a person. That split is wrong: the demo repos' CI runs take 2–4 minutes each, and
38.7 of the waiting minutes fall in the step "One spec for the whole system", where the coordinator waits on the
headless repo sessions of the system ship (spec 155) while those sessions are building. The measurement reads only the
coordinator's transcript and labels a wait by the command's name, so a repo session's agent work counts as "deploys"
(the performance record even notes it since journey 8). A consolidation round that targets "deploys" would aim at the
wrong thing.

## Stories

- As the platform owner, I want the time a headless repo session or a subagent works counted as agent time, so that the
  waiting share shows only time in which nothing of ours works.
- As the platform owner, I want each waiting minute attributed to CI, deploy and Argo sync, promotion, restore and
  backup, cluster or smoke from evidence, so that I can rank the real waits.
- As the person recording a journey, I want one per-step table with agent minutes, waits by kind and the person's
  minutes, and a corrected split for journeys 9 and 10, so that the next round starts from true numbers.

## Acceptance criteria

- **AC-181.1** Given a journey whose coordinator waits 40 minutes in `cplat system ship next --wait` while its headless
  repo sessions have model turns or local commands during 30 of those minutes, when the journey is measured, then those
  30 minutes count as agent minutes (shown as coordinator and children separately) and only the other 10 can count as
  waiting; the repo sessions are found from the system ship's run records (spec 155) without being named on the command
  line, and subagents of the repo sessions count as children too.
- **AC-181.2** Given any journey, when it is measured, then every minute of the wall clock is counted exactly once, in
  this order: a person, agents (any thread of the coordinator or a child working), waiting; the person, agent and waiting
  minutes add up to the wall clock within 0.1 minute, overall and in each step.
- **AC-181.3** Given a minute in which no agent works, when it is measured, then its kind is taken from evidence, first
  match wins: the kind of the `cplat` wait or run-store phase open at that minute in the coordinator or a child (`pr wait`
  → CI; `system wait`, `component ship deploy` and a ship wait on the deploy phase → deploy and Argo; `instance promote` →
  promotion; `resource restore` and backups → restore and backup; `cluster wait` and cluster set-up → cluster; `instance
  verify` → smoke); else a GitHub Actions run of a journey repo running or queued at that minute → CI; else `unattributed`.
  A command's name alone never sets the kind, and `system ship next --wait` itself is never a kind.
- **AC-181.4** Given a repo session listed in the system ship's run records whose transcript cannot be found, when the
  journey is measured, then the measurement still finishes (exit 0), prints one warning line naming the repo and the
  missing session, and counts that session's minutes in which nothing else works as `repo session, no transcript`, not as
  deploy.
- **AC-181.5** Given a steps file, when the journey is measured, then it prints one row per step with the wall clock, the
  person's minutes, agent minutes (coordinator, children), and waiting minutes per kind (CI, deploy and Argo, promotion,
  restore and backup, cluster, smoke, unattributed, repo session without transcript), plus a total row; `--json` gives the
  same numbers per step.
- **AC-181.6** Given journey records that carry the per-step split from a measurement, when `cplat platform runs report
  --benchmarks` shows the journey section, then each stage shows the median agent minutes and median waiting minutes per
  kind next to the existing columns; a record without the split shows `–` in those columns and the rest of the report is
  unchanged.
- **AC-181.7** Given this change, when it ships, then "Recording a journey" in the performance record uses the per-step
  table and records waits by kind from it, and journeys 9 and 10 are re-measured from their saved transcripts and run
  records: their existing rows stay unchanged and one note under the wall-clock table gives each journey's corrected split
  (person, agents with coordinator and children, waiting per kind).

## Non-goals

- Making any wait shorter or changing what a `cplat` wait waits for; this spec only measures.
- Re-measuring journeys 1–8 or rewriting any earlier row of the performance record.
- Running a new journey.
- A new run-store schema for wait records beyond what the per-step split in a journey record needs.

## Assumptions

- **A1** Agent work in a child session takes precedence over the coordinator's wait on it, exactly as subagents already
  do (other option: count children's agent time separately and leave the coordinator's wait as waiting, double-counting
  minutes; affects AC-181.1, AC-181.2).
- **A2** A queued Actions run counts as CI waiting, like a running one (other option: a separate `queued` kind; affects
  AC-181.3).
- **A3** A waiting minute without evidence is shown as `unattributed` rather than guessed from command names (other
  option: fall back to today's command-name rules; affects AC-181.3, AC-181.5).
- **A4** Explicit wait records and run-store phases win over Actions runs when both cover a minute (other option: Actions
  runs first; affects AC-181.3).
- **A5** The per-step split reaches `cplat platform runs report` by the measurement writing it into the journey record
  when given the journey id; journeys without it show `–` (other option: the report computes the split itself from
  transcripts; affects AC-181.6).
- **A6** The corrected split for journeys 9 and 10 is a note, not new rows, so each table keeps one row per journey
  (other option: a "re-measured" row per journey; affects AC-181.7).

## Open questions

None.

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
- 2026-11-10 building
- 2026-11-11 done
