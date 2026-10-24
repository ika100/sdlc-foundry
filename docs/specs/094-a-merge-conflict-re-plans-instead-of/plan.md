---
spec_id: 094-a-merge-conflict-re-plans-instead-of
spec_hash: a4afa0d794cc
summary: cplat build (schedule, merge, state, replan-commit, replan-abort, resolved) with a git-derived re-plan history;
  /svc:build re-plans a conflicting task once (at most 3 re-plans per build), then escalates; never resolves by hand
tasks:
- id: t1
  title: Re-plan history, budget, amended-plan check and re-plan commit (replan.py)
  files: [scripts/cplat/replan.py]
  covers: [AC-094.3, AC-094.4, AC-094.5, AC-094.6, AC-094.7, AC-094.9, AC-094.10, AC-094.11, AC-094.12, AC-094.13]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: cplat build CLI with schedule and the conflict-safe merge (buildcmd.py)
  files: [scripts/cplat/buildcmd.py, scripts/cplat/cplat.py]
  covers: [AC-094.1, AC-094.2, AC-094.3, AC-094.4, AC-094.5, AC-094.6, AC-094.7, AC-094.8, AC-094.9, AC-094.10, AC-094.11,
    AC-094.12, AC-094.13]
  parallel_safe: true
  depends_on: [t1]
  done: true
- id: t3
  title: Build and architect prompts run the re-plan loop
  files: [plugins/svc/commands/build.md, plugins/svc/agents/architect.md]
  covers: [AC-094.1, AC-094.2, AC-094.3, AC-094.5, AC-094.7, AC-094.8, AC-094.12, AC-094.14, AC-094.15]
  parallel_safe: true
  depends_on: []
  done: true
- id: t4
  title: Docs, ship prompt and ship gate say conflicts are re-planned once
  files: [docs/AGENTS.md, docs/unattended-delivery.md, docs/CHANGELOG.md, plugins/svc/commands/ship.md, scripts/cplat/ship.py]
  covers: [AC-094.14, AC-094.15]
  parallel_safe: true
  depends_on: []
  done: true
---

The contract for every task is [design.md](design.md): the `cplat build` subcommands, their output lines and exit
codes (0 / 1 / 3 / 4), the re-plan commit and its trailers, the pending file and the build.md prompt contract. Field
names, trailer keys and message wording are exactly as written there, because the acceptance tests assert them.
Recording goes only through `runs_agents` and never changes an exit code or stdout.

Levels: t1, t3, t4 → t2.

## t1 — Re-plan history, budget, amended-plan check and re-plan commit (replan.py)

**Files:** scripts/cplat/replan.py
**Covers:** AC-094.3, AC-094.4, AC-094.5, AC-094.6, AC-094.7, AC-094.9, AC-094.10, AC-094.11, AC-094.12, AC-094.13
**Goal:** a library module with no CLI that holds every rule of the re-plan. It covers the history read from git, the
pending conflicts, the budget decision, the amended-plan check, the commit, the abort, the clean-up and the messages.
t2 calls it.

**Implementation notes:**
- `CAP = 3`; `PENDING_FILE = "cplat-replan.json"` in `runs._git_common_dir(repo)` (or the same `git rev-parse
  --git-common-dir` logic). Unreadable or missing file means no pending conflicts. Writes are atomic (tmp + replace).
- `history(repo, spec) -> list[dict]`:
  - commits from `HEAD` back to, but excluding, the spec's `docs(spec): start building <spec_id>` commit (all of
    history when there is none);
  - oldest first;
  - only those with a `Replan-Spec: <spec_id>` trailer (`git log --format=%H%x1f%s%x1f%(trailers:unfold,only)%x1e`);
  - each gives `{"sha", "subject", "tasks": [{"task", "with", "paths", "branch"}]}`, parsed from `Replan-Task:` (`with=-`
    → None).
- `pending(repo, spec)`, `set_pending(repo, spec, task, entry)`, `drop_pending(repo, spec, task)`,
  `clear_pending(repo, spec)`.
- `decide(repo, spec, task) -> ("aside" | "again" | "cap", history)`: "again" when the task is in a `Replan-Task` of
  the history, else "cap" when `len(history) >= CAP`, else "aside".
- The message builders return the exact `CONFLICT` / `SET ASIDE` / `NEXT` / `ESCALATE:` lines of the contract. The
  "again" line takes the first collision from the history entry of that task.
- `check_amended(repo, spec) -> list[str]`: steps 1–4 of `replan-commit`, in that order, with the contract's messages.
  It parses `HEAD:<plan>` with `git show` and `yaml.safe_load` on the front matter (as `spec.load`). It compares task
  entries as dicts minus `files`/`depends_on`/`parallel_safe` for not-done tasks. Then `spec.check(spec.read(dir))`.
- `commit(repo, spec) -> sha`:
  - the message of the contract: tasks in plan order; the file list de-duplicated in first-seen order;
  - `git add <plan>`; `git ["-c", …core.git_identity(repo)] commit -q -s -F -`;
  - `clear_pending`;
  - then recording: `runs_agents.replan(rid, repo, first)` and `conflict_outcome(rid, repo, t, "re-planned")` for the
    rest, with `rid = runs.current_run(repo)`, all inside `try/except Exception: pass`.
