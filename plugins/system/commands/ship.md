---
description: "Ship an approved system spec unattended across all its repos, in plan order, until dev runs every merged build with passing smoke (one dev PR for the spec). Resumable. Usage: /system:ship <spec-id> [--max N] [--context C]"
---

You are the **system ship coordinator** ([ADR-042](../../../docs/adr/042-product-ship-coordinates-repo-ships.md), spec 097). The system spec's approval was the human decision: work without asking until `dev` runs every repo's merged build, or a rule needs the user. `cplat system ship` holds the state and does every step that can be code; each component repo is shipped by its own `/component:ship` in its own clone; you coordinate.

**Arguments:** $ARGUMENTS — a system spec (number, slug or id), `--max N` (parallel repos, default 3), `--context C` (the system's kube context).

## cplat

`cplat` is on the Bash PATH; one call per Bash invocation, output read whole (never piped into `grep`, `head` or `tail`; use `--json` where offered). First `cplat shape`, then `cplat system ship start <spec> [--max N] [--context C]`; print both verbatim.

The shape must be `gitops-app`. When `system ship start` refuses (a component repo → `/component:ship`, a spec that is not approved, no kube context for the system's cluster, another unfinished system run), show its hint and stop. A re-run **resumes** where the run stopped.

**While the run is not finished, the Stop hook holds only the session that started or resumed it** (`cplat system ship gate`): two stops without a new commit or phase change escalate the run, so commit each finished task. Stop earlier only after `cplat system ship escalate` or when the run is done.

## Rules

- Never ask the user. Never merge by hand, never push to a default branch, never force-push, never promote beyond dev (`cplat` merges, on green checks only).
- Every shell command goes through `devbox run <script>`, except git, gh and cplat.
- Never answer a repo spec's questions.
- Subagents run in the foreground (`run_in_background: false`; parallel ones as several Agent calls in one message). Never wait for one with a shell loop on its output file, git HEAD or a docker image (#496).

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` and follow its sections 1-2 unattended: no questions, no push, no PR. Architect blockers or a red `devbox run plan-check` → `cplat system ship escalate '<reason>' --cause decision`, stop. Otherwise `cplat system ship phase publish`.

## Phase `publish`

`cplat system ship publish`: when the spec and plan are not on `main` (or differ) it merges them through a PR on green checks. Exit 1 (a red check) → print its output and stop; no repo starts.

## Phase `repos`

Loop on `cplat system ship next --json`, one call per action, never a shell loop (`cplat system ship status` for the table when something changes).

- `action: start`: for each id, `cplat system ship repo start <id>` (clones the repo next to this one). A clone with uncommitted changes is refused: stop and tell the user its path. `preflight failed: <category>: …` (spec 131): that repo is escalated; print the line, the others go on.
  - The **gitops entry** (`entry: true`) is built by you in the printed worktree: read `${CLAUDE_PLUGIN_ROOT}/references/ship-entry.md` and follow it. No repo that depends on it starts before it is merged (in a joint run: before its checks passed).
  - Every other repo: in **one message**, one foreground subagent per repo (Agent tool, general-purpose, never `run_in_background`). Prompt: *work only in `<clone>` (`cd <clone> && …` in every Bash call; never touch another clone). Read every `cplat` output whole, never through `grep`, `head` or `tail` (its last lines carry the decisions and next steps). Run `/component:spec --from-plan <absolute plan path> <repo-id>` unattended (its section D.3): a repo spec whose criteria the plan wrote is approved at once, without a product-manager (spec 147); otherwise approve the repo spec when it has no open questions, or take their suggested answers and record them under `## Decisions taken during the ship`; only a question without a suggestion, or one that changes the system spec or the contract, is reported as `QUESTIONS:` followed by them verbatim, and then you stop. Then follow `/component:ship`'s command file with `cplat component ship start <n>` and the flag that links the run to this gitops-app repo (`cplat component ship start --help`) set to the absolute path of this repo; skip its Finish (`cplat component ship finish` is not called), and report the repo spec id and the output of the last `cplat component ship status`.*
  - Then `cplat system ship repo result <id>` per repo: exit 0 → passed (or `pinned` in a joint run: delivered); exit 1 → escalated. A report with `QUESTIONS:` → `cplat system ship repo escalate <id> '<the questions verbatim>' --cause decision`.
- `action: wait`: `cplat system ship next --wait` (spec 143) blocks, records each finished repo and prints the next action; go on with it. On exit 2 (`TIMEOUT:`, no repo made progress for the whole wait: a new phase or commit extends it, spec 148) run the same wait again, at most twice; after the third `cplat system ship escalate '<the TIMEOUT line>' --cause environment` and stop. A repo left `running` with no ship in its clone resumes at its own phase in the next message. One clone alone: `cplat component ship wait --repo <clone> [--phase P]`. Never write a polling loop on `cplat component ship status`, `kubectl` or `gh`.
- `action: escalate`: no repo can start (running ones finish, nothing new starts). `cplat system ship escalate '<the repo's reason>'`, print the table, stop. `/system:ship <spec>` resumes at the escalated repo.
- `action: land` (a joint run, spec 144): `cplat system ship land` merges the one dev PR on green checks, waits for Argo CD, runs every component's dev smoke (as `cplat instance verify dev` records it; prints `Smoke (dev) <repo>: …`) and, with staging `promote: after-dev-smoke`, promotes and smokes staging. Exit 0 → `complete`. Exit 1 → escalated: print it, stop. Exit 2 (`TIMEOUT:`) → `land` again, at most twice, then `cplat system ship escalate '<the TIMEOUT line>' --cause environment` and stop. A component escalated before `land` leaves the dev PR unmerged (landing a partial spec is the user's decision).
- `action: complete`: `cplat system ship phase complete`.

## Phase `complete`

`cplat system ship complete` (spec done, plan completed, through a PR merged on green) prints the final report: print it verbatim, then `cplat system ship finish`. Nothing is promoted beyond staging.

## Escalate

`cplat system ship escalate '<one line: what needs the user and where>' --cause platform|code|decision|environment` (`code` = the user's code or tests, `decision` = a spec or rule needs the user, `environment` = runner, cluster, network, secret or login, `platform` = a platform template, script or command misbehaved). Print the reason, the repo table and only what the user must decide.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. Never file anything without their OK (only a `platform` escalation is filed by the platform itself, ADR-033).
