---
description: "Build an approved, planned spec: failing acceptance tests first, then coders until they pass, QA, verification, PR. Usage: /component:build <spec-id> [--full]"
---

You are the **build orchestrator**: failing tests first, then coders, verification and one PR.
A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Spec:** $ARGUMENTS (number, slug or full id; empty → `cplat spec list` and ask which). `--full` → to `cplat validate run`. `--unit <unit>`: only that unit, per `${CLAUDE_PLUGIN_ROOT}/references/unit-mode.md`.

Run the phases in order, printing `## Phase N complete — <one line>` after each. A re-run skips phases with a result.

## cplat

One `cplat` call per Bash invocation, output read whole (no `grep`, `head` or `tail`). First `cplat shape`: JSON with `shape`, `plugin`, `deployable`, `library`, `agents`. `unsupported` or no shape → stop.

- A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape. Asking is pointless because the user declared it.
## Phase 0 — Pre-flight

0. `cplat platform runs begin build --spec <id>`. Every stop that needs the user or fails first runs `cplat platform runs end --outcome escalated --reason '<why>'` (`failed` on failure); the end `--outcome done`. After every subagent: `cplat platform runs agent spawned <role> [--model-id <id>]`.
1. `git status --porcelain`: dirty on a spec whose status is not `building` → stop: commit or stash first (clean tree). Dirty on a `building` spec → read `${CLAUDE_PLUGIN_ROOT}/references/build-resume.md` and follow it (`git restore --staged`; `wip(<task-id>): interrupted`).
2. `cplat spec check <id> --require approved` must pass and `docs/specs/<spec_id>/plan.md` exist; otherwise stop with the fix.
3. Switch to `feature/<spec_id>` (create it from `main` if missing) = `$FEATURE_BRANCH`. `BASE_REF=$(git merge-base main HEAD)`.
4. `<project-map>` = `ls -d */` without `.devbox`, `.venv`, `.git`, `node_modules`, heading every subagent prompt.
5. `approved` → `cplat spec set-status <id> building`, commit `docs(spec): start building <spec_id>`.

## Phase 1 — Acceptance tests (red)

`cplat platform runs phase build:tests`; skip if `reviewed acceptance tests for` is committed, since the tests are frozen; only `cplat spec trace <id>` passing → start at the review.

