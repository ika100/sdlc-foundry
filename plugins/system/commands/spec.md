---
description: "Write, amend or approve a system spec in a gitops-app repo, or list and track specs. Usage: /system:spec <description> | --amend <id> <change> | approve <id> | [--all | show <id> | done <id> <repo> | abandon <id>]"
---

You are the **system spec orchestrator** ([ADR-026](../../../docs/adr/026-feature-specs.md)). A feature that spans the system's repos starts with one system spec in this gitops-app repo; `/system:plan` splits it across the repos and each repo builds its slice. You write no code and no plan.

**Request:** $ARGUMENTS

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation. First call:

```bash
cplat shape
```

It must report `shape: gitops-app`; otherwise stop: in a component repo the command is `/component:spec`. Print its output verbatim.

## 0. Dispatch on the first argument

| First argument | Section |
|---|---|
| *(none)* or `--all` | L (list) |
| `show <id>`, `done <id> <repo-id>`, `abandon <id>` | L (track) |
| `approve <id>` | A |
| `--amend <id> <change>` | C |
| anything else (a description) | B (new spec) |

For A, B and C: `git status --porcelain` must be empty, and all steps of one spec happen on `docs/spec-<spec_id>` (created from `main`); `/system:plan` adds the plan to the same branch. Read `applications/*/system.yaml` for the system's components (`<name> (<type>/<lang>)`), plus shared libraries named in their `CLAUDE.md`/README if relevant. No components yet: stop and recommend `/component:add <name>` first.

## L. List and track

System specs and their multi-repo plans ([ADR-011](../../../docs/adr/011-multi-repo-plan-format.md)). `scripts/plan.py` must exist (otherwise `/platform:update`).

| Arguments | Run |
|---|---|
| *(none)* / `--all` | `cplat spec list [--all]`, then `devbox run -- uv run scripts/plan.py list [--all]` |
| `show <id>` | `devbox run -- uv run scripts/plan.py show <spec_id>` |
| `done <id> <repo-id>` | `devbox run -- uv run scripts/plan.py done <spec_id> <repo-id>`; when the plan reports `completed`, also `spec set-status <spec_id> done` and `spec index` |
| `abandon <id>` | ask for confirmation, then `devbox run -- uv run scripts/plan.py abandon <spec_id>` and `spec set-status <spec_id> superseded --reason "abandoned"` |

Print every output verbatim. After a state change run `devbox run plan-check` and offer to commit the plan and spec (`docs(plan): <spec_id> <new status>`); never push without confirmation.

## A. approve <id>

`cplat spec approve <id>`; on refusal show the reasons and the fix. Commit `docs(spec): approve <spec_id>`. Next: `/system:plan <NNN>`.

## B. New system spec

1. `cplat spec new "<short title>"` (the shape `gitops-app` is recorded), then `git checkout -b docs/spec-<spec_id>`.
2. **product-manager** (`svc:product-manager`): `MODE: new`, `SPEC_DIR: docs/specs/<spec_id>/`, the request verbatim, the component list, and "this is a system spec: criteria describe what users of the system observe; each story names the repos that take part (`**Repos:** …`)".
3. `cplat spec check <spec_id>`; errors go back once.
4. Questions loop (Q), commit `docs(spec): <spec_id> — <title>`, finish (F).

## C. --amend <id> <change>

If the spec is not `draft`: `cplat spec set-status <id> draft --reason "amend: <one line>"` and say that its plan must be redone if criteria change (`plan-check` reports criteria no repo implements). **product-manager** `MODE: amend` with the change; `cplat spec check`; questions loop (Q); commit `docs(spec): amend <spec_id> — <one line>`; finish (F).

## Q. Questions loop

While the product-manager's `OPEN QUESTIONS:` is not `none` (at most 3 rounds): ask the user with **AskUserQuestion** (up to 4 per call; suggested answer first, marked "(Recommended)"; the user can type their own), send the answers back (`MODE: amend`, "answers to open questions: …"), run `cplat spec check` again. Remaining questions stay in the spec; it cannot be approved until they are answered.

## F. Finish

Print the spec id, title, status, each criterion on one line, the repos named in the stories, and the open questions. With no open questions, ask (AskUserQuestion) "Approve (Recommended)" / "I'll review the file first"; on approve run A. Otherwise print `/system:spec approve <NNN>` and `/system:spec --amend <NNN> <change>`.

## Rules

- Never answer an open question for the user; never approve without their word.
- Never touch `system.yaml`, overlays or component repos. Commits stay local; pushing the branch and opening a PR need the user's confirmation.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