- `abort(repo, spec, reason) -> str`:
  - `git checkout HEAD -- <SPEC_DIR>` and removal of untracked files under it (`git clean` is not used: list them with
    `git ls-files --others --exclude-standard -- <SPEC_DIR>` and unlink);
  - recording `escalated` per pending task;
  - `clear_pending`;
  - it returns the `ESCALATE:` line.
- `resolve(repo, spec, task) -> str`: as the `resolved` contract (worktree by branch from `git worktree list
  --porcelain`, `worktree remove --force`, `worktree prune`, `branch -D`, missing ones fine, record `resolved`).
- Every git call goes through `core.run(..., check=False)`. Failures that the contract does not list raise
  `core.PlatformError` with git's last stderr line.

**Done when:** the acceptance tests that exercise this module through `cplat build` pass after t2. On its own, the
module imports cleanly and `tests/cplat/test_spec*.py` and `test_runs*.py` stay green.

## t2 — cplat build CLI with schedule and the conflict-safe merge (buildcmd.py)

**Files:** scripts/cplat/buildcmd.py, scripts/cplat/cplat.py
**Covers:** AC-094.1, AC-094.2, AC-094.3, AC-094.4, AC-094.5, AC-094.6, AC-094.7, AC-094.8, AC-094.9, AC-094.10,
AC-094.11, AC-094.12, AC-094.13
**Goal:** `cplat build schedule|merge|state|replan-commit|replan-abort|resolved`, exactly as the contract says, built
on `replan.py` and `spec.py`.

**Implementation notes:**
- `main(argv)` uses argparse with `--repo` (default `.`), as `spec.main`. The spec is resolved with `spec.find(root,
  ref)`, and a missing plan → `PlatformError`.
- `schedule`:
  - drop done tasks and gitops tasks (`repo:`), and drop `depends_on` entries that are no longer remaining;
  - `spec.topo_levels`, then reorder each level by plan order;
  - greedy batches as in the contract;
  - `replanned` and `replans` come from `replan.history`;
  - JSON or the table plus the `done: … · gitops: … · re-plans: n of 3` line. Omit an empty part.
- `merge`:
  - the preconditions;
  - `git merge --no-ff --signoff -m "merge(<task>): <branch>" <branch>`;
  - the clean path calls `runs_agents.merged(rid, repo, task, PRE, helpers)` inside try/except;
  - the conflict path collects the unmerged paths, then `git merge --abort`, then the restore assertion, then the
    partner rules (a)–(d), then `replan.decide`, then pending or not, then `runs_agents.conflict(..., outcome=
    "escalated", spec=spec_id)`, then the lines;
  - it returns 3 or 4. For rule (b) use `runs_agents._in_files`, or a local copy with the same semantics.
- `state`: `replan.history` + `replan.pending` + the plan's `done` flags → JSON or text as in the contract.
- `replan-commit`:
  - `replan.check_amended`; any errors → print them as `ERROR: <spec_id>: …` lines plus `<n> error(s)` (stdout, like
    `spec._print_errors`) and return 1;
  - otherwise `replan.commit`, print `RE-PLANNED …`, then the schedule text.
- `replan-abort --reason` (required) → print `replan.abort(...)`. `resolved` → print `replan.resolve(...)`.
- `cplat.py`: `"build": "buildcmd"` in `COMMANDS`, plus the docstring line `cplat.py build schedule|merge|state|
  replan-commit|replan-abort|resolved ...   /svc:build Phase 2: schedule, merge, re-plan on conflict (spec 094)`.

**Done when:** the acceptance tests for AC-094.1–.7 and .9–.13 pass. They run on temp git repos with a spec, a plan
and real task branches that conflict, and use `cplat build …` (and the CLI via `cplat.main(["build", …])`). The
`state` side of AC-094.8 passes, the existing `tests/cplat/` suite stays green, and `devbox run validate` passes.

## t3 — Build and architect prompts run the re-plan loop

**Files:** plugins/svc/commands/build.md, plugins/svc/agents/architect.md
**Covers:** AC-094.1, AC-094.2, AC-094.3, AC-094.5, AC-094.7, AC-094.8, AC-094.12, AC-094.14, AC-094.15
**Goal:** `/svc:build` Phase 2 uses `cplat build` and runs the re-plan loop of design.md "build.md, Phase 2" without
asking. The architect knows re-plan mode.

**Implementation notes:**
- 2.1: replace the hand-made sorting with `cplat build schedule <id>`, printed verbatim. Keep the phrase "skip tasks
  with `done: true`" (an existing test asserts it).
- 2.3:
  - add the re-planned-task paragraph with `git diff HEAD...<branch>` as reference;
  - "Do not merge or cherry-pick it";
  - take the branch from `cplat build state <id> --json`.
