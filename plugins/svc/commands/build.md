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

**Skip** (resume) when `cplat spec trace <id>` already passes: every criterion has a test.

**tester** agent (`agents.tester`), prompt: "**Acceptance mode.** `SPEC_DIR: docs/specs/<spec_id>/`" + `<project-map>`. It writes criterion-tagged tests against the spec and `design.md`'s contract, confirms they fail because the behaviour is missing, and commits only test files.

Then:
- `cplat spec trace <id>` must pass; otherwise send the missing ids back to the tester (once).
- `devbox run test-fast`: the new tests fail, nothing else newly fails. A test that errors for another reason goes back to the tester.
- `cplat spec trace <id> --json` → hold `TRACE` (criterion → test files) for Phase 2.
- `RED=$(git log -1 --format=%H --grep 'acceptance tests for')` — the commit the acceptance tests are measured against from now on (spec 048).

## Phase 2 — Implement (parallel via git worktrees)

### 2.1 Schedule

From `plan.md`: **skip tasks with `done: true`**. Topologically sort the rest by `depends_on`, group into levels, and within a level batch `parallel_safe` tasks with disjoint `files` (a task joins a batch only if its files are disjoint from every other task in it; otherwise it runs alone). Print the schedule as a table.

### 2.2 Worktree probe

Before the first parallel batch, record `FEATURE_HEAD=$(git rev-parse HEAD)` and run a throwaway Agent with `isolation: "worktree"` whose one task is to report `git rev-parse HEAD` in its worktree.

- It errors ("Cannot create agent worktree", "not in a git repository") → run every task sequentially on `$FEATURE_BRANCH` and note it in the Final Report (restart the session for parallelism).
- It reports a HEAD other than `$FEATURE_HEAD` → coders would not see the spec, the plan or the acceptance tests. Run every task sequentially and say in the Final Report: `worktree base is <sha>, not the feature head; set worktree.baseRef: "head" in .claude/settings.json (/shared:update-service)`.
- It reports `$FEATURE_HEAD` → parallel batches are safe: every task branch starts at the feature head, so merging it brings only that task's commits.

### 2.3 Coder prompt (every task)

- `<project-map>`; `SPEC_DIR`; the task's `id`, prose section verbatim, `files` (touch nothing else except new test helpers you must report).
- **Done when:** the acceptance tests naming the task's `covers` criteria pass (`devbox run test-fast`); list those test files from `TRACE`. A criterion that also depends on a not-yet-done task may still fail: the coder says which and why.
- "Never edit, skip or weaken the acceptance tests."
- Parallel batch only: "You are in an isolated worktree. Commit locally (`git add` + `git commit -m '<type>(<scope>): <title>'`, task id in the body) before returning. Do not push. Do not switch branches."

### 2.4 Run batches

**Parallel batch (≥ 2 tasks):** one coder per task **in a single message**, each with `isolation: "worktree"`. Collect `(branch, worktree_path)` from those that changed something. Then for each, in order:
1. `git merge --no-ff --no-edit <branch>` — a conflict means the plan's `files` were wrong: `git merge --abort`, stop and escalate. Never resolve it yourself.
2. `devbox run lint-fix`, stage; then `cplat spec test-diff $RED`: acceptance tests may only have changed in formatting. Exit 1 means a test was weakened or changed: stop and show the user the file and the reason (spec 048); never decide yourself that it is a false alarm — since spec 063 it only looks at test files, so a failure is real. Then `devbox run quality` — failures go back to that task's coder (lint/type fixes only).
3. `devbox run test-fast` — integration failures go back to the coder with the output.
4. `git worktree remove <path>`; `git branch -d <branch>`.

**Sequential task:** one coder without isolation on `$FEATURE_BRANCH`; commit for it if it did not.

After each task is merged and green: `cplat spec task-done <id> <task-id>`; commit the plan change together with the batch: `chore(plan): <spec_id> <task ids> done`.

### 2.5 All green

`devbox run test-fast`: every acceptance test passes. Failing ones go to the coder of a task that `covers` that criterion (at most 2 rounds); then escalate.

`TOUCHED_FILES=$(git diff --name-only $BASE_REF..HEAD)`.

## Phase 3 — QA fan-out (quality ‖ tester ‖ security)

Spawn all three **in one message**, each with `<project-map>` and `<touched-files>`:

1. **quality** (`agents.quality`): "Run `devbox run lint-fix` then `devbox run quality`. Report remaining violations."
2. **tester** (`agents.tester`): "Normal mode. The acceptance tests exist; do not change them. Add unit/integration tests for internals the touched files need, run `devbox run test`, report pass/fail, coverage and open bugs."
3. **security** (`agents.security`): "Run `devbox run security`. If a Dockerfile changed, also `devbox run image-build && devbox run image-scan`. Document findings in `docs/security/scan-<today>.md`."

Reconcile: quality failures → coder (lint/type only), tester bugs → coder; at most 2 cycles each. **CRITICAL** security findings → stop and escalate. **HIGH** → document and continue. Refresh `TOUCHED_FILES` if files changed.

