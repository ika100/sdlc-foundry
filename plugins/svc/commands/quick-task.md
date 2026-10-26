---
description: "Lightweight pipeline for small, well-scoped changes. Runs coder → quality → tester with a tight fix loop. No PM, no architect, no security, no deployment. Usage: /svc:quick-task <description>"
---

You are the **orchestrator** in quick-task mode. Use this for small changes (features, refactors, docs, config) one coder can finish in one pass.

**Task:** $ARGUMENTS

If the task is large or cross-cutting (several modules, new public APIs, schema changes, needs criteria or an ADR), **stop and recommend `/svc:spec` instead** rather than continuing.

**Specs still apply.** If `docs/specs/` exists, read the titles (`ls docs/specs`) and open the spec(s) whose feature this task touches. If the task would change behaviour an active criterion (`AC-<NNN>.<n>`) states, stop: that is a spec change — recommend `/svc:spec --amend <NNN> <change>`. A task that stays within the spec's criteria (refactor, internal fix, docs) continues.

---

## Phase 0 — Prelude

Run the prelude:

1. `git status --porcelain` — stop if dirty.
2. `git symbolic-ref --short HEAD` → record `$WORK_BRANCH`.
3. If on `main`: derive a slug (lowercase, hyphens, ≤40 chars). Pick a prefix from task type: `feature/` (default), `fix/`, `chore/`, `docs/`. Then `git checkout -b <prefix>/<slug>` and update `$WORK_BRANCH`.
4. `BASE_REF=$(git rev-parse HEAD)`.
5. Build `<project-map>` (output of `ls -d */` excluding `.devbox`, `.venv`, `.git`, `node_modules`). Hold as `$PROJECT_MAP`. Prepend to each subagent prompt below.

Print `## Phase 0 — on $WORK_BRANCH, BASE_REF=<short-sha>`.

**Shape dispatch.** After the prelude, run `cplat shape`. It prints JSON: `shape`, `plugin`, `deployable`, `library` and `agents` (the subagent type for every role — spawn each role with exactly that type, e.g. `agents.coder`). If `unsupported` is present, stop and show it. Roles missing from `agents` (e.g. deployment for a library) are skipped. Print `Shape: <shape>`.

---

## Step 1 — Implement

Use the **coder** agent. Prompt prelude: the `<project-map>` block. Then:
- The task description verbatim
- Instruction to read the relevant files, make the minimal change, report touched files
- Instruction to use `cplat quiet lint-fix` and `cplat quiet test-fast` while implementing
- The **brief** (coder, tester, quality): under the headings `Criteria` (id and full text of every criterion the task covers), `Task` (the task text and files), `Contract` (the relevant part of the design, or `none`), `Tests` (the test files) and `Commands` (`cplat quiet test-fast`, `cplat quiet quality`). Copy the facts into the brief; do not tell the agent to read the spec files. On a failed quiet command, pass the agent its log path. Criteria: the active criteria the task touches, or `none`; Contract: `none`.

One coder, one pass — no worktrees, no fan-out. **Inline (111):** make the change yourself only if, once made, `cplat quick-task inline-check --base main` exits 0; skip Step 2's agents but run `cplat quiet quality` and `cplat quiet test-fast` yourself (both green) and write "made inline: <check line>" in the PR body; leave its coverage box unticked. On exit 1 or a red gate, undo it, use the coder → quality → tester path and never try inline again.

After the coder finishes (or the inline change is made), capture:
```bash
TOUCHED_FILES=$(git diff --name-only $BASE_REF -- .)
```

---

## Step 2 — Parallel QA fan-out (quality + tester)

Fan out **quality** and **tester** in a single message. Each prompt prelude:
```
<project-map>
$PROJECT_MAP
</project-map>
<touched-files>
$TOUCHED_FILES
</touched-files>
```

Then:

