# Design — 167 A dispatcher runs the backlog in parallel slots

## Decisions

- **Deterministic code, two agent calls.** `cplat dispatch` is plain Python in `scripts/cplat/dispatch*.py`. The only model
  calls are the premise check (issues) and the mode check (specs without a valid plan), each one short `claude -p` call
  with read-only tools. Everything else (readiness, order, slots, claims, merges, budget) is code with tests.
  ADR: [ADR-088](../../adr/088-a-dispatcher-schedules-orchestrator-runs-from-a-policy-file.md).
- **Units are worktrees.** Each unit runs in its own git worktree on its own branch, with a unit file in that worktree's
  git dir. The dispatcher's state is rebuilt on every start from `git worktree list`, those unit files, the processes
  that still live, the claim comments on GitHub and the run store (AC-167.9). The central state file only holds what
  has no other home: steering, the token ledger, the check cache, the GitHub snapshot and the history for `report`.
- **The foreground loop is the dispatcher.** `cplat dispatch start` runs the loop in the foreground until SIGINT/SIGTERM
  (or one cycle with `--once`). Units are started detached (`start_new_session`), so killing the loop never kills a
  unit. One loop per repo and machine: a flock on `dispatch/<owner>__<name>/loop.lock`.
- **The merge lock is a repo-wide rule, not a dispatcher feature.** `cplat pr wait --merge` and
  `cplat component ship land` take a machine-wide lock per repo slug before they merge, and update a branch that is
  behind `main` and wait for its checks again before merging. Manual sessions get it too, with or without a policy
  file. ADR: [ADR-089](../../adr/089-every-merge-into-main-holds-the-repo-merge-lock.md).
- **Fix units are landed by the dispatcher.** `/component:fix` stops at an open PR; the dispatcher then starts a land
  process (`cplat dispatch land <unit>`, which calls `pr.wait(..., merge=True)`). Ship units land themselves through
  `cplat component ship land`.
- **`cplat needs` gains a repo scope.** Without `applications/*/system.yaml` but with `.platform/dispatch.yml`,
  `cplat needs` lists the needs of the current repo only. This makes AC-167.8, .10 and .12 true in the platform repo,
  which has no system. Inside a system nothing changes, except two new kinds.
- **One notifier per event.** In a repo linked to a system (`.platform-app.yml` exists) the console notifier keeps
  `approve`, `answer`, `escalation` and `triage`; the dispatcher sends only `budget` and `stuck`. In any other repo
  the dispatcher sends all six. No event is notified twice.
- **`triaged` comes from triage.** No part of the platform sets `triaged` yet. `/issue:triage` now adds `triaged` when
  it routes an issue to a fix (`bug`, `small-change`) or to a spec (`feature`, which also gets `tracked`). `tracked`
  together with `triaged` is what `needs-spec` reads.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `dispatch_policy.py` | load, validate and default `.platform/dispatch.yml`; `serialize(repo)` for the merge lock | new |
| `dispatch_state.py` | paths, the state file (locked read-modify-write), steering, unit files, events, history, the loop lock, the needs file | new |
| `dispatch_backlog.py` | the snapshot (GitHub, git, specs, worktrees, active runs; at most every 300 s) and the candidate list | new |
| `dispatch_ready.py` | the verdict of each candidate (held reasons) and the order (priority rules, `prioritize`) | new |
| `dispatch_agent.py` | premise and mode checks: prompt, `claude -p --output-format json`, tokens, cache | new |
| `dispatch_budget.py` | the daily token ledger, unit usage (live and final), unknown usage, the 7-day hint, the budget need | new |
| `dispatch_units.py` | start, adopt, observe, restart, pause, land, finish and escalate units; claims, labels, comments; stale close; self-approval | new |
| `dispatch_notify.py` | the six-kind inbox document, the `budget`/`stuck` needs file, the notification pass and the daily digest | new |
| `dispatch_cycle.py` | one cycle (`run_cycle`) and its read-only form for `plan` (`evaluate`) | new |
| `dispatch_view.py` | text and JSON of `plan`, `status`, `report`, `inbox`, `wait` | new |
| `dispatch.py` | the CLI: verbs, the loop, steering, `wait`, the hidden `land` verb | new |
| `merge_lock.py` | the repo merge lock, the behind check, `update-branch`, the re-check before merging | new |
| `pr.py`, `ship.py` | `pr wait --merge` and `ship land` merge under the lock (whole wait with `e2e` serialized) | changed |
| `headless.py`, `supervisor.py` | the dispatch result file; stop at the next checkpoint when the stop flag exists | changed |
| `claim.py` | `holder_by(issue)`: the branch and whether the claim names `cplat dispatch` | changed |
| `spec.py` | `approve(spec, shape, by=None)`: the changelog line names who approved | changed |
| `needs.py` | kinds `budget` and `stuck`; repo scope; issue-based escalations; `_triage(all_triage=)` | changed |
| `notify_config.py`, `notify.py` | events `triage`, `budget`, `stuck`; `process()` reusable by the dispatcher; `events_of(kinds=)` | changed |
| `console/inbox.py`, `console/glossary.py` | panels and terms for `budget` and `stuck` | changed |
| `triage.py`, `plugins/issue/commands/triage.md` | labels `triaged`, `needs-decision`, `stale-premise`; triage adds `triaged` | changed |
| `cplat.py` | `dispatch` as plumbing, one doc line | changed |

