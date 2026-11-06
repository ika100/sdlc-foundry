---
description: "Ship an approved spec unattended: plan, build, PR, merge after green CI, wait until dev runs it. Resumable. Usage: /component:ship <spec-id> [--no-merge] [--full]"
---

You are the **ship orchestrator** ([ADR-028](../../../docs/adr/028-unattended-delivery-without-branch-protection.md), specs 066 and 067). The spec's approval was the human decision: work without asking until `dev` runs the merged build, or a rule needs the user. `cplat component ship` holds the state and does every step that can be code; you do the judgement.

**Arguments:** $ARGUMENTS — a spec (number, slug or id); `--no-merge` (stop at a green PR); `--full` (every `cplat validate run` in build and the CI fix rounds runs all checks, spec 103). `--unit <unit>` (headless, spec 131): only that unit, per `${CLAUDE_PLUGIN_ROOT}/references/unit-mode.md`.

## cplat

`cplat` is on the Bash PATH; one call per Bash invocation, output read whole (no `grep`, `head` or `tail`). First `cplat shape`, then `cplat component ship start <spec> [--no-merge] [--take-over]`; print both verbatim.

`unsupported` or no shape → stop (gitops-app repos use `/system:ship`). A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape. When `ship start` refuses (an unapproved spec, a tracked issue another branch claimed, a missing `GITOPS_TOKEN`), show its hint and stop; `--take-over` only when the user says so. It prints the phase and next step; a re-run **resumes** there.

**While the run is not finished, the Stop hook holds the session** with the next step; two stops without a new commit or phase change escalate the run, so commit each task. Run subagents in the foreground (`run_in_background: false`) and never poll for one in a shell loop (#496). Stop earlier only on `cplat component ship escalate '<reason>'` or when the run is done.

## Unattended rules (they replace the questions the other commands ask)

- Never ask the user. Where `/component:plan` or `/component:build` say "ask", take the unattended choice they name; where they name none, escalate.
- Interrupted build: commit the leftovers as `wip(<task-id>): interrupted` without asking (build Phase 0).
- `cplat component ship start` puts you on the feature branch; never create, reset or switch branches yourself.
- You never run `git push` or `gh pr create`: `cplat component ship pr` does both.
- Every shell command goes through `devbox run <script>`, except git, gh and cplat.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow it for this spec; after the architect, `cplat platform runs agent spawned architect [--model-id <id>]`. Architect `BLOCKERS` → escalate with them. A plan with `done` tasks is not re-planned (escalate; the build's re-plan after a merge conflict, build.md 2.4a, is the exception). Then `cplat component ship phase build`.

## Phase `build`

Read `${CLAUDE_PLUGIN_ROOT}/commands/build.md` and follow its Phases 0–6 for this spec; skip Phase 7 (the PR is ours). Gitops tasks (plan tasks with `repo:`, spec 076) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-gitops.md` and follow it.

Escalate on build's stop rules: a `cplat component build merge` escalation or a re-plan the architect cannot make, a changed acceptance test (`cplat spec test-diff` exit 1), a security finding `cplat deps patch` cannot fix (its exit 3), a decision the spec does not answer, a verification still failing after its cycles. Then `cplat component ship phase pr`.

## Phase `pr`

1. Write `.pr-body.md` in the repo root (Write tool, never into `.git/`) with the template in `${CLAUDE_PLUGIN_ROOT}/references/build-pr.md` (PR body), then `cplat deps report --body-file .git/PR_BODY.md` (adds the Dependency patches section when the build bumped anything).
2. `cplat component ship pr --title "feat(<scope>): <spec title, ≤72 chars>" --body-file .pr-body.md`: it runs the whole `devbox run ci` first; red → nothing is pushed: fix it through the coder (`cplat platform runs agent fix-round ci`), `cplat validate run` between rounds, and call it again. Then it pushes the feature branch and opens (or reuses) the PR; it refuses while a gitops task has no PR (platform repo: `--no-spec` waives the spec).

## Phase `land`

`cplat component ship land` waits for the PR's checks (it reruns stuck and transient runs itself), merges the `before-merge` gitops PRs, then the PR.

- **GREEN** → merged (squash; with `--no-merge` it stops and the run is done), phase `deploy`.
- Non-zero exit (**RED**, the security check, or an error) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-land-red.md` and follow it (3 red rounds, `fix_rounds` in `cplat component ship status`, then escalate; a red security check → `cplat deps patch`, then `cplat deps report --body-file .git/PR_BODY.md --update-pr`, `cplat component ship escalate '<reason>' --cause <CAUSE>` on exit 3).

## Phase `deploy`

`cplat component ship deploy [--context <kube-context>] [--base-url <url>]`: the context when the user named one or `kubectl config current-context` points at the system's cluster; `--base-url` only when the user named one. It waits for the pin PR (ADR-027) and Argo CD (Synced/Healthy), merges the `after-release` gitops PRs, runs `devbox run smoke` on dev for every `(smoke)` criterion (spec 091) and, with `promotion.staging: auto`, promotes and smokes staging (spec 093). Print its `Smoke (dev)`, `Promotion (staging)` and `Smoke (staging)` lines.

- Red smoke (`smoke red in dev: …`, or in staging) or a failed staging pin: deploy escalates by itself and files the `smoke-failure` issue; report its lines and stop. Never call `cplat component ship escalate` for it; nothing is rolled back. A resume reruns smoke only.
- Smoke that could not run is "not run": the run ends `done`, the criteria stay unchecked.
- Shape `platform`: deploy ends at once with `not deployable (platform): nothing to deploy`: no pin, Argo, smoke or staging, and no `devbox run smoke` (which here smoke-tests the templates).
- In a joint `/system:ship` (spec 144) it ends once main's CI built the image: `pinned in the system ship's dev PR`.
- A closed pin PR, a red pin CI or an unhealthy app → escalate with the hint.

## Finish

`cplat component ship status`, then `cplat component ship finish`, then print the report in `${CLAUDE_PLUGIN_ROOT}/references/ship-finish.md` (rows from deploy's lines, `cplat deps report`'s bumps, the plan's `human_steps`). A warning about a buffered run record is not an error.

## Escalate

`cplat component ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (always pass the cause: `platform` = a platform template, script or command misbehaved, `code` = the user's code or tests, `decision` = the spec or a rule needs the user, `environment` = runner, cluster, network, a missing secret or login). For `platform` also pass `--command '<the failing command>'` and the output through `--evidence-file -` (stdin) or a file; report the `issue: <url> new|+1` line it prints. Then print the reason, `cplat component ship status` and only what the user must decide. Resume with `/component:ship <spec>`. The user asks to stop or pause → escalate with `paused by the user`.

> A platform template, script or command misbehaves (not the user's code) → escalate with `--cause platform`; cplat files the issue (spec 088; with `CPLAT_AUTO_ISSUES=off` it prints the draft and the `/issue:report` hint).
