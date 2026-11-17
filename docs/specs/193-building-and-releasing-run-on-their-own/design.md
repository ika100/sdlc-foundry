# Design — 193 Building and releasing run on their own and interrupt only to ask

Builds on spec 192's contract ([192 design](../192-the-delivery-process-guides-the-person/design.md)): every screen is
printed by `cplat next`, has the same three parts (bar, what is happening, `Your part:`), the same 80-column, ASCII,
list-of-5 and plain-word rules, and the same `--json` document (schema 1; this spec only adds keys). Everything not named
here stays as spec 192 says.

## Decisions

- **`cplat next` stays read-only; every change is a `cplat dispatch` verb that an option's `steps` runs** (AC-192.1, A6,
  A7). New verbs: `build`, `start --detach`, `budget`, `setup`, `answer`; `resume <item>` also lifts the
  `needs-decision` label. The screens never write; the build loop is a separate detached process (A1).
- **The queue comes from a read-only twin of `cplat dispatch plan`**: `dispatch_cycle.preview(repo, policy)` runs the
  same `_judge` and ship-busy rule as `evaluate` on a snapshot read with `fetch=False` (cached when younger than 300 s),
  without agent calls and without booking tokens, so its order is the order of `plan`'s candidates (AC-193.1). A ship
  that waits for an earlier one keeps its place with `after` (A2) instead of a held reason.
- **A build is a recorded span.** `cplat dispatch build --slots N` writes `state.json` `build = {"started_at", "slots"}`
  (a new build replaces the old record). "This build" is every dispatcher event at or after `started_at`; the end of
  build, its totals and the last screen are computed from it (AC-193.6, AC-193.8, A11). No other state is kept.
- **Today's budget raise is local state, never the policy file** (AC-193.5, user decision 2026-11-12):
  `steering.budget_today = {"day", "tokens", "at"}` overrides `budget.tokens_per_day` for that local day only; every
  reader of the limit goes through `dispatch_budget.limit_of(policy, slug)`. ADR: created in the plan's t10 with
  `cplat adr add a-days-budget-raise-lives-in-local-state --decision "A raise of the run queue's daily token budget holds for the local day in the dispatcher state and never changes the committed policy file"`.
- **An answer is an assumption the person decided; the criteria hash decides what happens next** (AC-193.4).
  `cplat dispatch answer` adds `Decided by the user (<date>, …)` to the spec's Assumptions in the unit worktree. When
  the spec's acceptance-criteria hash equals the approved one on `origin/main`, the answer is recorded in the Changelog
  as its approval and the item goes on; when the session changed a criterion first (an answer the person typed that asks
  for it), the spec goes back to `draft` with a draft PR, which is spec 192's Spec step. A fix item has no spec: the
  answer becomes a comment on its issue.
- **Decision or not** (AC-193.4 vs AC-193.5): a stop is a decision when its unit ended `escalated` with cause
  `decision`; `stuck`, a `red` event, any other cause and the budget need are failures. Stops of runs that are not
  dispatcher units keep spec 192's options and get the `What happened:` lines only.
- **Ship questions keep their alternatives**: `ship escalate` stores `{"text", "suggested", "options"}` per question
  (today only `suggested`), so the screen offers the suggested answer and one alternative.
- **Typed values travel as `input`** (A4, AC-193.5): an option with `input` makes the session ask for a value and put it
  in place of `<name>` in the option's `steps`, `then` and `undo`. So the set-up recommends no number when the 7-day
  hint has none, and "Raise today's budget" asks for the number before its confirmation screen.
- **Release step per shape** (A9): platform reads `docs/changelog.d/`, every other shape but `gitops-app` reads the
  first-parent subjects since the last `v*` tag (squash merges carry the PR title). Spec 192's release item extends from
  `platform`/`library-python` to every component shape.
