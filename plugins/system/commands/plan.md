---
description: "Split an approved system spec into a per-repo plan (docs/plan/<spec_id>.md). Usage: /system:plan <spec-id>"
---

You are the **system planning orchestrator** (ADR-011, ADR-026). You turn an approved system spec into a plan: which repo implements which criteria, in which order, against which contract. You never touch component repos, because each repo builds from its own spec.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Spec:** $ARGUMENTS (number, slug or full id; empty → `cplat spec list` and ask which)

## cplat

Run `cplat` one call per Bash invocation. Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered. First call:

```bash
cplat shape
```

Stop when it does not report `shape: gitops-app`, because a component repo plans with `/component:plan`.

## 1. Pre-flight

1. Require an empty `git status --porcelain` and an existing `scripts/plan.py` (else `/platform:update` first), so that the branch holds just the spec and plan.
2. `cplat spec check <id> --require approved`; on failure show the fix (`/system:spec approve <NNN>`) and stop.
3. Switch to `docs/spec-<spec_id>` (from `main` if missing). `GITOPS_APP` = `github_org`/`project_name` from `.copier-answers.yml`.
4. If `docs/plan/<spec_id>.md` exists and any repo is `done: true`, the system is partly built: ask before re-planning.

## 2. Planner

**planner** (`system:planner`) with `SPEC: docs/specs/<spec_id>/spec.md`, `PLAN_ID: <spec_id>`, `GITOPS_APP`. It writes `docs/plan/<spec_id>.md` with its `## Contract` and runs `devbox run plan-check`.

Then verify yourself: `devbox run plan-check` and `devbox run -- uv run scripts/plan.py show <spec_id>`. Errors go back to the planner once, then stop and show them. A needed repo that does not exist yet: stop and show the `/component:new` command the planner suggests.

## 3. Commit and hand off

Commit `docs/plan/<spec_id>.md` (and `design.md` if written): `docs(plan): <spec_id> — <n> repos`.

The approved spec and its plan reach `main` through a PR, so that every agent in a fresh clone builds from the reviewed version (spec 050). Ask, then:

```bash
git push -u origin docs/spec-<spec_id>
gh pr create --title "docs(spec): <spec_id> — system spec and plan" --body "<criteria count, repos, levels>"
```

If `gh pr create` is refused, print it as the last line.

Print the `plan.py show` output verbatim, then:

```
Ship it:    /system:ship <NNN>          (unattended, in plan order)
or by hand, per repo, in level order:
  cd ../<repo> && /component:spec --from-plan <abs path to docs/plan/<spec_id>.md> <repo>   then /component:plan <n> and /component:build <n>
Track:      /system:spec show <NNN>
```

## Rules

- Never edit `system.yaml`, overlays or another repo, and never overwrite a plan that has done repos without asking, because finished builds would lose their record.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
