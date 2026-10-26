---
description: "Plan an approved spec: the architect writes design.md and plan.md (tasks covering every criterion), checked by cplat. No code. Usage: /component:plan <spec-id>"
---

You are the **planning orchestrator** ([ADR-026](../../../docs/adr/026-feature-specs.md)). You turn an approved spec into a checked plan the build can schedule. You write no code.

**Spec:** $ARGUMENTS (number, slug or full id; empty → run `cplat spec list` and ask which)

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation. First call:

```bash
cplat shape
```

Print its output verbatim.

## 1. Pre-flight

1. `git status --porcelain` must be empty.
2. Shape from the routing JSON (`SHAPE`, `agents`). `unsupported` → stop (gitops-app: `/system:plan`). No shape → continue; the plan records none.
3. `cplat spec check <id> --require approved`. If it fails, show the errors and the fix (`/component:spec approve <NNN>` or `/component:spec --amend …`) and stop.
4. Switch to `feature/<spec_id>` (create it from `main` if it does not exist).
5. If `plan.md` exists and any task has `done: true`, the spec is partly built: ask before re-planning (task progress is lost; the build would redo those tasks).
6. `SPEC_HASH=$(cplat spec hash <id>)`. Build `<project-map>` (`ls -d */` without `.devbox`, `.venv`, `.git`, `node_modules`).

## 2. Architect

**architect** agent (`agents.architect`, or `svc:architect`), prompt: `SPEC_DIR: docs/specs/<spec_id>/`, `SHAPE`, `SPEC_HASH`, `<project-map>`, and "read the spec and the code, write design.md if warranted and plan.md, follow the spec-format references".

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
Design: docs/specs/<spec_id>/design.md | none · ADRs: <paths> | none · GitOps change: <from the architect> | none

Next: review the plan, then /component:build <NNN>
```

## Rules

- Gitops changes are plan tasks with `repo:` and `order: before-merge` | `after-release` (see the plan reference); removing CRD fields or namespaces is planned expand/contract, over two releases.
- Plan only an approved spec; never change the spec. If the architect needs a decision, it goes back to the user through `/component:spec --amend`.
- Commits stay local; `/component:build` pushes.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
