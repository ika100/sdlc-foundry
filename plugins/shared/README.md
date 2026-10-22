# shared plugin

Common agents and commands used by every shape's plugin. Pre-approves `gh repo create` / `gh repo edit --add-topic` so `/shared:new-service` can scaffold a repo end-to-end without permission prompts mid-flight.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `quality` | sonnet | `devbox run quality` for the repo's shape (ruff + mypy, ESLint + tsc, Spotless + Checkstyle, golangci-lint, kustomize/kubeconform, …). |
| `security` | sonnet | `devbox run security` (pip-audit / pnpm audit / OWASP DC / govulncheck + detect-secrets) and trivy when a Dockerfile is present. |

## Commands

| Command | Purpose |
|---|---|
| `/shared:check-quality` | Runs `quality` + `security` agents in parallel (read-only). |
| `/shared:new-service <name> [description words…] [--type <shape>] [--library\|--web\|--gitops] [--app <org>/<repo>]` | Bootstraps a new repo of any shape from its Copier template, creates the GitHub repo, tags deployable shapes for GitOps discovery. |
| `/shared:new-app <app.yml> [--resume] [--public] [--no-github]` | Creates a whole product: the gitops-app repo plus every component repo from a manifest, then opens one pull request that composes the deployable ones. A failure midway reports what exists; `--resume` continues. |
| `/shared:triage [<issue-number> \| --new \| --waiting]` | Reads new GitHub issues, discusses gaps with you (and, with your OK, the reporter), and routes each to a spec, `/svc:quick-task`, `/svc:fix-bug` or a reply. Labels and comments only after you confirm; never closes issues. |
| `/shared:update-service [--ref <tag>] [--data k=v]` | Re-applies the template skeleton to an existing repo on a review branch (project-owned files untouched). |

## `cplat` on the PATH (bin/)

`bin/cplat` is on the Bash tool's PATH while this plugin is enabled, so every platform command calls `cplat <command>` instead of fetching the platform first. It runs `scripts/cplat` from, in order: `$CPLAT_PLATFORM` (a local checkout), `$CPLAT_REF` (a fetched tag, used by `--ref`), the plugin's own repo when loaded in place, the installed marketplace checkout (the version your plugins came from; no network), and only then a fetched `main`. `/shared:doctor` shows which one ran (`platform scripts`).

Claude Code on claude.ai and in Cowork does not install plugins that ship a `bin/` directory; this plugin is meant for the Claude Code CLI and desktop app, where the platform's git, devbox and gh workflows run anyway.

Unattended delivery ([ADR-028](../../docs/adr/028-unattended-delivery-without-branch-protection.md)) adds three commands that do not belong to one slash command: `cplat ship …` (the state and steps of `/svc:ship`), `cplat headless "<prompt>"` (fresh `claude -p` sessions until a ship run is done, with a quiet window, log and notification) and `cplat adopt --type <shape>` (bring a repo that was not created from a template onto the platform without overwriting its files). See [docs/unattended-delivery.md](../../docs/unattended-delivery.md).

## Hooks

- `SessionStart`: checks devbox and runs `devbox install` when the repo has a `devbox.json`.
- `Stop`: while a `/svc:ship` run is unfinished (`<git dir>/cplat-ship.json`), `cplat ship gate` blocks the stop with the next step and what is still red; it allows it when the run is done, escalated or blocked 8 times. Without a run it exits in shell (spec 066).

## Pre-approved operations (settings.json)

To make `/shared:new-service` flow without prompts:

- `gh repo create * --private *`
- `gh repo edit * --add-topic *`
- `gh api user`
- `copier copy *`, `copier update *`
- `cplat`, `cplat *` (the launcher above)

Removal of topics, deletion of repos, and `--public` repo creation **prompt** the user.

## Usage notes

- Enable this plugin on every repo that uses any shape plugin — they depend on it for the canonical `quality` and `security` definitions and for `cplat`.
- The `/shared:new-service` command requires `copier` to be installed on the host. If absent, install once: `uv tool install copier`.
