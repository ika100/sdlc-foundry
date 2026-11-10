---
description: "Plan an approved spec: the architect writes design.md and plan.md (tasks covering every criterion), checked by cplat. No code. Usage: /component:plan <spec-id>"
---

You are the **planning orchestrator** (ADR-026). You turn an approved spec into a checked plan the build can schedule. You write no code.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Spec:** $ARGUMENTS (number, slug or full id; empty → run `cplat spec list` and ask which)

## cplat

`cplat` is on the Bash PATH (the version your plugins were installed from); one call per Bash invocation. Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered. First call:

```bash
cplat shape
```

Print its output verbatim.

## 1. Pre-flight

1. `git status --porcelain` must be empty so that the plan commit holds only the plan.
2. Shape from the routing JSON (`SHAPE`, `agents`). `unsupported` → stop (gitops-app: `/system:plan`). No shape → continue; the plan records none. A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape. That file already declares it, since the user put it there.
3. `cplat spec check <id> --require approved`. If it fails, show the errors and the fix (`/component:spec approve <NNN>` or `/component:spec --amend …`) and stop.
4. Switch to `feature/<spec_id>` (create it from `main` if it does not exist).
5. If `plan.md` exists and any task has `done: true`, the spec is partly built: ask before re-planning (task progress is lost).
6. `SPEC_HASH=$(cplat spec hash <id>)`. `ADR_NEXT=$(cplat spec adr-next)` (the first free ADR number, #337). Build `<project-map>` (`ls -d */` without dot and dependency directories).

## 2. Architect

**architect** agent (`agents.architect`, or `svc:architect`; in the foreground, `run_in_background: false`), prompt: `SPEC_DIR: docs/specs/<spec_id>/`, `SHAPE`, `SPEC_HASH`, `ADR_NEXT`, `<project-map>`, and "read the spec and the code, write design.md if warranted and plan.md, follow the spec-format references".

- `BLOCKERS` other than `none` → stop. Show them and recommend `/component:spec --amend <NNN> <answers>`; the plan is not committed.
- `cplat spec check <id>`. On errors, send them verbatim to the architect (at most 2 rounds); if they persist, stop and show them.

## 3. Commit and show

Commit `docs/specs/<spec_id>/` and any new ADRs: `docs(plan): <spec_id> — <n> tasks`.

Print:

```
## Plan ready: <spec_id>   (docs/specs/<spec_id>/plan.md)

| Level | Task | Covers | Parallel | Files |
|---|---|---|---|---|
| 1 | t1 — <title> | AC-NNN.1, AC-NNN.3 | yes | 2 |
...
Design: docs/specs/<spec_id>/design.md | none · ADRs: <paths> | none · GitOps change: <architect's> | none

Next: review the plan, then /component:build <NNN>
```

## Rules

- Gitops changes are plan tasks with `repo:` and `order: before-merge` | `after-release`; removing CRD fields or namespaces is planned expand/contract, over two releases.
- **Hard rule:** plan only an approved spec, because approval is the user's gate before any plan or code. Never change the spec, since a change needs a new approval.
- Commits stay local; `/component:build` pushes.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