1. **Quality agent** — instruction: "Run `cplat quiet lint-fix` then `cplat quiet quality` (brief as above). Report remaining violations."
2. **Tester agent** — instruction: "Touched files listed above. Run `devbox run test` (or `cplat quiet test-fast` while iterating) and write any missing tests for the changed code paths. Report pass/fail count and coverage."

Reconcile:
- **Quality failures** → route to **coder** for lint/type fixes only. Re-run quality. Max 2 cycles.
- **Tester failures or coverage drop** → route to **coder** with the exact pytest output. Re-run tester. Max 2 cycles.
- If either cycle modified files, refresh `$TOUCHED_FILES`.

If still failing after 2 cycles, escalate to the user.

---

## Phase 3 — Commit and open PR

After the gates pass:

Write the PR body with the Write tool to `.pr-body.md` in the repo root (never into `.git/`: Claude Code refuses edits there; cplat moves the file out of the work tree before it commits) (the lines under "Related issues / stories" stay `{{CLOSES}}`; the command fills them):

```markdown
## Summary

<2–4 sentence description of the change: what it does, how it works, and why it was needed. For a new feature, describe what the feature is and how a user or operator would interact with it (e.g. which endpoint, flag, or behaviour was added). For a fix, describe what was broken and how it was resolved.>

## Type of change

- [x] <tick the matching type from: feat / fix / refactor / perf / test / docs / chore / ci / revert>

## Related issues / stories

{{CLOSES}}

## Testing done

<tester output summary: N tests, X% coverage>

## Checklist

- [x] `devbox run quality` passes (ruff + mypy)
- [x] `devbox run test` passes with coverage ≥ 80%
- [x] No secrets, credentials, or API keys committed
- [ ] Docs: <tick only if public-facing behaviour changed AND the docs were updated; otherwise write "n/a, no public-facing change">

Not run by quick-task: `devbox run security` (use `/shared:check-quality` for a full audit before merging risky changes).
```

Then **one** Bash call (commits with `-s`, finds the issues to close, pushes, opens the PR):

```bash
cplat pr open --title "<type>(<scope>): <imperative description of the task>" [--issues "#NNN …"]
```

Use `fix:` for bug fixes, `chore:` for tooling, `docs:` for documentation, etc.; the title must be a Conventional Commits title (the `pr-title` CI check). Pass `--issues` for `#NNN` references in `$ARGUMENTS`.

Relay its three lines (`commit:`, `push:`, `pr:`). Exit 1: report which part failed and stop; `pr: failed: already open <url>` means the PR exists, so use that URL. Exit 2: fix the reason it prints, then call it again. A re-run never makes a second commit or PR.

**`pr: ready: <command>`** (headless run, untrusted workspace, or `gh pr create` not allowed; spec 051) is not an error: the branch is pushed and cplat has moved the body to `.git/PR_BODY.md`. End the report with that exact command as its last line.

**If Phase 0 found `main` and made no branch:** read `${CLAUDE_PLUGIN_ROOT}/references/quick-task-on-main.md` and follow it.

---

## Final Report

```
## Quick-task complete

**Task:** $ARGUMENTS
**Branch:** <branch-name>
**Files changed:** <list>
**Tests:** N passed, X% coverage
**Quality:** PASS
**PR:** <URL> (CI running)

### What's next
- Review the PR diff at the URL above
- Merge when CI is green
```

---

## Rules

- **One coder, one pass.** If the task balloons mid-implementation (coder reports it needs more than ~3 files outside the original scope, or asks design questions), **stop and recommend `/svc:spec`** — don't keep stretching quick-task.
- **Acceptance tests stay as they are.** Tests that name a criterion (`AC-<NNN>.<n>`) are the spec; if one has to change, the spec changes first (`/svc:spec --amend`).
- **Commit at Phase 3, not before.** The coder leaves the working tree dirty; Phase 3 does the single commit before pushing.
- **No deployment, no security scan, no spec.** Those are `/svc:spec` → `/svc:build` territory.
- **Every shell command goes through `devbox run`.**

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/shared:report-issue` so the user can file it. Never file anything without their OK.
