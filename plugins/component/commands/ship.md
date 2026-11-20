---
description: "Ship an approved spec unattended: plan, build, PR, merge after green CI, wait until dev runs it. Usage: /component:ship <spec-id> [--no-merge] [--full] [--here]"
---

You are the **ship orchestrator** (ADR-028). The spec's approval was the human decision: work without asking until `dev` runs the merged build, or a rule needs the user. `cplat component ship` holds the state; you do the judgement.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Arguments:** $ARGUMENTS — a spec (number, slug or id); `--no-merge` (stop at green PR); `--full` (every `cplat validate run` in build and CI fix rounds runs every check); `--here` (this session does the run). `--unit <unit>`: that unit alone, per `${CLAUDE_PLUGIN_ROOT}/references/unit-mode.md`.

## cplat

One `cplat` call per Bash invocation, output read whole (no `grep`, `head` or `tail`). First `cplat shape`, then `cplat component ship start <spec> --detach [--no-merge] [--full] [--take-over]` (without `--detach` for `--here` and `--unit`); print both verbatim.

- A `headless: pid` line → read `${CLAUDE_PLUGIN_ROOT}/references/ship-handoff.md` and follow it; only Finish and Escalate here apply, because the headless session does every phase.
- `unsupported` or no shape → stop (gitops-app repos use `/system:ship`).
- A `cplat shape` error that names `.platform-settings.yml` → stop and show it; never ask for the shape. Since the user fixes it, a guess hides it.
- When `ship start` refuses, show its hint and stop; `--take-over` is the user's call, since it takes over another branch's claim.
**The Stop hook holds the session until the run is finished**; a stop during a background `cplat` wait of yours is let through, so always stop there: its exit code and output (notification or start lines) decide the next step as the phase says. Two stops without a commit or phase change escalate, so commit each task. Run subagents in the foreground (`run_in_background: false`), never polling in a shell loop, because a loop can match itself and never end.

## Unattended rules

- Never ask the user, because the spec's approval was the decision. Where `/component:plan` or `/component:build` say "ask", take the unattended choice they name; where they name none, escalate.
- An escalation decision that needs work always becomes a plan task before the ship goes on, so that it is done.
- `cplat component ship start` puts you on the feature branch; never create, reset or switch branches yourself, so that the run stays on its branch.
- **Hard rule:** never run `git push` or `gh pr create`, because `cplat component ship pr` runs the whole CI before it pushes.
- **Shell rule:** run every tool other than git, gh and cplat through `devbox run <script>`, never directly, so that versions and flags match CI.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow it for this spec; after the architect, `cplat platform runs agent spawned architect [--model-id <id>]`. Architect `BLOCKERS` → escalate with them. A plan with `done` tasks is not re-planned (escalate); a merge-conflict re-plan (build.md 2.4a) is the exception. Then `cplat component ship phase build`.

## Phase `build`

Read `${CLAUDE_PLUGIN_ROOT}/commands/build.md` and follow its Phases 0–6 for this spec; skip Phase 7. Gitops tasks (with `repo:`) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-gitops.md` and follow it.

Escalate on build's stop rules. Then `cplat component ship phase pr`.

## Phase `pr`

1. Write `.pr-body.md` in the repo root (Write tool, never into `.git/`, because Claude Code refuses edits there) with the template in `${CLAUDE_PLUGIN_ROOT}/references/build-pr.md`, then `cplat deps report --body-file .git/PR_BODY.md`.
2. `cplat component ship pr --title "feat(<scope>): <spec title, ≤72 chars>" --body-file .pr-body.md`: it runs the whole `devbox run ci` first; red → nothing is pushed: fix it via the coder (`cplat platform runs agent fix-round ci`), `cplat validate run` between rounds, and call it again; after the fix `cplat spec test-diff $RED --task <task>` (`RED=$(git log -1 --format=%H --grep 'acceptance tests for')`): a `test helper` or `type-only` line → the last paragraph of `${CLAUDE_PLUGIN_ROOT}/references/build-tighten.md` without asking, exit 1 otherwise → escalate cause `decision` as a changed test. Then it pushes and opens the PR (platform repo: `--no-spec`). `cplat` puts a Summary at the top of the PR body; the orchestrator writes none.

## Phase `land`

`cplat component ship land` waits for the PR's checks, merges the `before-merge` gitops PRs and the PR, and posts the milestone comments on linked issues itself, without asking.

- **GREEN** → merged, phase `deploy` (`--no-merge`: done).
- Non-zero exit (**RED**, the security check, or an error) → read `${CLAUDE_PLUGIN_ROOT}/references/ship-land-red.md` and follow it (3 red rounds, `fix_rounds`, then escalate; a red security check: `cplat deps patch`, `cplat deps report --update-pr`, exit 3 → `cplat component ship escalate --cause <CAUSE>`).

## Phase `deploy`

`cplat component ship deploy [--context <kube-context>] [--base-url <url>]`: the user's context, or `kubectl config current-context` if it is the system's cluster; `--base-url` is the user's to name, since a guess may hit the wrong host.
- Red smoke (`smoke red in dev: …`, or in staging) or a failed staging pin: since deploy escalates by itself and files the `smoke-failure` issue, never call `cplat component ship escalate` for it; report its lines and stop.
- Shape `platform`: deploy ends with `not deployable (platform): nothing to deploy`.
- A closed pin PR, red pin CI or unhealthy app → escalate with the hint.

## Finish

`cplat component ship status`, `cplat component ship finish`, print the report in `${CLAUDE_PLUGIN_ROOT}/references/ship-finish.md`. A buffered-record warning is no error. End as Escalate ends.

## Escalate

`cplat component ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (always pass the cause, since it decides whether cplat files an issue: `platform` = a platform script or command failed, `code` = the user's code, `decision` = the spec or a rule needs the user, `environment` = runner, cluster, network, a secret). For `platform` also pass `--command '<command>'` and the output via `--evidence-file -` or a file; report its `issue:` line. For `decision` always pass each question as `--question '<question> (suggested: <answer>)'`, because the system ship can then answer it while other repos build. An `answer from the system ship:` or `answer from the shipping session:` line printed by `cplat component ship start` is the user's decision for the escalation that stopped the run: always apply it and go on, since the coordinator answered in the user's place. Then print the reason, `cplat component ship status`, the decision. A stop or pause request → escalate `paused by the user`. End with the hand-over: `cplat next --json`, follow its `how`, so that the person goes on by choosing.
