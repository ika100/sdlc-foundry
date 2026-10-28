# shared plugin

Common agents, the `cplat` launcher and the session hooks used by every shape's plugin. Pre-approves `gh repo create` / `gh repo edit --add-topic` so `/component:new` can scaffold a repo end-to-end without permission prompts mid-flight.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `quality` | sonnet | `devbox run quality` for the repo's shape (ruff + mypy, ESLint + tsc, Spotless + Checkstyle, golangci-lint, kustomize/kubeconform, …). |
| `security` | sonnet | `devbox run security` (pip-audit / pnpm audit / OWASP DC / govulncheck + detect-secrets) and trivy when a Dockerfile is present. It never bumps dependencies: `/component:build` and `/component:ship` patch fixable findings with `cplat deps patch` (spec 095). |

## Commands moved in 5.0

This plugin ships no working commands any more; the old `/shared:*` files are tombstones (removed in 6.0).

| 4.x command | 5.0 command |
|---|---|
| `/shared:check-quality` | `/component:check` |
| `/shared:new-service` | `/component:new` |
| `/shared:new-app` | `/system:new` |
| `/shared:triage` | `/issue:triage` |
| `/shared:report-issue` | `/issue:report` |
| `/shared:update-service` | `/platform:update` |
| `/shared:fleet` | `/platform:fleet` |
| `/shared:doctor` | `/platform:doctor` |
| `/shared:status` | `/system:status` |

## `cplat` on the PATH (bin/)

`bin/cplat` is on the Bash tool's PATH while this plugin is enabled, so every platform command calls `cplat <command>` instead of fetching the platform first. It runs `scripts/cplat` from, in order: `$CPLAT_PLATFORM` (a local checkout), `$CPLAT_REF` (a fetched tag, used by `--ref`), the plugin's own repo when loaded in place, the installed marketplace checkout (the version your plugins came from; no network), and only then a fetched `main`. `/platform:doctor` shows which one ran (`platform scripts`).

Claude Code on claude.ai and in Cowork does not install plugins that ship a `bin/` directory; this plugin is meant for the Claude Code CLI and desktop app, where the platform's git, devbox and gh workflows run anyway.

Unattended delivery ([ADR-028](../../docs/adr/028-unattended-delivery-without-branch-protection.md)) adds three commands that do not belong to one slash command: `cplat component ship …` (the state and steps of `/component:ship`), `cplat headless "<prompt>"` (fresh `claude -p` sessions until a ship run is done, with a quiet window, log and notification) and `cplat adopt --type <shape>` (bring a repo that was not created from a template onto the platform without overwriting its files). Runs of `cplat component ship`, `pr wait` and `headless` are recorded in a private run store (spec 087): `cplat platform runs init|flush|report`. See [docs/unattended-delivery.md](../../docs/unattended-delivery.md).

Other commands that have no slash command of their own:

| Command | Purpose |
|---|---|
| `cplat pr open` | Commit (`-s`), push and open the PR in one step; idempotent, the body is read from `.pr-body.md` (spec 100). |
| `cplat pr wait <pr> [-R owner/repo] [--merge]` | Wait for the PR's current head: report each check, stop at the first red one, rerun stuck or transient runs once, squash-merge on green with `--merge` (spec 079). |
| `cplat quiet <script>` | Run a devbox script: one line when green, a failure summary and the log path when red (specs 100, 108); `--raw` or `failure_summary: off` restores the plain tail. |
| `cplat headless "<prompt>" [--model M]` | Fresh `claude -p` sessions until a ship run is done; the coordinator runs on Sonnet unless `--model` or `coordinator_model` says otherwise ([ADR-036](../../docs/adr/036-coordinator-model-default-and-settings.md)). |
| `cplat budget show\|gate\|attempt\|stage\|resume` | The run tree's budget (minutes, invocations, reruns, cost), no-progress stops and verified stages for resume (spec 102, [guide](../../docs/unattended-delivery.md#budgets-and-repeated-failures)). |
| `CPLAT_OTLP_ENDPOINT` / `telemetry:` setting | Live OpenTelemetry export of headless and benchmark sessions (local endpoints only unless `allow_remote`), and a comparison note in the run record (spec 101, [guide](../../docs/unattended-delivery.md#live-usage-in-grafana-optional)). |
| `cplat instance verify [<env>]` | Run the repo's smoke tests against an environment (`SMOKE_BASE_URL`, spec 091). |
| `cplat alerts poll` | Evaluate the alert sources and turn firing alerts into deduplicated issues (spec 092). |
| `cplat platform retro [--week W] [--json] [--out DIR]` | The weekly report from the run store; by hand it prints and writes nothing. `cplat platform runs init` installs the Monday workflow that posts it with spec proposals (spec 090). |
| `cplat system ship …` | The state and steps of `/system:ship`: one `cplat component ship` per component repo in plan order (spec 097). |
| `cplat platform runs benchmark <workflow> [--model M] [--plugins DIR]` | Run a fixed task against the sample repo and record its usage; `cplat platform runs report --benchmarks` compares the runs (spec 099/100). |

## Hooks

- `SessionStart`: checks devbox and runs `devbox install` when the repo has a `devbox.json`.
- `PreToolUse` (`Task|Agent`): inside a recorded run, `cplat budget gate --invocation` counts the subagent and refuses it when the run's budget is used up (spec 102). Outside a run it exits in shell.
- `Stop`: while a `/component:ship` run is unfinished (`<git dir>/cplat-ship.json`, the worktree's own git dir, so parallel sessions in other worktrees are not blocked: [ADR-051](../../docs/adr/051-run-state-is-per-worktree.md)), `cplat component ship gate` blocks the stop with the next step and what is still red; it allows it when the run is done, escalated or blocked 8 times. Without a run it exits in shell (spec 066).

## Pre-approved operations (settings.json)

To make `/component:new` flow without prompts:

- `gh repo create * --private *`
- `gh repo edit * --add-topic *`
- `gh api user`
- `copier copy *`, `copier update *`
- `cplat`, `cplat *` (the launcher above)

Removal of topics, deletion of repos, and `--public` repo creation **prompt** the user.

## Usage notes

- Enable this plugin on every repo that uses any shape plugin — they depend on it for the canonical `quality` and `security` definitions and for `cplat`.
- `/component:new` requires `copier` to be installed on the host. If absent, install once: `uv tool install copier`.
