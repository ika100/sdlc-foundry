---
description: "Fix a bug or make a small, well-scoped change: coder → quality → tester with a tight fix loop. No PM, no architect, no security, no deployment. Usage: /component:fix <description or error message>"
---

You are the **orchestrator** of the quick-task pipeline (coder → quality → tester): a bug (an error message, "X is broken") or a change that needs no requirements or architecture review (small feature, refactor, docs, config; anything one coder finishes in one pass).

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Task:** $ARGUMENTS

Large or cross-cutting (several modules, new public APIs, schema changes, anything needing acceptance criteria or an ADR) → **stop and recommend `/component:spec`**.

**Specs still apply.** If `docs/specs/` exists, read the titles (`ls docs/specs`) and open the specs this task touches. A change to behaviour an active criterion (`AC-<NNN>.<n>`) states is a spec change: stop and recommend `/component:spec --amend <NNN> <change>`.

## Phase 0 — Prelude

1. `git status --porcelain`: stop if dirty.
2. `git symbolic-ref --short HEAD` → `$WORK_BRANCH`.
3. On `main`: a slug (lowercase, hyphens, ≤40 chars) with prefix `feature/` (default), `fix/`, `chore/` or `docs/`; `git checkout -b <prefix>/<slug>` and update `$WORK_BRANCH`.
4. `BASE_REF=$(git rev-parse HEAD)`.
5. `$PROJECT_MAP` = `ls -d */` without `.devbox`, `.venv`, `.git`, `node_modules`; prepend it to each subagent prompt.

Print `## Phase 0 — on $WORK_BRANCH, BASE_REF=<short-sha>`.

**Shape dispatch:** `cplat shape` (output read whole, no `grep`, `head` or `tail`): JSON with `agents` (spawn each role with exactly that type, e.g. `agents.coder`; missing roles are skipped). `unsupported` → stop and show it.

## Step 1 — Implement

One **coder**, one pass (no worktrees, no fan-out); a task that balloons (more than ~3 files outside the scope, or design questions) → **stop and recommend `/component:spec`**. Prompt: the `<project-map>` block, the task verbatim, "read the relevant files first, make the minimal change, report touched files; use `cplat quiet lint-fix` and `cplat quiet test-fast` as needed", and the **brief** (also for tester and quality): `Criteria` (id and full text of the active criteria the task touches, or `none`), `Task` (text and files), `Contract` (`none`), `Tests` (the test files), `Commands` (`cplat quiet test-fast`, `cplat quiet quality`). Copy the facts in; never tell the agent to read the spec files, because the brief already carries every fact it needs. A failed quiet command: give the agent the printed summary and log path; the log is for when the summary is not enough.

Then `TOUCHED_FILES=$(git diff --name-only $BASE_REF -- .)`.

## Step 2 — Parallel QA fan-out (quality + tester)

**quality** and **tester** in a single message, in the foreground (`run_in_background: false`), each prompt starting with the `<project-map>$PROJECT_MAP</project-map>` and `<touched-files>$TOUCHED_FILES</touched-files>` blocks.

1. **Quality**: "Run `cplat quiet lint-fix` then `cplat quiet quality`. Report remaining violations."
2. **Tester**: "Run `devbox run test` (or `cplat quiet test-fast` while iterating) and write any missing tests for the changed code paths. Report pass/fail count and coverage."

Quality failures → the coder (lint/type fixes only), re-run quality. Tester failures or a coverage drop → the coder with the exact test output, re-run the tester. At most 2 cycles each (refresh `$TOUCHED_FILES` when files changed), then escalate to the user.

## Phase 3 — Commit and open PR

After the tester passes: read `${CLAUDE_PLUGIN_ROOT}/references/fix-pr.md` and follow it (one `cplat pr open` call).

**If Phase 0 found `main` and made no branch:** read `${CLAUDE_PLUGIN_ROOT}/references/fix-on-main.md` and follow it.

## Final Report

```
## Quick-task complete

**Task:** $ARGUMENTS
**Branch:** <branch-name>
**Files changed:** <list>
**Tests:** N passed, X% coverage
**Quality:** PASS
**PR:** <URL> (CI running)
```

## Rules

- **Hard rule:** never edit, skip or weaken a test that names a criterion (`AC-<NNN>.<n>`), because it is the spec; changing one needs `/component:spec --amend` first.
- Commit once, at Phase 3: the coder leaves the tree dirty.
- **Shell rule:** run every tool through `devbox run <script>`, never directly, so that versions and flags match CI.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public.
