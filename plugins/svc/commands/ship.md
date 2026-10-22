---
description: "Ship an approved spec unattended: plan → build (red tests → green) → PR → merge after green CI → wait until dev runs it. Resumable; the Stop hook keeps the run going until it is done or needs you. Usage: /svc:ship <spec-id> [--no-merge]"
---

You are the **ship orchestrator** ([ADR-028](../../../docs/adr/028-unattended-delivery-without-branch-protection.md), specs 066 and 067). The spec's approval was the human decision; from here you work without asking until `dev` runs the merged build, or until a rule needs the user. `cplat ship` holds the run's state and does every step that can be code (open the PR, wait for checks, merge only on green, wait for the pin); you do the judgement.

**Arguments:** $ARGUMENTS — a spec (number, slug or id) and optionally `--no-merge` (stop at a green PR; you merge).

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation. First calls:

```bash
cplat shape
```

```bash
cplat ship start <spec> [--no-merge]
```

`unsupported` or no shape → stop (gitops-app repos ship through `/app:build`). `ship start` refuses an unapproved spec: show its hint and stop. It prints the phase and the next step; a re-run **resumes** at that phase. Print both outputs verbatim.

**While the run is not finished, the shared plugin's Stop hook refuses to let the session end** and tells you the next step, with the failing tests in the build phase. That is intended: keep working. You may stop only after `cplat ship escalate '<reason>'` (see Escalate) or when the run is done.

## Unattended rules (they replace the questions the other commands ask)

- Never ask the user. Where `/svc:plan` or `/svc:build` say "ask", take the unattended choice they name; where they name none, escalate.
- Interrupted build: commit the leftovers as `wip(<task-id>): interrupted` without asking (build Phase 0).
- `git push` and `gh pr create` are **not** run by you: `cplat ship pr` does both (it pushes only the spec's feature branch).
- Every shell command goes through `devbox run <script>`, except git, gh and cplat.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow it for this spec. Architect `BLOCKERS` → escalate with them. A plan that already has `done` tasks is not re-planned (escalate instead: re-planning loses progress). Then `cplat ship phase build`.

## Phase `build`

Read `${CLAUDE_PLUGIN_ROOT}/commands/build.md` and follow its Phases 0–6 for this spec: red acceptance tests, coders until they pass, QA fan-out, verification, image, `set-status done`. Skip its Phase 7 (the PR is ours).

**Gitops tasks** (plan tasks with `repo:`, spec 076) are not given to the service coders. For each, in plan order: `cplat ship gitops prepare <task>` (prints a checkout of that repo on `spec/<spec>-<task>`), make the change there through the gitops plugin's conventions (`devbox run validate` in that checkout), commit `feat(<scope>): <what>`, write a short body and `cplat ship gitops pr <task> --title <title> --body-file <file>` (a draft PR; its CI runs now). `cplat ship land` merges the `before-merge` ones, `cplat ship deploy` the `after-release` ones. Its stop-and-escalate rules stay rules here: a merge conflict between task branches, a changed acceptance test (`cplat spec test-diff` exit 1), a CRITICAL security finding, a decision the spec does not answer, a verification that still fails after its cycles. Each one → escalate.

Then `cplat ship phase pr`.

## Phase `pr`

1. Write the PR body to `.git/PR_BODY.md` with the template of build.md Phase 7 (summary, spec/plan/verification links, the criteria table from verification.md, `Closes #N` lines, testing done, checklist).
2. `cplat ship pr --title "feat(<scope>): <spec title, ≤72 chars>" --body-file .git/PR_BODY.md` — runs `devbox run ci` (the CI workflow's gates; red → nothing is pushed: fix it through the coder and call it again), then pushes the feature branch and opens the PR (or reuses the open one). It refuses while a gitops task has no PR.

## Phase `land`

`cplat ship land` waits for the PR's checks and prints each one as it concludes. The first red check ends the wait (spec 072); a run whose check stays in progress after the run completed, or whose jobs stay queued for `--queue-timeout` (300 s) while nothing of the PR runs, is rerun once; the second time it is an error naming the runner set. When all are green it marks each `before-merge` gitops PR ready, waits for its checks and merges it, then merges the PR.

- **GREEN** → it merges the PR (squash; with `--no-merge` it stops and the run is done) and moves to `deploy`.
- **RED** (exit 1) → it prints the failed checks and their log tails. Hand them to the coder agent (`agents.coder`) of the task whose files are involved, with `<project-map>`: "fix these CI failures; never edit, skip or weaken an acceptance test". Run `devbox run ci`, commit `fix(ci): <what>`, then `cplat ship pr --title <same title> --body-file .git/PR_BODY.md` (pushes) and `cplat ship land` again. After **3** red rounds (`fix_rounds` in `cplat ship status`), escalate with the last failure.
- An error (no checks reported, timeout, merge refused) → read its hint; a transient one (runner busy) → `cplat ship land` once more; otherwise escalate.

## Phase `deploy`

`cplat ship deploy` (add `--context <kube-context>` when the user named one or `kubectl config current-context` works and points at the product's cluster) waits until the gitops-app merged the pin PR for the merge commit (ADR-027) and, with a context, Argo CD reports `<service>-dev` Synced/Healthy. A red check on the open pin PR fails it at once. Then it merges the `after-release` gitops PRs in plan order and, with a context, waits for Synced/Healthy of `<service>-dev` and every app the gitops tasks name (`apps:`); a SyncError or Degraded app is an error. A repo without a gitops-app link finishes here with a note. A closed pin PR, a red pin CI or an unhealthy app → escalate with the hint. Its last lines list the plan's `human_steps` as a checklist: copy them into the final report.

## Finish

`cplat ship status`, then `cplat ship finish`, then print:

```
## Shipped: <spec_id> — <title>

| Step | Result |
|---|---|
| Plan | <n> tasks |
| Build | <m>/<m> criteria met (verification.md) |
| PR | <url> — merged after <k> CI round(s) |
| dev | <service>:sha-<7> (pin PR <url>) · Argo <state> | not linked |

Next: check the feature in dev; promote with /gitops:promote <service> dev staging in the gitops-app repo.
```

## Escalate

`cplat ship escalate '<one line: what needs the user and where>'`, then print the reason, the state (`cplat ship status`) and what the user should decide. The run resumes where it stopped with `/svc:ship <spec>`. If the user asks you to stop or pause, escalate with `paused by the user`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), escalate, summarize it in two lines and offer `/shared:report-issue`. Never file anything without the user's OK.
