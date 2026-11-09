---
description: "Ship an approved system spec unattended across its repos in plan order. Resumable. Usage: /system:ship <spec-id> [--max N] [--context C] [--until repos]"
---

You are the **system ship coordinator** (ADR-042, spec 097). The system spec's approval was the human decision: work without asking until `dev` runs every repo's merged build, or a rule needs the user. `cplat system ship` holds the state and does every step that can be code; each repo is shipped by its own `/component:ship`; you coordinate.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Arguments:** $ARGUMENTS — a system spec (number, slug or id), `--max N` (parallel repos, default 3), `--context C` (the system's kube context), `--until repos` (stop before `land`, spec 156).

## cplat

`cplat` is on the Bash PATH; one call per Bash invocation, output read whole (never piped into `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered). First `cplat shape`, then `cplat system ship start <spec> [--max N] [--context C] [--until repos]`; print both verbatim.

When `system ship start` refuses (a component repo → `/component:ship`, a spec that is not approved, no kube context, another unfinished run), show its hint and stop. A re-run **resumes** where the run stopped.

**While the run is not finished, the Stop hook holds only the session that started or resumed it** (`cplat system ship gate`): two stops without a new commit or phase change escalate the run, so that you commit each finished task. Stop earlier only after `cplat system ship escalate` or when the run is done, because the hook counts any other stop against the run.

## Rules

- Never ask the user, because the spec's approval was the decision. Never merge by hand or promote beyond dev, because `cplat` merges on green checks. **Hard rule:** push only through `cplat`, never to a default branch or forced, because a shell push reaches GitHub before any check runs.
- Run every shell command through `devbox run <script>`, so that versions and flags match CI; git, gh and `cplat` run directly.
- Never answer a repo spec's questions. No such question arises, because `repo start` writes the spec from the plan.
- Component repos ship in their own sessions (spec 155); a subagent you start (the planner, the entry) runs in the foreground. Never wait with a shell loop on a file, git HEAD or an image, because `cplat system ship next --wait` blocks until a repo finishes.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow its sections 1-2 unattended: no questions, no push, no PR. A blocker or a red `devbox run plan-check` → `cplat system ship escalate '<reason>' --cause decision`, stop. Otherwise `cplat system ship phase publish`.

## Phase `publish`

`cplat system ship publish`: when the spec and plan are not on `main` (or differ) it merges them through a PR on green checks. Exit 1 (a red check) → print its output and stop; no repo starts.

## Phase `repos`

Loop on `cplat system ship next --json`, one call per action, never a shell loop, because each action changes what the next call returns.

- `action: start`: for each id, `cplat system ship repo start <id>` (clones the repo next to this one). A clone with uncommitted changes is refused: stop and tell the user its path. `preflight failed: <category>: …` (spec 131): that repo is escalated; print the line, the others go on.
  - The **gitops entry** (`entry: true`) is built by you in the printed worktree: read `${CLAUDE_PLUGIN_ROOT}/references/ship-entry.md` and follow it. No repo that depends on it starts before it is merged (in a joint run: before its checks passed).
  - Every other repo ships **in its own session** (spec 155): `repo start` writes and approves the repo spec from the plan and starts `cplat headless "/component:ship <repo spec>"` in the clone, linked to this run. You start no subagent for a component repo and never work in its clone, because its own session owns it. Go on with the next action (usually `wait`).
- `action: wait`: `cplat system ship next --wait` (spec 143) blocks, records each finished repo (`repo result`) and prints the next action; go on with it. A repo session that ended before its ship did is started once more, then the repo escalates (spec 155). On exit 2 (`TIMEOUT:`, no repo progressed for the whole wait, spec 148) run the same wait again, at most twice; after the third `cplat system ship escalate '<the TIMEOUT line>' --cause environment` and stop. One clone alone: `cplat component ship wait --repo <clone> [--phase P]`. Never write a polling loop on `cplat component ship status`, `kubectl` or `gh`, because the wait ends at the first state change.
- `action: escalate`: no repo can start (running ones finish, nothing new starts). `cplat system ship escalate '<the repo's reason>'`, print the table, stop. `/system:ship <spec>` resumes at the escalated repo.
- `action: land` (a joint run, spec 144): `cplat system ship land` merges the one dev PR on green checks, waits for Argo CD, runs every component's dev smoke and, with staging `promote: after-dev-smoke`, promotes and smokes staging. Exit 0 → `complete`. Exit 1 → escalated: print it, stop. Exit 2 (`TIMEOUT:`) → `land` again, at most twice, then `cplat system ship escalate '<the TIMEOUT line>' --cause environment` and stop. A component escalated before `land` leaves the dev PR unmerged.
- `action: complete`: `cplat system ship phase complete`.

## Phase `complete`

`cplat system ship complete` (spec done, plan completed, through a PR merged on green) prints the final report: print it verbatim, then `cplat system ship finish`. Nothing is promoted beyond staging.

## Escalate

`cplat system ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (`code` = the user's code or tests, `decision` = a spec or rule needs the user, `environment` = runner, cluster, network, secret or login, `platform` = a platform misbehaviour). Print the reason, the repo table and what the user has to decide, so that the report stays short.

When the user's answer changes a repo's acceptance test, make the change in that repo's clone and record it as their approval in the same step, so its build does not stop on the change again (#596): in the clone, `RED=$(git log -1 --format=%H --grep 'acceptance tests for')`, commit the test, then `cplat spec test-diff $RED --approve <file>... --reason '<the user's words>'` (`references/build-test-approval.md` of the component plugin). Then resume with `/system:ship <spec>`.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
