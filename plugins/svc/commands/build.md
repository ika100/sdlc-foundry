---
description: "Build an approved, planned spec: failing acceptance tests first → parallel coders until they pass → quality ‖ tests ‖ security → verify against the spec → image → PR. Resumable. Usage: /svc:build <spec-id>"
---

You are the **build orchestrator** ([ADR-026](../../../docs/adr/026-feature-specs.md)). The approved spec defines done: you turn its criteria into failing tests, have coders make them pass, and prove the result against the spec before opening one PR. Delegate all code and test writing to subagents.

**Spec:** $ARGUMENTS (number, slug or full id; empty → `cplat spec list` and ask which)

Work through the phases in order. After each, print `## Phase N complete — <one line>`. A re-run of `/svc:build <id>` **resumes**: phases whose result already exists are skipped (each phase says how it detects that).

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation. First call, also the shape dispatch:

```bash
cplat shape
```

It prints JSON: `shape`, `plugin`, `deployable`, `library`, `agents` (the subagent type for every role — spawn each role with exactly that type, e.g. `agents.coder`). `unsupported` → stop and show it. A repo without a shape cannot be built (no coder to route to): stop. Roles missing from `agents` (e.g. deployment for a library) are skipped. Print its output verbatim.

---

## Phase 0 — Pre-flight

0. `cplat runs begin build --spec <id>` (spec 087). Inside `/svc:ship` it attaches to the ship run. Every stop below that needs the user, or fails, first runs `cplat runs end --outcome escalated --reason '<why>'` (`--outcome failed` for a hard failure); the Final Report ends with `cplat runs end --outcome done`. Recording never fails a build: a warning line about a buffered record is not an error.
   **Agent metrics (spec 089):** after every subagent you spawn, in any phase, run `cplat runs agent spawned <role> [--model-id <id>]` (`<role>` is the role name, e.g. `coder`; `--model-id` only when you know the model id). The calls below record what only you can judge. They never fail the build, and a `WARNING: agent metric not recorded` line is not an error.
1. `git status --porcelain`. A dirty tree on a spec whose status is not `building` stops the build: commit or stash first (the clean-tree rule). On a `building` spec it is an **interrupted build** (spec 047):
   - Staged entries that differ from both `HEAD` and the working tree are stale (left by the interrupted coder): `git restore --staged <files>` and name them.
   - The first task in `plan.md` that is not `done` is the interrupted one. Ask, then commit the remaining changes as `wip(<task-id>): interrupted` (in an unattended run, commit without asking and say so).
   - That task runs again in Phase 2 with `git show HEAD` (the WIP diff) in its coder prompt, so the coder finishes or redoes it.
2. `cplat spec check <id> --require approved` must pass, and `docs/specs/<spec_id>/plan.md` must exist. Otherwise stop with the fix: `/svc:spec approve <NNN>`, `/svc:plan <NNN>`, or for `spec_hash` drift `/svc:plan <NNN>` again.
3. Switch to `feature/<spec_id>` (create it from `main` if missing). `$FEATURE_BRANCH` = it.
4. `BASE_REF=$(git merge-base main HEAD)` — the build's diff baseline, stable across re-runs.
5. `<project-map>` = `ls -d */` without `.devbox`, `.venv`, `.git`, `node_modules`. Prepend it to every subagent prompt.
6. Status: `approved` → `cplat spec set-status <id> building` and commit `docs(spec): start building <spec_id>`. `building` → this is a resume: print which tasks are already `done` (`cplat spec list --json`).

Do not wait for CI on `main`.

## Phase 1 — Acceptance tests (red)

`cplat runs phase build:tests`

**Skip** (resume) when `cplat spec trace <id>` already passes: every criterion has a test.

**tester** agent (`agents.tester`), prompt: "**Acceptance mode.** `SPEC_DIR: docs/specs/<spec_id>/`" + `<project-map>`. It writes criterion-tagged tests against the spec and `design.md`'s contract, confirms they fail because the behaviour is missing, and commits only test files.

Then:
- `cplat spec trace <id>` must pass; otherwise send the missing ids back to the tester (once).
- `devbox run test-fast`: the new tests fail, nothing else newly fails. A test that errors for another reason goes back to the tester.
- Then record the tester's misses with one call, also when there were none: `cplat runs agent tester [--untraced <AC>]... [--wrong-failure <test>]...` (one `--untraced` for each criterion id sent back, one `--wrong-failure` for each test sent back).
- `cplat spec trace <id> --json` → hold `TRACE` (criterion → test files) for Phase 2.
- `RED=$(git log -1 --format=%H --grep 'acceptance tests for')` — the commit the acceptance tests are measured against from now on (spec 048).

## Phase 2 — Implement (parallel via git worktrees)

`cplat runs phase build:implement`

### 2.1 Schedule

