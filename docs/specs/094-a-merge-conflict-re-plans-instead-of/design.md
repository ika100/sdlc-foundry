# Design — 094 A merge conflict re-plans instead of escalating

## Decisions

- **The mechanics are code, the judgement stays in the prompt.** A new command group `cplat build` does everything
  that can be decided without judgement: the schedule, the merge of a task branch (and the abort on a conflict), the
  re-plan budget, the check of the amended plan, the re-plan commit, the clean-up of a set-aside branch and the 089
  recording. `/svc:build` only spawns the architect and the coders and acts on exit codes. That makes every criterion
  except the prompt wording testable on real git repos in `tests/cplat/` (AC-094.1–.7, .9–.13).
- **The re-plan history is the git history of the feature branch** (AC-094.11, .13). Every amended plan is one commit
  with fixed trailers. The number of re-plans, which tasks were re-planned, with whom they collided and which branch
  was set aside are all read back from those commits, so an interrupted build counts its earlier re-plans without
  any extra state. Only the conflicts of the current batch that have no re-plan commit yet live in a local file
  (`<git common dir>/cplat-replan.json`, never committed, like `cplat-ship.json`).
- **One re-plan is one amended plan** (AC-089.14 "each amended plan counts one re-plan"). Several conflicting tasks of
  one batch go to the architect together and produce one commit, one re-plan. The per-task limit (AC-094.6) asks
  whether a task id appears in any earlier re-plan commit; the per-build cap (AC-094.13) counts re-plan commits.
- **The budget is decided at the conflict, not after it.** `cplat build merge` knows the history, so it answers
  "set aside" (exit 3) or "escalate" (exit 4) itself. The orchestrator never counts.
- **The tree is clean before every merge.** `git merge --abort` cannot restore uncommitted changes reliably, so
  `cplat build merge` refuses a dirty tracked tree, and build.md now commits after each task (lint-fix, `task-done`)
  instead of once per batch. This is what makes "exactly as it was before that merge" (AC-094.1) provable.
- **The architect can change only plan metadata.** `cplat build replan-commit` compares the working plan with
  `HEAD:plan.md` and refuses any other change (AC-094.3), and any other changed file in the tree. So no hunk can be
  resolved by hand on the way to the commit (AC-094.12).
- **Recording order.** The conflict is recorded when it happens, with outcome `escalated`: that is the truth if the
  run ends there. The re-plan commit records one `re-plan` (which sets its linked conflict to `re-planned`) and sets
  the other tasks of the same re-plan to `re-planned`. The clean re-run sets `resolved`. The end state is the
  sequence spec 089's design names (`conflict` → `replan` → `conflict-outcome`). The intermediate outcome is only
  more cautious. All recording goes through `runs_agents`, which never raises and buffers without a store
  (AC-094.9, .10).
- No ADR: the rule "a conflict is re-planned once, then escalated, never resolved by hand" is documented in
  `docs/AGENTS.md` and in the build rules (AC-094.15). No new technology or cross-repo pattern is introduced.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/replan.py` | re-plan history from git, pending conflicts file, budget, amended-plan check, re-plan commit, abort, resolve, the messages, 089 recording | new |
| `scripts/cplat/buildcmd.py` | `cplat build` CLI: `schedule`, `merge`, `state`, `replan-commit`, `replan-abort`, `resolved` | new |
| `scripts/cplat/cplat.py` | registers `build` → `buildcmd`, docstring line | changed |
| `plugins/svc/commands/build.md` | Phase 2 uses `cplat build`; re-plan loop; coder prompt for re-runs; Final Report; Rules | changed |
| `plugins/svc/agents/architect.md` | "Re-plan mode" section | changed |
| `plugins/svc/commands/ship.md`, `scripts/cplat/ship.py` (gate text), `docs/AGENTS.md`, `docs/unattended-delivery.md`, `docs/CHANGELOG.md` | wording: conflicts are re-planned once, then escalated | changed |

## Contract

All subcommands take `--repo DIR` (default `.`) and a spec reference `<spec>` (number, slug or id, as `cplat spec`).
`ERROR: …` / `  fix: …` on stderr and exit 1 for usage or state errors (via `core.PlatformError`), as every cplat
command does. Recording never changes an exit code or stdout.

### Terms

- **Plan task**: an entry of `plan.md`'s `tasks`. A **gitops task** has `repo:`. It is never scheduled or merged here.
- **History**: the re-plan commits of this spec, i.e. commits reachable from `HEAD` with a `Replan-Spec: <spec_id>`
  trailer. The search starts after the spec's `docs(spec): start building <spec_id>` commit when it exists, else it
  covers all of `HEAD`'s history. Oldest first.
- **Re-planned task**: a task id that appears in a `Replan-Task` trailer of the history.
- **Pending conflict**: a set-aside task of the current batch that has no re-plan commit yet. Stored in
  `<git common dir>/cplat-replan.json` as
  `{"<spec_id>": {"<task>": {"with": str|null, "paths": [str], "branch": str, "at": "<sha of HEAD before the merge>"}}}`.
- **CAP** = 3 re-plans per build.

### Re-plan commit (written by `replan-commit`, read back by everything else)

```
chore(plan): <spec_id> re-plan <t2>, <t3> after a merge conflict