- 2.4, parallel batch:
  - step 1 becomes `cplat build merge <id> <task> <branch> [--helper <path>]...` (it records `merged` and the
    conflict);
  - exit 3 → continue with the next branch of the batch and leave its worktree;
  - exit 4 → `cplat runs end --outcome escalated --reason '<the ESCALATE line>'` and stop;
  - remove "stop and escalate. Never resolve it yourself" for the first conflict.
- After each task:
  - `cplat spec task-done <id> <task-id>`, then `cplat build resolved <id> <task-id>`;
  - then commit `chore(plan): <spec_id> <task id> done` with that task's lint-fix changes, one commit per task, so the
    next merge starts from a clean tree;
  - the sequential path keeps `cplat runs agent merged … --since $PRE`.
- New 2.4a "Re-plan after a conflict" (no question to the user, attended or not):
  - the architect prompt `**Re-plan mode.**` + `<project-map>` + `SPEC_DIR` + the `cplat build state <id>` output
    (the pending conflicts: task, collided-with task, paths) + the constraint;
  - `cplat runs agent spawned architect`;
  - `cplat build replan-commit <id>`, with one retry carrying its errors;
  - BLOCKERS or a second failure → `cplat build replan-abort <id> --reason '…'` and escalate with its line;
  - on success, continue from the printed schedule.
- Final Report Implementation row: `· plan amended <n>× after merge conflicts: <task>: <files> (re-run merged
  cleanly)`, from `cplat build state <id>`, only when count ≥ 1. It also applies to attended builds.
- Rules: replace "Never resolve merge conflicts automatically …" with the contract's rule text, which says "re-planned
  once per task", "at most 3 re-plans per build", "escalated" and "never resolved by hand". Nothing may still say
  that every conflict is escalated.
- Every paragraph that names `cplat spec test-diff` must keep saying that exit 1 stops the build
  (`test_build_stops_on_an_acceptance_test_change` splits build.md at numbered steps, `After ` and `## `).
- architect.md: a short "Re-plan mode" section as in design.md. Keep the existing lines that
  `tests/cplat/test_spec_agents.py` asserts (the `${CLAUDE_PLUGIN_ROOT}/skills/spec-format/references/` paths).

**Done when:** these acceptance tests pass:
- the prompt-text tests for AC-094.8 and .14, and the build.md side of .15;
- the prompt parts of .1, .2, .3, .5, .7 and .12.

`tests/cplat/test_spec_agents.py` also stays green.

## t4 — Docs, ship prompt and ship gate say conflicts are re-planned once

**Files:** docs/AGENTS.md, docs/unattended-delivery.md, docs/CHANGELOG.md, plugins/svc/commands/ship.md, scripts/cplat/ship.py
**Covers:** AC-094.14, AC-094.15
**Goal:** nothing in the guide, the ship prompt or the Stop-hook gate still says that every merge conflict is
escalated.

**Implementation notes:**
- `docs/AGENTS.md`:
  - replace "**Merge conflicts are escalated, never auto-resolved.** …" with "**A merge conflict is re-planned once
    per task (at most 3 re-plans per build), then escalated; it is never resolved by hand.**" Then one or two
    sentences:
    - `cplat build merge` aborts the merge and sets the task aside;
    - the architect amends only `files` / `depends_on` / `parallel_safe` of tasks that are not done;
    - the task runs again on top of the merged work;
    - this happens without asking, attended or not.
  - step 4 of the orchestrator list: one commit per task, and the merge through `cplat build merge`;
  - the Stop-hook paragraph (line ~24): "merge conflict" → "a merge conflict after its re-plan (or the 4th re-plan of
    a build)".
- `docs/unattended-delivery.md` line ~18: the same rewording of "a merge conflict" in the list of escalations.
- `plugins/svc/commands/ship.md`:
  - in Phase `build`, the stop-and-escalate list: "a merge conflict between task branches" → "a merge conflict that
    `cplat build merge` escalates (a task's second conflict, or the cap of 3 re-plans) or a re-plan the architect
    cannot make";
  - in Phase `plan`, add: the build's own re-plan after a conflict (build.md 2.4a) is the exception to "a plan that
    already has `done` tasks is not re-planned".
- `scripts/cplat/ship.py` `gate()` reason text: "merge conflict" → "a merge conflict after its re-plan". Change only
  that string.
- `docs/CHANGELOG.md`: one bullet at the top of `[Unreleased]`, **Feat (094): a merge conflict re-plans instead of
  escalating.** It names:
  - `cplat build merge` (abort, set aside);
  - `cplat build replan-commit` (only `files` / `depends_on` / `parallel_safe` of open tasks);
  - once per task and at most 3 per build, then escalation;
  - that conflicts are never resolved by hand;
  - that the Final Report says when the plan was amended.

  Only this task edits the CHANGELOG.
- No plugin or marketplace version bumps.

**Done when:** the doc-text acceptance tests for AC-094.14 and the AGENTS.md side of AC-094.15 pass.
`tests/cplat/test_ship*.py`, `test_headless.py` and `test_spec_agents.py` stay green, and `devbox run validate` and
the Markdown link check pass.
