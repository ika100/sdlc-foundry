# Design — 097 Ship a whole product across repos

## Decisions

- **`/app:ship` is a coordinator over the existing `/svc:ship`, not a second ship engine.** Each component repo runs its own `cplat ship` state machine in its own clone (same phases, limits, escalation rules: AC-097.7); the product run only schedules repos, evaluates gates, merges what belongs to the gitops-app and writes one record. ADR: [docs/adr/042-product-ship-coordinates-repo-ships.md](../../adr/042-product-ship-coordinates-repo-ships.md).
- **The product run's state lives in the gitops-app clone** at `<git common dir>/cplat-app-ship.json` (never committed, AC-097.4), next to where `cplat-ship.json` lives in a service repo. Scheduling reads this state and the plan; the plan's `done:` flags are written only at completion (AC-097.20), so the spec and plan on `main` stay identical to the published version during the run (AC-097.3). A plan repo already `done: true` from an earlier `/app:build` counts as past its gate (state `done-before`).
- **A repo ship is linked to the product run by `cplat ship start <spec> --product <gitops-app dir>`.** The repo's `cplat-ship.json` gets `product: {dir, run_id, context}`; that gives the repo run its `parent`, its default `--context` for `deploy`, and routes its gitops merges through the product's merge slot (AC-097.9). No environment variables are needed, so it survives resumes and subagents.
- **Gitops merges are serialized by one merge slot per product run**: an `fcntl` lock on `<gitops-app git common dir>/cplat-app-ship.lock`, held only for "check mergeable → merge → record". Waiters are served in plan order (lowest plan index of the waiting repos first; the gitops entry is index 0). Inside the slot a PR whose `mergeable` is `CONFLICTING` is never merged or rebased: that repo escalates naming it and the last PR the product run merged (AC-097.9).
- **Gate classes come from the gitops-app, not from the repo's smoke wording** (AC-097.19): `library` when the plan entry's shape has `deployable: false` in `shapes.yml`; `exposed` when the service's entry in `origin/main:applications/*/services.yaml` (matched by `repo:` slug, else `name:` = repo id) has `expose` and `dev` in `environments` (default `[dev]`) and `app.yaml` has `hosts.dev` — the same rule as `smoke.dev_url`; otherwise `internal`.
- **Parallel repos are foreground subagents in one message** (as `/app:build`, spec 046): at most `--max` per message. A repo whose dependencies pass during a message starts in the next one.
- **The run refuses without a kube context** (AC-097.18) and passes it to every repo ship; a context is the one from `--context`, else `kubectl config current-context`. It counts only if `kubectl --context C -n argocd get applications -o name` succeeds and lists `<entry>-dev` for at least one service of the gitops-app's `services.yaml`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/appship_state.py` | state file, start checks (shape, approval, context), resume, escalate, finish, run record, Stop hook gate | new |
| `scripts/cplat/appship_sched.py` | plan + state → ready/running/blocked; gate class and gate evaluation; repo start (clone, dirty check), repo result, repo escalate | new |
| `scripts/cplat/appship_merge.py` | merge slot (lock, plan order, conflict check, `gitops_merged` log); `land(pr)` wait-green-then-merge for the gitops-app's own PRs | new |
| `scripts/cplat/appship.py` | `cplat app-ship` CLI; `publish` (AC-097.3), `entry` (AC-097.8), `complete` and the final report (AC-097.20) | new |
| `scripts/cplat/cplat.py` | `"app-ship": "appship"` in `COMMANDS` | changed |
| `scripts/cplat/ship.py` | `start --product`; `deploy` default context from `product`; `merge_gitops` through the merge slot; `smoke.reason` kept in state | changed |
| `plugins/shared/hooks/hooks.json` | second Stop hook entry for `cplat-app-ship.json` | changed |
| `plugins/app/commands/ship.md` | the `/app:ship` coordinator prompt | new |

## Contract

### CLI: `cplat app-ship` (run in the gitops-app repo; `--repo DIR` default `.`)