Conflicting files: <p1>, <p2>, <p3>
Re-planned: <t2> (collided with <t1>), <t3> (collided with <t1>)

Replan-Spec: <spec_id>
Replan-Task: <t2> with=<t1|-> branch=<branch> paths=<p1>,<p2>
Replan-Task: <t3> with=<t1|-> branch=<branch> paths=<p3>
Signed-off-by: <git user> <email>
```

The subject names every re-planned task id in plan order, and the body names every conflicting file (AC-094.4).
`with=-` means the collision partner is unknown. Paths are comma-separated, in `git diff` order. Only `plan.md` is
in the commit. It is made with `git -c user.name… commit -s` (core.git_identity).

### `cplat build schedule <spec> [--json]` (AC-094.4)

The schedule of the tasks that are not `done` (build.md 2.1 is replaced by this call).

- Gitops tasks are listed apart and are never in a batch.
- `depends_on` entries naming `done` tasks or gitops tasks count as satisfied.
- Levels: `spec.topo_levels` over the remaining tasks. Within a level, tasks go in plan order.
- Batches within a level, greedy in plan order: a `parallel_safe` task joins the first batch whose tasks are all
  `parallel_safe` and whose `files` are disjoint from its own, else it starts a new batch. A task that is not
  `parallel_safe` is a batch of its own. A batch is `parallel` when it has ≥ 2 tasks.
- A dependency cycle → exit 1 with `spec.topo_levels`' message.

`--json` (stdout, exit 0):

```json
{"spec": "094-…", "done": ["t1"], "gitops": ["g1"], "replanned": ["t2"], "replans": 1, "cap": 3,
 "levels": [[{"tasks": ["t2", "t4"], "parallel": true}, {"tasks": ["t5"], "parallel": false}],
            [{"tasks": ["t6"], "parallel": false}]]}
```

Text (exit 0): one Markdown table, then one line.

```
| Level | Batch | Tasks | Mode |
|---|---|---|---|
| 1 | 1 | t2 (re-planned), t4 | parallel |
| 1 | 2 | t5 | sequential |
| 2 | 1 | t6 | sequential |
done: t1 · gitops: g1 · re-plans: 1 of 3
```

A re-planned task that is not done is marked `(re-planned)`. A re-planned task that now depends on another
not-done task is therefore printed in a later level than that task.

### `cplat build merge <spec> <task> <branch> [--helper PATH]...` (AC-094.1, .2, .6, .9, .12, .13)

Preconditions (exit 1, nothing changed): the task exists, is not done and is not a gitops task; `<branch>` resolves;
no `MERGE_HEAD`; `git status --porcelain --untracked-files=no` is empty (fix: `commit the previous task first`).

1. `PRE = git rev-parse HEAD`, then `git merge --no-ff --signoff -m "merge(<task>): <branch>" <branch>`.
2. **Clean** →
   - drop the task's pending conflict, if any;
   - `runs_agents.merged(run, repo, task, PRE, helpers)`;
   - print `MERGED <task> <short sha>`; exit 0.
3. **Failed without `MERGE_HEAD`** (e.g. untracked files would be overwritten) → exit 1 with git's last line. HEAD is
   unchanged.
4. **Conflict** (`MERGE_HEAD` exists):
   - `paths` = `git diff --name-only --diff-filter=U`;
   - `git merge --abort`;
   - assert `HEAD == PRE`, an empty tracked status and no `MERGE_HEAD`; otherwise exit 1, "merge --abort did not
     restore the feature branch" (a platform defect).
   - `with` is the first of:
     - (a) the task of a first-parent merge commit `merge(<id>): …` after `merge-base(PRE, branch)` whose change vs
       its first parent touches a conflicting path (the latest one);
     - (b) the done task whose `files` cover the most conflicting paths, matched exactly, by glob or by directory
       prefix as `runs_agents._in_files`, the later task in plan order on a tie;
     - (c) a task id that appears in the message of a non-merge commit after `merge-base(PRE, branch)` touching a
       conflicting path;
     - (d) `null`.
   - Then decide:
     - the task is re-planned already → **escalate (again)**;
     - else the history has ≥ CAP commits → **escalate (cap)**;
     - else → **set aside**: write the pending conflict, overwriting an older one of the same task.
   - Record `runs_agents.conflict(run, repo, task, with_task=with, paths=paths, outcome="escalated", spec=spec_id)`.
   - Print and exit:

Set aside, exit **3**:

```
CONFLICT <task> with <with|unknown task>: <p1>, <p2>
SET ASIDE <task>: branch <branch> is kept for the re-run; the feature branch is unchanged at <short PRE>
NEXT: merge the rest of the batch, then re-plan (build re-plans used: <n> of 3)
```

Escalate, exit **4**: the first line is the same `CONFLICT` line. The second line starts with `ESCALATE: ` and is the
whole one-line reason (for `cplat runs end --reason` / `cplat ship escalate`):

- again (AC-094.6): `ESCALATE: <task> conflicted again after its re-plan: now with <with> on <paths>; before with
  <with₁> on <paths₁>; re-plan commit <short sha> "<subject>". A task is re-planned once; conflicts are never resolved
  by hand.`
- cap (AC-094.13): `ESCALATE: the cap of 3 re-plans per build was reached; <task> conflicts with <with> on <paths>.
  Earlier re-plan commits: <short sha> "<subject>"; <short sha> "<subject>"; <short sha> "<subject>". Conflicts are
  never resolved by hand.`

In both cases the branch and its worktree are left as they are, and nothing is written to the pending file.

### `cplat build state <spec> [--json]` (AC-094.3, .5, .8, .11)

The re-plan history and the pending conflicts. The orchestrator uses it for the architect prompt, the re-run coder
prompts and the Final Report.

`--json`:

```json
{"spec": "094-…", "cap": 3, "count": 1,
 "replans": [{"sha": "<40>", "subject": "chore(plan): …", "tasks": [
     {"task": "t2", "with": "t1", "paths": ["src/a.py"], "branch": "worktree-agent-ab12", "merged": true}]}],
 "pending": [{"task": "t3", "with": "t1", "paths": ["src/c.py"], "branch": "worktree-agent-cd34"}]}
