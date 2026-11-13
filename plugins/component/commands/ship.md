---
description: "Ship an approved spec unattended: plan, build, PR, merge after green CI, wait until dev runs it. Resumable. Usage: /component:ship <spec-id> [--no-merge] [--full]"
---

You are the **ship orchestrator** (ADR-028). The spec's approval was the human decision: work without asking until `dev` runs the merged build, or a rule needs the user. `cplat component ship` holds the state; you do the judgement.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Arguments:** $ARGUMENTS — a spec (number, slug or id); `--no-merge` (stop at green PR); `--full` (every `cplat validate run` in build and CI fix rounds runs every check). `--unit <unit>`: that unit alone, per `${CLAUDE_PLUGIN_ROOT}/references/unit-mode.md`.

## cplat

One `cplat` call per Bash invocation, output read whole (no `grep`, `head` or `tail`). First `cplat shape`, then `cplat component ship start <spec> [--no-merge] [--take-over]`; print both verbatim.

- `unsupported` or no shape → stop (gitops-app repos use `/system:ship`).
- A `cplat shape` error that names `.platform-settings.yml` → stop and show it; never ask for the shape. Since the user fixes it, a guess hides it.
- When `ship start` refuses (an unapproved spec, a tracked issue another branch claimed, a missing `GITOPS_TOKEN`), show its hint and stop; `--take-over` is the user's call, since it takes over another branch's claim.
**Until the run is finished, the Stop hook holds the session** with the next step; two stops without a new commit or phase change escalate the run, so commit each task. Run subagents in the foreground (`run_in_background: false`), never polling in a shell loop, because a loop can match itself and never end. Stop earlier through `cplat component ship escalate '<reason>'`.

## Unattended rules

- Never ask the user, because the spec's approval was the decision. Where `/component:plan` or `/component:build` say "ask", take the unattended choice they name; where they name none, escalate.
- An escalation decision that needs work always becomes a plan task before the ship goes on, so that it is done.
- Interrupted build: commit leftovers as `wip(<task-id>): interrupted` (build Phase 0).
- `cplat component ship start` puts you on the feature branch; never create, reset or switch branches yourself, so that the run stays on its branch.
- **Hard rule:** never run `git push` or `gh pr create`, because `cplat component ship pr` runs the whole CI before it pushes.
- **Shell rule:** run every tool other than git, gh and cplat through `devbox run <script>`, never directly, so that versions and flags match CI.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow it for this spec; after the architect, `cplat platform runs agent spawned architect [--model-id <id>]`. Architect `BLOCKERS` → escalate with them. A plan with `done` tasks is not re-planned (escalate); a merge-conflict re-plan (build.md 2.4a) is the exception. Then `cplat component ship phase build`.

## Phase `build`

Read `${CLAUDE_PLUGIN_ROOT}/commands/build.md` and follow its Phases 0–6 for this spec; skip Phase 7. Gitops tasks (with `repo:`) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-gitops.md` and follow it.

Escalate on build's stop rules: a `cplat component build merge` escalation, a changed acceptance test (`cplat spec test-diff` exit 1), a security finding `cplat deps patch` cannot fix (exit 3), a decision the spec leaves open, a failing verification. Then `cplat component ship phase pr`.

## Phase `pr`

1. Write `.pr-body.md` in the repo root (Write tool, never into `.git/`, because Claude Code refuses edits there) with the template in `${CLAUDE_PLUGIN_ROOT}/references/build-pr.md` (PR body), then `cplat deps report --body-file .git/PR_BODY.md`.
2. `cplat component ship pr --title "feat(<scope>): <spec title, ≤72 chars>" --body-file .pr-body.md`: it runs the whole `devbox run ci` first; red → nothing is pushed: fix it via the coder (`cplat platform runs agent fix-round ci`), `cplat validate run` between rounds, and call it again. Then it pushes and opens (or reuses) the PR, refusing while a gitops task has no PR (platform repo: `--no-spec`).

## Phase `land`

`cplat component ship land` waits for the PR's checks, merges the `before-merge` gitops PRs and the PR.

- **GREEN** → merged (squash; with `--no-merge` the run is done), phase `deploy`.
- Non-zero exit (**RED**, the security check, or an error) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-land-red.md` and follow it (3 red rounds, `fix_rounds` in `cplat component ship status`, then escalate; a red security check: `cplat deps patch`, `cplat deps report --body-file .git/PR_BODY.md --update-pr`, exit 3 → `cplat component ship escalate '<reason>' --cause <CAUSE>`).

## Phase `deploy`

`cplat component ship deploy [--context <kube-context>] [--base-url <url>]`: the user's context, or `kubectl config current-context` if it is the system's cluster; `--base-url` is the user's to name, since a guess may hit the wrong host. It waits for the pin PR and Argo CD, merges `after-release` gitops PRs, runs `devbox run smoke` on dev for every `(smoke)` criterion and, with `promotion.staging: auto`, promotes and smokes staging. Print its `Smoke`/`Promotion` lines.

- Red smoke (`smoke red in dev: …`, or in staging) or a failed staging pin: since deploy escalates by itself and files the `smoke-failure` issue, never call `cplat component ship escalate` for it; report its lines and stop.
- Smoke that could not run is "not run": the run ends `done`.
- Shape `platform`: deploy ends at once with `not deployable (platform): nothing to deploy`: no pin, Argo, smoke, staging or `devbox run smoke` (it tests the templates here).
- In a joint `/system:ship` it ends once main's CI built the image: `pinned in the system ship's dev PR`.
- A closed pin PR, red pin CI or unhealthy app → escalate with the hint.

## Finish

`cplat component ship status`, `cplat component ship finish`, then print the report in `${CLAUDE_PLUGIN_ROOT}/references/ship-finish.md` (rows from deploy's lines, `cplat deps report`'s bumps, the plan's `human_steps`). A buffered-record warning is no error.

## Escalate

`cplat component ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (always pass the cause, since it decides whether cplat files an issue: `platform` = a platform template, script or command failed, `code` = the user's code or tests, `decision` = the spec or a rule needs the user, `environment` = runner, cluster, network, a secret or login). For `platform` also pass `--command '<command>'` and the output via `--evidence-file -` (stdin) or a file; report its `issue: <url> new|+1` line. For `decision` always pass each question as `--question '<question> (suggested: <answer>)'`, because the system ship can then answer it while other repos build. An `answer from the system ship:` line printed by `cplat component ship start` is the user's decision for the escalation that stopped the run: always apply it and go on, since the coordinator answered in the user's place. Then print the reason, `cplat component ship status`, the decision. A stop or pause request → escalate `paused by the user`.