From `plan.md`: **skip tasks with `done: true`**. Run `cplat build schedule <id>` and print its output verbatim: the remaining tasks in levels, batched by `parallel_safe` with disjoint `files`, gitops tasks apart, and the re-plans used so far. Run the batches in that order.

### 2.2 Worktree probe

Before the first parallel batch, record `FEATURE_HEAD=$(git rev-parse HEAD)` and run a throwaway Agent with `isolation: "worktree"` whose one task is to report `git rev-parse HEAD` in its worktree.

- It errors ("Cannot create agent worktree", "not in a git repository") → run every task sequentially on `$FEATURE_BRANCH` and note it in the Final Report (restart the session for parallelism).
- It reports a HEAD other than `$FEATURE_HEAD` → coders would not see the spec, the plan or the acceptance tests. Run every task sequentially and say in the Final Report: `worktree base is <sha>, not the feature head; set worktree.baseRef: "head" in .claude/settings.json (/shared:update-service)`.
- It reports `$FEATURE_HEAD` → parallel batches are safe: every task branch starts at the feature head, so merging it brings only that task's commits.

### 2.3 Coder prompt (every task)

- `<project-map>`; `SPEC_DIR`; the task's `id`, prose section verbatim, `files` (touch nothing else except new test helpers you must report).
- **Done when:** the acceptance tests naming the task's `covers` criteria pass (`devbox run test-fast`); list those test files from `TRACE`. A criterion that also depends on a not-yet-done task may still fail: the coder says which and why.
- "Never edit, skip or weaken the acceptance tests."
- A task that was re-planned after a merge conflict (`cplat build state <id> --json`: a `replans[].tasks[]` entry that is not merged) also gets: "This task was re-planned after a merge conflict on `<paths>` with `<with>`. Start from the feature branch, which already contains every merged task. Your earlier attempt is a reference only. Do not merge or cherry-pick it:" followed by the output of `git diff HEAD...<branch>`, with `<branch>` from that state output.
- Parallel batch only: "You are in an isolated worktree. Commit locally (`git add` + `git commit -s -m '<type>(<scope>): <title>'`, task id in the body; the sign-off `-s` is required) before returning. Do not push. Do not switch branches."

### 2.4 Run batches

**Parallel batch (≥ 2 tasks):** one coder per task **in a single message**, each with `isolation: "worktree"`. Collect `(branch, worktree_path)` from those that changed something. Then for each, in order:
1. `cplat build merge <id> <task> <branch> [--helper <path>]...` (one `--helper` for each new test helper the coder reported). It merges with `--no-ff`, records `merged` (spec 089) and, on a conflict, does what `cplat runs agent conflict <task>` and `git merge --abort` would (it aborts the merge first, then records the conflict) and sets the task aside. Exit 0 → continue with step 2. Exit 3 → the task is set aside: leave its worktree and branch in place and continue with the next branch of the batch. Exit 4 → `cplat runs end --outcome escalated --reason '<the ESCALATE line>'` and stop. Never resolve a conflict yourself.
2. `devbox run lint-fix`, stage; then `cplat spec test-diff $RED --task <task>`: acceptance tests may only have changed in formatting. Exit 1 means a test was weakened or changed: stop and show the user the file and the reason (spec 048); never decide yourself that it is a false alarm — since spec 063 it only looks at test files, so a failure is real. Then `devbox run quality` — failures go back to that task's coder (lint/type fixes only; record each hand-back with `cplat runs agent fix-round lint/type --task <task>`).
3. `devbox run test-fast` — integration failures go back to the coder with the output (`cplat runs agent fix-round test --task <task>`).
4. `git worktree remove <path>`; `git branch -d <branch>`. A set-aside branch is removed by `cplat build resolved`, not here.

**Sequential task:** `PRE=$(git rev-parse HEAD)`, then one coder without isolation on `$FEATURE_BRANCH`; commit for it if it did not, then `cplat runs agent merged <task> --since $PRE [--helper <path>]...`. Run `cplat spec test-diff $RED --task <task>` (exit 1 stops the build, as in the parallel batch) and record hand-backs as above.

After each task is merged and green: `cplat spec task-done <id> <task-id>`, then `cplat build resolved <id> <task-id>` (removes the branch and worktree of a re-planned task; it does nothing for any other). Then commit `chore(plan): <spec_id> <task id> done` with that task's lint-fix changes: one commit per task, so the next merge starts from a clean tree.

### 2.4a Re-plan after a conflict

After a batch in which `cplat build merge` set a task aside (exit 3), re-plan **without asking the user**, in an attended build as well as an unattended one:

