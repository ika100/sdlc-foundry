# Design — 131 Runs that finish on their own

## Decisions

- **One session per unit, supervised by `cplat headless`.** The unit list and the checkpoints live in a new module
  `units.py` and a per-worktree state file `<git dir>/cplat-units.json` (ADR-051). The loop that starts the unit sessions
  lives in a new module `supervisor.py`. `headless.py` keeps the CLI, the preflight and the legacy resume loop of spec 070,
  which is used for every prompt that is not `/component:ship` or `/component:build`. A checkpoint is detected from git
  and the ship state by fixed rules. The model never declares it. ADR:
  [ADR-075](../../adr/075-an-unattended-ship-runs-one-session-per-unit-saved-at-checkpoints.md).
- **Permissions are granted per session, never written.** A new module `preflight.py` computes the run allowlist and the
  refused rules for the command, checks them against every settings layer and the environment before the first session,
  and passes them as `--allowedTools` and `--disallowedTools` to each session. cplat's own bundles (`cplat pr open`) read
  the same allowlist from `CPLAT_RUN_ALLOWLIST` (amends ADR-037). ADR:
  [ADR-076](../../adr/076-an-unattended-run-gets-its-permissions-per-session-from-a-checked-run-allowlist.md).
- **Budgets scale with the plan, and verification gets one grace.** The ledger keeps one *part* per spec of the run.
  The limits are the sum of the parts, raised and never lowered when a plan appears. The grace extends every limit once,
  only while verification is the one unit left. ADR:
  [ADR-077](../../adr/077-budgets-scale-with-the-plan-and-verification-gets-one-grace.md).