## Contract

### The policy: `.platform/dispatch.yml` (AC-167.1, AC-167.2)

```yaml
slots: 2                      # integer 1..10                                   default 1
budget:
  tokens_per_day: 20000000    # integer >= 1; NO default: start/resume refuse without it
  per_unit:                   # passed to `cplat headless` as --budget KEY=VALUE  default {} (AC-131.13 defaults)
    cost: 20                  # keys: minutes, invocations, reruns, cost; value a number > 0 or `off`
sources: [issues, specs]      # non-empty subset of issues, specs              default [issues]
ready:
  labels: [bug]               # labels an issue needs besides `triaged`        default []
  exclude_labels: [blocked]   # labels that hold an issue besides needs-decision, wontfix   default []
priority: [label:bug, label:p1, spec-order, oldest]   # rules: label:<name> | spec-order | oldest   (this is the default)
gates:
  approve_specs: human        # human | self                                    default human
  merge: green-ci             # green-ci                                        default green-ci
serialize: [merge]            # subset of merge, e2e; must contain merge        default [merge]
```

Errors (exit 1, stderr, nothing started, nothing written):

- no file, on `start` and `resume`: `ERROR: no .platform/dispatch.yml in <repo>` / `  fix: commit a policy file (see docs/dispatch.md); cplat dispatch plan shows the defaults`
- no `budget.tokens_per_day`, on `start` and `resume`: `ERROR: .platform/dispatch.yml: budget.tokens_per_day is required (it has no default)` / `  fix: …; cplat dispatch plan shows the daily usage of the last 7 days`
- unknown key, on every verb that reads the file: `ERROR: .platform/dispatch.yml: <dotted key>: unknown key (allowed: <keys of that level>)`
- bad value: `ERROR: .platform/dispatch.yml: <dotted key>: <value> is not allowed (allowed: <values>)`; `serialize` without
  `merge`: `ERROR: .platform/dispatch.yml: serialize: must contain merge (allowed: merge, e2e)`

Every other verb works without the file and uses the defaults. `dispatch_policy.serialize(repo) -> list[str]` never
raises: a missing or broken file is `["merge"]`.

### Words and item references

- An **item** is `#<N>` (issue) or a spec (`<NNN>`, `spec-<NNN>` or the spec id) on the command line; its **key** is
  `issue-<N>` or `spec-<NNN>`. A **unit id** is `<key>.<seq>` (`issue-123.1`); `seq` counts the units of the item.
- Branches: a fix unit `fix/issue-<N>`; a ship unit `feature/<spec id>`.
- **Kind** `fix` (issue) or `ship` (spec). **Mode** `single` or `team`; fix units are always `single` (A4).
- **Candidates** (AC-167.3 words): with `issues` in `sources`, every open issue labelled `triaged` without
  `needs-decision`, `wontfix` or any `ready.exclude_labels`, carrying every `ready.labels`; with `specs`, every spec on
  `origin/main` with status `approved` or `building`, and every `draft` on `origin/main` or in an open draft spec PR
  (body marker `<!-- cplat:spec <id> -->`). A spec and the issues it `tracks` are one candidate: the spec.

### Readiness (AC-167.3, AC-167.4, AC-167.5, AC-167.6)

