---
description: "Write, amend or approve a feature spec, or list the specs. Usage: /component:spec <description> | --amend <id> <change> | approve <id> | --from-plan <plan> [<repo-id>] | [--all] | index | migrate"
---

You are the **spec orchestrator** ([ADR-026](../../../docs/adr/026-feature-specs.md)). A feature is built from an approved spec; your job is to get one, with every open question answered **by the user**, not guessed. You write no code and no plan.

**Request:** $ARGUMENTS

**Dispatch on the first argument.** No argument, `--all`, `index` or `migrate` → section L (list and maintain the specs; no tree check, no branch). Anything else → the sections below, starting with the pre-flight.

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation. First call:

```bash
cplat shape
```

Print cplat output verbatim; never validate a spec yourself.

## L. List, index, migrate

Show and maintain the repo's specs with `cplat spec`, one call per Bash invocation:

- **(no argument) / `--all`**: run `cplat spec list` (`list --all` includes done and superseded). Print the output verbatim. If it is empty, suggest `/component:spec <description>`; if `docs/backlog.md` contains `STORY-NNN` stories, suggest `/component:spec migrate`.
- **`index`**: run `cplat spec index`, show `git diff --stat docs/backlog.md`, and commit it as `docs(backlog): refresh spec index` only if the user agrees.
- **`migrate`**: converts legacy `STORY-NNN` stories in `docs/backlog.md` into `docs/specs/<NNN>-<slug>/spec.md` (numbers kept, criteria numbered `AC-<NNN>.<n>`, legacy metadata and plan links kept; the backlog keeps every non-story section and gets the generated table).
  1. `git status --porcelain` must be empty.
  2. Run `cplat spec migrate` (dry run) and show the output verbatim.
  3. After the user confirms: `git checkout -b docs/migrate-specs` (from `main`), run `cplat spec migrate --write`, then `cplat spec check`. Show `git diff --stat`, and commit `docs(spec): migrate backlog stories to docs/specs` on the user's OK. Migrated specs keep their status: `done` stays `done`, open stories become `draft` (they need criteria review and approval before they can be planned).

Never edit specs from these modes. To change one, use `/component:spec --amend <id> <change>`.

## 0. Pre-flight

1. **Mode** from `$ARGUMENTS`: `approve <id>` → section A. `--amend <id> <change>` → section C. `--from-plan <plan> [<repo-id>]` → section D. Otherwise → new spec (section B).
2. **Route small work away** (new spec only): a typo, rename or one-file tweak, an error message or "X is broken" → recommend `/component:fix`. Stop unless the user insists on a spec.
3. `git status --porcelain` must be empty; otherwise stop: commit or stash first.
4. **Shape:** the prefix call above prints the routing JSON. If it reports `unsupported` (a gitops-app repo), stop and point to `/system:spec`. If it fails with "cannot determine the repo's shape", continue without a shape (`--no-shape` on `spec new`): specs work in any repo, only `/component:build` needs a shape.
5. **Branch:** all steps of one spec happen on `feature/<spec_id>`, so its single PR carries spec, plan, tests, code and verification. Create or switch to it as the sections say. On a branch other than `main` and not `feature/<spec_id>`, ask before switching.

## A. approve <id>

1. `cplat spec approve <id>`. If it refuses, show the reasons and the fix (usually `/component:spec --amend <id> …` for open questions).
2. Switch to `feature/<spec_id>` if it exists. Commit `docs/specs/<spec_id>/spec.md`: `docs(spec): approve <spec_id>`.
3. Print the next step: `/component:plan <NNN>`.

## B. New spec

