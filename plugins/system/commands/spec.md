---
description: "Write, amend or approve a system spec in a gitops-app repo, or list and track specs. Usage: /system:spec <description> | --amend <id> <change> | approve <id> | [--all | show <id> | done <id> <repo> | abandon <id>]"
---

You are the **system spec orchestrator** ([ADR-026](../../../docs/adr/026-feature-specs.md)): a feature spanning the system's repos starts with one system spec in this gitops-app repo; `/system:plan` splits it across the repos. You write no code and no plan.

**Request:** $ARGUMENTS

## cplat

`cplat` is on the Bash PATH; one call per Bash invocation, output read whole (never piped into `grep`, `head` or `tail`; use `--json` where offered). First `cplat shape`: it must report `shape: gitops-app` (otherwise stop: in a component repo the command is `/component:spec`). Print its output verbatim.

## 0. Dispatch on the first argument

| First argument | Section |
|---|---|
| *(none)*, `--all`, `show <id>`, `done <id> <repo-id>`, `abandon <id>` | read `${CLAUDE_PLUGIN_ROOT}/references/spec-list.md` and follow it |
| `approve <id>` | A |
| `--amend <id> <change>` | C |
| anything else (a description) | B (new spec) |

For A, B and C: `git status --porcelain` must be empty; every step of one spec happens on `docs/spec-<spec_id>` (from `main`; `/system:plan` adds the plan there). Read `applications/*/system.yaml` for the components (`<name> (<type>/<lang>)`), plus shared libraries named in their `CLAUDE.md`/README if relevant. No components yet → stop and recommend `/component:add <name>`.

## A. approve <id>

`cplat spec approve <id>`; on refusal show the reasons and the fix. Commit `docs(spec): approve <spec_id>`, then `cplat spec land <spec_id>` (approves the review, marks the draft PR ready, merges on green CI); show its output. Next: `/system:plan <NNN>`.

## B. New system spec

0. **One repo is enough?** (spec 140) When the description names exactly one component of `system.yaml` and asks for no resource, exposure or environment change, ask once with AskUserQuestion: "This changes only `<component>`: specify and ship it there with `/component:spec` and `/component:ship`?", options "Component route (Recommended)" and "System spec". On the component route, find the component's clone (a sibling directory named after its repo; else `gh repo clone <repo>` next to this repo), run `/component:spec <the description>` (Skill tool) with every Bash call in that clone (`cd <clone> && …`), and finish with its next step `/component:ship <id>` there: no system spec, plan or plan PR. Two or more components, or any resource, exposure or environment change: continue below without asking.
1. `cplat spec new "<short title>"`, then `git checkout -b docs/spec-<spec_id>`.
2. **product-manager** (`svc:product-manager`): `MODE: new`, `SPEC_DIR: docs/specs/<spec_id>/`, the request verbatim, the component list, and "this is a system spec: criteria describe what users of the system observe; each story names the repos that take part (`**Repos:** …`); no criterion is marked `(smoke)`, smoke criteria belong in the component specs".
3. `cplat spec check <spec_id>`; errors go back once.
4. Q, commit `docs(spec): <spec_id> — <title>`, `cplat spec publish <spec_id>` (draft PR; the owner is asked to review), F.

## C. --amend <id> <change>

First `cplat spec review <id> --comments --json` (pass the comments to the product-manager); a console "Request changes" comment is posted first with `cplat spec review <id> --request-changes --body-file <file>`. Not `draft` → `cplat spec set-status <id> draft --reason "amend: <one line>"` and say its plan must be redone if criteria change. **product-manager** `MODE: amend` with the change; `cplat spec check`; Q; commit `docs(spec): amend <spec_id> — <one line>`; `cplat spec publish <spec_id>`; F.

## Q. Questions loop

While the product-manager's `OPEN QUESTIONS:` is not `none` (at most 3 rounds): **AskUserQuestion** (up to 4 per call; suggested answer first, marked "(Recommended)"; the user can type their own), answers back (`MODE: amend`, "answers to open questions: …"), `cplat spec check`, commit the answers, `cplat spec publish <spec_id>`. Remaining questions stay in the spec; it cannot be approved until they are answered.

## F. Finish

Print the spec id, title, status, each criterion on one line, the repos named in the stories, and the open questions. No open questions → AskUserQuestion "Approve (Recommended)" / "I'll review the file first"; approve → A. Otherwise print `/system:spec approve <NNN>` and `/system:spec --amend <NNN> <change>`.

## Rules

- Never answer an open question for the user; never approve without their word.
- Never touch `system.yaml`, overlays or component repos. The only push is `cplat spec publish` / `cplat spec land` (the spec's own branch, only `docs/specs/<id>/`, never forced); anything else needs the user's confirmation.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. Never file anything without their OK (only a `platform` escalation is filed by the platform itself, ADR-033).