- **The subagent cost is fixed where it is read.** `runs_usage` marks a usage read incomplete whenever it stopped early or
  could not read a transcript, and `budget` treats an incomplete read as `unknown`. A transcript file that has not changed
  is not parsed again, so the 3 s peek of a budget check no longer runs out before the subagent files. Cause (#324): the
  peek deadline stopped the read after the main transcript, and the partial sum was reported as the cost.
- **Unit mode in the commands is one shared reference.** `/component:ship` and `/component:build` accept `--unit <unit>`,
  set only by the supervisor. Both read `plugins/component/references/unit-mode.md`. Attended runs (no `--unit`) are
  unchanged (Non-goals).
- Choices the spec leaves to the design:
  - The grace for `reruns` is `ceil(20 %)` with no floor.
  - A `budget:` value in the settings files replaces the floor of the formula (the `15`, `180`, `60`) and the reruns
    default. `off` turns the limit off.
  - The `land` unit of `/component:build` opens the PR (build Phase 7), because a build never merges.
  - `--max-minutes` has no default in unit mode, so the budget's `minutes` bounds the run. The legacy loop keeps 240.
  - `cplat pr wait --merge` is a merge outside the land step, so it is refused in an unattended session.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/units.py` | unit ids and order, completion rules, checkpoints, validity, 5.5 derivation, status rows, the unit Stop-hook answer, the stall count, `only_verification_left` | new |
| `scripts/cplat/supervisor.py` | the unit loop: one `claude -p` session per unit, the summary lines, the stall escalation, rescale at the plan checkpoint, the grace at the verification start, ship finish after land | new |
| `scripts/cplat/preflight.py` | the run allowlist, the refused rules, the settings-layer matcher, the five checks, `preflight failed:` lines | new |
| `scripts/cplat/headless.py` | the CLI: unit mode or legacy loop, the preflight before the first session, `--allowedTools`/`--disallowedTools`/env on every session, `--max-runs` and `--max-minutes` defaults, the preflight record | changed |
| `scripts/cplat/budget.py` | parts, the plan formula, rescale, the limits line with T and C, the $0 rule, an incomplete cost is `unknown`, the grace | changed |
| `scripts/cplat/runs_usage.py`, `scripts/cplat/transcripts.py` | an incomplete read means `cost_complete: false`; the parse cache for unchanged transcript files | changed |
| `scripts/cplat/ship.py` | the unit gate in `gate`, units in `status`, `ship unit`, rescale on `phase build`, the grace-aware check on `phase`, ending the grace on `phase pr`, archiving the units file on `finish` | changed |
| `scripts/cplat/runs.py` | `runs end --outcome escalated` inside a unit session also escalates the units file | changed |
| `scripts/cplat/pr_open.py` | `pr_allowed` also accepts the rules of `CPLAT_RUN_ALLOWLIST` | changed |
| `scripts/cplat/appship_state.py`, `scripts/cplat/appship_sched.py` | product ship: placeholder budget parts per plan repo; the preflight of a repo at `repo start` | changed |
| `scripts/cplat/runs_report.py` | the "Unattended ships (spec 131)" section of `cplat platform runs report` | changed |
| `plugins/component/references/unit-mode.md`, `commands/ship.md`, `commands/build.md`, `plugins/system/commands/ship.md`, `plugins/shared/hooks/hooks.json` | unit mode, the Stop hook for unit sessions, the repo preflight note | new / changed |

## Contract

### Units (AC-131.1, AC-131.3, AC-131.7, AC-131.19)

**Ids.** `plan`, `red-tests`, `task:<task id>` (one per task of the plan, gitops tasks included), `verification`, `land`.

**Order.** `plan`, `red-tests`, then the task units level by level as `spec.topo_levels` gives them, with the plan's own task
order inside a level (not the sorted ids), then `verification`, `land`. The list is rebuilt from the plan every time the
units file is loaded. Stored entries are matched by id, and an entry whose task left the plan is dropped. Before the plan
exists the list is `plan`, `red-tests`, `verification`, `land`.

**Feature head `B`.** `refs/heads/feature/<spec id>` when it exists, else `HEAD`. Every rule below reads the **committed**
tree of `B` (`git show B:<path>`), never the working tree.

**Completion rules** (`units.detect(repo, command, spec_id, unit) -> commit | None`, where `command` is `ship` or `build`):

| Unit | Complete when | Checkpoint commit |
|---|---|---|
| `plan` | `docs/specs/<id>/plan.md` is in `B` and `spec.check_plan` reports no error for it (the `spec_hash` matches) | `B` |
| `red-tests` | `cplat spec trace <id>` passes, and `git log --grep 'acceptance tests for' <merge-base main B>..B` finds a commit | `B` |
| `task:<t>` | `plan.md` in `B` has `done: true` for `<t>` | `B` |
| `verification` | the spec's `status` in `B` is `done` and `spec.verification_result` is `pass`. For `ship`, also the ship phase is `pr`, `land`, `deploy` or `done` | `B` |
| `land` | `ship`: the ship phase is `done`. `build`: `gh pr list --head feature/<id> --state all --json state` has an `OPEN` or `MERGED` PR, and `origin/feature/<id>` equals `B` | `ship`: `merge_sha`, else `B`. `build`: `B` |

**Validity (AC-131.3).** A checkpoint of a unit before `land` counts while `git merge-base --is-ancestor <commit> B`
succeeds. A checkpoint that no longer counts is reset to `open` (sessions and stalls kept). Once the ship state has a
`merge_sha`, or its phase is `deploy` or `done`, the checkpoints before `land` are not checked again: the squash merge
deletes the branch.

**`units.prepare(repo, command, spec_id) -> dict`** runs at every start and resume of the supervisor and in this order:
load the file (or create it), derive it if needed (below), reset `running` to `open`, check validity, then run `detect`
on every unit that is not `done` and record each complete one as a checkpoint. A unit that is complete is never started
(it is "skipped").

**Derivation of a 5.5 run (AC-131.19).** This applies when the ship state of the spec exists, is not `done` or escalated,
and the units file is missing or belongs to another spec. Each unit counts as checkpointed at `B` by this rule:

| Ship phase | Checkpointed units |
|---|---|
| `plan` | none |
| `build` | `plan`, and every `task:<t>` with `done: true` in `B` |
| `pr`, `land`, `deploy` | `plan`, `red-tests`, every task, `verification` |

`derived: "5.5"` is written. `red-tests` in phase `build` is then found by `detect`. Nothing is asked or printed besides
the normal start output.

**State file** `<git dir>/cplat-units.json` (local, never committed):

```json
{
  "version": 1,
  "command": "ship",
  "spec": "128-some-spec",
  "derived": null,
  "escalated": null,
  "units": [
    {"id": "plan", "status": "done", "sessions": 1, "stalls": 0, "commit": "<40 hex>", "at": "<ISO 8601 UTC>", "hold": null},
    {"id": "task:t1", "status": "running", "sessions": 2, "stalls": 1, "commit": null, "at": null, "hold": {"head": "<40 hex>"}}
  ]
}
```

- `status` is one of `done`, `running` or `open`. `escalated` is `null` or `{"reason": str, "cause": str}`.
- `ship.finish` renames the file to `cplat-units-<spec>-<YYYYmmddHHMMSS>.json` next to the archived ship state.

**Status (AC-131.7).** `cplat component ship status` prints its existing lines, then (only when a units file for the
spec exists):

```
  units:
    plan                 done      1 session    1a2b3c4
    red-tests            done      1 session    5d6e7f8
    task:t1              running   2 sessions   -
    task:t2              open      0 sessions   -
    verification         open      0 sessions   -
    land                 open      0 sessions   -
```

The format is `    {id:<20} {status:<9} {n} session{s:<5}{sha7 or -}`. `--json` adds
`"units": [{"id", "status", "sessions", "commit"}]`, where `commit` is the full sha or `null`. Without a ship state but
with a units file (an unattended build), `status` prints only `build <spec>:` and the units block, exit 0.

**`cplat component ship unit [--json]`** (the session's own check, reads `CPLAT_UNIT`): checkpointed →
`unit <u>: done at <sha7>`. Otherwise `unit <u>: open: <the first rule of the table that is not met>`. Exit 0 in both
cases. Without `CPLAT_UNIT` → `not a unit session`, exit 2.

### Stop hook in a unit session (AC-131.2)

`hooks.json` runs `cplat component ship gate` when `<git dir>/cplat-ship.json` exists **or** `$CPLAT_UNIT` is set. When
`CPLAT_UNIT` is set, `ship.gate` returns `units.gate(repo, unit, hook_input)`, before any owner logic:

| Situation | Answer |
|---|---|
| the ship or the units file is escalated, or the unit is checkpointed (detected now, recorded now) | `None`: the session stops |
| no checkpoint, `hold` is null or its `head` differs from `B` now | `{"decision": "block", "reason": "Unit <u> of <spec> is not finished: <missing rule>.\nNext: <units.next_step>.\nCommit your work. Stop when the unit is done; never start another unit."}`, `hold.head = B` |
| no checkpoint, `hold.head == B` (a stop without a new commit since the last hold) | `None`: the session stops, and the supervisor counts it |

A unit session is never escalated by the hook. The 2-stop escalation of spec 126 stays for attended runs.

### Supervisor (AC-131.1, AC-131.3 to AC-131.6, AC-131.14, AC-131.15)

Unit mode applies when the prompt's first word is `/component:ship` or `/component:build` and it names at least one spec.
Several specs run one after another, each with its own units.

```
for spec in specs:
    data = units.prepare(repo, command, spec)
    while (u := first unit with status open):
        quiet window: as spec 070
        limit = budget.check(rid, "session", repo=repo)           # grants the grace when only verification is left
        limit → budget stop (ship: ship.budget_stop; build: budget.stop + snapshot); result "budget exhausted: <limit>[ (grace used)]"; exit 1
        --max-runs given and sessions == max-runs → "stopped after <n> runs, ship run still unfinished"; exit 1 (AC-070.2)
        --max-minutes given and used up → as spec 070
        print budget.limits_line(rid) when it differs from the last printed one
        budget.count_invocation(rid); units.start_session(repo, u, sid)     # status running, sessions += 1
        before = B
        code = run_once(prompt + " --unit " + u, env CPLAT_UNIT=u, CPLAT_RUN_ALLOWLIST, CPLAT_SESSION_ID, CPLAT_RUN_PARENT)
        ending = units.end_session(repo, command, spec, u, before)   # detect; checkpoint, or stalls = 0 if B moved, else stalls + 1
        summary line (below)
        ship or units escalated → result "needs you: …"; exit 1
        ending is a checkpoint and u == "plan" → budget.rescale(rid, repo, [spec])
        ending is a checkpoint and u == "verification" → budget.end_grace(rid)
        stalls == 2 → escalate "no progress: unit <u> after 2 sessions without a commit"; exit 1
    ship: ship.finish(repo) → result "shipped <spec>[ (<deployed> in dev)]"; build: "finished"
```

- **Prompt of a session:** the original prompt plus ` --unit <unit>`. For example, `/component:ship 012 --no-merge`
  becomes `/component:ship 012 --no-merge --unit task:t2`.
- **Summary log** (`~/.cache/sdlc-foundry/headless/<repo>/summary.log`): one line per session, then the existing final line:
  `<YYYY-MM-DD HH:MM> HEADLESS <repo>: <spec id> unit <unit> session <k>: <end>  (<log file>)`. `<end>` is one of
  `checkpoint <sha7>`, `no checkpoint (exit <code>)`, `no checkpoint (timed out after <m> min)`, or
  `escalated: <reason>`.
- **Stall (AC-131.5):** the escalation goes through `ship.escalate(repo, reason, cause)` for `ship`, and through
  `units.escalate` plus the headless record for `build`. The cause is `ship.no_progress_cause(repo, st, last message)`.
  For `build`, `st` is `{"spec": <id>, "phase": "build"}`. A session that moves `B` resets `stalls` to 0.
- **Interrupted supervisor (AC-131.4):** the same command continues through `units.prepare` and `budget.open_root`, which
  continues the unfinished ledger (AC-102.6).
- **`--max-runs` (AC-131.6):** default `None`, so no session cap in unit mode. A given value counts every session of
  the run, as in AC-070.2. `--max-minutes`: default `None` in unit mode. The legacy loop keeps 6 and 240.

### Run allowlist and preflight (AC-131.8 to AC-131.12)

**Run allowlist** (`preflight.run_allowlist(command, branches) -> list[str]`, in this order). `<B>` is each
`feature/<spec id>` of the prompt. For `/system:ship` it is the literal `feature/*`.

| Action | Rules | Commands |
|---|---|---|
| branch | `Bash(git switch <B>)`, `Bash(git switch -c <B>)` | all |
| commit | `Bash(git add *)`, `Bash(git commit -s *)` | all |
| push | `Bash(git push -u origin <B>)`, `Bash(git push origin <B>)` | all |
| pr | `Bash(gh pr create *)` | all |
| land | `Bash(cplat component ship land)`, `Bash(cplat component ship land *)` | `/component:ship`, `/system:ship` |
| land | `Bash(cplat system ship entry land *)` | `/system:ship` |

**Refused rules** (`preflight.refused_rules(default_branch) -> list[str]`). They are passed as `--disallowedTools`, and
the run allowlist never contains any of them (AC-131.10). `<D>` is the default branch: `git symbolic-ref --short
refs/remotes/origin/HEAD` without `origin/`, else `main`.

```
Bash(git push --force*)  Bash(git push -f*)  Bash(git push * --force*)  Bash(git push * -f*)  Bash(git push * +*)
Bash(git push * <D>)  Bash(git push * <D>:*)  Bash(git push * *:<D>)  Bash(git push * *:refs/heads/<D>)
Bash(gh pr merge*)  Bash(gh api *merge*)  Bash(cplat pr wait *--merge*)
```

A merge with a pending, failed or missing check is refused by `cplat component ship land` itself (spec 072, unchanged).

**Every session** (unit mode and the legacy loop of a covered command) gets:

- the arguments `--allowedTools <rule> <rule> …` (one argument per rule, exactly the run allowlist) and
  `--disallowedTools <rule> …` (the refused rules), after the existing arguments and before `--session-id`;
- the env `CPLAT_RUN_ALLOWLIST=<JSON array of the run allowlist>`.

No file is written: the existing `--settings` JSON for plugin dirs stays inline (AC-131.9).

**Start output**, printed once before the first session (and by `--dry-run`, after the command line):

```
run allowlist (this run's sessions only; no settings file is changed):
  Bash(git switch feature/012-x)
  …
refused: Bash(git push --force*), …
```

**Checks** (`preflight.check(repo, command, specs, targets) -> Failure | None`) run in this order, and the first failure
wins:

| Category | Fails when | Detail and what to do |
|---|---|---|
| `no-repo-allowlist` | `<repo>/.claude/settings.json` is not a file (AC-070.5) | `<repo> has no committed allowlist (.claude/settings.json): run /platform:update or cplat adopt` |
| `blocked-by-settings` | a `deny` or `ask` rule of a layer matches the representative command of an action | `<action>: <deny\|ask> rule "<rule>" in <layer> settings (<path>) matches "<command>": remove or narrow the rule, or run the command attended` |
| `git-identity` | `git config --get user.name` or `user.email` is empty in the repo, and `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` are not set | `commit -s needs an author: git config --global user.name '<name>' and user.email '<email>'` |
| `gh-auth` | `gh auth status --hostname <host>` exits non-zero (`<host>` from `origin`, else `github.com`) | `gh is not logged in for <host>: gh auth login --hostname <host>` |
| `no-push-access` | `gh api repos/<slug> --jq .permissions.push` is not `true` | `<gh user> cannot push to <slug>: ask for write access to it` |

- **Layers**, as `preflight.layers(repo) -> [(name, path)]` (tests replace it): `managed` (macOS
  `/Library/Application Support/ClaudeCode/managed-settings.json`, else `/etc/claude-code/managed-settings.json`), `user`
  (`$CLAUDE_CONFIG_DIR/settings.json`, else `~/.claude/settings.json`), `project` (`<repo>/.claude/settings.json`) and
  `local` (`<repo>/.claude/settings.local.json`). A missing or unreadable file is skipped.
- **Representative commands:** branch `git switch -c <B>`, commit `git commit -s -m "<subject>"`, push
  `git push -u origin <B>`, pr `gh pr create --base <D> --head <B> --title "<title>" --body-file .pr-body.md`, land
  `cplat component ship land`. For `feature/*`, `<B>` is `feature/x`.
- **Matcher** (`preflight.matches(rule, command) -> bool`): `Bash` and `Bash(*)` match every command. `Bash(<p>:*)`
  matches a command that starts with `<p>`. `Bash(<p>)` matches when the glob `<p>` matches the whole command, where `*`
  is any run of characters, spaces included. Rules of other tools never match.
- **Targets:** the repo itself. For `/system:ship`, also every repo of `docs/plan/<spec>.md` when that plan exists: its
  slug `<org>/<id>` for `no-push-access`, and its clone (`appship_sched.clone_path`) for `no-repo-allowlist` and the
  `project`/`local` layers when the clone exists. Checks that do not depend on the repo run once.

**A failed preflight (AC-131.11, AC-131.12)** happens after `runs.start` and `budget.open_root`, and before any session,
`ship start`, branch, commit or PR. It does this:

- prints `preflight failed: <category>: <detail>` (one line) and the `HEADLESS <repo>: preflight failed: <category>`
  summary line;
- ends the headless record with outcome `escalated`, `escalation {"reason": "preflight failed: <category>", "cause":
  "environment"}` and `stop_reason: "preflight"`;
- exits with code 1.

The ledger shows `invocations 0` and cost `0` (the $0 rule below). `stop_of` maps `preflight failed` to
`("preflight", "escalated")`.

**`CPLAT_RUN_ALLOWLIST` (amends ADR-037):** `pr_open.pr_allowed(repo)` adds the env's rules to the allow set before it
checks the settings files. A deny or ask rule in the files still wins.

**`/system:ship` repos started later:** `appship_sched.start_repo` runs `preflight.check_repo(clone, slug)` after the clone
exists (categories `no-repo-allowlist`, `blocked-by-settings`, `no-push-access`). On a failure the repo is recorded
`escalated` with the reason `preflight failed: <category>` and the cause `environment`. The command prints the
`preflight failed:` line and exits with 1, and no repo ship starts.

### Budgets (AC-131.12 to AC-131.17)

**Formula** (`budget.plan_limits(T, C, floors) -> dict`). `T` is the number of tasks in `plan.md` (done tasks and gitops
tasks included), and `C` is `len(spec.active_acs())`:

```
cost        = max(F.cost, 10 + 1.5*T + 0.5*C)        F.cost = 15
minutes     = max(F.minutes, 60 + 15*T + 5*C)        F.minutes = 180
invocations = max(F.invocations, 20 + 5*T + C)       F.invocations = 60
reruns      = F.reruns                               F.reruns = 6
```

`F` is `budget.defaults(repo)`: the platform values, replaced by `budget:` in the settings files. A settings value of
`off` makes the limit `off`. Values go through `_number` (spec 128: T=8, C=14 → cost 29, minutes 250, invocations 74,
reruns 6).

**Ledger additions:**

```json
"parts": {"<repo key>:<spec id>": {"limits": {...}, "T": 8, "C": 14}},
"fixed": ["cost"],
"grace": null
```

- `open_root` makes one part per spec of the prompt, using the formula when the spec has a plan that checks and `F`
  otherwise. Without any resolvable spec it makes one part `F × ships` (AC-102.1 unchanged).
- `limits` is the sum of the parts. A limit given as an option replaces its sum and is listed in `fixed`.
- A continued ledger rescales on open, so it is raised and never lowered.
- **The $0 rule:** a headless root that has not started a session (ledger `invocations` 0 and no `usage` source of the
  run) costs `0`, both in `used_of` and in `on_finish`.

**Rescale** (`budget.rescale(run_id, repo, spec_ids) -> list[change]`, which never raises):

- For each spec with a plan that checks, its part becomes the formula part. It replaces the part `<repo key>:<spec id>`,
  else a placeholder part `<repo key>:*`, else it is added.
- Each limit not in `fixed` becomes `max(current, sum of parts)`.
- Each raise appends `{"at", "limit", "from", "to", "reason": "plan of <spec id>: T=<T>, C=<C>"}` to `changes`
  (AC-102.6).
- `budget.add_parts(run_id, {key: limits})` adds placeholder parts and raises the same way (product ship).

**Limits line:** `budget: minutes 250, invocations 74, reruns 6, cost $29 (plan: T=8, C=14)  (cplat budget show)`.
With several planned parts the bracket lists each part, for example `(plan: 128 T=8 C=14; 129 T=3 C=5)`. Without a
planned part there is no bracket.

**Grace (AC-131.15, AC-131.16).** `budget.check(run_id, point, repo=None)` keeps its result (`None` or a limit name):

1. No limit is used up → `None`.
2. A limit is used up, `repo` is given, the ledger's `grace` is `null` and `units.only_verification_left(repo)` is true.
   Then the grace is granted:
   - the ledger gets `grace = {"for": "verification", "limit": <limit>, "granted_at": <ISO>, "state": "active",
     "add": {...}}`;
   - `add` is `minutes max(30, 0.2·L)`, `invocations max(10, ceil(0.2·L))`, `cost max(3, round(0.2·L, 2))` and
     `reruns ceil(0.2·L)`, for every limit `L` that is not `off`;
   - the line `budget grace: verification` is printed to stdout;
   - the result is `None`.
3. Grace `active`: the limits checked are `limits + add`. When one of them is used up, `grace.state` becomes `used` and
   the result is that limit. `budget.stop` then returns `budget exhausted: <limit> (grace used)`.
4. Grace `active` but `only_verification_left(repo)` is false, or `budget.end_grace(run_id)` was called: `state` becomes
   `ended` and only the base limits count. `land` therefore never runs on the grace.
5. Once `grace` is not `null` it is never granted again. `allow_rerun` ignores the grace.

- `units.only_verification_left(repo)`:
  - with a units file: every unit before `verification` is `done` and `verification` is not;
  - without one: the ship phase is `build`, every task of `plan.md` in `B` has `done: true`, and the red-tests commit
    exists.
- The grace never touches `stages` or `attempts`. A gate result is recorded and read exactly as before (AC-102.8).

**Budget section** (run record and `cplat budget show --json`): the existing keys, plus `grace` (the ledger's object or
`null`), `parts` (`{key: {"T", "C"}}`) and, on a stop, `verification_left` (bool, `units.only_verification_left` at the
stop).

**Cost (AC-131.17):**

- `_cost_of` returns `unknown` when `totals.cost_complete` is false, whatever the number of calls.
- `runs_usage.for_run` sets `totals.cost_complete = false` when `incomplete` names a missing or unreadable transcript, a
  subagent it could not read, the time budget, or an error. Malformed lines alone do not make it incomplete.
- `transcripts` keeps a parse cache in `runs.state_dir()/usage/cache/`, keyed by path, size and `mtime_ns`. A file whose
  key is unchanged is not parsed again, and the deadline only counts files that were parsed.
- A headless root still counts only its own sessions' transcripts. Those include every subagent file under
  `<session>/subagents/`.

### Success measure (AC-131.18)

`cplat platform runs report --since N` gets a section with these lines:

```
Unattended ships (spec 131):
  runs: <n> (/component:ship and /system:ship under cplat headless)
  done: <d>/<n> = <p>%   (target >= 70%)   <ok|MISSED>
  spend in escalated or failed: $<x> of $<y> = <q>%   (target < 20%)   <ok|MISSED>   [<k> runs with unknown cost]
  escalations on a git/gh approval: <a>   (target 0)   <ok|MISSED>
  budget stops with only verification left: <b>   (target 0)   <ok|MISSED>
```

- A run is a `headless` record whose `command` starts with `/component:ship` or `/system:ship`.
- Its spend is `usage.totals.cost_usd`.
- An approval escalation is a reason for which `escalation_rules.classify` returns `git-action-awaits-approval`, or one
  that starts with `preflight failed: blocked-by-settings`.
- A budget stop with only verification left has `stop_reason` `budget` and `budget.verification_left` true.
- `--json` adds the same values under `unattended_ships`.

## Risks

- **A stray working-tree change hides a checkpoint.** Detection reads only committed trees, so uncommitted work never
  counts. The unit hold tells the session to commit.
- **Two unit sessions in one checkout.** The supervisor runs one session at a time. The ship slot and the ship state
  owner (spec 126) stay unchanged.
- **More sessions mean more start-up turns.** Each unit session pays the cost of reading the command file again. This is
  bounded by the scaled invocations.
- **A deny rule pattern that is too wide.** `Bash(git push * -f*)` must not match a branch named `feature/x-fix`. The
  matcher test pins it, and so do the refused-rule tests.
