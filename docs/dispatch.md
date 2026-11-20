# The dispatcher: run the backlog in parallel slots

`cplat dispatch` ([ADR-088](adr/088-a-dispatcher-schedules-orchestrator-runs-from-a-policy-file.md)) works through the backlog of a repo
so you do not start each run yourself. It reads a policy file, picks the issues and specs that are ready, and starts the existing
`/component:fix` and `/component:ship` runs, one per slot, each in its own git worktree. It is plain code: it calls a model only to check
whether an issue is still true on `main` and whether a spec's work splits into parallel tasks. Your decisions stay yours: you route issues in
triage, you approve specs (unless you let the dispatcher do it), you promote to prod.

## Turn it on step by step

1. **Look first.** `cplat dispatch plan` reads only. It works without a policy file and shows the defaults, every candidate with its verdict
   (`ready` or `held: <reason>`), the order, the slot each would take and the daily token usage of the last 7 days. It writes nothing to
   GitHub and creates no branch, worktree or claim.
2. **One slot, issues only.** Commit `.platform/dispatch.yml` with a daily limit in US dollars and leave `slots` at 1 and `sources` at `[issues]`:

   ```yaml
   slots: 1
   budget:
     usd_per_day: 20
   ```

   Pick the limit from the 7-day cost hint of `plan`. On a subscription, set `budget.mode: plan` instead and install the
   [usage sensor](#plan-usage-sensor). Then run `cplat dispatch start --once` once and read the lines it prints, then
   `cplat dispatch start` for the loop. Fix runs open a PR; the dispatcher lands it when the checks are green.
3. **Specs and more slots.** Add `specs` to `sources` and raise `slots` (or `cplat dispatch slots 3` for a try without a commit). Specs are
   still approved by you (`gates.approve_specs: human`); a draft waits as `held: needs-approval`.
4. **Optional: let the dispatcher approve.** `gates.approve_specs: self` approves a draft that has no open question and passes
   `cplat spec check`. The approval is a commit on the feature branch (`approved by cplat dispatch` in the changelog of the spec).

`start` runs in the foreground until Ctrl-C or SIGTERM. Units are started detached, so ending the loop never kills a unit; the next `start`
adopts the units that still run. Keep it alive with a terminal multiplexer, launchd or systemd. One loop per repo and machine.

## The policy file `.platform/dispatch.yml`

| Key | Values | Default |
|---|---|---|
| `slots` | integer 1 to 10 | `1` |
| `budget.mode` | `cost`, `plan` | `cost` |
| `budget.usd_per_day` | number > 0: the daily limit in US dollars | none: in mode `cost`, `start` and `resume` refuse without it (or without the deprecated `budget.tokens_per_day`) |
| `budget.usd_per_month` | number > 0: the limit since the 1st of the local month | none |
| `budget.tokens_per_day` | integer >= 1; **deprecated**, use `budget.usd_per_day` | none |
| `budget.per_unit` | map of `minutes`, `invocations`, `reruns`, `cost` to a number > 0 or `off`; passed to `cplat headless` as `--budget KEY=VALUE` | `{}` (the budgets of [unattended delivery](unattended-delivery.md#budgets-and-repeated-failures)) |
| `budget.plan.weekly_target` | number 0.50 to 1.00: the share of the weekly limit to use by its reset; only with mode `plan` | `0.92` |
| `budget.plan.window_stop` | number 0.50 to 1.00: the share of the 5-hour window at which no unit starts; only with mode `plan` | `0.80` |
| `budget.plan.filler_only` | rules `label:<name>` or `priority:P0` to `P2`; only with mode `plan`; `[]` is allowed | `[priority:P2, label:enhancement]` |
| `budget.plan.filler_tasks` | list of `{name, command}` with unique names; only with mode `plan` | `[]` |
| `budget.plan.filler_drafts` | `true`, `false`; only with mode `plan` | `true` |
| `sources` | non-empty subset of `issues`, `specs` | `[issues]` |
| `ready.labels` | labels an issue needs besides `triaged` | `[]` |
| `ready.exclude_labels` | labels that hold an issue besides `needs-decision` and `wontfix` | `[]` |
| `priority` | rules `label:<name>`, `spec-order`, `oldest` | `[label:p0, label:bug, label:p1, spec-order, oldest]` (a spec at `P0` matches `label:p0` and so sorts first) |
| `gates.approve_specs` | `human`, `self` | `human` |
| `gates.merge` | `green-ci` | `green-ci` |
| `serialize` | subset of `merge`, `e2e`; must contain `merge` | `[merge]` |
| `guard.loop_calls` | integer 3 to 100: model calls without a tool call or other progress that make a unit "looping" | `10` |
| `guard.loop_minutes` | integer 1 to 60: the window those calls are counted in | `5` |

A full file:

```yaml
slots: 2
budget:
  mode: cost
  usd_per_day: 20
  usd_per_month: 300
  per_unit:
    cost: 20
sources: [issues, specs]
ready:
  labels: [bug]
  exclude_labels: [blocked]
priority: [label:p0, label:bug, label:p1, spec-order, oldest]
gates:
  approve_specs: human
  merge: green-ci
serialize: [merge]
guard:
  loop_calls: 10
  loop_minutes: 5
```

A `budget.plan.*` key in mode `cost` fails with `budget.plan.<key>: needs budget.mode: plan`. A mistake in the file exits 1 and names the key, for example `ERROR: .platform/dispatch.yml: slots: 11 is not allowed (allowed: ...)`;
nothing is started (`guard.loop_calls: 2 is not allowed (allowed: an integer 3..100)`). Every verb that reads the file checks it; only `start` and `resume` need it to exist and, in mode `cost`, to carry a daily limit.

## What is ready

A candidate is an open issue labelled `triaged` (`/issue:triage` adds it when it routes an issue to a fix or a spec), or a spec on `main`
with status `approved` or `building`, or a draft. A spec and the issues it tracks are one candidate: the spec. A fix run's task is the newest `Triage:` comment by a user with write access (the reporter's text is added fenced); without one it is `/component:fix #<n>`. The verdict is `ready` or
`held` with the first reason that applies; a held item gets no label, comment or claim.

| Held reason | Meaning and what to do |
|---|---|
| `skipped` | you ran `cplat dispatch skip`; `resume <item>` lifts it |
| `needs-decision` | a run escalated; remove the label `needs-decision` from the issue (or `resume <item>` for a spec without issue) |
| `stuck` | the last unit ended twice without finishing; read its log, then remove the label or `resume <item>` |
| `claimed` | another person, branch, run or worktree holds the item |
| `blocked` | `blocked by #N` or `depends on #N` in the text and #N is open |
| `duplicate` | an open PR already closes the issue, or a spec tracks it |
| `needs-spec` | the issue is `tracked` and no approved spec tracks it yet |
| `needs-approval` | a draft waits for your approval (or, with `self`, has an open question or a failing spec check) |
| `ship-busy` | one ship unit runs at a time per repo |
| `stale` | `plan` only: the premise check found the issue already resolved on `main` |

**Order.** Items you pinned with `prioritize` come first; then the `priority` rules, each breaking ties of the rules before it. A spec
matches `label:pN` through its `priority: PN` and through the labels of an open issue it tracks.

**Premise check.** Before an issue takes a slot, one short read-only model call checks that it is still true on `main`. If it finds the
fix already merged (the evidence must be a commit on `main` or a merged PR, checked in code), `start` comments with the evidence, labels the
issue `stale-premise` and closes it. A reopened issue is never closed as stale again. A failed call counts as "still true".

## Units, claims and labels

Each unit runs `cplat headless` in its own worktree under `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/dispatch/<owner>__<name>/worktrees/`
on `fix/issue-<N>` or `feature/<spec id>`. Before it starts, the dispatcher claims the issue (label `in-progress`, assignee `@me`, a comment
that names `cplat dispatch`). Fix units are landed by the dispatcher itself (`cplat dispatch land`); ship units land themselves.

- A unit that ends without finishing is **restarted once** in the same worktree; a second time it is `stuck` and you get a `stuck` need
  with the log path.
- A unit that **escalates** gets the label `needs-decision` and a comment with the reason and the log path. Remove the label to let the
  dispatcher try again; the next unit reuses the worktree and branch, and a ship resumes its escalated run.
- A unit whose session only talks (`guard.loop_calls` model calls without a tool call or other progress within `guard.loop_minutes`) is
  stopped and **escalates** with cause `platform` and a reason that starts `looping:`; `status` lists it under `escalated today` as
  `escalated: looping`. The dispatcher passes the effective guard to every unit as `--loop-guard <calls>/<minutes>`
  ([ADR-115](adr/115-a-waiting-session-stops-and-its-wait-outlives-it.md)).
- Labels used: `triaged`, `needs-decision`, `stale-premise`, `in-progress`.

## The merge lock

Every merge into the default branch that cplat makes holds a machine-wide lock per repository ([ADR-089](adr/089-every-merge-into-main-holds-the-repo-merge-lock.md)),
with or without a policy file. Inside it, a branch behind `main` is updated with `gh pr update-branch`, its checks run again, and only then
does the merge happen with `--match-head-commit`. This is how parallel slots can land one after another without breaking `main`. While it waits,
cplat prints who holds the lock; past its timeout the command fails with `the merge lock of <repo> is held by ...`, which is no red check and
no fix round: run it again. With `serialize: [merge, e2e]` the lock covers the whole land phase, so only one PR at a time waits for its
end-to-end checks.

During a platform release every merge into that repository waits for the release hold instead: cplat prints
`waiting for the release hold of <repo>: release <version> since <time>` every minute, the wait has no timeout, and the merge continues by
itself when the hold is cleared or expires. `cplat dispatch status` shows it as `release hold:`, and `cplat platform hold --clear` lifts a
hold a release left at a confirmation stop.

## Budget

The day is your local calendar day, the month starts on the 1st. The mode is the one the policy states (`cost` by default) and never
changes on its own; `plan` and `status` only print a hint when another mode fits (readings of a subscription found while the mode is
`cost`, or an API key and no readings in mode `plan`). Both verbs show the mode's line: `cost today: $1.20 of $5.00` or
`plan usage: 5h 83 % (stop 80 %, resets 15:45) · week 41 % (pace 46 %, target 92 %, resets Mon 00:00) · reading 4 min old`.

### Mode cost

The dispatcher adds up the US dollar cost of every unit and of its own model calls (the reported cost of a call, else its tokens priced
from the platform's price table) since local midnight. At `budget.usd_per_day` no unit starts and no model call is made; running units go on
within their own budgets, and you get one `budget` need per day. With `budget.usd_per_month` the same holds for the sum since the 1st, with
one need per month. Starts continue after midnight, on the 1st or when you raise the limit. When a unit's usage is unknown, or its model has
no price in the table, no unit starts until it is known, and `status` names the unit.

`budget.tokens_per_day` still works as a deprecated cap in raw tokens, and `plan` and `status` warn about it with the cost of today. With
both keys, the first limit reached holds starts. Without `budget.usd_per_day`, `plan` shows the key as unset with the cost of the last 7 days.

### Mode plan

On a subscription the limits are shares of your plan, not dollars. The dispatcher reads them from the [usage sensor](#plan-usage-sensor):

- **Weekly target.** `budget.plan.weekly_target` (92 %) of the weekly limit is the target by its reset. The pace is the target times the
  elapsed share of the week. Ahead of the pace, or at the target, no unit starts. Up to 5 points behind the pace, at most 1 unit runs at a
  time; further behind, up to `slots`.
- **Window stop.** At `budget.plan.window_stop` (80 %) of the 5-hour window no unit starts. Running units always finish.
- **Stale reading.** A reading older than 30 minutes is estimated: the reading plus the tokens the dispatcher booked since then, divided by
  the tokens per percentage point of the readings of the last 7 days. A window whose reset has passed counts from 0 %. `plan` shows
  `source: estimate`. Without a reading, or without a calibration for a stale one, no unit starts and `plan` shows
  `held: plan usage unknown (install the sensor and open an interactive session)`.
- **Limit messages.** A unit that ends with the usage-limit message (a session or weekly limit) holds every start until the reset it names,
  or for 60 minutes without one, even when a later reading is lower. `plan` shows `source: limit`. Usage credits are never spent to go on.

`budget.usd_per_day`, `budget.usd_per_month` and `budget.tokens_per_day` are optional in mode `plan`; when set, they cap as in mode `cost`.
While a start is held, every candidate that would have taken a slot shows `held: <reason>` in `plan` and `status`; a paused or draining
dispatcher keeps its candidates ready.

## Plan usage sensor

The readings of mode `plan` come from the status line of your interactive Claude Code sessions, which passes the subscription's limits to
the sensor script. Install it once per machine:

```
cplat dispatch sensor install
cplat dispatch sensor remove
```

`install` copies the script to `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/usage/` and sets it as the `statusLine` of
`${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`. A status line you had before keeps working: the sensor runs it and prints its output
unchanged. `remove` restores the earlier status line (and leaves a status line you changed since the install alone). Running `install`
again only refreshes the copy.

Readings are written only while an interactive session runs and shows its status line: a headless unit does not write one. A reading
holds both windows with the time it was taken; input without a window leaves that window's last reading in place. Readings are kept for the
machine, not for a repo, because one subscription serves all repos.

## Filler work

Near the end of the weekly window, unused plan is spent on work that can wait. The filler window opens in the last 24 hours before the
weekly reset, when no limit above holds and no regular candidate is ready. Filler starts show `(filler)` and `plan` prints `filler: true`.
In this order:

1. **Filler-only candidates**, in priority order: the ones that match `budget.plan.filler_only` (by default P2 specs and `enhancement`
   issues). Outside the filler window they are held as `held: filler only`.
2. **`budget.plan.filler_tasks`**: each named command runs once per weekly window, in its own worktree. Use it for the benchmark, the
   mutation run or a journey; the commands differ per machine, so the list is empty by default.
3. **Retro drafts**, with `filler_drafts: true`: one run per proposal of the latest weekly retro issue that no spec or open pull request
   answers yet, at most 3 per weekly window, one at a time. Each opens a pull request with a draft spec that tracks the retro issue.
   The pull request stays open for you: the dispatcher never approves or lands it, even with `gates.approve_specs: self`.

## Verbs

All verbs take `--repo DIR` (default `.`); `plan`, `status`, `report` and `inbox` take `--json`.

| Verb | What it does |
|---|---|
| `cplat dispatch start [--once]` | run the loop (one cycle with `--once`); prints one line per action: `started`, `adopted`, `landing`, `done`, `escalated`, `restarted`, `stuck`, `closed ... as stale`, `approved`, `no starts: <why>` |
| `cplat dispatch plan` | read-only view: policy, tokens, candidates with verdict, mode, slot and premise |
| `cplat dispatch status` | local reads: loop, units with phase and tokens, queue, held, tokens |
| `cplat dispatch wait [--timeout S]` | exit 0 `IDLE`; exit 1 `ESCALATED:` or `RED:` for an event you have not seen; exit 2 `TIMEOUT` after 540 s by default, with the running units |
| `cplat dispatch report [--since D]` | per day: delivered, escalated, held, tokens (default 7 days) |
| `cplat dispatch inbox` | `cplat needs` for this repo: approvals, answers, escalations, triage, budget, stuck |
| `cplat dispatch pause [--drain]` | `pause` starts nothing new, and a running unit stops at its next stop (its session is let through and nothing is counted; `status` keeps `paused` and adds `paused_at`, the phase and last checkpoint); `--drain` lets running units finish and starts nothing new |
| `cplat dispatch resume [<item>]` | continue; with an item, lift its skip or hold only |
| `cplat dispatch slots <N>` | override the slots (1 to 10); a lower number stops nothing, it only delays starts |
| `cplat dispatch prioritize <item>` | pin an item first |
| `cplat dispatch skip <item> --reason <text>` | hold an item |

An item is `#<N>` or `issue-<N>` (the issue), or `spec-<N>`, a zero-padded number (`054`) or the spec id (the spec). A bare number is the spec or the open issue with that number, and is refused (exit 2, nothing changes) when it is both or neither, or when it matches a spec and the open issues cannot be read; write `spec-<N>` or `#<N>` then. Each verb prints what it acted on (`skipped: spec <id> (reason: ...)`, `prioritized: issue #<N>`). Steering takes effect within one cycle (60 seconds, sooner when a
unit ends) and survives a restart of the loop.

## Needs and notifications

`cplat needs` in a repo with `.platform/dispatch.yml` but no system lists the needs of that repo; inside a system nothing changes except two
new kinds: `budget` (the daily limit was reached) and `stuck` (a unit ended twice without finishing). Each cycle the dispatcher sends
notifications through the channels of `notify.yaml` ([console](console.md)). In a repo linked to a system the console notifies `approve`,
`answer`, `escalation` and `triage`, and the dispatcher only `budget` and `stuck`; elsewhere it sends all six. No event is notified twice.
Starts and completions are not notified. The recommended preset sets `triage` and `budget` to desktop and `stuck` to GitHub and desktop.

**Daily digest.** Once a day at `digest.at` of `notify.yaml` (default 09:00 local), outside quiet hours, every `slack` or `email` channel
that has an event set to `digest` gets the sections Delivered, Escalated, Held, Queue and Tokens since the last digest. An empty digest is
not sent.

## State

Everything the loop needs is rebuilt on start from `git worktree list`, the unit files in the worktrees' git dirs, live processes, the claim
comments on GitHub and the run store. The state file in `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/dispatch/<owner>__<name>/state.json` holds only
steering (pause, slots override, pins, skips, holds), the token ledger, the check cache, the GitHub snapshot (read at most every 300
seconds) and the history behind `report`. Logs are in `logs/<unit>.log` next to it. Killing the loop or rebooting loses no unit: run
`cplat dispatch start` again.

The committed allowlist of the repo decides what a fix session may do; a repo that does not allow `cplat pr open` stops at the PR and the unit
escalates with the session's last message.