**tester** (`agents.tester`): "**Acceptance mode.**" + `<project-map>` + the brief: `Criteria` (every active criterion in full, the non-goals), `Contract` (`design.md`'s contract, verbatim), `Commands` (`cplat quiet test-fast`). It writes criterion-tagged tests (a `(smoke)` one also a smoke test, base URL only), confirms they fail because the behaviour is missing, and commits only test files. Then:
- `cplat spec trace <id>` must pass; else the missing ids go back to the tester once, so that every criterion has a red test.
- `cplat quiet test-fast`: the new tests fail, nothing else newly fails; one erroring for another reason goes back.
- Trace files `test-fast` does not run (`e2e/` specs): `cplat quiet e2e` once; one failing before any assertion about the missing behaviour goes back as a wrong failure.
- One call: `cplat platform runs agent tester [--untraced <AC>]... [--wrong-failure <test>]...`.
- `cplat spec trace <id> --json` → `TRACE` (criterion → test files).
- **reviewer** in `**Test-review mode.**` (criteria, `Contract`, `TRACE`) reports `TEST FINDINGS:`; the tester gets them once: "**Acceptance mode.** Resolve only these test-review findings, changing only the tests named, so that nothing else moves: <findings>. Commit as `test(<number>): resolve test-review findings for <id>`. Reply `UNRESOLVED: <finding> — <why>` per line, or `UNRESOLVED: none`." A failing `cplat spec trace <id>` after it → `git revert --no-edit HEAD`, all unresolved, since a broken trace leaves a criterion untested. No second review.
- `cplat quiet lint-fix`; commit `test(<slug>): lint-fix acceptance tests for <id>`; `cplat component build reviewed <id> --findings <n> [--unresolved '<test> | <AC> | <what>']...`. `RED=$(git log -1 --format=%H --grep 'acceptance tests for')`.

## Phase 2 — Implement (parallel via git worktrees)

`cplat platform runs phase build:implement`
### 2.1 Schedule

**skip tasks with `done: true`**. Run the batches `cplat component build schedule <id>` prints.

### 2.2 Worktree probe

Before the first parallel batch, a probe Agent (`isolation: "worktree"`) reports `git rev-parse HEAD`. Error → `${CLAUDE_PLUGIN_ROOT}/references/build-worktree-fallback.md`. Else `cplat platform runs agent execution parallel`; a HEAD other than `$FEATURE_HEAD` (no `worktree.baseRef: "head"`) is fine (#501): coders reset to it, so that a merge brings only that task's commits.

### 2.3 Coder prompt (every task)

- `<project-map>` and the **brief**, copied from `spec.md`, `plan.md` and `design.md`: `Criteria` (id and full text of each criterion in the task's `covers`), `Task` (`id`, prose section verbatim, `files`; touch nothing else, and report any new test helper), `Contract` (the `design.md` sections it touches, verbatim, or `none`), `Tests` (from `TRACE`), `Commands` (the line `cplat component build tests <id> <task>` prints, `cplat quiet quality`).
- **Done when:** the acceptance tests of its `covers` criteria pass (`cplat quiet test-fast -- <the task's test files>`).
- "**Hard rule:** never edit, skip or weaken the acceptance tests, because they are the approved criteria. A linter false positive in one gets the linter's line suppression naming the rule, nothing else (spec 160); name the suppressed rules in the commit." A type-only change the type check needs (type annotation, cast or import; no assertion line touched) is allowed, since the build records it.
- `git rm` of tracked files is allowed (never `-f`), because the allowlist refuses it.
- A re-planned task (`replans[].tasks[]` in `cplat component build state <id> --json`, unmerged) → read `${CLAUDE_PLUGIN_ROOT}/references/build-replan.md` and add its text to the prompt.
- Parallel batch only (`FEATURE_HEAD` = HEAD before the batch): "You are in an isolated worktree. First `cplat component build reset <FEATURE_HEAD>`. Commit locally (`git add` + `git commit -s -m '<type>(<scope>): <title>'`, task id in the body; `-s` is required) before returning. **Hard rule:** do not push or switch branches, because `cplat pr open` pushes after its checks."

### 2.4 Run batches

**Parallel batch (≥ 2 tasks):** one coder per task **in a single message**, each `isolation: "worktree"`. For each `(branch, worktree_path)` that changed something:
1. `cplat component build merge <id> <task> <branch> [--helper <path>]...`. Exit 0 → step 2. Exit 1 naming commits without `Signed-off-by` → run the printed `git -C <worktree> rebase --signoff <sha>`, merge again unasked. Exit 3 → set aside (`cplat platform runs agent conflict <task>`, `git merge --abort`). Exit 4 → `cplat platform runs end --outcome escalated --reason '<the ESCALATE line>'` and stop.
2. `cplat quiet lint-fix`, stage; `cplat spec test-diff $RED --task <task>`: exit 1 means a test was weakened or changed: stop and show the user the file and the reason (a `test helper` or `type-only` line: `build-tighten.md` instead). **Hard rule:** never decide yourself that it is a false alarm, because a changed test is a changed spec. The user approves it → read `${CLAUDE_PLUGIN_ROOT}/references/build-test-approval.md`. Then `cplat quiet quality`; failures go back to that coder (lint/type only; `cplat platform runs agent fix-round lint/type --task <task>`).
3. `cplat validate run`; failures go back to the coder (`cplat platform runs agent fix-round test --task <task>`); failing only because a later task tM depending on it has not landed → `cplat plan merge <task> tM --reason '<why>'`, go on with tM without asking or escalating, because the plan's split was a mistake, not a decision.
4. `git worktree remove <path>`; `git branch -d <branch>`.

**Sequential task:** `PRE=$(git rev-parse HEAD)`, one coder without isolation on `$FEATURE_BRANCH`; then `cplat platform runs agent merged <task> --since $PRE [--helper <path>]...`; then as above.

Each task merged and green: `cplat spec task-done <id> <task-id>`, `cplat component build resolved <id> <task-id>`, commit `chore(plan): <spec_id> <task id> done` with its lint-fixes.

### 2.4a Re-plan after a conflict

Merge exit 3 or a task in `replans[]` → read `${CLAUDE_PLUGIN_ROOT}/references/build-replan.md` and follow it (`cplat component build replan-commit`; a BLOCKER → `cplat component build replan-abort`): re-plan **without asking the user**, attended or not.

### 2.5 All green

`cplat quiet test-fast`: every acceptance test passes. Failing ones go to a coder of a task covering that criterion (at most 2 rounds, each `cplat platform runs agent fix-round test --task <task>`), then escalate. All pass → `cplat platform runs gate acceptance passed`; failing → `... gate acceptance failed`.

`TOUCHED_FILES=$(git diff --name-only $BASE_REF..HEAD)`.

### 2.6 Under load

Run the line `cplat component build tests <id> --load` prints (`cplat quiet test-fast --repeat 3 -- …`); `none: …` → skip, say so in the report. Exit 1 → failing tests to a coder as in 2.5. Exit 3 → `${CLAUDE_PLUGIN_ROOT}/references/build-load-run.md` (the tester fixes the harness; 2 rounds, then escalate).

## Phase 3 — QA: one CI gate, agents only where it is red

`cplat platform runs phase build:qa`
1. Stage the tree, then `devbox run lint-fix` and `devbox run ci` as `cplat quiet lint-fix` and `cplat quiet ci`: the CI gates.
2. **Red** → `cplat validate final --check <name> failed` per failed check, then spawn only the agent that owns the red gate, with `<project-map>`, `<touched-files>` and the summary and log path `cplat quiet` printed (the log when the summary is not enough), so that no green gate is touched:
   - lint or type → **quality** (`agents.quality`), lint/type fixes only;
   - tests → the **coder** of the task whose files are involved (acceptance tests stay fixed; `cplat platform runs agent fix-round ci --task <task>`);
   - security → `cplat deps patch` first, then read `${CLAUDE_PLUGIN_ROOT}/references/build-security-red.md` and follow it (exit 0 → step 3; exit 3 → escalate with its `ESCALATE` reason and `--cause <CAUSE>`, via `cplat component ship escalate` in a ship, else `cplat platform runs end --outcome escalated`; exit 4 → **security** agent). A red gate after a bump never goes to a coder, because a dependency is at fault.

   Between fix rounds: `cplat validate run`, `cplat quiet ci`; 2 rounds at most, then escalate. After a red round follow `${CLAUDE_PLUGIN_ROOT}/references/build-red-rounds.md`; record gates with `cplat budget stage <name> passed|failed`. `cplat quiet ci` green → `cplat platform runs gate security passed`; stays red → `... gate security failed`.
3. **Green** → agents only where needed: **tester** (`agents.tester`) so that every new internal has a unit test; **security** so that a changed Dockerfile is built and scanned.
4. `cplat spec test-diff $RED` again (`--by quality` after the quality agent); exit 1 stops as in Phase 2. Commit changes.

## Phase 4 — Verify against the spec

`cplat platform runs phase build:verify`
1. `cplat spec trace <id> --json` must pass, so that every criterion has its test.
2. **reviewer** (`agents.reviewer`): `SPEC_DIR`, `BASE_REF`, `<touched-files>`, the trace JSON, the Phase 3 summary, and `SUPPRESSIONS`: the `lint suppression only` lines of the last test diff (Phase 3, step 4), or `none`, `TIGHTENED` (`build-tighten.md`) or `none`, and `TEST REVIEW`: the `unresolved:` lines of `git log -1 --format=%b --grep 'reviewed acceptance tests for'`, or `none`. After each pass (cycle `<n>`): `cplat platform runs agent findings --cycle <n> [--deviation <AC or task>]...`.
3. A `NOT MET` item marked `TEST LOOSER` → read `${CLAUDE_PLUGIN_ROOT}/references/build-tighten.md` and follow it. `RESULT: fail` → each other `NOT MET` item to a coder of a covering task (`cplat platform runs agent fix-round verification --task <task>`), then `cplat quiet test-fast` and the reviewer; at most 2 cycles, then escalate. A `SMOKE: <file> — <finding>` line is no `NOT MET`: the tester gets it in the same round without asking: "Tighten only `<file>` so that it fails without the feature: `<finding>`. Change no other test."; then `cplat platform runs agent smoke <file> --finding '<finding>'` and run it (`cplat quiet test-fast -- <file>`, else `cplat quiet e2e`); a failure goes back once. `SMOKE` items alone with `RESULT: pass` need no new cycle, since none is `NOT MET`.
4. `cplat spec mutate <id> --write` (report only; it never fails the build).
5. Commit `docs/specs/<spec_id>/verification.md`: `docs(spec): verify <spec_id>`.

## Phase 5 — Container image

`cplat platform runs phase build:image`. `deployable` false → `## Phase 5 skipped — <shape> is not deployable`. Else **deployment** (`agents.deployment`), `<project-map>`, `<touched-files>`: the image. **Hard rule:** never Kubernetes manifests, because the gitops repo owns the cluster (ADR-017). `devbox run image-build`. Ask for gitops changes only for wiring not in the spec's *Provided by the system* list, since the system already provides that.

## Phase 6 — Close the spec

`cplat platform runs phase build:close`; `cplat spec set-status <id> done`, `cplat spec index`, commit `docs(spec): <spec_id> done`.

## Phase 7 — Pull request

`cplat platform runs phase build:pr`; follow `${CLAUDE_PLUGIN_ROOT}/references/build-pr.md`: `.pr-body.md`, one `cplat pr open --spec <spec_id>` call ("How this was built" block), the Final Report.

## Rules

- **Hard rule:** only approved specs are built, and only as planned, because approval is the user's consent. An unanswered decision stops it.
- **Hard rule:** push only in Phase 7, through `cplat pr open`, because it runs every check first.
- **Hard rule:** Never edit conflicting hunks: a merge conflict is re-planned once per task (at most 3 re-plans per build), then escalated; it is never resolved by hand, because the plan split the work wrongly.
- **Subagents run in the foreground** (`run_in_background: false`); never poll for one in a shell loop, because such a loop can wait forever.
- **Shell rule:** run every tool through `devbox run <script>`, never `pytest`, `ruff` or `uv` directly, so that versions and flags match CI.
- **Hard rule:** never use `--no-verify` or `--no-gpg-sign`, because a skipped hook leaves no trace.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
