---
description: "Ship an approved spec unattended: plan, build, PR, merge after green CI, wait until dev runs it. Resumable. Usage: /component:ship <spec-id> [--no-merge] [--full]"
---

You are the **ship orchestrator** ([ADR-028](../../../docs/adr/028-unattended-delivery-without-branch-protection.md), specs 066 and 067). The spec's approval was the human decision; from here you work without asking until `dev` runs the merged build, or until a rule needs the user. `cplat component ship` holds the run's state and does every step that can be code (open the PR, wait for checks, merge only on green, wait for the pin); you do the judgement.

**Arguments:** $ARGUMENTS — a spec (number, slug or id) and optionally `--no-merge` (stop at a green PR; you merge) and `--full` (every `cplat validate run` in build and the CI fix rounds runs all checks, spec 103).

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation. First calls:

```bash
cplat shape
```

```bash
cplat component ship start <spec> [--no-merge] [--take-over]
```

`unsupported` or no shape → stop (gitops-app repos ship through `/system:ship`). `ship start` refuses an unapproved spec, an issue the spec tracks that another branch has claimed (spec 082: `--take-over` only when the user says so; it also ends another spec's unfinished run, recorded as `abandoned`), and a repo linked to a gitops-app without the secret `GITOPS_TOKEN` (spec 077). In each case, show its hint and stop. (the system-clone link option is passed by `/system:ship` only.) It prints the phase and the next step; a re-run **resumes** at that phase. Print both outputs verbatim. A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape.

**While the run is not finished, the shared plugin's Stop hook holds only the session that started or resumed the run** (its owner) and tells you the next step, with the failing tests in the build phase. A stop without a new commit or a phase change counts; after two such stops the run escalates by itself, so commit each finished task. Keep working. You may stop earlier only after `cplat component ship escalate '<reason>'` (see Escalate) or when the run is done.

## Unattended rules (they replace the questions the other commands ask)

- Never ask the user. Where `/component:plan` or `/component:build` say "ask", take the unattended choice they name; where they name none, escalate.
- Interrupted build: commit the leftovers as `wip(<task-id>): interrupted` without asking (build Phase 0).
- `cplat component ship start` puts you on the feature branch (creates or switches to it); never create, reset or switch branches yourself.
- `git push` and `gh pr create` are **not** run by you: `cplat component ship pr` does both (it pushes only the spec's feature branch).
- Every shell command goes through `devbox run <script>`, except git, gh and cplat.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow it for this spec. After the architect returns, run `cplat platform runs agent spawned architect [--model-id <id>]` (spec 089). Architect `BLOCKERS` → escalate with them. A plan that already has `done` tasks is not re-planned (escalate instead: re-planning loses progress); the build's own re-plan after a merge conflict (build.md 2.4a) is the exception. Then `cplat component ship phase build`.

## Phase `build`

Read `${CLAUDE_PLUGIN_ROOT}/commands/build.md` and follow its Phases 0–6 for this spec: red acceptance tests, coders until they pass, QA fan-out, verification, image, `set-status done`. Skip its Phase 7 (the PR is ours).

**Gitops tasks** (plan tasks with `repo:`, spec 076) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-gitops.md` and follow it. Its stop-and-escalate rules stay rules here: a `cplat component build merge` escalation (a task's second conflict, the cap of 3 re-plans) or a re-plan the architect cannot make, a changed acceptance test (`cplat spec test-diff` exit 1), a security finding `cplat deps patch` cannot fix (its exit 3), a decision the spec does not answer, a verification that still fails after its cycles. Each one → escalate.

Then `cplat component ship phase pr`.

## Phase `pr`

1. Write the PR body with the Write tool to `.pr-body.md` in the repo root (never into `.git/`: Claude Code refuses edits there; cplat moves the file out of the work tree before it commits) with the template of build.md Phase 7 (summary, spec/plan/verification links, the criteria table from verification.md, `Closes #N` lines, testing done, checklist), then `cplat deps report --body-file .git/PR_BODY.md` to add the Dependency patches section when the build bumped anything.
2. `cplat component ship pr --title "feat(<scope>): <spec title, ≤72 chars>" --body-file .pr-body.md` — runs `devbox run ci` (the CI workflow's gates; red → nothing is pushed: fix it through the coder, record it with `cplat platform runs agent fix-round ci`, and call it again; between rounds `cplat validate run` checks only what the fix can affect, `cplat component ship pr` always runs the whole `devbox run ci`), then pushes the feature branch and opens the PR (or reuses the open one). It refuses while a gitops task has no PR. In the platform repo it also refuses a bad title or a PR that closes an issue and changes platform code without a spec, before pushing; `--no-spec` (only for a one-line fix or docs-only PR that closes an issue) adds the `no-spec` label.

## Phase `land`

`cplat component ship land` waits for the PR's checks and prints each one as it concludes. The first red check ends the wait (spec 072); a run whose check stays in progress after the run completed, or whose jobs stay queued for `--queue-timeout` (300 s) while nothing of the PR runs, is rerun once; the second time it is an error naming the runner set. A job that failed on a transient error (a download, a registry, the network) is rerun once before it counts as red (spec 079). Outside a ship run, wait for any PR with `cplat pr wait <pr> [-R owner/repo] [--merge]`; never write a polling loop. When all are green it marks each `before-merge` gitops PR ready, waits for its checks and merges it, then merges the PR.

- **GREEN** → it merges the PR (squash; with `--no-merge` it stops and the run is done) and moves to `deploy`.
- `cplat component ship land` exits non-zero (**RED**, exit 1, the security check, or an error such as no checks reported, timeout, merge refused) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-land-red.md` and follow it (3 red rounds, `fix_rounds` in `cplat component ship status`, then escalate; a red security check → `cplat deps patch`, then `cplat deps report --body-file .git/PR_BODY.md --update-pr`, `cplat component ship escalate '<reason>' --cause <CAUSE>` on exit 3).

## Phase `deploy`

`cplat component ship deploy` (add `--context <kube-context>` when the user named one or `kubectl config current-context` works and points at the system's cluster) waits until the gitops-app merged the pin PR for the merge commit (ADR-027) and, with a context, Argo CD runs that build: `<service>-dev` counts only once `status.summary.images` shows the merged build's tag, never on the old image (spec 077). A red service CI on main, a failed pin-dev run, or no pin-dev run 5 min after main's CI passed (no `GITOPS_TOKEN`) fails it at once; a stuck pin-dev run is rerun once. Then it merges the `after-release` gitops PRs in plan order and, with a context, waits for Synced/Healthy of `<service>-dev` and every app the gitops tasks name (`apps:`), once they reached the merged gitops commit; a SyncError or Degraded app is an error. Then it runs `devbox run smoke` against the dev URL the gitops-app publishes (spec 091; pass `--base-url <url>` only when the user named one), one retry after 30 s, 600 s at most: it checks every `(smoke)` criterion of the spec. Red or timed-out smoke makes deploy itself escalate with cause `code` (`smoke red in dev: <n> failing (<spec>)`) and file the `smoke-failure` issue in the service repo: report its lines and stop; never call `cplat component ship escalate` for it, and dev is not rolled back. Resuming (`/component:ship <spec>`) reruns smoke only. After a green dev smoke, deploy promotes staging itself when `promotion.staging` is `auto` (spec 093, ADR-041): it dispatches the gitops-app's `pin-staging` workflow, waits for its self-merging PR and for Argo `<service>-staging` (15 minutes from the green smoke), then smokes staging: print its `Promotion (staging)` and `Smoke (staging)` lines. A failed pin escalates with cause `environment` (`staging pin failed for …`), a red staging smoke with cause `code` (`smoke red in staging: …`, a `smoke-failure` issue; no rollback). Otherwise deploy prints `Promotion (staging): not promoted: <reason>`. Smoke that could not run (no `--context`, not exposed in dev, URL unreachable, no recipe) is "not run": deploy finishes `done` and the criteria stay unchecked. A repo without a gitops-app link finishes here with a note. In the platform repo (shape `platform`) deploy ends at once with `not deployable (platform): nothing to deploy`: no pin, Argo, smoke or staging, and no `devbox run smoke` (which here smoke-tests the templates). A closed pin PR, a red pin CI or an unhealthy app → escalate with the hint. Its last lines list the plan's `human_steps` as a checklist: copy them into the final report.

## Finish

When deploy printed `not deployable (<shape>): nothing to deploy`, the `dev`, `Promotion (staging)`, `Smoke (staging)` and `Smoke (dev)` rows read `not deployable`; leave out the Unchecked line and every `Next:` line that names `/instance:promote`.

The run record (spec 087) is written when the run reaches `done` or escalates; a warning line about a buffered record is not an error.

`cplat component ship status`, then `cplat component ship finish`, then print:

```
## Shipped: <spec_id> — <title>

| Step | Result |
|---|---|
| Plan | <n> tasks |
| Build | <m>/<m> criteria met (verification.md) |
| PR | <url> — merged after <k> CI round(s) |
| dev | <service>:sha-<40> (pin PR <url>) · Argo <state> | not linked |
| Promotion (staging) | <the `Promotion (staging):` line from deploy: `sha-<40> (<pin PR url>)`, or `not promoted: <reason>` (spec 093)> |
| Smoke (staging) | <the `Smoke (staging):` value, or `-` when nothing was promoted> |
| Smoke (dev) | <the `Smoke (dev):` value from deploy: `<p>/<total> passed`, `passed on retry` or `not run: <reason>`> |

Dependency patches: the bumps of `cplat deps report` (package, from → to, CVE), a major bump marked "major bump"; leave out when none.

Unchecked (smoke) criteria: <ids>   (only when smoke did not run; "none" otherwise)

Next: check staging, then promote with /instance:promote <component> --to prod in the gitops-app repo.     (staging promoted)
Next: promote with /instance:promote <component> --to staging in the gitops-app repo.     (smoke passed, staging not promoted)
Next: check the unchecked criteria in dev by hand; then promote with /instance:promote <component> --to staging.     (smoke did not run)
```

## Escalate

`cplat component ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (always pass the cause; it says who must act: `platform` = a platform template, script or command misbehaved, `code` = the user's code or tests, `decision` = the spec or a rule needs the user, `environment` = runner, cluster, network, a missing secret or login; a missing or unknown cause is recorded as `unknown`). For `platform` also pass `--command '<the failing command>'` and the failing output through `--evidence-file -` (stdin) or a file. cplat files the platform failure as a deduplicated issue (or adds a +1 to the open one) and prints `issue: <url> new|+1`: report that line, then print the reason, the state (`cplat component ship status`) and only what the user must decide. The run resumes where it stopped with `/component:ship <spec>`. If the user asks you to stop or pause, escalate with `paused by the user`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), escalate with `--cause platform`. The issue is filed automatically (spec 088); with `CPLAT_AUTO_ISSUES=off` cplat prints the draft and the `/issue:report` hint instead.
