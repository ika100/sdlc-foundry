# End-to-end run: todo app, spec-driven (2026-10-08)

<!-- historical -->
> **Historical.** This field report describes a run with a pre-5.0 platform; command and file names are those of 4.x. It is kept as a record and is not part of the current documentation; the current flow is in the [quickstart](../QUICKSTART.md) and the [user journey](../USER-JOURNEY.md).

A real run of the spec-driven platform ([ADR-026](../adr/026-feature-specs.md)) from an empty folder to a running, verified product: three public repos, one product spec, a multi-repo plan, three builds, a local cluster. It used the implementation of PRs #77–#81 (`feature/spec-dx` at `33432d0`).

**Result:** the todo app runs on the local cluster and meets its spec. 60 min 32 s wall clock; 17 issues found (3 high, 6 medium, 8 low), each with the workaround used.

## Setup

| | |
|---|---|
| Repos (public) | [ika100/todo](https://github.com/ika100/todo) (gitops-app), [ika100/todo-api](https://github.com/ika100/todo-api) (service-python), [ika100/todo-web](https://github.com/ika100/todo-web) (web-nextjs) |
| Driver | Headless Claude Code 2.1.285 (`claude -p`, Opus), one session per command, `--plugin-dir` for every plugin of the checkout, `--permission-mode bypassPermissions` |
| Human role | Played by the operator: answered spec questions, reviewed and merged PRs, opened the PRs agents could not open |
| Host | Apple silicon laptop, Docker Desktop, devbox 0.17.5; GitHub-hosted runners |
| Feature | "Todo list: see all todos, add one with a title, mark done / not done, delete; the web app calls todo-api, which stores the todos" |

## Timeline

| Clock | Step | Took | Agent cost |
|---|---|---|---|
| 11:05 | `/shared:new-app todo.yml --public`: 3 repos, bootstrap commits, compose PR `todo#1` | 1m07s | $0.19 |
| 11:07 | Compose PR checks (42 s), merge | ~1 min | — |
| 11:08 | `/app:spec`: product spec 001, 13 criteria, 8 open questions (headless: listed, not asked) | 1m14s | $0.50 |
| 11:10 | `/app:spec --amend 001 <answers>`: 14 criteria (Postgres persistence added), approved | 0m57s | $0.43 |
| 11:11 | `/app:plan 001`: 3 repos in one wave, contract in the plan | 2m04s | $0.70 |
| 11:13 | `/app:build 001`: gitops changes pushed; both repo specs stopped on one question each | 3m12s | $1.86 |
| 11:16 | Answers; `todo#3` (addon, exposure, env) opened by hand, merged at 11:17 | 10m42s* | $6.71 |
| 11:28 | `/svc:build` resume in todo-api ‖ todo-web | 2m48s ‖ 6m36s | $3.10 |
| 11:31 | Product spec + plan PR `todo#4` (pushed by hand), merged | — | — |
| 11:31 | todo-api continues after a lint stop | 14m20s | $3.73 |
| 11:34 | `todo-web#3` opened by hand; checks 3m04s; merged 11:37 (25/25 criteria verified) | — | — |
| 11:45 | `todo-api#2` opened by hand; checks 2m34s; merged 11:48 (18/18 criteria verified); main CI + multi-arch image 2m42s | — | — |
| 11:52 | `/app:build 001` resume: repos done, plan completed, spec done; `todo#5` merged | 0m30s | $0.26 |
| 11:55 | `devbox run cluster-up` (port 8088 taken, rerun on 8089) | 2m29s | — |
| 11:58 | ArgoCD converged: 4 apps synced and healthy, 3 pods running, 0 restarts | ~3 min | — |
| 12:05 | Acceptance smoke on the deployed app: all checks pass | — | — |

\* cut off by the 600 s background ceiling of print mode (issue 4).

**Totals:** 60 min 32 s wall clock; 10 agent sessions, 43 min 30 s agent time (two of them in parallel); $17.48. The repo builds produced 18 + 25 acceptance criteria, 94 + 70 tests and 97 % / 96.8 % line coverage.

## Acceptance check on the running system

Done through the Gateway (`http://todo-web.todo-dev.localhost:8089/`) and a port-forward to todo-api:

| Check | Criterion | Result |
|---|---|---|
| Empty page shows "No todos yet" | AC-001.2 | ✓ 200 |
| `"  Buy milk  "` is stored trimmed | AC-001.7 | ✓ 201 |
| Blank title → "Title is required" | AC-001.5 | ✓ 422 |
| 201 characters refused, 200 accepted | AC-001.6 | ✓ 422 / 201 |
| Mark done | AC-001.8 | ✓ 200 |
| Survives `rollout restart` of todo-api (Postgres) | AC-001.14 | ✓ |
| Page renders the todo from the API in-cluster | AC-001.3 | ✓ |
| Changing a deleted todo → "This todo no longer exists" | AC-001.11 | ✓ 204 then 404 |

## What worked as designed

- **Specs first, for real.** Product spec → per-repo spec slices (`cplat spec new --from-plan`) → plans with `covers` → **failing acceptance tests committed before any code** (`test(todo): acceptance tests for 001` in both repos) → tasks marked `done` one by one.
- **Questions go to the human.** The product-manager never guessed: 8 product questions, then one per repo; headless sessions listed them and left the spec `draft`.
- **The reviewer earns its place.** todo-web's first verification failed AC-001.25 (the check that `TODO_API_URL` never reaches the browser only scanned sources); the fix added a bundle check. Both repos ended with every criterion `met`.
- **Resume works.** Two interrupted builds resumed from the last `done` task; `/app:build` resumed into bookkeeping (plan `completed`, spec `done`, index written).
- **Deterministic parts held.** `new-app` (1 min, no errors), `plan-check`, `cplat spec check`, the addon contract (`DATABASE_URL` + `PG*`), cluster-up, ArgoCD convergence, the `specs` CI job (ran on every PR; skipped correctly because `main` of the platform has no spec checks yet).

## Issues and workarounds

Severity: **high** blocks or silently degrades the flow; **medium** needs a human workaround; **low** is friction or noise.

| # | Sev | Issue | Workaround used | Proposed fix | Spec |
|---|---|---|---|---|---|
| 1 | high | **The service-python template fails its own quality gate.** `src/<module>/tracing.py` and `tests/test_tracing.py` have lines over 100 characters and an unsorted import block (ruff E501/I001, reproduced with ruff 0.7.4 and 0.16.10). The bootstrap CI on `main` of todo-api was red and **no image was published until the first feature PR**. Platform CI renders the Python templates but never lints or tests them (only local `devbox run smoke` does); Go, web and Java are linted in CI. | The build agent reformatted both files in the feature PR (`style: fix template lint`). | Wrap the lines in the template; add lint + test of the rendered Python templates to platform CI (as for Go/web/Java). | [043](../specs/043-python-templates-pass-their-own-quality/spec.md) |
| 2 | high | **Worktree isolation starts from `main`, not the feature branch.** Parallel coders in `/svc:build` Phase 2 did not see the spec, plan or acceptance tests. Moving the worktree with `git reset --hard` is in the `ask` list, so it was refused. | The build fell back to running every task sequentially on the feature branch. | Phase 2 starts each coder with a non-destructive `git checkout -B <task-branch> <feature-head>` inside its worktree and checks the base before work; extend the worktree probe to assert the base. | [044](../specs/044-parallel-coders-build-on-the-feature/spec.md) |
| 3 | high | **The product plan includes the gitops-app repo itself** (addon, exposure, env wiring), but `/app:build` routes every repo through `/svc:spec --from-plan`, which refuses gitops-app. | The `/app:build` agent improvised (branch `compose/001-todo-list` in a new worktree `../todo-build-001`, `/gitops:addon` + `/gitops:compose`); the operator opened the PR. The worktree was never removed. | `/app:build` handles `shape: gitops-app` entries in the gitops repo itself with `/gitops:addon` and `/gitops:compose`; planner and ADR-011 say so. | [045](../specs/045-multi-repo-builds-handle-the-gitops-app/spec.md) |
| 4 | medium | **Print mode kills background subagents after 600 s** ("Background tasks still running after 600s; terminating"). `/app:build` runs its repo agents in the background, so the unattended build was cut off mid-task. | `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, then resumed each repo with `/svc:build`. | Document the variable for unattended runs (`/loop`, `/schedule`, CI); have `/app:build` wait for its agents in the foreground. | [046](../specs/046-unattended-builds-survive-long-runs/spec.md) |
| 5 | medium | **Resume after an interruption trips the clean-tree pre-flight.** The interrupted coder left uncommitted files and a stale index (five bootstrap files staged at old versions). | Told the build to commit `wip: interrupted task` first; squash merge keeps it off `main`. | On resume (`status: building`), detect a dirty tree and offer to commit it as WIP for the interrupted task. | [047](../specs/047-builds-resume-after-an-interruption/spec.md) |
| 6 | medium | **"Acceptance tests are fixed" also forbade formatting.** The tester's acceptance file failed ruff (imports, long lines); the build stopped instead of running `lint-fix`. | The operator allowed a formatting-only change; the agent compared the AST before and after. | Allow `lint-fix` formatting of acceptance tests; forbid changes to assertions and values (the reviewer checks an AST diff). | [048](../specs/048-acceptance-tests-may-be-reformatted/spec.md) |
| 7 | medium | **`ruff format` also formats Python code blocks in Markdown,** so the architect's `design.md` failed `quality`. | Reformatted `design.md` in a separate commit. | Exclude `docs/**` from ruff in the Python templates, or run `lint-fix` after the architect writes. | [049](../specs/049-spec-documents-do-not-break-the-python/spec.md) |
| 8 | medium | **The product spec and plan branch is never pushed.** `/app:spec` and `/app:plan` commit locally on `docs/spec-<id>`; `/app:build` reads the local file. | Pushed it and opened `todo#4` by hand. | `/app:plan` ends by pushing the branch and opening the PR (with confirmation); `/app:build` warns when the plan is not on `main`. | [050](../specs/050-product-spec-and-plan-reach-main/spec.md) |
| 9 | medium | **Agents cannot open PRs in headless or untrusted workspaces.** The templates' allowlist is ignored there ("workspace has not been trusted"), but the `ask` list still applies, and `gh pr create` is in it, even with `bypassPermissions`. | Agents pushed their branches and wrote the PR body to a file; the operator opened 5 PRs. | Keep the human gate, but make it the documented path: every pipeline ends with a pushed branch, a body file and the exact `gh pr create` command (they did this when asked). | [051](../specs/051-pipelines-end-at-a-ready-pull-request/spec.md) |
| 10 | medium | **Repo agents cannot see the gitops state.** Both repo builds asked to add `TODO_API_URL` / `DATABASE_URL` to `services.yaml`, which `todo#3` had already done. | Checked by hand; nothing to change. | Put the gitops wiring the plan assigns (env names, addon) into each repo's *Product context*. | [052](../specs/052-repo-specs-know-the-gitops-wiring/spec.md) |
| 11 | low | Every repo spec raised one more question (DB-down timeout, unlisted responses): one round-trip per repo. | Answered in one resume. | The planner writes timeouts and the error mapping for unlisted responses into the contract. | [053](../specs/053-contracts-settle-cross-repo-details/spec.md) |
| 12 | low | `new-app` does not protect `main`, although the generated `CLAUDE.md` says it is protected; `todo#5` merged before its checks finished. | — | Set branch protection with the required checks when creating the repos (or drop the claim). | [054](../specs/054-new-repos-protect-main/spec.md) |
| 13 | low | The templates pin `actions/checkout` v5 (the platform uses v7): Dependabot opened a PR in every new repo within a minute. | Ignored. | Bump the template action pins together with the platform's. | [055](../specs/055-template-action-pins-match-the-platform/spec.md) |
| 14 | low | AC-001.1 hard-codes the local port `:8088`, which was taken on this host (`cluster-up` reported it, with the fix). | `LOCAL_HTTP_PORT=8089 devbox run cluster-up`. | Product-manager guidance: no environment details in criteria; consider `LOCAL_HTTP_PORT=auto` as default. | [056](../specs/056-criteria-stay-environment-neutral/spec.md) |
| 15 | low | `spec-check` prints "platform main predates spec checks (ADR-026); using main" when the ref already is `main`. | — | Say "the platform has no spec checks yet" directly. | [057](../specs/057-spec-check-says-what-happened/spec.md) |
| 16 | low | The `spec-format` skill appears as a user command `/svc:spec-format`. | — | Hide it from the command list (reference-only skill). | [058](../specs/058-reference-skills-stay-out-of-the-command/spec.md) |
| 17 | low | The web security recipe prints 61 "No plugins to scan with!" lines (detect-secrets) but passes. todo-api's image scan reports 44 HIGH CVEs in `python:3.12-slim` with no fixes yet. | — | Check the detect-secrets baseline in the web template; track the base image. | [059](../specs/059-security-scans-are-quiet-and-the-base/spec.md) |

Driver-side notes, not platform defects: `/shared:new-app` and every later step needed only the documented inputs; two of the operator's own shell snippets failed (zsh does not split `$CMD` strings) and were rerun as bash scripts.

## Follow-up

**Status 2026-10-08:** all 17 issues are fixed and verified: specs 043–059 are `done`, each with a `verification.md` (PRs #83 wave 1, #84 wave 2, #85 wave 3, #86 waves 4–5). The next end-to-end run is the live check of the prompt-level fixes (044 probe, 045 gitops execution, 046 foreground agents, 047 resume, 051 PR fallback).

Issues 1–3 block a clean unattended run and should be fixed first. Each issue is a draft spec (043–059, column *Spec*) in [`../specs/`](../specs/README.md): P0 for high, P1 for medium, P2 for low. Specs with open questions need answers (`/svc:spec --amend <id>`), the others only approval (`/svc:spec approve <id>`).