1. Spawn the **architect** (`agents.architect`) with the prompt `**Re-plan mode.**` + `<project-map>` + `SPEC_DIR` + the output of `cplat build state <id>` (the pending conflicts: task, the task it collided with, the paths) + "Change only `files`, `depends_on` and `parallel_safe` of tasks that are not done; anything else is a BLOCKER." Then `cplat runs agent spawned architect`.
2. `cplat build replan-commit <id>`. On exit 1, send its errors to the architect once and call it again.
3. The architect reports a BLOCKER, or the second call also exits 1 → `cplat build replan-abort <id> --reason '<the blockers or errors>'`, then `cplat runs end --outcome escalated --reason '<its ESCALATE line>'` and stop.
4. Exit 0 → continue from the schedule it printed. The set-aside task runs again on top of the merged work (coder prompt in 2.3).

### 2.5 All green

`devbox run test-fast`: every acceptance test passes. Failing ones go to the coder of a task that `covers` that criterion (at most 2 rounds, each recorded with `cplat runs agent fix-round test --task <task>`); then escalate.

When every acceptance test passes, run `cplat runs gate acceptance passed`. Before escalating because they still fail after the fix rounds, run `cplat runs gate acceptance failed` (spec 099).

`TOUCHED_FILES=$(git diff --name-only $BASE_REF..HEAD)`.

## Phase 3 — QA: one CI gate, agents only where it is red (spec 080)

`cplat runs phase build:qa`

1. Stage the tree (`git add -u`, plus new files the build created), then run `devbox run lint-fix` and `devbox run ci`: the gates the CI workflow runs, in its order, each once.
2. **Red** → spawn only the agent that owns the red gate, with `<project-map>`, `<touched-files>` and the output's tail:
   - lint or type check → **quality** (`agents.quality`): lint/type fixes only;
   - tests → the **coder** of the task whose files are involved: acceptance tests stay fixed; record it with `cplat runs agent fix-round ci --task <task>`;
   - security → run `cplat deps patch` first (ADR-034): it bumps every fixable dependency finding, re-runs the gates and commits, or reverts. Exit 0 → the gate is green, go to step 3. Exit 3 → escalate with the `ESCALATE` reason and the `CAUSE` it printed: in a `/svc:ship` run `cplat ship escalate '<reason>' --cause <CAUSE>`, alone `cplat runs end --outcome escalated --reason '<reason>' --cause <CAUSE>`. Exit 4 → not a dependency finding (secrets, bandit, image scan): the **security** agent (`agents.security`) handles it as before: a CRITICAL secrets or bandit finding escalates at once; HIGH is documented and the build continues. A red gate after a bump is never handed to a coder, and acceptance tests stay fixed. Patch rounds (at most 2, counted by cplat) are separate from the 2 fix rounds below.

   Run `devbox run ci` again; at most 2 rounds, then escalate.

   When `devbox run ci` is green, run `cplat runs gate security passed`. When the security gate stays red (escalation, or a HIGH finding documented while the build goes on), run `cplat runs gate security failed` first (spec 099).
3. **Green** → spawn agents only where needed:
   - **tester** (`agents.tester`, normal mode) only when the touched files add internals that no unit test covers: it adds those tests and runs `devbox run test`;
   - **security** only when a Dockerfile changed (`devbox run image-build && devbox run image-scan`), writing `docs/security/scan-<today>.md`.
4. `cplat spec test-diff $RED` once more (`lint-fix` may have reformatted), with `--by quality` when the quality agent changed files in this phase's rounds; exit 1 stops the build as in Phase 2. Commit what changed.

## Phase 4 — Verify against the spec

`cplat runs phase build:verify`

1. `cplat spec trace <id> --json` must pass.
2. **reviewer** (`agents.reviewer`), prompt: `SPEC_DIR`, `BASE_REF`, `<touched-files>`, the trace JSON and the Phase 3 test summary. After each reviewer pass (cycle `<n>` = 1, 2): `cplat runs agent findings --cycle <n> [--deviation <AC or task>]...` for the deviations it judged not acceptable.
3. `RESULT: fail` → send each `NOT MET` item to the coder of a task covering that criterion (`cplat runs agent fix-round verification --task <task>` for each), re-run `devbox run test-fast` and the reviewer. At most 2 cycles; then stop and escalate with `verification.md`.
4. Commit `docs/specs/<spec_id>/verification.md`: `docs(spec): verify <spec_id>`.

## Phase 5 — Container image

`cplat runs phase build:image`