The verdict is `ready` or `held` with a reason. Text form `held: <reason>` plus ` (<detail>)`; a skip is
`held: skipped: <text>`. Reasons, checked in this order (the first that applies wins):

| reason | when | detail |
|---|---|---|
| `skipped` | `cplat dispatch skip <item> --reason <text>` and no `resume <item>` since | the text |
| `needs-decision` | a spec without tracked issue whose last unit escalated, until `resume <item>` | the reason |
| `stuck` | the item's last unit is stuck and the item still carries `needs-decision` (or, without issue, until `resume <item>`) | the log path |
| `claimed` | `in-progress` without a dispatcher claim; a claim for another branch; an active run record (not a unit's) with this issue or spec; the unit branch is checked out in another worktree | who / which branch / which run / which path |
| `blocked` | `blocked by #N` or `depends on #N` (case-insensitive) in the issue or spec text, and #N is open | `#N is open` |
| `duplicate` | an open PR (not a unit's) lists the issue in `closingIssuesReferences`, or an approved/building spec tracks it; for a spec: an open PR on `feature/<id>` that is not a unit's | the PR or spec |
| `needs-spec` | the issue carries `tracked` and no approved/building spec tracks it | - |
| `needs-approval` | a draft while `gates.approve_specs: human`; with `self`, a draft with an open question or a failing `cplat spec check` | which |
| `ship-busy` | a ship unit is not ended, or an earlier ship candidate takes a slot in this cycle | the running unit |
| `stale` | the premise check found the issue resolved on `main` (`plan` only; `start` closes it, below) | the commit or PR |

Items with a unit that is not ended are not candidates. An item whose last unit ended after the snapshot was read is
not judged until the next snapshot. A held candidate gets no label, comment or claim (AC-167.3).

**Order (AC-167.5).** First the pinned items (`prioritize`, most recent pin first), then the policy's rules in order,
each used only to break a tie of the rules before it:

- `label:<name>`: items carrying the label first. An issue matches its labels; a spec matches `label:pN` through its
  `priority: PN`, and any label of an open issue it tracks.
- `spec-order`: two specs by number, ascending; any other pair is a tie.
- `oldest`: by creation time (issue `createdAt`; a spec's `created` changelog date); a last tie by item key.

A pin is dropped when the item's unit starts. Pins and skips live in the state file and survive a restart.

**Premise check (AC-167.4, A3).** Only for an issue that is about to take a free slot, in `plan` as well; the others
show `premise: unchecked`. Skipped for an issue whose comments hold the stale marker while it is open again (it was
reopened after a stale close: never closed as stale again). Verdict `holds` or `resolved` with evidence; the evidence
must be a commit on `origin/main` or a merged PR, checked in code, else the verdict counts as `holds`. A failed call
counts as `holds` (the fix run itself finds out). `start` then: comment
`<!-- cplat-dispatch-stale -->\nResolved on main by <sha or PR url>: <why> (cplat dispatch premise check).`, label
`stale-premise` (created if missing), `gh issue close`, no unit. `plan` only shows `held: stale (<evidence>)`.

**Mode check (A4).** For a spec about to take a slot. With a committed plan (on `feature/<id>` or `origin/main`) that
passes `check_plan`: `team` when the plan's units at `--parallel 3` (`units._task_units`) hold at least one `batch:`
unit, else `single`; no agent call. Without one: the agent reads `spec.md` and answers. A failed call is `single`.

**Self-approval (AC-167.6).** With `gates.approve_specs: self`, a draft without open question whose approved form passes
`spec.check` is `ready` with `approve: self` in `plan`. At start, in the unit's worktree on `feature/<id>` (created from
the draft's branch, or `origin/main`), `spec.approve(sp, shape, by="cplat dispatch")` writes the changelog line
`- <date> approved by cplat dispatch`, committed with `git commit -s -m "docs(spec): approve <id> (cplat dispatch)"`.
A draft PR on another branch than `feature/<id>` is closed with a comment naming the ship PR when the unit is done.

### Units (AC-167.6 to AC-167.9)

**Start**, for each ready item in order while a slot is free, not paused, the budget not reached and no usage unknown:

1. Claim (issue: the issue; spec: each open tracked issue) with `claim.claim(repo, [N], branch, what="cplat dispatch")`:
   label `in-progress`, assignee `@me`, comment `<!-- cplat-claim -->\nClaimed for branch \`<branch>\` (cplat dispatch).`
   A claim refused because another branch holds it: held `claimed`, nothing else happens.
2. Worktree `dispatch/<owner>__<name>/worktrees/<repo name>-<key>` on the unit branch (`git worktree add -b <branch>
   <path> origin/main` for a new fix branch; an existing branch is reused).
3. Unit file `<worktree git dir>/cplat-dispatch-unit.json` (below), then the unit run record
   `runs.start("dispatch", repo=<slug>, spec=<spec id or None>)` with sections `issue` `{repo, number, url}` (or null) and
   `dispatch` `{unit, kind, mode, branch}`.
4. Spawn detached, cwd the worktree, stdout and stderr to `dispatch/<owner>__<name>/logs/<unit id>.log`:
   `cplat headless --repo <worktree> [--budget K=V …] [--parallel 3|1 (ship only)] "/component:fix #<N>" | "/component:ship <spec id>"`
   with env `CPLAT_DISPATCH_UNIT=<unit id>`, `CPLAT_DISPATCH_RESULT=<worktree git dir>/cplat-dispatch-result.json`.
   `$CPLAT_DISPATCH_HEADLESS`, when set, is the executable used instead of `cplat headless` (same arguments): the seam
   for the fake headless of the tests.

**Unit file** `cplat-dispatch-unit.json`:
`{"schema": 1, "unit": "issue-123.1", "item": "#123", "key": "issue-123", "kind": "fix", "mode": "single", "branch": "fix/issue-123",
"worktree": "<path>", "slot": 1, "pid": 4242, "land_pid": null, "log": "<path>", "starts": 1, "run_id": "<dispatch run id>",
"status": "starting|running|landing|paused|done|escalated|stuck", "pr": null, "started_at": "<iso>", "ended_at": null,
"reason": null, "tokens": null}`.

**Result file** written by `cplat headless` when `CPLAT_DISPATCH_RESULT` is set: at start
`{"unit", "run_id", "pid", "started_at", "ended_at": null}`, at the end (also on an exception) the same plus
`"ended_at", "result", "stop_reason", "outcome", "cause", "code", "tokens"` (`tokens`: the sum of input, output,
cache_read and cache_write of the run's usage totals; null when unknown). The headless run record gets the field
`dispatch_unit`.

**Observe** (every tick of 5 s: a cycle runs when a unit process ended, else every 60 s). A process lives when
`os.kill(pid, 0)` succeeds and `ps` shows `headless` or `dispatch land` in its command (as `appship_proc.alive`).
When the headless process of a unit ended:

| what the worktree and result file say | fix unit | ship unit |
|---|---|---|
| ship state `done`, or result `shipped …` | - | `done` |
| result outcome `escalated`, or ship state / units file escalated | escalate | escalate |
| result `stop_reason: paused` (stop flag) | `paused` | `paused` |
| outcome `done`, open PR on the unit branch | `landing`: spawn `cplat dispatch land <unit>` | - |
| outcome `done`, PR merged | `done` | - |
| outcome `done`, no PR | escalate, cause `decision`, reason `the fix run ended without a pull request` + last-message excerpt | - |
| anything else (failed, abandoned, no result, process killed) | restart once, then stuck | restart once, then stuck |

**Land** (`cplat dispatch land <unit>`, hidden verb): `pr.wait(worktree, pr, merge=True, timeout=7200, …)`; the unit
file gets `landed: merged | red | closed | merge-failed` and the red summary. Merged → `done`; red, closed, merge
failed → escalate with cause `code` (red) or `decision`, and a `RED:` event for `wait`. A land process that died is
started once more, then the unit is stuck.

**Done:** release the claim (`claim.release(repo, [N], "done in <PR> (cplat dispatch)")`), finish the unit record
`runs.finish(run_id, "done", fields={"pr": {...}, "tokens": n})`, add a history entry, free the slot. The worktree is
removed (`git worktree remove`) once the branch is merged; the branch is deleted by the merge.

**Escalate (AC-167.8):** release the claim; label the issue (a spec: each open tracked issue) `needs-decision`
(created if missing) and comment `<!-- cplat-dispatch-escalation -->\n<reason>\nLog: <path>\nRemove the label
needs-decision to let cplat dispatch try again.`; finish the unit record `escalated` with
`escalation {reason, cause, run}` (`run`: the escalated ship run id, when there is one); event `escalated`; free the
slot; keep the worktree. A spec without tracked issue is held `needs-decision` in the state until `resume <item>`.
When the label is removed, the next cycle judges the item again; its next unit reuses the worktree and branch (a ship
resumes its escalated run).

**Restart (AC-167.8):** a unit whose process ended while its run is neither done nor escalated is started again in the
same worktree with the same command (`starts: 2`); a fix worktree with uncommitted changes is stashed first
(`git stash push -u -m "cplat dispatch: before restart"`). A second such end escalates with cause `environment`, status
`stuck`, and writes a `stuck` need naming the log path.

**Pause (AC-167.11):** `pause` writes the stop flag `<worktree git dir>/cplat-dispatch-stop` in every running unit;
`cplat headless` (legacy loop and supervisor) checks it before each next session and ends with result
`paused at a checkpoint by cplat dispatch`, stop reason `paused`, outcome `abandoned`, exit 1. A land process is not
interrupted; a fix unit whose session ended waits as `paused` instead of landing. `resume` removes the flags and
restarts paused units first (not counted as a restart, claims kept). `pause --drain` writes no flag.

**Adopt (AC-167.9):** on every start the loop lists `git worktree list --porcelain`, reads the unit file of each
worktree under `dispatch/<owner>__<name>/worktrees/`, adopts every live process and treats dead ones as above. A
dispatcher claim (comment names `cplat dispatch`) for a unit branch with no worktree is the loop's own: the unit is
started (the claim is not repeated, as `claim.claim` skips a claim for the same branch). No item gets a second unit
while one is not ended.

### The merge lock (AC-167.7)

`merge_lock.held(slug, who, timeout, interval=5)` is a context manager: an exclusive `flock` on
`${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/locks/<owner>__<name>.merge.lock`; the holder is written to
`<owner>__<name>.merge.json` `{who, pid, since}`. While waiting it prints
`waiting for the merge lock of <slug>: held by <who> since <HH:MM:SS>` once a minute; past `timeout` it raises
`merge_lock.Busy` (a `PlatformError`: exit 1, `ERROR: the merge lock of <slug> is held by <who> since <time>`,
hint `run it again`). A `Busy` is no red check, no fix round and no escalation.

`merge_lock.merge(repo, url, watch, timeout, interval) -> (ok, lines)`, called inside the lock:

1. Behind check: `gh api repos/<slug>/compare/<default branch>...<head sha> --jq .behind_by`; `> 0` is behind.
2. Behind: `gh pr update-branch <url>` (a merge commit on the branch, never a force push), line
   `<url> was behind <branch>: updated, waiting for its checks again`; then the checks of the new head are waited for
   (the same `CheckWatch` rules, first red ends it). A conflict: `MergeFailed` (`conflicts with main: a human decision`).
3. `gh pr merge <url> --squash --delete-branch --match-head-commit <head sha>`.

`pr.wait(..., merge=True)` and `ship.land` call it. With `e2e` in `dispatch_policy.serialize(repo)` the lock is taken
before the first check wait (the whole land phase); otherwise around steps 1 to 3 only. `ship.land` fast-forwards the
local feature branch after an update (`git pull --ff-only origin <branch>`), so a later push of the session works.
`pr wait` without `--merge` takes no lock.

### Budget (AC-167.10)

- The **day** is the local calendar day. The ledger in the state file: `ledger[<YYYY-MM-DD>] = {"units": {<unit>: tokens},
  "agent": tokens}`, and `counted[<unit>]` = the unit's tokens already booked. Each cycle books the growth of each
  unit's tokens to today. Today's usage = sum of `units` + `agent`.
- A unit's tokens: running, `runs_usage.for_run(runs.active(<headless run id>), peek=True, budget_s=3)` (no session
  registered yet = 0); ended, the result file's `tokens`, else the `usage` of the headless record found in the buffer or
  store. **Unknown** (a section with `incomplete`, or no totals while sessions exist): no unit starts, `status` names the
  unit, until the usage is known or the day ends.
- An agent call books the `usage` of `claude -p --output-format json` (input + output + cache tokens); a call whose
  answer has no usage books 200 000 tokens (its bounded ceiling: `--max-turns 8`).
- Usage `>= budget.tokens_per_day`: no unit starts and no agent call is made; running units go on within their own
  budgets (spec 102); one `budget` need for the day; it is resolved, and starts continue, when the day changes or the
  limit is raised above the usage.
- The 7-day hint of `plan` (no `tokens_per_day`): today and the 6 days before, oldest first, the tokens of the
  top-level run records (no `parent`) of this repo by local start day, from the buffer and the store; `null` for a day
  that cannot be read.

### Steering (AC-167.11)

Each verb changes the state file under its lock and prints one line; the loop applies it within one cycle.

| verb | effect | needs the policy file |
|---|---|---|
| `cplat dispatch pause [--drain]` | `paused: "pause"` or `"drain"` (above) | no |
| `cplat dispatch resume` | `paused: null`, flags removed | yes (AC-167.1) |
| `cplat dispatch resume <item>` | drops the item's skip and its `needs-decision`/`stuck` hold in the state | yes |
| `cplat dispatch slots <N>` | `slots` override (1..10); a lower N stops nothing, only no start until running < N | no |
| `cplat dispatch prioritize <item>` | pins the item first | no |
| `cplat dispatch skip <item> --reason <text>` | held `skipped: <text>` | no |

### Commands and output

All verbs take `--repo DIR` (default `.`). JSON documents carry `"schema": 1`.

**`cplat dispatch start [--once]`** — exits 1 as above without the file or the key; `ERROR: a dispatcher already runs for
<slug> (pid N)` when the loop lock is held. One line per action: `started <unit> (<kind>, <mode>, slot <n>): <command>  log: <path>`,
`adopted <unit> (pid N)`, `landing <unit>: <pr>`, `done <unit>: <pr>`, `escalated <unit>: <reason>`,
`restarted <unit> (start 2)`, `stuck <unit>: <log>`, `closed #N as stale: <evidence>`, `approved <spec> (cplat dispatch)`,
`no starts: <paused|drain|daily budget reached|usage unknown: <unit>>`. Exit 0 after `--once` or a signal.

**`cplat dispatch plan [--json]`** — reads; writes nothing to GitHub, creates no branch, worktree or claim, fetches
nothing (it reads `origin/main` as last fetched, and the snapshot cache when younger than 300 s, else GitHub). It may
make the two agent calls and update the local check cache and ledger.

```json
{"schema": 1, "repo": "acme/shop-api", "read_at": "<iso>",
 "policy": {"file": ".platform/dispatch.yml" | null, "values": {"slots": 1, "budget": {"tokens_per_day": null, "per_unit": {}}, "sources": ["issues"],
            "ready": {"labels": [], "exclude_labels": []}, "priority": ["label:bug", "label:p1", "spec-order", "oldest"],
            "gates": {"approve_specs": "human", "merge": "green-ci"}, "serialize": ["merge"]},
            "defaulted": ["slots", "..."], "unset": ["budget.tokens_per_day"],
            "usage_hint": [{"day": "2026-11-03", "tokens": 1204331}, "… 7 entries, null when unreadable"] },
 "tokens": {"day": "2026-11-09", "used": 3104221, "limit": 20000000 | null, "unknown": ["issue-123.1"]},
 "starts": {"allowed": true, "why_not": null | "paused" | "drain" | "daily budget reached" | "usage unknown"},
 "slots": {"total": 2, "running": 1, "free": 1},
 "candidates": [{"item": "#123", "key": "issue-123", "kind": "fix", "title": "…", "verdict": "ready", "reason": null, "detail": null,
                 "mode": "single", "slot": 2, "premise": "holds" | "resolved" | "unchecked" | null, "approve": null | "self"}],
 "unavailable": [{"source": "github", "error": "…"}]}
```

Text: the policy block (`policy: defaults (no .platform/dispatch.yml)` or `policy: .platform/dispatch.yml`; one line per
key, `(default)` after a defaulted one; `budget.tokens_per_day: unset (required by start and resume) — last 7 days: <day> <tokens> …`),
`tokens today: <used> of <limit>`, then `candidates (<n>):` and one line per candidate in order:
`<item>  <kind>  <ready | held: <reason>[ (<detail>)]>  <mode or ->  <slot n | queued | ->  premise <…>  <title>`.
`premise unchecked` is printed for issues not about to take a slot.

**`cplat dispatch status [--json]`** — local reads only (state, unit files, processes, usage).

```json
{"schema": 1, "repo": "…", "loop": {"running": true, "pid": 4242}, "paused": null | "pause" | "drain",
 "slots": {"total": 2, "units": [{"slot": 1, "unit": "issue-123.1", "item": "#123", "kind": "fix", "mode": "single",
           "phase": "starting|running|landing|paused|plan|red-tests|build|pr|land|deploy", "since": "<iso>", "tokens": 412003 | null,
           "pid": 4243, "log": "<path>", "pr": null}]},
 "queue": [{"item": "#130", "kind": "fix", "mode": "single"}], "held": [{"item": "#140", "reason": "claimed", "detail": "…"}],
 "tokens": {"day": "…", "used": 3104221, "limit": 20000000, "unknown": []}, "last_cycle": "<iso>"}
```

A ship unit's phase is its ship state phase; `queue` and `held` are those of the last cycle.

**`cplat dispatch wait [--timeout S]`** (default 540, ADR-082; `waits.record`): exit 0 `IDLE: no unit runs and nothing ready is queued`;
exit 1 when an `escalated` or `red` event not yet seen by a wait exists (it is marked seen): first line
`ESCALATED: <unit> <item>: <reason>` or `RED: <unit> <item> <pr>: <failed checks>`; exit 2 `TIMEOUT: <n> unit(s) running after <S>s`
then one line per unit `  <unit> <item> <phase> since <HH:MM>`. It reads the state only; without a live loop it says so on
a second line.

**`cplat dispatch report [--since D] [--json]`** (D days, default 7): per local day, newest first,
`{"day", "delivered": [{"item", "unit", "pr", "tokens"}], "escalated": [{"item", "unit", "reason"}], "held": [{"item", "reason"}], "tokens": n}`;
text `<day>  delivered <n>  escalated <n>  held <n>  tokens <n>` and one indented line per list.

**`cplat dispatch inbox [--json]`** — `cplat needs` in repo scope, only the kinds `approve`, `answer`, `escalation`,
`triage`, `budget`, `stuck`; the same document and text as `cplat needs`.

### Needs (AC-167.8, AC-167.10, AC-167.12)

- **Repo scope:** `cplat needs` in a directory without `applications/*/system.yaml` that has `.platform/dispatch.yml`
  lists the current repo's items: drafts (`approve`/`answer`), escalations of run records of this repo, `triage` (every
  open issue labelled `triage`), `budget`, `stuck`. Without either file the AC-122.4 error stays.
- **Issue escalations:** a run record with an `issue` section gives the command
  `gh issue edit <N> --remove-label needs-decision` for a `dispatch` record and `/component:fix #<N>` otherwise; a newer
  run hides it only when it serves the same issue. A `dispatch` record whose `escalation.run` names another escalated
  record is not listed (the ship run's item is).
- **New kinds**, read from `dispatch/*/needs.json` (written by the loop, one file per repo), included for the system's
  repos or, in repo scope, this repo:

```json
{"id": "budget:acme/shop-api:2026-11-09", "kind": "budget", "stage": "Build",
 "object": {"type": "dispatch", "repo": "acme/shop-api", "spec": null, "run_id": null, "issue": null, "component": null, "version": null, "pr": null, "url": null},
 "since": "<iso>", "reason": "daily token budget reached: 20104332 of 20000000 tokens",
 "command": "raise budget.tokens_per_day in .platform/dispatch.yml (starts continue after midnight)", "cwd_repo": "acme/shop-api",
 "consequence": {"used": 20104332, "limit": 20000000, "running": ["issue-123.1"]}, "way_back": null}
{"id": "stuck:acme/shop-api:issue-123.1", "kind": "stuck", "stage": "Build",
 "object": {"type": "run", "repo": "acme/shop-api", "spec": null, "run_id": "<dispatch run id>", "issue": 123, "log": "<path>", "…": null},
 "since": "<iso>", "reason": "unit issue-123.1 ended twice without finishing (cause environment); log: <path>",
 "command": "gh issue edit 123 --remove-label needs-decision" | "cplat dispatch resume <spec>", "cwd_repo": "acme/shop-api",
 "consequence": {"log": "<path>", "starts": 2}, "way_back": null}
```

  A `stuck` need is resolved when its item no longer carries `needs-decision` (or is resumed); a `budget` need as above.

### Notifications and digest (AC-167.12)

- `notify_config.EVENTS` gains `triage`, `budget`, `stuck`. Recommended preset: `triage` desktop instant (GitHub off: the
  issue exists), `budget` desktop instant, `stuck` GitHub and desktop instant.
- `notify.process(cfg, doc, state_path, *, kinds, digest)` is the body of today's `run_once` (instant delivery, quiet
  hours, resolve, digest when due); `run_once` calls it with the old kinds. `events_of(doc, kinds)` maps needs items of
  the given kinds; `triage` items become event `triage`.
- Each cycle the loop builds the inbox document and calls `process` with state
  `notify/dispatch-<owner>__<name>.json` and kinds: all six, or only `budget` and `stuck` when `.platform-app.yml`
  exists. Nothing else (no start, no done) is notified.
- The digest: daily (every day of the week) at `digest.at` of `notify.yaml` (default 09:00 local), outside quiet hours,
  on every `slack`/`email` channel that has at least one event set to `digest`. Body sections `Delivered`, `Escalated`,
  `Held`, `Queue`, `Tokens` since the last digest (`last_digest` in the dispatcher's notify state). All empty and 0
  tokens: not sent.

### Labels and markers

`triaged` (routed by triage), `needs-decision` (a decision of the user holds the item), `stale-premise` (closed by the
premise check), `in-progress` (claim, spec 082). Comment markers: `<!-- cplat-claim -->`, `<!-- cplat-release -->`,
`<!-- cplat-dispatch-stale -->`, `<!-- cplat-dispatch-escalation -->`. `claim.holder_by(issue) -> (branch | None,
by_dispatch: bool)`; `by_dispatch` is true when the last unreleased claim comment contains `(cplat dispatch)`.

## Data

`${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/dispatch/<owner>__<name>/`:

- `state.json` (schema 1), changed only under `state.lock`:
  `{steering: {paused, slots, pinned: [item], skipped: {item: {reason, at}}, holds: {item: {reason, unit, at}}},
  ledger, counted, checks: {key: {premise: {verdict, evidence, why, main_sha, issue_updated, at}, mode: {mode, why, plan_sha, at}}},
  snapshot: {read_at, main_sha, issues, prs, specs, drafts, runs}, last_cycle: {at, queue, held, slots},
  events: [{seq, at, kind: started|done|escalated|red|stuck|stale, unit, item, reason, pr, seen}] (last 500),
  history: [{unit, item, kind, outcome, pr, tokens, reason, started_at, ended_at}], days: {day: {held: {item: reason}}},
  seq: {key: n}}`; ledger, history and days are kept 90 days.
- `loop.lock`, `needs.json` (`{"items": [...]}`), `logs/<unit>.log`, `worktrees/<repo name>-<key>/`.

Per unit worktree git dir: `cplat-dispatch-unit.json`, `cplat-dispatch-result.json`, `cplat-dispatch-stop`.
Locks: `${XDG_STATE_HOME}/sdlc-foundry/locks/<owner>__<name>.merge.lock` and `.merge.json`.

The snapshot (refreshed by the loop at most every 300 s): `gh issue list --state open --limit 500 --json
number,title,body,labels,assignees,createdAt,updatedAt` (comments only for issues with `in-progress` or a dispatcher
marker, `gh issue view N --json comments`), `gh pr list --state open --limit 200 --json
number,url,headRefName,body,isDraft,closingIssuesReferences`, `git fetch -q origin main` and the PR heads of draft spec
PRs, the specs of `origin/main` (`git ls-tree`/`git show`), active run records (`runlist.collect(2)`). Per-unit calls
(claim, the unit's PR, labels and comments it writes) are made when the action happens.

## Risks

- **The repo's committed allowlist decides what a fix session may do.** `/component:fix` runs under headless's legacy
  loop with `acceptEdits` and the repo's rules; a repo without `cplat pr open` allowed stops at the PR. `start` checks
  nothing extra; the unit escalates with the session's last message.
- **CI that starts at PR open is not serialized.** With `e2e` in `serialize` the *wait* is serialized; a PR opened
  while another lands queues its run on the runner, and its CI runs again after `update-branch` inside the lock.
- **Self-approval is a commit on the unit branch**, so main shows the spec as approved only once the ship merges.
- **Many issues:** the snapshot reads at most 500 open issues; more are ignored with a line in `unavailable`.
- **Untrusted text:** issue and spec text in agent prompts is redacted (`feedback.redact`) and fenced
  (`triage.fenced`); the agent's tools are `Read`, `Grep`, `Glob`, `Bash(git log:*)`, `Bash(git show:*)` only.
