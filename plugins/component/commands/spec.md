---
description: "Write, amend or approve a feature spec, or list the specs. Usage: /component:spec <description> | --amend <id> <change> | approve <id> | --from-plan <plan> [<repo-id>] | [--all] | index | migrate"
---

You are the **spec orchestrator** (ADR-026): get an approved spec. The product-manager decides by default and lists those decisions as **assumptions**; the user approves them with the spec in one step and answers the few open questions that may not be decided by default (ADR-084). You write no code and no plan.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Request:** $ARGUMENTS

**Dispatch on the first argument.** No argument, `--all`, `index` or `migrate` → read `${CLAUDE_PLUGIN_ROOT}/references/spec-list.md` and follow it. Anything else → the pre-flight below.

## cplat

`cplat` is on the Bash PATH; one call per Bash invocation. Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered. First `cplat shape`. Print cplat output verbatim.

## 0. Pre-flight

1. **Mode:** `approve <id>` → A. `--amend <id> <change>` → C. `--from-plan <plan> [<repo-id>]` → D. Otherwise → B (new spec).
2. **Route small work away** (for a new spec): a typo, rename, one-file tweak, an error message or "X is broken" → recommend `/component:fix` and stop; the user may still insist.
3. `git status --porcelain` must be empty so that the commit holds only the spec; otherwise stop: commit or stash first.
4. **Shape:** `unsupported` (a gitops-app repo) → stop and point to `/system:spec`. "cannot determine the repo's shape" → continue with `--no-shape` on `spec new` (`/component:build` needs a shape). A repo with a shape (the platform repo too, `shape: platform`) records it: no `--no-shape`. A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape. That file already declares it, since the user put it there.
5. **Branch:** every step of one spec happens on `feature/<spec_id>` (one PR for everything). On another branch than `main`, ask before switching.

## A. approve <id>

1. `cplat spec approve <id>`. Refused → show the reasons and the fix (usually `/component:spec --amend <id> …`). It set the plan aside (criteria changed) → tell the user the spec needs a new plan.
2. Switch to `feature/<spec_id>` if it exists; commit `docs/specs/<spec_id>/`: `docs(spec): approve <spec_id>`.
3. `cplat spec land <spec_id>` (merges the PR on green CI); show its output, stop on a failure.
4. Next step: `/component:plan <NNN>`.

## B. New spec

1. A title (≤ 60 chars) and any `#N` issues in the request: `cplat spec new "<title>" [--tracks N …] [--no-shape]`, plus `--explored` when the request ends in a `DECIDED:` block (the handoff of `/component:explore`; no decisions file exists) (prints `docs/specs/<spec_id>/spec.md`, claims each tracked issue). An issue another branch claimed stops it: tell the user who has it; `--take-over` takes it from them, so use it after the user says yes.
2. `git checkout -b feature/<spec_id>` (from `main`).
3. **product-manager** (`agents.product-manager`; `svc:product-manager` without a shape): `MODE: new`, `SPEC_DIR: docs/specs/<spec_id>/`, the request verbatim, the `<project-map>` (`ls -d */` without dot and dependency directories), and `cplat spec list --all`. With a `DECIDED:` block also `cplat explore context "<title>" --json`: pass the block verbatim and that output's `specs` and `adrs`, so that a decision contradicting an active criterion or accepted ADR becomes an open question.
4. `cplat spec check <spec_id>`; errors go back to the product-manager once; still failing → stop and show them.
5. Questions loop (Q).
6. Commit `docs(spec): <spec_id> — <title>`, then `cplat spec publish <spec_id>` (opens or updates the draft PR); print its note. Then F.

## C. --amend <id> <change>

1. `cplat spec list --all --json` for the spec and its status. Switch to `feature/<spec_id>` (create it from `main` if the spec is merged).
2. Not `draft` → `cplat spec set-status <id> draft --reason "amend: <one line>"`; tell the user it needs a new approval and, if it has a plan and the criteria change, a new plan.
3. First `cplat spec review <id> --comments --json`. A console review comment ("Request changes") in the request → write it to a temp file and post it: `cplat spec review <id> --request-changes --body-file <file>`. **product-manager**: `MODE: amend`, `SPEC_DIR`, the change verbatim, the review comments, any answers the user gave.
4. `cplat spec check <id>`, Q, commit `docs(spec): amend <spec_id> — <one line>`, `cplat spec publish <spec_id>`, F.

## D. --from-plan <plan> [<repo-id>]

Read `${CLAUDE_PLUGIN_ROOT}/references/spec-from-plan.md` and follow it.

## Q. Questions loop

Only open questions are asked here, because assumptions are decided by default and shown at F. While the product-manager's `OPEN QUESTIONS:` is not `none` (at most 3 rounds):

1. **AskUserQuestion**, up to 4 questions per call: the question as header, the suggested answer first marked "(Recommended)", one or two alternatives. A suggested answer `explore first` becomes the option `/component:explore <topic>` (Recommended); chosen → `cplat spec discard <spec_id>`, `git switch main`, `git branch -d feature/<spec_id>`, then print that command as the next step and stop.
2. Answers to the product-manager: `MODE: amend`, "answers to open questions: …".
3. `cplat spec check <spec_id>`; when the answers change a committed draft, commit `docs(spec): answer open questions for <spec_id>` and `cplat spec publish <spec_id>`.

The user stops answering → the questions stay and the spec stays `draft`.

## F. Finish

```
## Spec <spec_id> — <title>   [<status>]
<n> acceptance criteria:
- AC-NNN.1 …   (one short line each)
Assumptions (decided by default):
- A1 …
Open questions: <n or none> · Non-goals: <short list>
File: docs/specs/<spec_id>/spec.md · Branch: feature/<spec_id>
```

No open questions → one AskUserQuestion: "Approve with these <n> assumptions (Recommended)" / "Change an assumption" / "I'll review the file first". Approve → A. Change → ask which one and the new decision (the user types it), then C with that change and F again. Otherwise the next step: `/component:spec approve <NNN>` after review, or `/component:spec --amend <NNN> <change>`.

## Rules

- Change `status` only through `cplat spec`, because it checks each transition.
- **Hard rule:** Never answer an open question on the user's behalf and never approve without the user's word, because approval exists only in the user's own words.
- **Hard rule:** the only push is `cplat spec publish` / `cplat spec land` (the spec's own branch, never forced, only `docs/specs/<id>/`), so that every check runs before a push.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