Every command prints plain lines; `--json` where shown prints one JSON object. Errors are `PlatformError` with a hint (exit 1), like `cplat ship`.

| Command | Does | Exit |
|---|---|---|
| `start <spec> [--max N] [--context C]` | refuse or begin/resume; prints `describe` (phase, repo table, `next:` line) | 0; 1 on refusal |
| `status [--json]` | the state + `next` | 0 |
| `phase <plan\|publish\|repos\|complete\|done>` | record progress | 0 |
| `publish [--timeout S]` | AC-097.3, see below | 0 green/nothing to do; 1 red (run escalated) |
| `next [--json]` | the scheduler, see below | 0 |
| `repo start <id>` | mark `running`; prints the clone path (or, for the gitops entry, the worktree path on `compose/<spec>`) | 0; 1 dirty clone |
| `repo result <id>` | read the clone's ship state, evaluate the gate, archive the clone's state (`ship.finish`) | 0 passed; 1 escalated |
| `repo escalate <id> <reason> --cause C` | a repo that escalated before its ship state existed (open questions, AC-097.6) | 0 |
| `entry pr <id> --title T --body-file F` | push `compose/<spec>`, open (or reuse) its PR | 0 |
| `entry land <id> [--timeout S]` | wait for all checks, merge through the slot (AC-097.8) | 0 merged; 1 red (repo escalated, failed checks printed) |
| `complete [--timeout S]` | AC-097.20, see below; prints the report | 0; 1 red |
| `escalate <reason> --cause C` | end the run escalated (cause as `cplat ship`, spec 088) | 0 |
| `finish` | archive the state to `cplat-app-ship-<spec>-<ts>.json`; an unrecorded run is recorded `abandoned` | 0 |
| `gate [--max-blocks N]` | Stop hook (reads hook JSON on stdin) | 0 |

**`start` refusals (nothing is written, AC-097.1, AC-097.18):**

- shape is not `gitops-app` → `this is a <shape> repo: a component spec ships with /svc:ship <spec>` (no shape: same with `unknown`).
- product spec status not `approved` or `building` → `<id> is '<status>'; only an approved product spec is shipped`, hint `/app:spec approve <NNN>`.
- no usable context → `no kube context for the product's cluster`, hint `pass --context <name> or select it: kubectl config use-context <name>`.
- another unfinished product run for a different spec → refuse, hint `cplat app-ship finish`.

**Resume (AC-097.4):** `start` for the spec of an existing state clears `escalated`/`cause`, resets `blocks`, keeps every repo's state; an escalated run gets a new `run_id` with `resumes` = the old one. Repos `passed`/`done-before` are never started again; an `escalated` repo goes back to `ready` (its clone's ship resumes at its own phase via `cplat ship start`); a `running` repo stays `running` and is started again (its ship resumes).

**Initial phase:** `plan` when `docs/plan/<spec>.md` does not exist; else `publish`.

**`publish` (AC-097.3):** `git fetch origin`; if `docs/specs/<spec>/` and `docs/plan/<spec>.md` exist on `origin/main` and `git diff --quiet origin/main -- <both>` → phase `repos`, prints `spec and plan are on main`. Otherwise: the working tree must hold no other change; commit them on `docs/spec-<spec>` (`docs(spec): <spec> — product spec and plan`), push that branch, open or reuse its PR, then `appship_merge.land`. Green → merged, `git switch main && git pull --ff-only`, phase `repos`. Red → the run escalates `spec/plan PR <url> is red: <checks>` cause `code`; no repo starts.

**`next --json`:**

```json
{"phase": "repos",
 "start": [{"id": "shop-api", "shape": "service-python", "clone": "/abs/../shop-api", "entry": false}],
 "running": ["shop-web"],
 "blocked": [{"id": "shop-admin", "waits_for": ["shop-api"]}],
 "escalated": ["shop-lib"],
 "action": "start" | "wait" | "complete" | "escalate" | "done"}
```