- **Deployable repos step through Staging, Release, Prod in that order, one step at a time** (AC-193.7, user decision
  2026-11-15): `/component:release` tags the commit staging runs (specs 106, 138), so a manual staging comes before
  the release and prod after it. With `promote: after-dev-smoke` Staging is done by itself (A10): the screen offers
  Release, then Prod. Release and promote keep their own checks and gates; this spec only orders the choices.
- **One promote item per component and version**: the new promote items use spec 192's id `promote:<component>:<version>`,
  so a prod item that `needs.json` already carries (system scan) and the repo's own read collapse into one.
- **Ids**: an item is `#<n>` for an issue and `spec <n>` for a spec (AC-192.9), also in `starts after <ref>` (A2) and in
  the event lines; the spec writes `#<n>` for both.
- **The event list keeps the newest 5 lines** with `  and <n> earlier` first, because the newest events matter in a log
  (spec 192's "and <n> more" is written for lists read from the top).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/dispatch_state.py` | `raise_today`, `reset_today`, `budget_today`; `open_build`, `build_of` | changed |
| `scripts/cplat/dispatch_budget.py` | `limit_of(policy, slug=None)`, `reached(usage, policy, slug=None)`; `budget_need` with the raise | changed |
| `scripts/cplat/dispatch_view.py` | `tokens_doc` with `raised`, `starts_doc` with the raise | changed |
| `scripts/cplat/dispatch_cycle.py` | the raise in `_why_not`/`_reached`; `preview(repo, policy)` | changed |
| `scripts/cplat/dispatch_setup.py` | the policy text from the 7-day hint; branch, commit, PR, merge on green, fast-forward | new |
| `scripts/cplat/dispatch_answer.py` | the answer into the spec (or the issue), the hash rule, resume or back to draft | new |
| `scripts/cplat/ship.py` | `escalate` keeps each question's options | changed |
| `scripts/cplat/dispatch.py` | verbs `build`, `start --detach`, `budget`, `setup`, `answer`; `resume <item>` lifts the label | changed |
| `scripts/cplat/nextbuild.py` | read-only build state: queue, estimates, tokens, events, running, stops, totals, release sections, deploy steps, flow | new |
| `scripts/cplat/nextstate.py` | calls `nextbuild`; group `build`; release items for every component shape; promote items | changed |
| `scripts/cplat/nextbuildscreen.py` | the text of the build start, set-up, progress, stops, end of build, release, promote and last screens | new |
| `scripts/cplat/nextscreen.py` | hands these cases to `nextbuildscreen`; `Also waiting` words for build and release | changed |
| `scripts/cplat/nextbuildquestions.py` | the questions and options of those screens | new |
| `scripts/cplat/nextquestions.py` | hands the build, stop, release and promote groups to `nextbuildquestions`; `input`, `other` | changed |
| `scripts/cplat/nextcmd.py` | `--watch`, `--after`, new `--show` values, `judge_items`, `build` key, the `how` additions | changed |
| `plugins/platform/commands/next.md` | the judgement for `judge_items` | changed |

## Contract

### `cplat dispatch` verbs

All take `--repo DIR` (default `.`); output is plain text lines; a refused input exits 2 with `ERROR: <why>` on
stderr; a git or GitHub failure exits 1 with the failing step.

```
cplat dispatch build --slots N
cplat dispatch start --detach
cplat dispatch budget [--today N | --reset-today]
cplat dispatch setup (--show [--json] | --tokens-per-day N)
cplat dispatch answer <item> --answer TEXT [--question K]
cplat dispatch resume <item>
```

- **`build --slots N`** (N 1..10, AC-193.1, A1): needs the policy file with a budget (else exit 2, the `dispatch start`
  message). Sets the slots (`set_slots`, not the file), clears a `pause`/`drain`, writes the build record, then does
  what `start --detach` does. Prints `slots: <N>`, `build started at <HH:MM>`, the `start --detach` line, and
  `Undo: cplat dispatch pause --drain`.
- **`start --detach`**: when the loop lock is held, prints `running: the build loop runs already (pid <pid>)` (adopted);
  else spawns `cplat dispatch start --repo <repo>` in a new session (stdin closed, output appended to
  `<state base>/logs/loop.log`), waits up to 5 s for the loop lock and prints `started: the build loop (pid <pid>), log
  <path>`; no lock after 5 s exits 1 with the log path. Closing the session never stops it.
- **`budget`**: no flag prints `budget for <day>: <limit> tokens` (plus ` (raised for today; the policy says <p>)`).
  `--today N`: N must be an integer above today's effective limit, and the policy must set a budget (else exit 2);
  writes `steering.budget_today = {"day": <today>, "tokens": N, "at": <stamp>}` and prints `budget for <day>: <N>
  tokens (the policy says <p>; back to it at midnight)` and `Undo: cplat dispatch budget --reset-today`. A raise of an
  earlier day is ignored by every reader. `--reset-today` removes it and prints `budget for <day>: back to <p>`. No
  committed file changes.
- **`setup`** (AC-193.2, A4, A5): the file, byte for byte (`<N>` with thousands written plainly, e.g. `21000000`):

  ```yaml
  # The run queue's policy (docs/dispatch.md), written by /platform:next.
  budget:
    tokens_per_day: <N>
  sources: [issues, specs]
  gates:
    approve_specs: human
  ```

  `N` from the hint: the highest known day of `dispatch_budget.history_hint` (days with `null` left out) rounded up to
  the next 1,000,000; no known day above 0 means no suggestion. `--show` prints the file (with `<your number>` for a
  missing suggestion); `--show --json` prints `{"file": "<text>", "tokens_per_day": <N|null>, "hint": [<the hint>]}`.
  `--tokens-per-day N` (N ≥ 1): refuses (exit 2) when the file exists; creates branch `chore/dispatch-setup` from
  `origin/main`, writes the file, commits signed off (`chore(dispatch): set up the run queue policy`), pushes, opens a
  PR (body names `/platform:next`), waits for green CI and merges as `cplat pr wait --merge` does, then fast-forwards the
  local `main` when it is checked out and clean (else prints `the policy is on main; switch to main to build` and exits
  1). Prints `merged: PR #<m>`. A red check exits 1 with the `pr wait` lines and leaves the PR open.
- **`answer <item> --answer TEXT [--question K]`** (AC-193.4): the item's unit (`<state base>/worktrees/<repo>-<key>`)
  must have ended `escalated` (else exit 2: `<ref> has no stop to answer`). The question is question K (1-based) of the
  unit's ship state (the live one or the newest archive in the worktree's git dir), else the unit's reason.
  - Spec item: appends to `## Assumptions` of `docs/specs/<id>/spec.md` in the worktree
    `- Decided by the user (<YYYY-MM-DD>, stop of <unit>): <question> Answer: "<TEXT>"`; records `answers[K]` (or
    `answers["reason"]`) in the unit file. Then compares the spec's `ac_hash()` with that of
    `git show origin/main:docs/specs/<id>/spec.md` (missing on main: the spec at the worktree's `HEAD` before the edit).
    - Equal: Changelog line `answer to the stop of <unit> approved by the user: "<TEXT>"` (`spec.add_changelog`), commit
      signed off `docs(spec): answer to the stop of <spec id>`. Once every question of the stop has an answer: drop the
      hold (`resume_item`), remove `needs-decision` from the spec's open tracked issues, print `answered: spec <n>; it goes
      on from <phase>`; otherwise print `answered 1 of <q>: spec <n> waits for the other answers`. Then
      `Undo: git -C <worktree> revert --no-edit <sha>`.
    - Not equal: `spec.set_status(spec, "draft", "the answer changes criteria")`, Changelog line `answer of the user
      changes criteria: "<TEXT>"; back to approval`, commit, `spec_pr.publish` (push and the draft PR with the spec
      marker), drop the hold; print `back to approval: spec <n> (PR #<m>)`. The dispatcher builds only approved specs,
      so the item waits in the Spec step of `cplat next`.
  - Issue item: `gh issue comment <n>` with `<!-- cplat-dispatch-answer -->`, `Answer of the person to the stop of
    <unit>: "<TEXT>"`; removes `needs-decision`; drops the hold; prints `answered: #<n>`.
- **`resume <item>`**: as today, and also removes `needs-decision` from the item's open issues (a fix: its issue; a
  spec: its tracked issues), so "Try again" lets the dispatcher start it again (A7). Prints one `label removed: #<n>`
  line per issue.

### `dispatch_cycle.preview(repo, policy) -> list[dict]`

The ready candidates and the ship-busy holds of `plan`, in `plan`'s order, numbered from 1:
`{"n", "key", "item", "ref", "kind": "fix"|"ship", "title", "spec": <spec id|null>, "tracks": [int], "after": <ref|null>}`.
`after` is the ref of the running ship unit or of the earlier ship candidate it waits for. Writes nothing (no
`state.json` change, no ledger booking, no agent call, no GitHub write).

### `cplat next` additions

```
cplat next [... spec 192 options ...] [--watch S --after SEQ]
           [--show details:<QID> | --show log:<key> | --show raise-budget:<N> | --show assumptions]
```

- `--watch S --after SEQ`: before printing, waits (polling the local state every 2 s, read-only) until a dispatcher event
  with `seq` > SEQ exists, the repo's `needs.json` changed, nothing runs any more, or S seconds passed; then prints as
  without it. Exit 0.
- `--show log:<key>`: part 2 is `Log: <path>` (no log recorded: `No log is recorded for <ref>.`); the item's question
  without "Show the log".
- `--show raise-budget:<N>`: the confirmation screen of "Raise today's budget" (below).
- `--judgement FILE` also reads `{"items": {"<key>": {"you_get": str, "what_happened": str, "why_ask": str}}}`
  (`key`: `issue-<n>` / `spec-<NNN>`); the spec 192 `specs` key is unchanged.

`--json` document, new keys (all others as spec 192):

```json
{
  "build": null,
  "judge_items": [{"key": "spec-189", "ref": "spec 189", "title": "...", "text": "<≤600 chars>",
                   "wants": ["you_get"]},
                  {"key": "issue-712", "ref": "#712", "title": "...", "text": "<stop reason, ≤600 chars>",
                   "wants": ["what_happened", "why_ask"]}]
}
```

- `judge_items`: each queue entry and each running item without a `you_get`, and each dispatcher stop without
  `what_happened` (decision stops also `why_ask`); `judgement_wanted` is true when `drafts` or `judge_items` is not
  empty and no `--judgement` was given.
- A question may carry `"input": {"name": "tokens", "prompt": "<text>"}` on an option and `"other": {"steps": [<str>],
  "spec": "<path>"|null}` on the question; both are absent when unused.

`build` (null in a repo where no queue, build or flow exists):

```json
{"policy": true,
 "setup": null,
 "queue": [{"n": 1, "key": "issue-712", "ref": "#712", "kind": "fix", "title": "...", "you_get": "...",
            "after": null, "minutes": 25, "tokens": 1200000}],
 "total_minutes": 95, "need_tokens": 6800000,
 "tokens": {"used": 4200000, "limit": 20000000, "raised": false},
 "loop": {"running": true, "pid": 4711}, "slots": 2, "paused": null,
 "current": {"started_at": "2026-11-15T09:10:00", "slots": 2},
 "events": [{"seq": 12, "time": "09:12", "kind": "started", "ref": "#712", "what": "...", "pr": null}],
 "last_seq": 12,
 "running": [{"key": "spec-189", "ref": "spec 189", "what": "...", "step": "building"}],
 "ended": false,
 "totals": {"wall_minutes": 190, "tokens": 12400000, "questions": 2},
 "deploy": {"component": "shop-api", "staging": "manual", "step": "staging", "version": null, "head": "<sha>"},
 "flow": {"done": false, "issues_closed": [712], "released": "v5.23.0", "your_minutes": 14.0,
          "parked": [{"ref": "spec 190", "reason": "stopped by you"}]}}
```

- `setup` (no policy file only): `{"tokens_per_day": <N|null>, "file": "<text of setup --show>"}`; the queue is then
  computed with the set-up values.
- `queue`: `preview`; `you_get` from the judgement, else the title (A6); `minutes`/`tokens`: the median of at least 3
  comparable runs, else null. Comparable (A3): `state.json` `history` entries of this repo with outcome `done`, the same
  kind, a `started_at` and `ended_at` (minutes) and an integer `tokens`. Minutes round to 5 (at least 5), tokens to
  100,000 (at least 100,000).
- `total_minutes`: the sum when every entry has `minutes`, else null; `need_tokens`: the sum when every entry has
  `tokens`, else null.
- `tokens`: today's used, `limit_of(policy, slug)`, `raised` when a raise of today applies; `limit` null without a budget.
- `events`: the dispatcher events at or after `current.started_at`, oldest first; `time` is `at[11:16]` (local).
- `ended`: `current` exists, at least one `started` event is in it, no unit is running and `queue` is empty.
- `totals` (only when `ended`; a value that cannot be read is left out): `wall_minutes` from the first `started` to the
  last `done` event; `tokens` the sum of `counted[unit]` of this build's units; `questions` the sum of `questions` of
  the AC-192.10 person lines whose `spec`/`issue` is an item of this build (whole store and buffer).
- `deploy` (deployable component shapes only, else absent; null when the gitops-app cannot be read):
  `staging` is `manual` or `after-dev-smoke` (`model.staging_promotion` of the component, found as `staging._find`
  finds it); `step` is the first that applies of `staging` (manual, and the staging instance does not run the head of
  `origin/main`, resolved as `staging.resolve`), `release` (changes since the last `v*` tag), `prod` (the newest `v*`
  tag is not what prod runs), else null. With `after-dev-smoke`, `staging` is never a step (A10).
- `flow` (only when `current` exists): `issues_closed` — the fix issues and the tracked issues of this build's specs
  that GitHub shows closed; `released` — the newest `v*` tag created after `current.started_at` (else null);
  `your_minutes` — the sum of `minutes` of the person lines of this build's items; `parked` — `steering.skipped`;
  `done` — `ended`, `released` set, nothing waits, and in a deployable repo `deploy.step` is null.

Stop items (stopped group) gain `stop`:
`{"kind": "decision"|"failure"|"budget", "key", "ref", "branch", "log", "phase", "worktree", "spec_path",
"tried": ["restarted once", "check rerun once"], "questions": [{"text", "options"}], "answered": [int],
"asked_minutes": int}` — `null` for a stop that is not a dispatcher unit's (its spec 192 options stay). `tried`:
`restarted once` when the unit's `starts` ≥ 2, `landing restarted once` when `land_starts` ≥ 2, `check rerun once` for a
`red` event; `asked_minutes` from the item's `since` (A8). A ship state written before this spec has no `options`: the
question then has only its `suggested` answer.

Release items gain `consequence.sections = {"Fixed": [str], "Added": [str], "Changed": [str]}`: platform — per
fragment its bold summary without `**` and the final `.` (section from the file name); other component shapes — per
first-parent subject since the last `v*` tag (not `comprelease.FOLLOW_UP`), `fix…:` → Fixed, `feat…:` → Added, else
Changed, the subject as written. Promote items (deployable component repos): id `promote:<component>:<version>`
(`<version>` the head sha for staging), `kind: promote`, `object.component`, `object.version`, `consequence.env`
(`staging` | `prod`), `command` `/instance:promote <component> --to staging` or
`/instance:promote <component> --to prod --version <tag>`. A `needs.json` item with the same id is kept and gains
`consequence.env: prod`.

### Groups and screens

Group order: `stopped`, `specs`, `issues`, **`build`**, `release`. The `build` group holds one item
`build:<repo>` (`kind: build`) when `queue` is not empty, nothing runs and the loop does not run (or is paused or
draining). In `release`, a deployable repo shows only the item of `deploy.step` (staging promote, release, or prod
promote), so the person meets Staging, Release and Prod in that order (AC-193.7); other shapes show the release item.
`Also waiting` words: build → `Build: <n> ready`, release → `Release: <n> changes ready` (AC-193.7); other kinds as
spec 192.

Formats: `<t>` as spec 192 (`45 min`, `1 h`, `1 h 35 min`); tokens with thousands separators (`4,200,000`); ages
`<m> min`, `<h> h <mm> min` (zero-padded), `<d> day(s)`.

**Build start** (AC-193.1) — part 2:

```
3 items are ready to build.
  1. <you get> (#712), about 25 min
  2. <you get> (spec 188), about 1 h 10 min
  3. <you get> (spec 189)
     starts after spec 188: one spec builds at a time
Tokens today: 4,200,000 of 20,000,000
```

`, about <t>` only with `minutes`; `Total: about <t> of work.` before the tokens line only with `total_minutes`;
`; this queue needs about <n>` appended to the tokens line only with `need_tokens`; ` (raised for today)` after the limit
when raised. `Your part: choose how many items build at once.`

**Set-up** (AC-193.2) — part 2: the queue lines, then `Building needs a run policy; I can set one up.`;
`Your part: set up the build, or leave it for now.` Its details sub-screen prints `It commits this file through a pull
request that merges on green CI:`, the file indented two spaces, and the actions.

**Progress** (AC-193.3) — when dispatcher units run and nothing waits (replaces spec 192's runs lines for them):

```
Building 2 items, two at a time.
  09:12 started #712 <you get>
  09:40 merged #712 (PR #760)
  09:40 finished #712
  09:41 started spec 189 <you get>
Building now:
  <you get> (spec 189): building
```

Event lines: `started <ref> <you get>`; `done` → `merged <ref> (PR #<m>)` when it has a PR, then `finished <ref>`;
`escalated`/`red`/`stuck` → `stopped <ref>`; `stale` → `closed <ref>: already fixed on main`. No agent output.
`Your part:` as spec 192's runs case.

**Stops** — first line as spec 192 (`<n> run(s) stopped and wait for you.`), then per stop:

```
  ! <what> (spec 189)
    What happened: <judgement, else the stop reason, one line>
    Why I ask: <judgement, else the first unanswered question, else "it needs your decision to go on">
    While you think:
      <what> (#712) keeps running.
      <what> (spec 190) waits for this one.
    asked 2 h 05 min ago
```

`While you think: nothing else runs.` when neither exists. Failures replace the two middle fields with `Already tried:
<tried joined by ", ">` (`nothing yet` when empty) and have no `While you think`. Budget: `What happened: The day's token
budget is reached: <used> of <limit>.` and `Already tried: nothing yet`. The age line only from 5 minutes on.

**Raise confirmation** (`--show raise-budget:<N>`) — part 2: `Tokens today: <used> of <limit>.`, `This queue needs about
<n>.` (only with `need_tokens`), `New budget for today: <N>.`; an N that is not an integer above the limit gives `<N> is
not above today's budget of <limit>.` instead of the last line.

**End of build** (AC-193.6) — the release group while `build.ended` and no tag after `current.started_at`, preceded by:

```
The build is done.
Wall time: 3 h 10 min
Tokens: 12,400,000
Questions to you: 2
Ready to release:
  Fixed
    <line> (#755)
  Added
    <line>
```

Empty sections are left out, each section cut at 5. Without `ended` the release group shows `A release is ready: <n>
change(s) since <tag>.` and `Ready to release:` with its sections. In a deployable repo whose `deploy.step` is
`staging`, the end of build shows the same head and then the staging lines instead of the release ones.
Promote: `<component> <version> can go to staging.` (`<version>` the short head sha) / `<component> <version> can go to
prod.`; `Your part: promote, or hold it back.`

**Last screen** (AC-193.8) — when `flow.done` and nothing waits or runs (replaces spec 192's nothing lines):

```
Issues closed: #712, #713
Released: v5.23.0
Your time: 14 min
Nothing is waiting for you.
Parked: spec 190 (stopped by you)
New issues show up here in /platform:next
```

`Issues closed: none`, `Parked: none`; `Your time` left out when unreadable, minutes rounded. `Your part: nothing. You
can walk away.`

### Questions

| Screen | Question id / header | Options in order (`steps`, `then`, undo) |
|---|---|---|
| Build start | `build` / `Build` | "Two at a time" (`cplat dispatch build --slots 2`), "One at a time" (`… --slots 1`), "Show details", "Not now" (= Later of `build:<repo>`) |
| Set-up | `build-setup` / `Set up` | "Set up and build" (`cplat dispatch setup --tokens-per-day <N>`; no N: `input` `tokens`, steps with `<tokens>`), "Show details", "Not now" |
| Progress | `watch` / `Building` | "Keep watching" (then: `cplat next --json … --watch 540 --after <last_seq>`), "Leave it running" (nothing), "Stop after the running items" (`cplat dispatch pause --drain`; undo `cplat dispatch resume`) |
| Decision stop | item id / `Decide` | the suggested answer and one alternative (`cplat dispatch answer <key> --question <k> --answer "<answer>"`), "Show details", "Stop this item (its work stays on branch <branch>)" (`cplat dispatch skip <key> --reason "stopped by you"`; undo `cplat dispatch resume <key>`); `other.steps` = the answer step with `<answer>`, `other.spec` = `spec_path`. Without questions: "Let it go on" (`cplat dispatch resume <key>`), "Show details", "Stop this item …"; `other` without `--question` |
| Failure | item id / `Stopped` | "Try again" (`cplat dispatch resume <key>`), "Park it" (`cplat dispatch skip <key> --reason "parked: <reason, ≤60>"`; undo `cplat dispatch resume <key>`), "Show the log" (then `--show log:<key>`), "Show details" when Try again removes a label |
| Budget | item id / `Budget` | "Wait for tomorrow" (nothing), "Raise today's budget" (`input` `tokens`; then `--show raise-budget:<tokens>`), "Park it" (`cplat dispatch pause --drain`; undo `cplat dispatch resume`) |
| Raise confirmation | `raise-budget` / `Raise` | "Raise to <N>" (`cplat dispatch budget --today <N>`; undo `cplat dispatch budget --reset-today`), "Keep the budget" (nothing); invalid N: "Try another number" (`input`, then `--show raise-budget:<tokens>`), "Keep the budget" |
| Release / end of build | item id / `Release` | "Release now" (`/platform:release` or `/component:release`), "Show details", "Collect more" (= Later) |
| Promote | item id / `Staging` or `Prod` | "Promote to Staging" / "Promote to Prod" (`item.command`), "Show details", "Not now" (= Later) |

Actions (for "Show details" and `cannot_undo`): build — `the run queue starts: claims, pull requests, merges on green
CI`, `<repo> main`, `cplat dispatch pause --drain`, plus cannot-undo `each merge (a revert pull request takes it back)`;
set-up — `pull request with .platform/dispatch.yml`, `<repo> main`, null; answer (spec) — `answer commit`,
`docs/specs/<id>/ on <branch>`, `printed by the command`, and per tracked issue `label removed`, `<repo>#<n>
needs-decision`, `gh issue edit <n> -R <repo> --add-label needs-decision`; answer (issue) — `comment`, `<repo>#<n>`,
null, and the label action; try again — the label actions; release and promote — as spec 192.

`record` refs: build — every queue entry; stop questions — the item; all others none (spec 192).

### The `how` additions (appended to `nextcmd.HOW`; spec 192's sentences stay verbatim)

An option with `input`: before running it, ask its `input.prompt` and wait for the typed value; put it in place of
`<name>` in its `steps`, `then` and `undo`. An answer the person types for a question with `other`: when it changes an
acceptance criterion, change that criterion in `other.spec` as asked first; then run `other.steps` with `<answer>`
replaced by the typed text, and go on as after an option. Print the output of a `cplat dispatch` step whole.
