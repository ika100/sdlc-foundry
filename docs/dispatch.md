# The dispatcher: run the backlog in parallel slots

`cplat dispatch` (spec 167, [ADR-088](adr/088-a-dispatcher-schedules-orchestrator-runs-from-a-policy-file.md)) works through the backlog of a repo
so you do not start each run yourself. It reads a policy file, picks the issues and specs that are ready, and starts the existing
`/component:fix` and `/component:ship` runs, one per slot, each in its own git worktree. It is plain code: it calls a model only to check
whether an issue is still true on `main` and whether a spec's work splits into parallel tasks. Your decisions stay yours: you route issues in
triage, you approve specs (unless you let the dispatcher do it), you promote to prod.

## Turn it on step by step

1. **Look first.** `cplat dispatch plan` reads only. It works without a policy file and shows the defaults, every candidate with its verdict
   (`ready` or `held: <reason>`), the order, the slot each would take and the daily token usage of the last 7 days. It writes nothing to
   GitHub and creates no branch, worktree or claim.
2. **One slot, issues only.** Commit `.platform/dispatch.yml` with a token budget and leave `slots` at 1 and `sources` at `[issues]`:

   ```yaml
   slots: 1
   budget:
     tokens_per_day: 20000000
   ```

   Pick the budget from the 7-day hint of `plan`. Then run `cplat dispatch start --once` once and read the lines it prints, then
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
| `budget.tokens_per_day` | integer >= 1 | none: `start` and `resume` refuse without it |
| `budget.per_unit` | map of `minutes`, `invocations`, `reruns`, `cost` to a number > 0 or `off`; passed to `cplat headless` as `--budget KEY=VALUE` | `{}` (the budgets of [unattended delivery](unattended-delivery.md#budgets-and-repeated-failures)) |
| `sources` | non-empty subset of `issues`, `specs` | `[issues]` |
| `ready.labels` | labels an issue needs besides `triaged` | `[]` |
| `ready.exclude_labels` | labels that hold an issue besides `needs-decision` and `wontfix` | `[]` |
| `priority` | rules `label:<name>`, `spec-order`, `oldest` | `[label:bug, label:p1, spec-order, oldest]` |
| `gates.approve_specs` | `human`, `self` | `human` |
| `gates.merge` | `green-ci` | `green-ci` |
| `serialize` | subset of `merge`, `e2e`; must contain `merge` | `[merge]` |

A full file:

```yaml
slots: 2
budget:
  tokens_per_day: 20000000
  per_unit:
    cost: 20
sources: [issues, specs]
ready:
  labels: [bug]
  exclude_labels: [blocked]
priority: [label:bug, label:p1, spec-order, oldest]
gates:
  approve_specs: human
  merge: green-ci
serialize: [merge]
```

A mistake in the file exits 1 and names the key, for example `ERROR: .platform/dispatch.yml: slots: 11 is not allowed (allowed: ...)`;
nothing is started. Every verb that reads the file checks it; only `start` and `resume` need it to exist and to carry the budget.

## What is ready

A candidate is an open issue labelled `triaged` (`/issue:triage` adds it when it routes an issue to a fix or a spec), or a spec on `main`
with status `approved` or `building`, or a draft. A spec and the issues it tracks are one candidate: the spec. The verdict is `ready` or
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
- Labels used: `triaged`, `needs-decision`, `stale-premise`, `in-progress`.

## The merge lock

Every merge into the default branch that cplat makes holds a machine-wide lock per repository ([ADR-089](adr/089-every-merge-into-main-holds-the-repo-merge-lock.md)),
with or without a policy file. Inside it, a branch behind `main` is updated with `gh pr update-branch`, its checks run again, and only then
does the merge happen with `--match-head-commit`. This is how parallel slots can land one after another without breaking `main`. While it waits,
cplat prints who holds the lock; past its timeout the command fails with `the merge lock of <repo> is held by ...`, which is no red check and
no fix round: run it again. With `serialize: [merge, e2e]` the lock covers the whole land phase, so only one PR at a time waits for its
end-to-end checks.

## Budget

The day is your local calendar day. The dispatcher books the tokens of every unit and of its own model calls to today's ledger. At
`budget.tokens_per_day` no unit starts and no model call is made; running units go on within their own budgets, and you get one `budget` need.
Starts continue after midnight or when you raise the limit above the usage. When a unit's usage cannot be read, no unit starts until it is
known, and `status` names the unit.

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
| `cplat dispatch pause [--drain]` | `pause` stops units at the next checkpoint and starts nothing; `--drain` lets running units finish and starts nothing new |
| `cplat dispatch resume [<item>]` | continue; with an item, lift its skip or hold only |
| `cplat dispatch slots <N>` | override the slots (1 to 10); a lower number stops nothing, it only delays starts |
| `cplat dispatch prioritize <item>` | pin an item first |
| `cplat dispatch skip <item> --reason <text>` | hold an item |

An item is `#<N>` (issue) or a spec (`<NNN>`, `spec-<NNN>` or the spec id). Steering takes effect within one cycle (60 seconds, sooner when a
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