`start` holds the repos whose `depends_on` are all `passed`/`done-before`, not running, not escalated, capped so that `running + start ≤ max`; the gitops entry (shape `gitops-app`) is listed with `entry: true` and `clone` = the worktree path. After an escalation (AC-097.10) `start` is always empty; `action` is `wait` while repos run and `escalate` once none run (the coordinator then calls `escalate` with the repo's reason; the record takes the repo's cause). `complete` when every repo is past its gate.

**`repo start <id>`:** clone `../<id>` (`gh repo clone <github_org>/<id>`) when missing; refuse a clone whose `git status --porcelain` is not empty: `<abs path> has uncommitted changes; commit or stash them, then resume` (AC-097.7). For the entry: `git worktree add <common>/cplat-app-ship/<spec>-entry -b compose/<spec> origin/main` (reused when present).

**`repo result <id>`:** reads `<clone>/.git/cplat-ship.json` (via `ship.load_state`). Its `spec` must carry `parent: <github_org>/<gitops repo>:<product spec>`; else error. Then:

| Clone ship state | Gate class | Result |
|---|---|---|
| `escalated` | any | repo `escalated` with its reason and cause (smoke-red issue lines kept) |
| phase not `done` | any | error `ship of <id> is in phase <p>; resume it` (the repo stays `running`) |
| `done`, `merge_sha` set | `library` | `passed` |
| `done`, `smoke.outcome` `passed`/`passed-on-retry` | `exposed` | `passed` |
| `done`, smoke `not-run` or anything else | `exposed` | `escalated`: `smoke not run in dev for <id>: <reason>; an exposed service needs passing smoke` cause `environment` |
| `done`, `deployed` = `sha-<merge_sha>` and `ship.argo_health(context, "<svc>-dev", 120, 10, images)` Synced/Healthy | `internal` | `passed` |
| `done`, otherwise | `internal` | `escalated`: `<svc>-dev is not Synced/Healthy on sha-<merge_sha>` cause `environment` |

On `passed` and `escalated` it copies into the repo's state: `spec`, `pr`, `fix_rounds`, `deployed`, `argo` (`Synced/Healthy` | `-`), `smoke_row`, `human_steps` (the repo plan's), `run_id`; then archives the clone's ship state (`ship.finish`, which records nothing more because the repo run is already recorded).

### Merge slot (`appship_merge`)

```python
@contextmanager
def slot(gitops_dir: Path, repo_id: str, plan_index: int, timeout: float) -> Iterator[None]
def merge(gitops_dir: Path, pr: str, repo_id: str, *, cwd: Path) -> None     # inside slot; raises Conflict
class Conflict(PlatformError): pr: str; after: str | None                      # `after` = last PR in gitops_merged
def land(gitops_dir: Path, pr: str, repo_id: str, timeout: float, interval: float) -> tuple[bool, list[str]]
```

- `slot`: registers `{repo_id, plan_index}` in `waiting` (state file), loops: take the lock; if no waiter has a lower `plan_index`, yield; else release, `sleep(interval)`. Always removes itself from `waiting`.
- `merge`: `gh pr view <pr> --json mergeable,state`; `MERGED` → record only; `CONFLICTING` → `Conflict`: message `gitops PR <pr> no longer merges cleanly after <after> merged` (without `after`: `… merges cleanly`). Else `gh pr merge --squash --delete-branch`; append `{pr, repo, at}` to `gitops_merged`. Never `--admin`, never a force-push.
- `land`: `ship.wait_checks(ship.CheckWatch(...))` (marks a draft ready first), red → `(False, red lines)`, green → `slot` + `merge`.
- `ship.merge_gitops` with `st["product"]` set: the existing wait-checks stays outside; only the merge call goes through `slot` + `merge`. A `Conflict` makes that repo's `cplat ship land/deploy` escalate itself with cause `decision` and the Conflict message.

### `complete` (AC-097.20)

On `docs/done-<spec>`: `cplat spec set-status <spec> done`, `devbox run -- uv run scripts/plan.py done <spec> <id>` for every repo not yet `done`, `cplat spec index`; commit `docs(spec): <spec> done`, push, PR, `land` (red → run escalated cause `code`). Then phase `done` (the record is written) and the report:

```
## Shipped: <spec_id> — <title>

| Repo | Repo spec | PR | CI rounds | dev | Argo | Smoke (dev) |
|---|---|---|---|---|---|---|
| <gitops repo> (entry) | - | <url> | <n> | - | - | - |
| <id> | <repo spec id> | <url> | <fix_rounds+1> | <svc>:sha-<40> or - | Synced/Healthy or - | <smoke row> or `not run: <reason>` |

Human steps (the run cannot do these):
- [ ] <each human_steps line of the repo plans, then the product plan's>

Next (staging is not promoted by this run):
/gitops:promote <svc> dev staging          (one per deployable service)
```

`Smoke (dev)` for a library is `not run: not deployable (library)`; for an internal service `not run: <svc> has no dev URL (not exposed in dev)`. A repo `done-before` shows `-` in every column but the first and `done before this run` as its smoke cell.

On escalation `describe` prints the same table with a `State` column (`passed`, `running`, `escalated: <reason>`, `blocked`, `ready`, `done-before`) instead of the report header (AC-097.10).

### State file `<git common dir>/cplat-app-ship.json`

```json
{"spec": "012-shop", "phase": "repos", "max": 3, "context": "kind-shop", "run_id": "…", "recorded": false,
 "started": "<local iso>", "updated": "<local iso>", "blocks": 0, "escalated": null, "cause": null,
 "repos": {"<id>": {"state": "ready|running|passed|escalated|done-before", "gate": "exposed|internal|library|entry",
                     "clone": "/abs", "spec": "…", "pr": "…", "fix_rounds": 0, "deployed": "sha-…", "argo": "Synced/Healthy",
                     "smoke_row": "…", "human_steps": [], "run_id": "…", "reason": "…", "cause": "…"}},
 "ships": ["<repo ship run_id>", "…"],
 "waiting": [{"repo": "<id>", "plan_index": 2}],
 "gitops_merged": [{"pr": "<url>", "repo": "<id>", "at": "<utc iso>"}]}
```

### `cplat ship start --product DIR` (ship.py)

Adds `"product": {"dir": "<abs gitops-app dir>", "run_id": "<product run_id>", "context": "<context>"}` to the repo's state on a fresh start and on resume (overwriting). `runs.start("ship", …, parent=product.run_id)`. `cplat ship deploy` without `--context` uses `product.context`. `_smoke_state` additionally stores `"reason": result.reason` in `st["smoke"]`. Without `--product` nothing changes.

### Run record (AC-097.12)

`runs.start("product-ship", repo=<gitops-app slug>, spec=<product spec>, resumes=<old>)` at `start` (local active record only; nothing in the store). One `runs.finish` at the run end: `done` from `complete`, `escalated` from `escalate` (escalation `{reason, cause}`; `cause` = the escalated repo's cause, else the given one), `abandoned` from `finish` of an unrecorded run or from a take-over. `fields={"ships": [run_ids of every repo ship it drove, in start order], "repos": {"<id>": "<state>"}}`.

### Stop hook

`hooks.json` gets a second `Stop` entry: `f="$(git rev-parse --git-common-dir 2>/dev/null)/cplat-app-ship.json"; [ -f "$f" ] || exit 0; exec "${CLAUDE_PLUGIN_ROOT}/bin/cplat" app-ship gate`. `gate` returns `None` when the run is `done` or escalated, else `{"decision": "block", "reason": "The product ship of <spec> is not finished (phase <p>, stop attempt k/N). Next: <next>. …"}`; after `--max-blocks` (8) it escalates `gave up after 8 attempts to stop` and lets the session end, as `cplat ship gate`.

## Risks

- A subagent's ship may outlive its foreground call (headless 600 s limit does not apply to foreground calls, spec 046); a repo left `running` is simply started again on the next `next` round and resumes at its phase.
- `fcntl` locks are local: two product runs from two machines are not serialized. One product run per gitops-app is the supported case (state refuses a second spec in the same clone).