After the fan-out, run `cplat spec test-diff $RED` once more (the quality agent ran `lint-fix` too); exit 1 stops the build as in Phase 2.

**CI gate:** stage the tree (`git add -u`, plus new files the build created) and run `devbox run ci` once: the same gates the CI workflow runs, so a red check is found here and not after a push. Red → the coder of the touched task (lint, test or baseline fixes only; acceptance tests stay fixed), at most 2 rounds; then escalate. Commit what it changed.

## Phase 4 — Verify against the spec

1. `cplat spec trace <id> --json` must pass.
2. **reviewer** (`agents.reviewer`), prompt: `SPEC_DIR`, `BASE_REF`, `<touched-files>`, the trace JSON and the Phase 3 test summary.
3. `RESULT: fail` → send each `NOT MET` item to the coder of a task covering that criterion, re-run `devbox run test-fast` and the reviewer. At most 2 cycles; then stop and escalate with `verification.md`.
4. Commit `docs/specs/<spec_id>/verification.md`: `docs(spec): verify <spec_id>`.

## Phase 5 — Container image

Skip with `## Phase 5 skipped — <shape> is not deployable` when `deployable` is false. Otherwise **deployment** (`agents.deployment`) with `<project-map>` + `<touched-files>`: verify or update the image only — Dockerfile (numeric `USER`, read-only-filesystem friendly), the CI docker job, needed `devbox run` recipes; **never Kubernetes manifests** (the product's gitops-app repo owns them, ADR-017). Run `devbox run image-build` and smoke-start the image. If the port, probe paths or user changed, say that the gitops `services.yaml` entry must change. Ask for gitops changes **only for** wiring the spec's *Provided by the product* list (in the Product context of a repo spec sliced from a product plan) does not already contain: env variables, addons and exposure listed there exist (spec 052).

## Phase 6 — Close the spec

1. `cplat spec set-status <id> done`.
2. `cplat spec index` (refreshes the table in `docs/backlog.md`). If it refuses because the backlog still holds legacy `STORY-NNN` stories, skip it and mention `/svc:specs migrate` in the Final Report.
3. Commit: `docs(spec): <spec_id> done`.

## Phase 7 — Pull request

1. **Issues:** `tracks:` from the spec plus `#NNN` in `git log $BASE_REF..HEAD --format=%B`; keep those `gh issue view <n> --json state -q .state` reports `OPEN`. Build the `Closes #N` lines or `N/A`.
2. `git push -u origin $FEATURE_BRANCH` (asks for confirmation).
3. `gh pr create` (asks for confirmation), title `feat(<scope>): <spec title, ≤72 chars>` (Conventional Commits), body:

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

   <Closes lines or N/A>

   ## Testing done

   <acceptance tests per criterion; N tests total, X% coverage; security PASS/WARN>

   ## Checklist

   - [x] Acceptance tests were written from the approved spec before the code
   - [x] `devbox run quality` passes
   - [x] `devbox run test` passes with coverage ≥ 80%
   - [x] `devbox run security` passes (no CRITICAL findings)
   - [x] No secrets, credentials, or API keys committed
   ```

**When `gh pr create` is not allowed** (headless run, untrusted workspace, or the user declines; spec 051): this is not an error. The branch is pushed; write the PR body to `.git/PR_BODY.md` and end the report with the exact command as its last line: `gh pr create --base main --head <branch> --title "<title>" --body-file .git/PR_BODY.md`.

4. Print the PR URL. If the branch has `wip(` commits (an interrupted build, spec 047), the PR body ends with: "Contains WIP commits from an interrupted build: squash-merge."

## Final Report

```
## Build complete: <spec_id> — <title>

| Phase | Output |
|---|---|
| Acceptance tests | <n> tests for <m> criteria, red at <short sha> |
| Implementation | <n> tasks (<p> parallel, <s> sequential), <files> files |
| QA | quality PASS · tests N (X% cov) · security PASS/WARN |
| Verification | <m>/<m> criteria met (verification.md) |
| Image | built and smoke-started | skipped |
| PR | <URL> |

### Next steps
<gitops change needed (services.yaml / /gitops:promote after release), HIGH findings, sequential fallback, `/svc:specs migrate` hint>
```

## Rules

- **Only approved specs are built**, and only as planned. A decision the spec does not answer stops the build: `/svc:spec --amend`, then `/svc:plan` again.
- **Acceptance tests are fixed** once Phase 1 committed them. If one is wrong, stop and take it to the user; a changed test is a changed spec.
- **Push only in Phase 7**; `git push` and `gh pr create` require confirmation.
- **Never resolve merge conflicts automatically**; they mean the plan's `files` were wrong.
- **Every shell command goes through `devbox run <script>`** (see `CLAUDE.md`), except git, gh and `cplat`.
- **No `--no-verify`, no `--no-gpg-sign`.**

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/shared:report-issue` so the user can file it. Never file anything without their OK.