Skip with `## Phase 5 skipped — <shape> is not deployable` when `deployable` is false. Otherwise **deployment** (`agents.deployment`) with `<project-map>` + `<touched-files>`: verify or update the image only — Dockerfile (numeric `USER`, read-only-filesystem friendly), the CI docker job, needed `devbox run` recipes; **never Kubernetes manifests** (the product's gitops-app repo owns them, ADR-017). Run `devbox run image-build` and smoke-start the image. If the port, probe paths or user changed, say that the gitops `services.yaml` entry must change. Ask for gitops changes **only for** wiring the spec's *Provided by the product* list (in the Product context of a repo spec sliced from a product plan) does not already contain: env variables, addons and exposure listed there exist (spec 052).

## Phase 6 — Close the spec

`cplat runs phase build:close`

1. `cplat spec set-status <id> done`.
2. `cplat spec index` (refreshes the table in `docs/backlog.md`). If it refuses because the backlog still holds legacy `STORY-NNN` stories, skip it and mention `/svc:specs migrate` in the Final Report.
3. Commit: `docs(spec): <spec_id> done`.

## Phase 7 — Pull request

`cplat runs phase build:pr`

1. Write the PR body to `.git/PR_BODY.md` (`{{CLOSES}}` stands where the issue lines go; the command fills them from the spec's `tracks:` and the branch's commits):

   ```markdown
   ## Summary

   <3–5 sentences: the problem from the spec, what was built, how a user or operator uses it — endpoints, flags, config, responses.>

   **Spec:** [docs/specs/<spec_id>/spec.md](docs/specs/<spec_id>/spec.md) · **Plan:** plan.md · **Verification:** verification.md

   | Criterion | Verdict | Test |
   |---|---|---|
   <one row per criterion, copied from verification.md>

   ## Type of change

   - [x] feat — new user-visible feature

   ## Related issues

   {{CLOSES}}

   ## Testing done

   <acceptance tests per criterion; N tests total, X% coverage; security PASS/WARN>

   <output of `cplat deps report`: the "Dependency patches" section, after the criteria table; empty when nothing was bumped>

   ## Checklist

   - [x] Acceptance tests were written from the approved spec before the code
   - [x] `devbox run quality` passes
   - [x] `devbox run test` passes with coverage ≥ 80%
   - [x] `devbox run security` passes (fixable dependency findings patched, see Dependency patches)
   - [x] No secrets, credentials, or API keys committed
   ```

2. Make **one** Bash call; it commits what is left with `-s`, pushes the feature branch, opens the PR and adds "Contains WIP commits from an interrupted build: squash-merge." to the body when the branch has `wip(` commits (spec 047):

   ```bash
   cplat pr open --spec <spec_id> --title "feat(<scope>): <spec title, ≤72 chars>"
   ```

   Relay its three lines (`commit:`, `push:`, `pr:`). Exit 1: report which part failed and stop; `pr: failed: already open <url>` means the PR exists, so use that URL. Exit 2: fix the reason it prints, then call it again. A re-run never makes a second commit or PR.

   **`pr: ready: <command>`** (headless run, untrusted workspace, or `gh pr create` not allowed; spec 051) is not an error: the branch is pushed and the body is in `.git/PR_BODY.md`. End the report with that exact command as its last line.

## Final Report

```
## Build complete: <spec_id> — <title>

| Phase | Output |
|---|---|
| Acceptance tests | <n> tests for <m> criteria, red at <short sha> |
| Implementation | <n> tasks (<p> parallel, <s> sequential), <files> files[ · plan amended <n>× after merge conflicts: <task>: <files> (re-run merged cleanly)] |
| QA | `devbox run ci` green in <n> round(s) · agents: <none | which> |
| Verification | <m>/<m> criteria met (verification.md) |
| Image | built and smoke-started | skipped |
| PR | <URL> |

<the Dependency patches table from `cplat deps report`, when the run bumped anything>

### Next steps
<gitops change needed (services.yaml / /gitops:promote after release), HIGH findings, sequential fallback, `/svc:specs migrate` hint>
```

The bracketed part of the Implementation row is added, attended builds too, only when `cplat build state <id>` shows a re-plan count of 1 or more: one `<task>: <files>` entry per re-planned task.

## Rules

- **Every stop and the end are recorded** with `cplat runs end` (Phase 0), so no run goes missing.
- **Only approved specs are built**, and only as planned. A decision the spec does not answer stops the build: `/svc:spec --amend`, then `/svc:plan` again.
- **Acceptance tests are fixed** once Phase 1 committed them. If one is wrong, stop and take it to the user; a changed test is a changed spec.
- **Push only in Phase 7**; `cplat pr open` pushes the feature branch and opens the PR (or ends at a ready PR), so a headless build needs no further prompt.
- **A merge conflict is re-planned once per task (at most 3 re-plans per build), then escalated; it is never resolved by hand.** `cplat build merge` aborts the merge and sets the task aside; the architect amends only the plan and the task runs again on top of the merged work, without asking. Never edit conflicting hunks.
- **Every shell command goes through `devbox run <script>`** (see `CLAUDE.md`), except git, gh and `cplat`.
- **No `--no-verify`, no `--no-gpg-sign`.**

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/shared:report-issue` so the user can file it. Never file anything without their OK.