```

`merged` is true when the task is `done` in the plan. Text:

```
re-plans: 1 of 3
  <short sha> t2: src/a.py (collided with t1) — re-run merged cleanly
pending: t3 with t1: src/c.py (branch worktree-agent-cd34)
```

A re-planned task that is not done prints `— re-run pending`. Without history and pending conflicts it prints only
`re-plans: 0 of 3`.

### `cplat build replan-commit <spec>` (AC-094.3, .4, .9)

The architect has written the amended `plan.md` into the working tree. Checks, in this order. Each failing check
prints `ERROR: <spec_id>: <message>` on stdout, the last line is `<n> error(s)`, the exit is 1, and nothing is
committed or reset (the orchestrator sends the errors to the architect once):

1. There is at least one pending conflict, else `nothing to re-plan: no pending conflict`.
2. `git status --porcelain` (untracked included) lists only the plan file, else
   `the re-plan may change only plan.md; also changed: <paths>`.
3. Compared with `HEAD:<SPEC_DIR>/plan.md`:
   - every metadata key other than `tasks` is equal (`spec_id`, `spec_hash`, `shape`, `summary`, `human_steps`, …);
   - the task ids are the same set;
   - for a `done` task the whole entry is equal;
   - for a not-done task only `files`, `depends_on` and `parallel_safe` may differ: every other key (including
     `title`, `covers`, `repo`, `order`, `apps`, `done`) is present with the same value or absent in both.
   - Messages: `task <id>: <key> changed (only files, depends_on and parallel_safe of tasks that are not done may
     change)`, `task <id> is done and changed`, `tasks added: …` / `tasks removed: …`, `<key> changed`.

   The prose below the metadata may change.
4. `spec.check(amended spec)` errors, each prefixed `plan.md: ` as in `cplat spec check`.

All pass →

- commit the plan with the message above (tasks: all pending, plan order);
- clear the spec's pending conflicts;
- record `runs_agents.replan(run, repo, <first task>)`, then `runs_agents.conflict_outcome(run, repo, t, "re-planned")`
  for each other task;
- print `RE-PLANNED <t2>, <t3> in <short sha> (re-plans: <n> of 3)` and then the `schedule` text; exit 0.

### `cplat build replan-abort <spec> --reason TEXT` (AC-094.7)

For architect blockers or a second failed `replan-commit`:

- `git checkout HEAD -- <SPEC_DIR>`, and untracked files under `SPEC_DIR` are removed, so the plan on the branch is the
  last committed (valid) one;
- `runs_agents.conflict_outcome(run, repo, t, "escalated")` for each pending task;
- clear the spec's pending conflicts.

It prints one line, exit 0: `ESCALATE: the re-plan of <tasks> failed: <TEXT>. The plan stays at <short HEAD>.
Conflicts are never resolved by hand.`

### `cplat build resolved <spec> <task>` (AC-094.5, .9)

Run after `cplat spec task-done` for every task. It is a no-op for a task that is not re-planned:
`<task> was not re-planned` (exit 0). For a re-planned task:

- the task must be `done`, else exit 1;
- remove the set-aside branch's worktree (`git worktree list --porcelain` → the worktree whose `branch` is
  `refs/heads/<branch>`; `git worktree remove --force <path>`, then `git worktree prune`);
- `git branch -D <branch>`; a branch or worktree that is already gone is fine;
- `runs_agents.conflict_outcome(run, repo, task, "resolved")`;
- print `RESOLVED <task>: removed branch <branch>[ and worktree <path>]`; exit 0.

### build.md, Phase 2 (prompt contract)

- **2.1**: `cplat build schedule <id>`, printed verbatim (replaces the hand-made table).
- **2.3**, coder prompt, for a re-planned task (`cplat build state <id> --json`, `replans[].tasks[]` not merged):
  "This task was re-planned after a merge conflict on `<paths>` with `<with>`. Start from the feature branch, which
  already contains every merged task. Your earlier attempt is a reference only. Do not merge or cherry-pick it:" and
  the output of `git diff HEAD...<branch>`.
- **2.4**:
  - Merges go through `cplat build merge <id> <task> <branch> [--helper P]...`, which also records `merged`.
  - Exit 3 → keep merging the rest of the batch. Leave that worktree in place.
  - Exit 4 → `cplat runs end --outcome escalated --reason '<ESCALATE line>'` and stop.
  - After each task: lint-fix, `test-diff`, quality, `test-fast`, `cplat spec task-done`, `cplat build resolved`, then
    commit `chore(plan): <spec_id> <task> done`. That is one commit per task, so the next merge starts from a clean
    tree.
- **2.4a, Re-plan** (after a batch with ≥ 1 set-aside task, without asking, also in an attended build):
  - The architect (`agents.architect`) gets the prompt `**Re-plan mode.**` + `SPEC_DIR` + the `cplat build state <id>`
    pending lines + "change only `files`, `depends_on` and `parallel_safe` of tasks that are not done; anything else is
    a BLOCKER";
  - then `cplat runs agent spawned architect`;
  - then `cplat build replan-commit <id>`. On exit 1, send its errors to the architect once and call it again.
  - BLOCKERS, or a second exit 1 → `cplat build replan-abort <id> --reason '<blockers or errors>'`, then escalate with
    its line.
  - Exit 0 → continue with the printed schedule.
- **Final Report**: the Implementation row adds, when `cplat build state` shows `count ≥ 1`,
  `· plan amended <n>× after merge conflicts: <task>: <files> (re-run merged cleanly)`. That is one entry per
  re-planned task.
- **Rules**: "**A merge conflict is re-planned once per task (at most 3 re-plans per build), then escalated; it is
  never resolved by hand.** `cplat build merge` aborts the merge and sets the task aside; the architect amends only
  the plan and the task runs again on top of the merged work, without asking. Never edit conflicting hunks."

### architect.md: "Re-plan mode"

On a `**Re-plan mode.**` prompt, the architect:

- reads the plan and the conflicts;
- changes only `files`, `depends_on` and `parallel_safe` of not-done tasks. Typically the conflicting task gets a
  `depends_on` on the task it collided with, or the missing file joins `files`, and it is no longer `parallel_safe`
  with that task;
- writes nothing but plan.md (it may adjust that task's prose);
- reports a BLOCKER when the fix would need any other change: a new task, other `covers`, the spec or design.

Reply: the usual block, with `PLAN: … — re-plan of <tasks>`.

## Data

`<git common dir>/cplat-replan.json` (pending conflicts per spec; local, never committed; a missing or unreadable file
means none). Re-plan commits on the feature branch carry the trailers above. The 089 record sections are unchanged.

## Risks

- **Squash merges copy trailers into `main`**: the history search starts after the spec's `start building` commit,
  so a later build of another spec never sees them, and a spec is not built twice.
- **Worktree branch names come from the Agent tool**: the set-aside branch is stored in the trailer and the pending
  file, never guessed.
- **One commit per task instead of per batch** adds commits to the feature branch. That is accepted: the PR is
  squash-merged, and a clean tree before each merge is what makes the abort safe.
- **The collision partner may be unknown** (`with: null`) when the colliding task changed a file outside its `files`
  and its commits do not name it. The messages then say `unknown task`, and the architect still gets the paths.
