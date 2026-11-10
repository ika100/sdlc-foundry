---
description: "Build an approved, planned spec: failing acceptance tests first, then coders until they pass, quality/tests/security, verification, PR. Usage: /component:build <spec-id> [--full]"
---

You are the **build orchestrator** ([ADR-026](../../../docs/adr/026-feature-specs.md)): the approved spec's criteria become failing tests, coders make them pass, the result is proven against the spec, then one PR. Delegate all code and test writing to subagents.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Spec:** $ARGUMENTS (number, slug or full id; empty → `cplat spec list` and ask which). `--full` → pass it to `cplat validate run`. `--unit <unit>`: only that unit, per `${CLAUDE_PLUGIN_ROOT}/references/unit-mode.md`.

Run the phases in order; after each print `## Phase N complete — <one line>`. A re-run **resumes**: a phase whose result exists is skipped.

## cplat

`cplat` is on the Bash PATH; one call per Bash invocation, output read whole (no `grep`, `head` or `tail`). First `cplat shape`: JSON with `shape`, `plugin`, `deployable`, `library`, `agents` (spawn each role with exactly that type; roles missing from it are skipped). `unsupported` or no shape → stop.

- A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape. Asking is pointless because the user declared it.

## Phase 0 — Pre-flight

0. `cplat platform runs begin build --spec <id>` (attaches to a `/component:ship` run). Every stop that needs the user or fails first runs `cplat platform runs end --outcome escalated --reason '<why>'` (`--outcome failed` for a hard failure); the end runs `cplat platform runs end --outcome done`. After every subagent: `cplat platform runs agent spawned <role> [--model-id <id>]`.
1. `git status --porcelain`: dirty on a spec whose status is not `building` → stop: commit or stash first (clean tree). Dirty on a `building` spec (interrupted build) → read `${CLAUDE_PLUGIN_ROOT}/references/build-resume.md` and follow it (stale staged files: `git restore --staged`; WIP commit: `wip(<task-id>): interrupted`).
2. `cplat spec check <id> --require approved` must pass and `docs/specs/<spec_id>/plan.md` exist; otherwise stop with the fix (`/component:spec approve <NNN>`, `/component:plan <NNN>`; `/component:plan <NNN>` again for `spec_hash` drift).
3. Switch to `feature/<spec_id>` (create it from `main` if missing) = `$FEATURE_BRANCH`. `BASE_REF=$(git merge-base main HEAD)`.
4. `<project-map>` = `ls -d */` without `.devbox`, `.venv`, `.git`, `node_modules`; prepend it to every subagent prompt.
5. `approved` → `cplat spec set-status <id> building`, commit `docs(spec): start building <spec_id>`. `building` → resume: print the `done` tasks (`cplat spec list --json`).

Do not wait for CI on `main`, because the build runs on the feature branch.

## Phase 1 — Acceptance tests (red)

`cplat platform runs phase build:tests`. **Skip** when `cplat spec trace <id>` already passes.

