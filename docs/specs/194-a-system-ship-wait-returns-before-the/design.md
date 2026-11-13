# Design — 194 A system ship wait returns before the Bash limit

## Decisions

- **Fixed deadline, progress is reported instead of extending.** `next --wait` keeps `begin` from the call's start and never
  resets it; progress (a new phase or commit, or a session started again under AC-155.5) only sets a flag that chooses the
  outcome when the deadline runs out: `WAIT:` with exit 0 when the flag is set, today's `TIMEOUT:` with exit 2 when not
  (AC-194.1–194.3, A1, A2). `PROGRESS_CAP` and the six-timeout extension of AC-148.7 go away.
- **A poll that has begun completes** (A1): the loop checks the deadline only between polls and sleeps `min(interval, left)`,
  so the overrun is at most one poll's own work, below the 10 s interval.
- **The coordinator counts, not `cplat`** (AC-194.4, A5): the three-`TIMEOUT:`-in-a-row escalation lives in
  `/system:ship`, as the at-most-twice rule does today; `cplat` keeps no count across calls.
- **No new ADR.** The change narrows one wait of [ADR-082](../../adr/082-a-coordinator-waits-with-a-cplat-wait-never-a-polling-loop.md)
  (exit 0 now also means "still running and moving" for `next --wait`, and its escalation rule counts timeouts in a row);
  the plan adds an `**Amended by:**` line to ADR-082 pointing here instead of a new decision record.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/shipwait.py` | `next_wait`: fixed deadline, progress flag, `WAIT:` outcome | changed |
| `scripts/cplat/appship.py` | `_next_wait`: prints the action, then the `WAIT:` line (stderr with `--json`); result word | changed |
| `scripts/cplat/waits.py` | `record`: an own run whose result is `progress` finishes `done` | changed |
| `plugins/system/commands/ship.md` | `action: wait` rule: rerun on `WAIT:`, escalate after three `TIMEOUT:` in a row | changed |
| `docs/rules/plugins/system/commands/ship.yml` | register entry for the changed rule | changed |

## Contract

`cplat system ship next --wait [--timeout T] [--json]` (T default 540):

| Outcome | When | stdout (plain) | stdout (`--json`) | stderr (`--json`) | exit |
|---|---|---|---|---|---|
| reached | the action is no longer `wait` at a poll (unchanged, spec 186) | the action as `next` prints it | the action JSON as `next --json` prints it | phase lines | 0 |
| progress | T ran out, the action is still `wait`, and at least one running repo made progress during the call | phase lines, the `wait` action as `next` prints it, then exactly one line `WAIT: repos still running, progress in the last <T>s; run the same wait again` | only the `wait` action JSON as `next --json` prints it | phase lines, then the `WAIT:` line | 0 |
| timeout | T ran out, no running repo made progress during the whole call | phase lines, `TIMEOUT: action still wait, no repo made progress for <T>s; running: <id> (<phase>), …`, `run the same wait again` (unchanged) | nothing | phase lines; the two `TIMEOUT` lines go where they go today (`say`) | 2 |

- `<T>` is `int(T)`. The call ends no later than T + 10 s after it started in every outcome (AC-194.1).
- **Progress during the call** (per running repo, compared with the first poll of this call): the mark
  `"<phase text> <git HEAD of the clone>"` changed, or `sched.check_session` returned a line (session started again,
  AC-155.5). A repo first seen mid-call sets its baseline and is not progress by itself.
- A repo whose ship ends or escalates is recorded (`sched.result`) at the poll that sees it, and the loop polls again
  at once, as today (AC-186.1).
- Run record: the wait's `waits[]` entry has `result` `reached`, `progress` or `timeout`; an own `wait` run (no attached
  run) finishes `done` for `reached` and `progress`.

`next_wait` signature stays `(gitops, timeout, as_json, interval) -> (code, action | None, lines)`; the progress outcome
returns `(0, <the wait action>, ["WAIT: …"])`, the timeout `(2, None, [TIMEOUT lines])`, reached `(0, action, [])`.

Pseudocode:

```
begin = now(); progressed = False; marks = {}
loop:
  action = next_action(); if action != wait: return 0, action, []
  for rid in running:
     mark = f"{text} {head}"
     if marks.get(rid) not in (None, mark): progressed = True
     marks[rid] = mark
     ... ended / check_session(...) -> progressed = True
  record ended; if ended: continue
  left = timeout - (now() - begin)
  if left <= 0:
     return (0, action, [WAIT line]) if progressed else (2, None, [TIMEOUT lines])
  sleep(min(interval, left))
```

### `/system:ship` rule (AC-194.4)

In the `action: wait` bullet: a `wait` action with exit 0 (`WAIT:`) is run again as the same wait; on exit 2 (`TIMEOUT:`)
run the same wait again, and after three `TIMEOUT:` results in a row (a `WAIT:` between them starts the count again)
`cplat system ship escalate '<the TIMEOUT line>' --cause environment`, stop. The sentence carries a reason clause (e.g.
"because repos that stopped moving that long point to the runner or cluster"), has register entry `R15` in
`docs/rules/plugins/system/commands/ship.yml` with `class: practice` and `source: spec 194`, and the file does not grow
(rule 6 of `docs/rules/README.md`): drop the sentence that only describes `cplat` behaviour ("A repo session that ended
before its ship did is started once more, then the repo escalates (spec 155).") and the `(spec 148)` reference to pay for it.