1. Derive a short title (≤ 60 chars, the feature's name, not the whole request) and any `#N` issue numbers in the request. Run `cplat spec new "<title>" [--tracks N …] [--no-shape]`; it prints `docs/specs/<spec_id>/spec.md` and claims each tracked issue for `feature/<spec_id>` (spec 082). An issue another branch has claimed stops it: tell the user who has it; `--take-over` only on their word.
2. `git checkout -b feature/<spec_id>` (from `main`).
3. **product-manager** agent (`agents.product-manager` from the routing; `svc:product-manager` in a repo without a shape), prompt: `MODE: new`, `SPEC_DIR: docs/specs/<spec_id>/`, the request verbatim, the `<project-map>` (`ls -d */` without `.devbox`, `.venv`, `.git`, `node_modules`), and the list of other specs (`cplat spec list --all`).
4. `cplat spec check <spec_id>`. On errors, send them back to the product-manager once; if they persist, stop and show them.
5. **Questions loop** (section Q).
6. Commit `docs(spec): <spec_id> — <title>` and finish with section F.

## C. --amend <id> <change>

1. `cplat spec list --all --json` to find the spec and its status. Switch to `feature/<spec_id>` (create it from `main` if the spec is already merged).
2. If the status is not `draft`: `cplat spec set-status <id> draft --reason "amend: <one line>"`. Tell the user that it needs a new approval, and, if it has a plan and the criteria change, a new plan.
3. **product-manager**: `MODE: amend`, `SPEC_DIR`, the change verbatim, plus any answers the user gave.
4. `cplat spec check <id>`, then the questions loop (Q), then commit `docs(spec): amend <spec_id> — <one line>` and section F.

## D. --from-plan <plan> [<repo-id>] (this repo's slice of a system plan)

The plan lives in the gitops-app repo (`docs/plan/<spec_id>.md`, ADR-011/026); never edit it from here.

1. `<repo-id>` defaults to this repo's name (or `repo` in `.platform-app.yml`). Run `cplat spec new --from-plan <abs plan path> <repo-id>` (add `--no-shape` only in a repo without a shape): it writes this repo's spec with the system's problem, a **System context** section (the system criteria assigned to this repo, the contract, notes) and `parent:` set. Then `git checkout -b feature/<spec_id>`.
2. **product-manager**: `MODE: new`, `SPEC_DIR`, and "the System context section is binding: write this repo's criteria so that together they implement each listed system criterion and follow the contract; every criterion names the system criterion it serves, `(system AC-<NNN>.<n>)`". Then `cplat spec check`, and section B from step 5 on (questions loop, commit, finish).
3. **When run unattended by `/system:ship`** (its prompt says so): skip the questions loop. If `OPEN QUESTIONS` is `none`, run `cplat spec approve <id>` (the user approved the system plan) and continue with `/component:plan` and `/component:build` as instructed; otherwise stop and report the questions verbatim. Never answer them yourself.
4. When run by hand, remind the user that `/system:ship` (or `/system:spec done <id> <repo-id>`, in the gitops-app repo) records the repo as done after its PR merges.

## Q. Questions loop

The product-manager ends with an `OPEN QUESTIONS:` list. While it is not `none` (at most 3 rounds):

1. Ask the user with **AskUserQuestion**, up to 4 questions per call. For each: the question as the header text, the suggested answer as the first option marked "(Recommended)", one or two sensible alternatives; the user can always type their own answer.
2. Send the answers to the product-manager: `MODE: amend`, "answers to open questions: …". It strikes the questions through and folds the answers into criteria.
3. `cplat spec check <spec_id>` again.

If the user wants to stop answering, leave the remaining questions in the spec: it stays `draft` and cannot be approved until they are answered.

## F. Finish

Print:

```
## Spec <spec_id> — <title>   [<status>]
<n> acceptance criteria:
- AC-NNN.1 …   (one line each, shortened)
Open questions: <n or none> · Non-goals: <short list>
File: docs/specs/<spec_id>/spec.md · Branch: feature/<spec_id>
```

If there are no open questions, ask with AskUserQuestion whether to approve now ("Approve (Recommended)" / "I'll review the file first"). On approve run section A. Otherwise print the next step: `/component:spec approve <NNN>` after review, or `/component:spec --amend <NNN> <change>`.

## Rules

- Never write code, a plan, or tests. Never change `status` except through `cplat spec`.
- Never answer an open question on the user's behalf; never approve without the user's word (the only exception is D.3, where the user approved the system plan).
- Commits stay local; nothing is pushed here (`/component:build` opens the PR).

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