**tester** (`agents.tester`): "**Acceptance mode.**" + `<project-map>` + the brief: `Criteria` (every active criterion in full, and the non-goals), `Contract` (`design.md`'s contract, verbatim), `Commands` (`cplat quiet test-fast`). It writes criterion-tagged tests (a `(smoke)` criterion also gets its smoke test, base URL only), confirms they fail because the behaviour is missing, and commits only test files. Then:
- `cplat spec trace <id>` must pass; else the missing ids go back to the tester once, so that every criterion has a red test.
- `cplat quiet test-fast`: the new tests fail, nothing else newly fails; a test erroring for another reason goes back.
- Trace files `test-fast` does not run (Playwright specs under `e2e/`): `cplat quiet e2e` once; one failing before any assertion about the missing behaviour goes back as a wrong failure.
- One call, even with no misses: `cplat platform runs agent tester [--untraced <AC>]... [--wrong-failure <test>]...`.
- `cplat spec trace <id> --json` → `TRACE` (criterion → test files).
- `cplat quiet lint-fix`; commit changed tests as `test(<slug>): lint-fix acceptance tests for <id>`. `RED=$(git log -1 --format=%H --grep 'acceptance tests for')`.

## Phase 2 — Implement (parallel via git worktrees)

`cplat platform runs phase build:implement`

### 2.1 Schedule

From `plan.md`, **skip tasks with `done: true`**. Print `cplat component build schedule <id>` verbatim; run its batches in that order.

### 2.2 Worktree probe

Before the first parallel batch, a probe Agent with `isolation: "worktree"` reports `git rev-parse HEAD`. It errors → read `${CLAUDE_PLUGIN_ROOT}/references/build-worktree-fallback.md` (sequential). Otherwise `cplat platform runs agent execution parallel`; a HEAD other than `$FEATURE_HEAD` (no `worktree.baseRef: "head"`) is fine (#501): coders reset to it, so that a merge brings only that task's commits.

### 2.3 Coder prompt (every task)

- `<project-map>` and the **brief**, copied from `spec.md`, `plan.md` and `design.md` you read once in Phase 0 (never tell the coder to read them, so that its context stays small): `Criteria` (id and full text of each criterion in the task's `covers`), `Task` (`id`, prose section verbatim, `files`; touch nothing else, and report any new test helper), `Contract` (the `design.md` sections it touches, verbatim, or `none`), `Tests` (from `TRACE`), `Commands` (`cplat quiet test-fast`, `cplat quiet quality`).
- **Done when:** the acceptance tests of its `covers` criteria pass (`cplat quiet test-fast`; name the files from `TRACE`). One that also depends on a not-yet-done task may still fail: the coder says which and why.
- "**Hard rule:** never edit, skip or weaken the acceptance tests, because they are the approved criteria. A linter false positive in one gets the linter's line suppression naming the rule, nothing else (spec 160); name the suppressed rules in the commit."
- A re-planned task (a `replans[].tasks[]` entry in `cplat component build state <id> --json` not yet merged) → read `${CLAUDE_PLUGIN_ROOT}/references/build-replan.md` and add its text to the prompt.
- Parallel batch only (`FEATURE_HEAD` = HEAD before the batch): "You are in an isolated worktree. First `cplat component build reset <FEATURE_HEAD>`. Commit locally (`git add` + `git commit -s -m '<type>(<scope>): <title>'`, task id in the body; `-s` is required) before returning. **Hard rule:** do not push or switch branches, because `cplat pr open` pushes after its checks."

### 2.4 Run batches

**Parallel batch (≥ 2 tasks):** one coder per task **in a single message**, each `isolation: "worktree"`. For each `(branch, worktree_path)` that changed something, in order:
1. `cplat component build merge <id> <task> <branch> [--helper <path>]...`. On a conflict it aborts and sets the task aside (as `cplat platform runs agent conflict <task>` and `git merge --abort` would). Exit 0 → step 2. Exit 3 → set aside: leave its worktree and branch, go on with the next branch. Exit 4 → `cplat platform runs end --outcome escalated --reason '<the ESCALATE line>'` and stop.
2. `cplat quiet lint-fix`, stage; `cplat spec test-diff $RED --task <task>`: exit 1 means a test was weakened or changed: stop and show the user the file and the reason (a `test helper` line: `build-tighten.md` instead). **Hard rule:** never decide yourself that it is a false alarm, because a changed test is a changed spec. The user approves it → read `${CLAUDE_PLUGIN_ROOT}/references/build-test-approval.md`. Then `cplat quiet quality`; failures go back to that coder (lint/type only; `cplat platform runs agent fix-round lint/type --task <task>`).
3. `cplat validate run` (only what this change can affect); failures go back to the coder (`cplat platform runs agent fix-round test --task <task>`).
4. `git worktree remove <path>`; `git branch -d <branch>`.

**Sequential task:** `PRE=$(git rev-parse HEAD)`, one coder without isolation on `$FEATURE_BRANCH`; commit for it if it did not, then `cplat platform runs agent merged <task> --since $PRE [--helper <path>]...`. `cplat spec test-diff $RED --task <task>` (exit 1 stops the build, as above) and hand-backs as above.

Each task merged and green: `cplat spec task-done <id> <task-id>`, `cplat component build resolved <id> <task-id>`, commit `chore(plan): <spec_id> <task id> done` with its lint-fix changes.

### 2.4a Re-plan after a conflict

Merge exit 3 or a task in `replans[]` → read `${CLAUDE_PLUGIN_ROOT}/references/build-replan.md` and follow it (`cplat component build replan-commit`; a BLOCKER → `cplat component build replan-abort`): re-plan **without asking the user**, attended or not.

### 2.5 All green

`cplat quiet test-fast`: every acceptance test passes. Failing ones go to a coder of a task covering that criterion (at most 2 rounds, each `cplat platform runs agent fix-round test --task <task>`), then escalate. All pass → `cplat platform runs gate acceptance passed`; before escalating on them → `cplat platform runs gate acceptance failed`.

`TOUCHED_FILES=$(git diff --name-only $BASE_REF..HEAD)`.

## Phase 3 — QA: one CI gate, agents only where it is red

`cplat platform runs phase build:qa`

1. Stage the tree (`git add -u` plus new files), then `devbox run lint-fix` and `devbox run ci` as `cplat quiet lint-fix` and `cplat quiet ci`: the CI gates, in order, once each.
2. **Red** → `cplat validate final --check <name> failed` per failed check, then spawn only the agent that owns the red gate, with `<project-map>`, `<touched-files>`, the summary and log path `cplat quiet` printed (the log when the summary is not enough), so that no green gate is touched:
   - lint or type → **quality** (`agents.quality`), lint/type fixes only;
   - tests → the **coder** of the task whose files are involved (acceptance tests stay fixed; `cplat platform runs agent fix-round ci --task <task>`);
   - security → `cplat deps patch` first (ADR-034), then read `${CLAUDE_PLUGIN_ROOT}/references/build-security-red.md` and follow it (exit 0 → step 3; exit 3 → escalate with its `ESCALATE` reason and `--cause <CAUSE>`, via `cplat component ship escalate` in a ship run, else `cplat platform runs end --outcome escalated`; exit 4 → **security** agent). A red gate after a bump never goes to a coder, because a dependency is at fault, and acceptance tests stay fixed.

   Between fix rounds: `cplat validate run`, then `cplat quiet ci` (whole, so that a fix cannot hide a new failure; record failures as above); at most 2 rounds, then escalate. After a red round follow `${CLAUDE_PLUGIN_ROOT}/references/build-red-rounds.md`; record gates with `cplat budget stage <name> passed|failed`. `cplat quiet ci` green → `cplat platform runs gate security passed`; the security gate stays red (escalation, or a HIGH finding documented while the build goes on) → `cplat platform runs gate security failed` first.
3. **Green** → agents only where needed: **tester** (`agents.tester`, normal mode) so that every new internal has a unit test (adds them, runs `devbox run test`); **security** so that a changed Dockerfile is built and scanned (`devbox run image-build && devbox run image-scan`, writes `docs/security/scan-<today>.md`).
4. `cplat spec test-diff $RED` again (`--by quality` when the quality agent changed files here); exit 1 stops as in Phase 2. Commit what changed.

## Phase 4 — Verify against the spec

`cplat platform runs phase build:verify`

1. `cplat spec trace <id> --json` must pass, so that every criterion has its test.
2. **reviewer** (`agents.reviewer`): `SPEC_DIR`, `BASE_REF`, `<touched-files>`, the trace JSON, the Phase 3 test summary, and `SUPPRESSIONS`: the `lint suppression only` lines of the last test diff (Phase 3, step 4), or `none`, and `TIGHTENED` (`build-tighten.md`) or `none`. After each pass (cycle `<n>`): `cplat platform runs agent findings --cycle <n> [--deviation <AC or task>]...` for deviations not acceptable.
3. A `NOT MET` item marked `TEST LOOSER` → read `${CLAUDE_PLUGIN_ROOT}/references/build-tighten.md` and follow it. `RESULT: fail` → each other `NOT MET` item to a coder of a covering task (`cplat platform runs agent fix-round verification --task <task>`), then `cplat quiet test-fast` and the reviewer; at most 2 cycles, then escalate with `verification.md`.
4. `cplat spec mutate <id> --write` (report only: written into `verification.md`; it never fails the build).
5. Commit `docs/specs/<spec_id>/verification.md`: `docs(spec): verify <spec_id>`.

## Phase 5 — Container image

`cplat platform runs phase build:image`. Skip with `## Phase 5 skipped — <shape> is not deployable` when `deployable` is false. Otherwise **deployment** (`agents.deployment`) with `<project-map>` + `<touched-files>`: the image (numeric `USER`, read-only-filesystem friendly; the CI docker job; `devbox run` recipes). **Hard rule:** never Kubernetes manifests, because the gitops repo owns the cluster (ADR-017). `devbox run image-build`, smoke-start the image. A changed port, probe path or user → say the `system.yaml` entry must change (`/component:set`). Ask for gitops changes only for wiring not in the spec's *Provided by the system* list, since the system already provides that.

## Phase 6 — Close the spec

`cplat platform runs phase build:close`. `cplat spec set-status <id> done`; `cplat spec index` (refused while the backlog holds `STORY-NNN` stories: skip it, mention `/component:spec migrate`); commit `docs(spec): <spec_id> done`.

## Phase 7 — Pull request

`cplat platform runs phase build:pr`, then read `${CLAUDE_PLUGIN_ROOT}/references/build-pr.md` and follow it: the body in `.pr-body.md`, one `cplat pr open --spec <spec_id>` call (it adds the generated "How this was built" block), the Final Report.

## Rules

- **Hard rule:** only approved specs are built, and only as planned, because approval is the user's consent. A decision the spec does not answer stops the build: `/component:spec --amend`, then `/component:plan` again.
- **Hard rule:** push only in Phase 7, through `cplat pr open`, because it runs every check first.
- **Hard rule:** Never edit conflicting hunks: a merge conflict is re-planned once per task (at most 3 re-plans per build), then escalated; it is never resolved by hand, because the plan split the work wrongly.
- **Subagents run in the foreground** (`run_in_background: false`; a batch is several Agent calls in one message); never poll for one in a shell loop, because such a loop can wait forever.
- **Shell rule:** run every tool through `devbox run <script>`, never `pytest`, `ruff` or `uv` directly, so that versions and flags match CI (git, gh and `cplat` run directly).
- **Hard rule:** never use `--no-verify` or `--no-gpg-sign`, because a skipped hook leaves no trace.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
