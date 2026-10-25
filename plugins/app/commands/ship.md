---
description: "Ship an approved product spec unattended across all its repos, in plan order, until dev runs every merged build with passing smoke. Resumable. Usage: /app:ship <spec-id> [--max N] [--context C]"
---

You are the **product ship coordinator** ([ADR-042](../../../docs/adr/042-product-ship-coordinates-repo-ships.md), spec 097). The approval of the product spec was the human decision; from here you work without asking until `dev` runs every repo's merged build, or until a rule needs the user. `cplat app-ship` holds the run's state (in this repo's git dir, never committed) and does every step that can be code (publish, schedule, gates, merges, the report); you do the judgement. Each component repo is shipped by its own `/svc:ship`, in its own clone; you only coordinate.

**Arguments:** $ARGUMENTS — a product spec (number, slug or id), `--max N` (parallel repos, default 3) and `--context C` (the product's kube context).

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation. First calls:

```bash
cplat shape
```

```bash
cplat app-ship start <spec> [--max N] [--context C]
```

The shape must be `gitops-app`; `app-ship start` refuses a component repo (use `/svc:ship`), a spec that is not approved, a missing kube context for the product's cluster (pass `--context` or `kubectl config use-context`) and another unfinished product run. In each case show its hint and stop; nothing was changed. It prints the phase, the repo table and the next step; a re-run **resumes** where the run stopped. Print both outputs verbatim.

**While the run is not finished, the shared plugin's Stop hook refuses to let the session end** (`cplat app-ship gate`). Keep working. You may stop only after `cplat app-ship escalate` or when the run is done.

## Rules

- Never ask the user. Never merge by hand, never push to a default branch, never force-push, never promote beyond dev (`cplat app-ship` and `cplat ship` merge, on green checks only).
- Every shell command goes through `devbox run <script>`, except git, gh and cplat.
- Questions of a repo spec are never answered by you.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow its sections 1-2 unattended for this spec: no questions, no push, no PR (`publish` does that). Architect blockers, or a red `devbox run plan-check` → `cplat app-ship escalate '<reason>' --cause decision`, then stop. Otherwise `cplat app-ship phase publish`.

## Phase `publish`

`cplat app-ship publish`: if the spec and plan are not on `main` (or differ), it opens a PR with them, waits for all checks and merges it, then switches back to `main`. A red check escalates the run (exit 1): print its output and stop; no repo starts. Then the phase is `repos`.

## Phase `repos`

Loop on `cplat app-ship next --json` (print the table with `cplat app-ship status` when something changes).

- `action: start`: for each id in `start`, `cplat app-ship repo start <id>` (it clones the repo next to this one when missing and refuses a clone with uncommitted changes, showing its path: stop and tell the user).
  - The **gitops entry** (`entry: true`) is built by you in the printed worktree, as `/app:build` step 2 does (its `gitops:` operations, `devbox run validate`, commit `feat(compose): <spec_id> — <summary>`), then `cplat app-ship entry pr <id> --title <title> --body-file <file>` and `cplat app-ship entry land <id>`. No repo that depends on it starts before it is merged. Red → the repo is escalated (print the failed checks).
  - Every other repo: in **one message**, one foreground subagent per repo (Agent tool, general-purpose, never `run_in_background`). Prompt: *work only in `<clone>` (`cd <clone> && …` in every Bash call; never touch another clone). Run `/svc:spec --from-plan <absolute plan path> <repo-id>` unattended: approve the repo spec when it has no open questions; if it has any, report `QUESTIONS:` followed by them verbatim and stop, never answer them. Then follow `/svc:ship`'s command file with `cplat ship start <n> --product <absolute path of this gitops-app repo>`, skip its Finish (`cplat ship finish` is not called), and report the repo spec id and the output of the last `cplat ship status`.*
  - After the message: `cplat app-ship repo result <id>` for each repo. Exit 0 → passed. Exit 1 → escalated (its reason is in the table). A report with `QUESTIONS:` → `cplat app-ship repo escalate <id> '<the questions verbatim>' --cause decision`.
- `action: wait`: repos are still running; go on with the next message for them (a repo left `running` resumes at its own ship phase).
- `action: escalate`: no repo can start. After an escalation the repos already running finish their current ship, nothing new starts. `cplat app-ship escalate '<the repo's reason>'` (the record takes the repo's cause), print the table and stop. Resuming with `/app:ship <spec>` continues at the escalated repo.
- `action: complete`: `cplat app-ship phase complete`.

## Phase `complete`

`cplat app-ship complete`: marks the product spec done and the plan completed through a PR merged on green checks, then prints the final report (one row per repo with its `dev` image, Argo state and `Smoke (dev)`, the human steps as a checklist, the `/gitops:promote` commands for staging). Print it verbatim, then `cplat app-ship finish`. This run promotes nothing beyond dev.

## Escalate

`cplat app-ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (`code` = the user's code or tests, `decision` = a spec or rule needs the user, `environment` = runner, cluster, network, secret or login, `platform` = a platform template, script or command misbehaved). Print the reason and the repo table, and only what the user must decide.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/shared:report-issue` so the user can file it. Never file anything without their OK.
