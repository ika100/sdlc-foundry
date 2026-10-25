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
cplat ship start <spec> [--no-merge] [--take-over]
```

`unsupported` or no shape → stop (gitops-app repos ship through `/app:build`). `ship start` refuses an unapproved spec, an issue the spec tracks that another branch has claimed (spec 082: `--take-over` only when the user says so; it also ends another spec's unfinished run, recorded as `abandoned`), and a repo linked to a gitops-app without the secret `GITOPS_TOKEN` (spec 077). In each case, show its hint and stop. (`--product <dir>` is passed by `/app:ship` only: it links the run to a product ship, giving it a parent record, the product's kube context and the gitops merge slot.) It prints the phase and the next step; a re-run **resumes** at that phase. Print both outputs verbatim.

**While the run is not finished, the shared plugin's Stop hook refuses to let the session end** and tells you the next step, with the failing tests in the build phase. That is intended: keep working. You may stop only after `cplat ship escalate '<reason>'` (see Escalate) or when the run is done.

## Unattended rules (they replace the questions the other commands ask)

- Never ask the user. Where `/svc:plan` or `/svc:build` say "ask", take the unattended choice they name; where they name none, escalate.
- Interrupted build: commit the leftovers as `wip(<task-id>): interrupted` without asking (build Phase 0).
- `git push` and `gh pr create` are **not** run by you: `cplat ship pr` does both (it pushes only the spec's feature branch).
- Every shell command goes through `devbox run <script>`, except git, gh and cplat.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow it for this spec. After the architect returns, run `cplat runs agent spawned architect [--model-id <id>]` (spec 089). Architect `BLOCKERS` → escalate with them. A plan that already has `done` tasks is not re-planned (escalate instead: re-planning loses progress); the build's own re-plan after a merge conflict (build.md 2.4a) is the exception. Then `cplat ship phase build`.

## Phase `build`

Read `${CLAUDE_PLUGIN_ROOT}/commands/build.md` and follow its Phases 0–6 for this spec: red acceptance tests, coders until they pass, QA fan-out, verification, image, `set-status done`. Skip its Phase 7 (the PR is ours).

**Gitops tasks** (plan tasks with `repo:`, spec 076) are not given to the service coders. For each, in plan order: `cplat ship gitops prepare <task>` (prints a checkout of that repo on `spec/<spec>-<task>`), make the change there through the gitops plugin's conventions (`devbox run validate` in that checkout), commit `feat(<scope>): <what>`, write a short body and `cplat ship gitops pr <task> --title <title> --body-file <file>` (a draft PR; its CI runs now). `cplat ship land` merges the `before-merge` ones, `cplat ship deploy` the `after-release` ones. Its stop-and-escalate rules stay rules here: a merge conflict that `cplat build merge` escalates (a task's second conflict, or the cap of 3 re-plans) or a re-plan the architect cannot make, a changed acceptance test (`cplat spec test-diff` exit 1), a security finding `cplat deps patch` cannot fix (its exit 3), a decision the spec does not answer, a verification that still fails after its cycles. Each one → escalate.

Then `cplat ship phase pr`.

## Phase `pr`

1. Write the PR body to `.git/PR_BODY.md` with the template of build.md Phase 7 (summary, spec/plan/verification links, the criteria table from verification.md, `Closes #N` lines, testing done, checklist), then `cplat deps report --body-file .git/PR_BODY.md` to add the Dependency patches section when the build bumped anything.
2. `cplat ship pr --title "feat(<scope>): <spec title, ≤72 chars>" --body-file .git/PR_BODY.md` — runs `devbox run ci` (the CI workflow's gates; red → nothing is pushed: fix it through the coder, record it with `cplat runs agent fix-round ci`, and call it again), then pushes the feature branch and opens the PR (or reuses the open one). It refuses while a gitops task has no PR.

## Phase `land`

`cplat ship land` waits for the PR's checks and prints each one as it concludes. The first red check ends the wait (spec 072); a run whose check stays in progress after the run completed, or whose jobs stay queued for `--queue-timeout` (300 s) while nothing of the PR runs, is rerun once; the second time it is an error naming the runner set. A job that failed on a transient error (a download, a registry, the network) is rerun once before it counts as red (spec 079). Outside a ship run, wait for any PR with `cplat pr wait <pr> [-R owner/repo] [--merge]`; never write a polling loop. When all are green it marks each `before-merge` gitops PR ready, waits for its checks and merges it, then merges the PR.

- **GREEN** → it merges the PR (squash; with `--no-merge` it stops and the run is done) and moves to `deploy`.
- **RED** (exit 1) → `cplat ship land` records the round against the coder itself (spec 089), so there is no `cplat runs agent` call here. It prints the failed checks and their log tails. Hand them to the coder agent (`agents.coder`) of the task whose files are involved, with `<project-map>`: "fix these CI failures; never edit, skip or weaken an acceptance test". Run `devbox run ci`, commit `fix(ci): <what>`, then `cplat ship pr --title <same title> --body-file .git/PR_BODY.md` (pushes) and `cplat ship land` again. After **3** red rounds (`fix_rounds` in `cplat ship status`), escalate with the last failure.
- **RED, the security check** (spec 095) → other red checks go to the coder first. Then `cplat deps patch`: exit 0 → `cplat deps report --body-file .git/PR_BODY.md --update-pr`, then `cplat ship pr --title <same title> --body-file .git/PR_BODY.md` and `cplat ship land`; exit 3 → `cplat ship escalate '<reason>' --cause <CAUSE>` with the `ESCALATE` and `CAUSE` lines it printed; exit 4 → the coder as above. The round counts toward the 3 (`fix_rounds`).
- An error (no checks reported, timeout, merge refused) → read its hint; a transient one (runner busy) → `cplat ship land` once more; otherwise escalate.

## Phase `deploy`

`cplat ship deploy` (add `--context <kube-context>` when the user named one or `kubectl config current-context` works and points at the product's cluster) waits until the gitops-app merged the pin PR for the merge commit (ADR-027) and, with a context, Argo CD runs that build: `<service>-dev` counts only once `status.summary.images` shows the merged build's tag, never on the old image (spec 077). A red service CI on main, a failed pin-dev run, or no pin-dev run 5 min after main's CI passed (no `GITOPS_TOKEN`) fails it at once; a stuck pin-dev run is rerun once. Then it merges the `after-release` gitops PRs in plan order and, with a context, waits for Synced/Healthy of `<service>-dev` and every app the gitops tasks name (`apps:`), once they reached the merged gitops commit; a SyncError or Degraded app is an error. Then it runs `devbox run smoke` against the dev URL the gitops-app publishes (spec 091; pass `--base-url <url>` only when the user named one), one retry after 30 s, 600 s at most: it checks every `(smoke)` criterion of the spec. Red or timed-out smoke makes deploy itself escalate with cause `code` (`smoke red in dev: <n> failing (<spec>)`) and file the `smoke-failure` issue in the service repo: report its lines and stop; never call `cplat ship escalate` for it, and dev is not rolled back. Resuming (`/svc:ship <spec>`) reruns smoke only. Smoke that could not run (no `--context`, not exposed in dev, URL unreachable, no recipe) is "not run": deploy finishes `done` and the criteria stay unchecked. A repo without a gitops-app link finishes here with a note. A closed pin PR, a red pin CI or an unhealthy app → escalate with the hint. Its last lines list the plan's `human_steps` as a checklist: copy them into the final report.

## Finish

The run record (spec 087) is written when the run reaches `done` or escalates; a warning line about a buffered record is not an error.

`cplat ship status`, then `cplat ship finish`, then print:

```
## Shipped: <spec_id> — <title>

| Step | Result |
|---|---|
| Plan | <n> tasks |
| Build | <m>/<m> criteria met (verification.md) |
| PR | <url> — merged after <k> CI round(s) |
| dev | <service>:sha-<40> (pin PR <url>) · Argo <state> | not linked |
| Smoke (dev) | <the `Smoke (dev):` value from deploy: `<p>/<total> passed`, `passed on retry` or `not run: <reason>`> |

Dependency patches: the bumps of `cplat deps report` (package, from → to, CVE), a major bump marked "major bump"; leave out when none.

Unchecked (smoke) criteria: <ids>   (only when smoke did not run; "none" otherwise)

Next: promote with /gitops:promote <service> dev staging in the gitops-app repo.     (smoke passed)
Next: check the unchecked criteria in dev by hand; then promote with /gitops:promote <service> dev staging.     (smoke did not run)
```

## Escalate

`cplat ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (always pass the cause; it says who must act: `platform` = a platform template, script or command misbehaved, `code` = the user's code or tests, `decision` = the spec or a rule needs the user, `environment` = runner, cluster, network, a missing secret or login; a missing or unknown cause is recorded as `unknown`). For `platform` also pass `--command '<the failing command>'` and the failing output through `--evidence-file -` (stdin) or a file. cplat files the platform failure as a deduplicated issue (or adds a +1 to the open one) and prints `issue: <url> new|+1`: report that line, then print the reason, the state (`cplat ship status`) and only what the user must decide. The run resumes where it stopped with `/svc:ship <spec>`. If the user asks you to stop or pause, escalate with `paused by the user`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), escalate with `--cause platform`. The issue is filed automatically (spec 088); with `CPLAT_AUTO_ISSUES=off` cplat prints the draft and the `/shared:report-issue` hint instead.
