---
description: "Targeted bug-fix pipeline. Runs coder → tester in a tight loop until the bug is resolved. Usage: /svc:fix-bug <bug description or error message>"
---

You are the **orchestrator** in bug-fix mode. No planning or deployment phases — focus on fixing and verifying.

**Bug report:** $ARGUMENTS

---

## Phase 0 — Prelude

Run the prelude:

1. `git status --porcelain` — stop if dirty.
2. `git symbolic-ref --short HEAD` → record `$WORK_BRANCH`.
3. If on `main`: derive a `fix/<slug>` slug (lowercase, hyphens, ≤40 chars). Then `git checkout -b fix/<slug>` and update `$WORK_BRANCH`.
4. `BASE_REF=$(git rev-parse HEAD)`.
5. Build `<project-map>` (output of `ls -d */` excluding `.devbox`, `.venv`, `.git`, `node_modules`). Hold as `$PROJECT_MAP`. Prepend to each subagent prompt below.

Print `## Phase 0 — on $WORK_BRANCH, BASE_REF=<short-sha>`.

**Shape dispatch.** After the prelude, run `cplat shape`. It prints JSON: `shape`, `plugin`, `deployable`, `library` and `agents` (the subagent type for every role — spawn each role with exactly that type, e.g. `agents.coder`). If `unsupported` is present, stop and show it. Roles missing from `agents` (e.g. deployment for a library) are skipped. Print `Shape: <shape>`.

---

**Bug or spec change?** A bug is code that does not do what was intended. If the "bug" is behaviour an active spec criterion explicitly states (the spec says so, the user wants it different), it is a spec change: stop and recommend `/svc:spec --amend <NNN> <change>`.

---

## Step 1 — Diagnose and fix

Use the **coder** agent. Prompt prelude: the `<project-map>` block. Then:
> "Bug report: `$ARGUMENTS`.
>
> Step 1: read the relevant files and identify the root cause. State the root cause and the minimal change you intend to make in 2-3 lines before editing.
>
> Step 2: apply the minimal fix. Do not refactor surrounding code or add unrelated changes.
>
> Step 3: report what you changed (files + 1-line summary per file) and the root cause you found."

After the coder finishes, capture:
```bash
TOUCHED_FILES=$(git diff --name-only $BASE_REF -- .)
```

---

## Step 2 — Verify

Use the **tester** agent. Prompt prelude:
```
<project-map>
$PROJECT_MAP
</project-map>
<touched-files>
$TOUCHED_FILES
</touched-files>
```

Then the **brief** under the headings `Criteria` (the criteria the bug breaks, or `none`), `Task` (root cause and files), `Contract` (`none`), `Tests` and `Commands`; the agent starts from it, so do not tell it to read the spec files:
- Run the existing test suite via `cplat quiet test-fast` (it prints one line on success, the tail and a log path on failure)
- Write a regression test that would have caught this bug (anchor it on the files in `<touched-files>`). If the broken behaviour is stated by a spec criterion (`docs/specs/*/spec.md`, `AC-<NNN>.<n>`), name that id in the test so `cplat spec trace` links it; never edit an existing acceptance test to make it pass
- Confirm the bug is resolved

---

## Step 3 — Loop if needed

If the tester reports the bug is NOT fixed:
- Feed the failure back to the **coder** (with `<project-map>` + refreshed `<touched-files>`)
- Re-run the **tester**
- Repeat up to 3 times. If still unresolved, stop and report with full context.

---

## Phase 4 — Commit and open PR

After the tester confirms the bug is resolved:

Write a short PR body with the Write tool to `.pr-body.md` in the repo root (never into `.git/`: Claude Code refuses edits there; cplat moves it out of the work tree before it commits) (summary of the bug and the fix, the regression test, `{{CLOSES}}` on its own line under "Related issues"), then make **one** Bash call:

```bash
cplat pr open --title "fix(<scope>): <imperative description of the fix>" [--issues "#NNN …"]
```

It commits everything with `-s`, pushes the branch, finds the open issues to close and opens the PR.

Relay its three lines (`commit:`, `push:`, `pr:`). Exit 1: report which part failed and stop; `pr: failed: already open <url>` means the PR exists, so use that URL. Exit 2: fix the reason it prints, then call it again. A re-run never makes a second commit or PR.

**`pr: ready: <command>`** (headless run, untrusted workspace, or `gh pr create` not allowed; spec 051) is not an error: the branch is pushed and cplat has moved the body to `.git/PR_BODY.md`. End the report with that exact command as its last line.

**If Phase 0 found we were already on `main`:** warn "Skipping PR creation — working directly on main." and skip Phase 4.

---

## Final Report

```
## Bug fix complete (or: escalating to user)

**Bug:** $ARGUMENTS
**Branch:** <branch-name>
**Root cause:** <one line>
**Fix:** <files changed, what changed>
**Regression test:** <test file and test name>
**Test result:** N passed
**PR:** <URL> (CI running)
```

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/shared:report-issue` so the user can file it. Never file anything without their OK.
