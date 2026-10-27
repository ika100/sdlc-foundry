# Design — 122 A local console shows the system, its process and what needs you

## Decisions

- **UI technology: a Python stdlib server, HTML rendered on the server, one dependency-free script.** `cplat ui` runs `http.server.ThreadingHTTPServer` on `127.0.0.1` on a free port. Pages and side panels are HTML built by Python view functions in `scripts/cplat/console/`. The browser gets one `console.css` and one `console.js` (palette, keys, panels, polling, actions panel), with no framework, bundler, CDN, web font or vendored library. Why: the plugin checkout is never built on install, `devbox run test-fast` is pytest only, the console must work offline, and every view can be tested by parsing its HTML. The Astro site and the Next.js template need Node and a build, so they are not used. ADR: [docs/adr/055-local-console-over-cplat-json.md](../../adr/055-local-console-over-cplat-json.md).
- **Data: `cplat … --json` as subprocesses, one cache entry per source (AC-122.3, AC-122.42).** Sources: `model` (`cplat model show --json`), `status` (`cplat system status --json`), `specs:<repo>` (`cplat spec list --all --detail --json`, one per system repo), `runs` (`cplat runs --json --since 90`), `needs` (`cplat needs --json`), `doctor` (`cplat platform doctor --json`, prerequisites only, AC-122.41). Each call runs `sys.executable scripts/cplat/cplat.py …` from the same checkout with a 60 s timeout. A failure marks only that source as unavailable and keeps its last data marked stale. Calls run in process isolation, so a hang or crash in `gh` or `kubectl` can never block the server.
- **Repo content is a snapshot of `main`, never the working tree.** `console/mirror.py` downloads each system repo's `main` (`gh api repos/<o>/<r>/tarball/<sha>`) into `${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/console/<system>/<owner>__<repo>/<sha>/`. It also writes the `docs/specs/<id>/` folders of open draft spec pull requests (AC-122.30) into the snapshot, at their head ref. `model`, `status` and `specs:*` run with `--repo-dir`/`--repo` on the snapshot. Every 15 s the mirror polls the `main` sha of each repo (`gh api repos/<o>/<r>/commits/main`) and the mtime of `runs.state_dir()/active/`. A change re-reads the affected sources at once. All sources are also re-read every 30 s, which meets AC-122.3's 30 s.
- **Actions: `cplat headless "<slash command>"` in the target repo's local clone (AC-122.18).** That gives budgets, run records and resumes. `--max-runs 1` is used for everything except `ship`. The console never runs `git` writes, `gh` writes or `kubectl`. The two exceptions are reads, and `gh repo clone` for the system switcher (AC-122.29), which creates a new clone and changes no repo. Output is captured per action and streamed to the browser by polling `/api/actions` every 2 s. Server-sent events are not used: polling also keeps working across a server restart.
- **Every model form runs a real command, and its preview runs that same command on a scratch copy.** The five forms map to these commands:

  | Form | Command |
  |---|---|
  | component | `/component:add|set|remove` |
  | API | `/component:add|set --provides|--consumes` (AC-122.50) |
  | resource | `/resource:add|remove` |
  | environment rules | `/system:set --env` (AC-122.51) |
  | new system | `/system:new <manifest>` |

  The checks are whatever `render.py` reports on the scratch copy (ADR-054), so the preview and the command can never disagree.
- **Notifications run locally in `cplat ui notify` (`notify.py`).** The console starts it as a child process (`--loop`, every 60 s). A user without the console open can run `cplat ui notify --once` from cron or launchd. Webhook URLs and SMTP passwords come only from the environment or the OS keychain (AC-122.22).
- **`cplat runs --json` and spec 114's moved name.** `cplat runs <verb>` stays the AC-114.26 moved-name error (exit 2). Only the verb-less form (`cplat runs`, optionally with `--json`, `--since`, `--repo`, `--spec`) lists runs. That form was a usage error in 4.x, so AC-114.26 still holds for every 4.x command. In-scope prose for AC-114.52 (commands, READMEs, `docs/*.md`) never writes the two words `cplat runs` together: it says "the run list" and links to this design.
- **`cplat ui` and `cplat needs` are plumbing names**, like `model` and `spec`. `cplat platform ui` is an alias, so `/platform:ui` follows the noun rule. `cplat system set` is a new noun verb behind `/system:set`. AC-114.59 grows by `platform:ui` and `system:set` to 32 working commands.
- **Spec drafts as pull requests (AC-122.30).** A component spec keeps its branch `feature/<spec_id>` and a system spec keeps `docs/spec-<spec_id>` (spec claims, spec 082, stay unchanged). `cplat spec publish <id>` pushes the branch and opens or updates a draft PR that holds only `docs/specs/<id>/`, with the body marker `<!-- cplat:spec <id> -->`, and requests review from the system owner. `cplat spec land <id>` runs after `cplat spec approve`: it commits and pushes, approves the review, marks the PR ready and merges it with `cplat pr wait <n> --merge`. When the owner is the PR author, GitHub refuses both a self-review request and a self-approval. In that case the PR is assigned to the author instead, and `land` merges with the comment "approved by <login> (author is the system owner)". The owner is `owner:` from `system.yaml` (for a component repo, the gitops-app's `system.yaml` named in `.platform-app.yml`). A value without `/` that is not a user is tried as `<org>/<owner>` (a team).
- **The failure summary of AC-122.33 reads the run's recovery snapshot (spec 102) and escalation today.** Spec 108 is still a draft. `runs.failure` (below) is the binding contract, and spec 108 later only changes where it is filled from.
- **Stages are computed in one module, `scripts/cplat/stages.py`**, used by `needs`, `runs`, the board and every panel. No view maps a status or a phase by itself (AC-122.32).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/stages.py` | stage vocabulary, mapping rules, column explanations | new |
| `scripts/cplat/releases.py` | between two refs of a component: commits, specs, fixes, migrations (additive or not), next version, digests | new |
| `scripts/cplat/runlist.py` | `cplat runs`: active, buffered and stored records → run rows | new |
| `scripts/cplat/needs.py` | `cplat needs`: open decision points with consequence and way back | new |
| `scripts/cplat/cplat.py` | dispatch `ui`, `needs`, verb-less `runs`, `platform ui`, `system set` | changed |
| `scripts/cplat/compose.py` | `--provides NAME[:TYPE]`, `--consumes NAME` on `component add|set` | changed |
| `scripts/cplat/systemset.py` | `cplat system set --env`: one environment's `promote`/`policy`/`host`, one PR | new |
| `scripts/cplat/status.py` | per-cell `version`/`state`, environment rules, per-env contexts, libraries, release candidate, `unavailable` | changed |
| `scripts/cplat/spec.py` | `spec list --detail`; wiring of `publish`, `land`, `review` | changed |
| `scripts/cplat/spec_pr.py` | draft spec PR: publish, land, review comments | new |
| `scripts/cplat/notify_config.py` | `notify.yaml` schema, Recommended preset, secret lookup, doctor check | new |
| `scripts/cplat/notify.py` | `cplat ui notify`: event detection, channels, quiet hours, digest, resolution | new |
| `scripts/cplat/doctor.py` | checks `claude` and the notification channels | changed |
| `scripts/cplat/ui.py` | `cplat ui` entry: find `system.yaml`, port, browser, stop confirmation, `notify` routing | new |
| `scripts/cplat/console/server.py` | HTTP routes, token and Host checks, static files, job threads | new |
| `scripts/cplat/console/sources.py` | the source cache: call, parse, read_at, stale, unavailable, retry | new |
| `scripts/cplat/console/mirror.py` | snapshots of `main` and draft spec PRs, change detection | new |
| `scripts/cplat/console/actions.py` | run, track, lock, stop and persist actions; prerequisites | new |
| `scripts/cplat/console/preview.py` | form → command; the command on a scratch copy, `render.py` check, `system.yaml` diff, consequence | new |
| `scripts/cplat/console/handoff.py` | Open in Claude Code; deep links (PR, CI, run record, Argo CD, Grafana, logs) | new |
| `scripts/cplat/console/layout.py`, `html.py`, `static/console.css`, `static/console.js` | page shell, shared fragments, styles, browser behaviour | new |
| `scripts/cplat/console/inbox.py`, `board.py`, `panels.py`, `system_page.py`, `palette.py`, `switcher.py`, `settings_page.py` | the places, side panels, palette, switcher, settings | new |
| `plugins/component/commands/add.md`, `set.md` | usage lines for `--provides`/`--consumes` | changed |
| `plugins/system/commands/set.md` | `/system:set` | new |

## Contract

### Stage vocabulary (AC-122.32, AC-122.10, AC-122.12)

`stages.STAGES = ("Issue", "Spec", "Plan", "Build", "Land", "Dev", "Staging", "Prod")`. `stages.DECISION = {"Spec", "Build", "Prod"}`.

| Item | Stage |
|---|---|
| open issue not tracked by a spec (no `tracked` label) | Issue |
| spec `draft` | Spec |
| spec `approved` without a run; run phase `plan` | Plan |
| run phase `build`; spec `building` without a run | Build |
| run phase `pr` or `land` | Land |
| run phase `deploy` | Dev |
| run phase `staging` | Staging |
| release verified in staging, not running in prod | Prod |
| run phase `escalated` | the stage of `stopped_in`, with `stopped: true` |
| spec `done`/`superseded`, closed issue, release running in prod | no column (Done view) |

A system spec with slices takes the earliest stage of its slices. It is `stopped` if any slice is stopped. Functions: `stage_of_spec(status, run) -> str | None`, `stage_of_run(phase, stopped_in) -> (str, bool)`, `stage_of_issue(issue) -> str | None`, `stage_of_release(release) -> str | None`, `explain(stage) -> {"what", "agents", "commands", "decision" | None}` (the text of AC-122.12, one entry per stage). `stage_of_*` returns only names from `STAGES`.

Run phase derivation (`runlist`, AC-122.5): `ship`/`build` records use the last opened top-level phase in `plan|build|pr|land|deploy|done`. After `deploy` ends, a pending `staging` section (spec 093) gives `staging`. Outcome `escalated` gives `escalated` with `stopped_in` = the open phase at escalation (or `budget.stop.phase`). `product-ship`: `plan`/`publish` → `plan`, `repos` → `build`, `complete`/`done` → `done`. `headless` records of `/component:fix` follow the ship phases they recorded, else `build`.

### `cplat runs [--json] [--since DAYS] [--repo OWNER/NAME] [--spec ID]` (AC-122.5)

`--since` defaults to 30 (`0` = all). Rows come from active records (`runs.state_dir()/active`), the local buffer and the private store. A store that is unset or unreachable leaves `store.state` set and still lists the local records. Exit 0; exit 1 only for bad arguments. Without `--json` it prints a table. Rows are sorted active first, then `ended_at` newest first.

```json
{"schema": 1, "read_at": "2026-10-26T08:00:00Z",
 "store": {"state": "ok|unset|unreachable|public", "detail": "acme/runs"},
 "runs": [{
   "run_id": "20261026T070000Z-1a2b3c4d", "kind": "ship", "level": "component|system",
   "spec": "012-checkout", "repo": "acme/shop-api", "parent": null, "children": [],
   "phase": "plan|build|pr|land|deploy|staging|done|escalated", "stopped_in": null,
   "stage": "Build", "stopped": false, "active": true,
   "started_at": "…", "ended_at": null, "outcome": null,
   "escalation": {"reason": "3 CI fix rounds without progress", "cause": "code", "summary": "CI stayed red after three fix rounds."},
   "failure": {"check": "tests", "test": "tests/test_cart.py::test_total", "criterion": "AC-012.3",
               "error": "AssertionError: 41 != 42", "excerpt": ["…"], "log": "/path/to/log", "diagnosis": "rounding in total()"},
   "budget": {"used": {"minutes": 42, "invocations": 17, "reruns": 1, "cost": 3.1},
              "limit": {"minutes": 180, "invocations": 60, "reruns": 6, "cost": 15}, "exhausted": null},
   "activity": [{"at": "…", "agent": "svc:coder", "text": "merged t3"}],
   "session_id": "uuid|null", "repo_dir": "/abs/clone|null",
   "pr": {"number": 41, "url": "https://github.com/acme/shop-api/pull/41"}, "ci_url": "…|null",
   "image": "sha-<40>|null",
   "smoke": {"dev": {"result": "passed|failed|not-run", "instance": "shop-api/dev"}, "staging": null}
 }]}
```

`escalation` and `failure` are `null` unless the run escalated or failed. `budget.used.cost` may be `"unknown"`. `activity` holds at most 10 entries, newest first. They merge phase changes (agent `orchestrator`), `agents` events (spec 089), CI reruns and the escalation. `session_id`/`repo_dir` are the newest session of the run in the local session ledger (spec 099), or `null`. `failure` comes from the escalation and the recovery snapshot (`cplat-recovery.json`, spec 102): `criterion` is the first AC id in it, `diagnosis` the escalation's rule message.

### `cplat needs [--json] [--repo-dir DIR] [--system NAME]` (AC-122.4)

It reads the system from `--repo-dir` (a gitops-app clone, default `.`). It then reads the system's repos (the gitops repo and each component `repo`) through `gh`, the run list (`runlist.collect`) and the status (`status.collect`). Exit 0 even when a source fails. Exit 1 when no `applications/<system>/system.yaml` is found, with the same message as `cplat ui`. Items are sorted by `since`, oldest first.

```json
{"schema": 1, "system": "shop", "read_at": "…",
 "items": [{
   "id": "approve:acme/shop-api:012-checkout",
   "kind": "approve|answer|escalation|promote|triage",
   "stage": "Spec",
   "object": {"type": "spec|run|issue|release", "repo": "acme/shop-api", "spec": "012-checkout", "run_id": null,
              "issue": null, "component": null, "version": null, "pr": 41, "url": "https://github.com/…"},
   "since": "…", "reason": "draft without open questions; spec check passes",
   "command": "/component:spec approve 012", "cwd_repo": "acme/shop-api",
   "consequence": {}, "way_back": {}
 }],
 "unavailable": [{"source": "github|runs|cluster:<env>", "error": "…", "kinds": ["promote"]}]}
```

| kind | when | stage | `since` | command |
|---|---|---|---|---|
| `answer` | draft spec (on `main` or in a draft spec PR) with unstruck open questions | Spec | PR `createdAt`, else the spec's created line | `/<level>:spec --amend <NNN> <answers>` |
| `approve` | draft spec without open questions | Spec | same | `/<level>:spec approve <NNN>` |
| `escalation` | run with `phase: escalated` and no newer active or done run for the same repo and spec | stage of `stopped_in` | `ended_at` | `/component:ship <NNN>` (or `/system:ship <NNN>`) |
| `promote` | a release whose digest a green staging smoke verified, prod runs another version, and prod's `promote` is `manual` | Prod | staging smoke time | `/instance:promote <component> --to prod --version <v>` |
| `triage` | open issue labelled `triage` and `alert` or `smoke-failure` | Issue | `createdAt` | `/issue:triage <n>` |

A routed issue (its `triage` label is removed) is not listed. `<level>` is `system` for a gitops-app spec and `component` otherwise.

`consequence` / `way_back` (AC-122.34, AC-122.35):

- `approve`: `{"repos": ["acme/shop-api"], "unattended": ["Plan", "Build", "Land", "Dev", "Staging"], "estimate": {"cost_usd": 4.2, "minutes": 55, "runs": 5} | null}`. The estimate is the median of the last ≥ 3 done runs of the same `kind` and `level` in the run list, and `null` means "no estimate yet". `way_back`: `{"text": "The run can be paused at any stage; nothing reaches prod without you."}`.
- `answer`: `{"questions": 2}`, `way_back: null`.
- `promote`: `{"from": "1.3.0", "to": "1.4.0", "specs": ["012-checkout"], "criteria": 7, "commits": 23, "migrations": [{"file": "migrations/versions/0005.py", "additive": false}], "digest": "sha256:…", "verified_digest": "sha256:…", "digest_matches": true}` from `releases.between`. `way_back`: `{"command": "/instance:promote shop-api --to prod --version 1.3.0", "warning": "migration 0005.py is not additive" | null}`.
- `escalation`: `{"branch": "feature/012-checkout", "pr": 41, "deployed": false}`. `way_back`: `{"text": "Stopping keeps the branch and pull request #41; nothing was deployed."}`.
- `triage`: both `null`.

### `cplat system status --json` additions (AC-122.7, AC-122.8, AC-122.42, AC-122.47)

New keys only; the existing keys keep their meaning. New flags: `--context ENV=CTX` (repeatable, next to the existing `--context CTX` for all environments; default: the current kube context).

```json
{"environment_rules": [{"name": "dev", "promote": null, "policy": "audit"},
                       {"name": "staging", "promote": "after-dev-smoke", "policy": "audit"},
                       {"name": "prod", "promote": "manual", "policy": "enforce"}],
 "rows": [{"component": "shop-api", "type": "service",
           "cells": {"staging": {"…existing keys…": "…", "version": "1.4.0|sha-1a2b3c4",
                                 "state": "pinned|healthy|verified|NOT VERIFIED|alert|unknown",
                                 "digest": "sha256:…|null", "release": "1.4.0|null"}},
           "release_candidate": {"version": "1.5.0", "commits": 9, "specs": ["014-x"], "fixes": ["#57"], "digest": "sha256:…"} }],
 "libraries": [{"component": "shop-lib", "used_by": ["shop-api"]}],
 "resources": [{"resource": "postgres", "cells": {"dev": {"argo": "Synced/Healthy", "state": "healthy"}}}],
 "unavailable": [{"source": "cluster:prod", "error": "context k3d-prod not found"}]}
```

The cell `state`, in this order of precedence: `unknown` when Argo cannot be read for its environment (never the last value). `alert` with an open `alert` issue for the component and `env:<env>`. `NOT VERIFIED` when the smoke of the pinned commit in this environment failed or did not run. `verified` when it passed. `healthy` when Argo reports `Synced/Healthy`. Otherwise `pinned`. `release_candidate` is set only when the staging cell is `verified` and its commit is newer than the component's last release tag (AC-122.47). Libraries leave `rows`.

### `cplat spec list --json --detail` (AC-122.13 – AC-122.17)

`--detail` adds these keys to each row:

```json
{"title": "…", "level": "system|component", "path": "docs/specs/012-checkout/spec.md", "tracks": [57], "parent": null,
 "criteria": [{"id": "AC-012.1", "text": "…", "smoke": false, "tests": ["tests/test_cart.py"], "verdict": "met|not met|partial|not judged"}],
 "questions": [{"text": "Should …?", "options": ["50 per user", "no limit"], "answered": false}],
 "check": {"ok": true, "errors": []},
 "slices": [{"repo": "acme/shop-api", "spec": "012-checkout", "status": "approved"}],
 "contract_change": "POST /cart … | null",
 "draft_pr": {"number": 41, "url": "…"} }
```

`options` holds the `(suggested: …)` answer first, then alternatives the question lists after `or`/`alternatives:`. `slices` comes from `docs/plan/<id>.md` (system specs only). `contract_change` is the plan's `## Contract` section, or `design.md`'s, cut to 600 characters. `draft_pr` is read from a `.cplat-draft-pr.json` the mirror writes into the snapshot folder, else `null`.

### `cplat spec publish|land|review` (AC-122.30, AC-122.23)

- `publish <id>`: push the spec's branch, open or update a **draft** PR holding `docs/specs/<id>/` (title `docs(spec): <id> — <title>`, body marker `<!-- cplat:spec <id> -->`), and request review from the owner (see Decisions). Prints `{"pr": n, "url": …, "reviewer": login|team|null, "note": …}` with `--json`. The spec commands run it after every write of a draft (new, amend, answers).
- `land <id>`: requires `status: approved`. It commits and pushes, then `gh pr review --approve` (or the author note), `gh pr ready` and `cplat pr wait <n> --merge`. Exit 1 with the reason when CI fails.
- `review <id> --request-changes --body-file F`: posts a "changes requested" review. `review <id> --comments --json` lists `[{"author", "body", "at"}]` for the amend to read.

### `cplat component add|set … --provides NAME[:TYPE] --consumes NAME` (AC-122.50)

- Both flags are repeatable and apply to exactly one component (like `--env`). `TYPE` is one of `openapi`, `grpc`, `graphql`, `events`, and defaults to `openapi`. A new name is added to `apis:` with its type. An existing name keeps its type, and a different `:TYPE` for it is an error. The name is appended to the component's `provides`/`consumes` (no duplicate).
- Validation is the renderer's (ADR-054): the edit is applied, then `render.py` runs. On any render failure (`apis.<a>: provided by 2 components …; an API has exactly one provider`, `apis.<a>: provided by 0 components …`, an unknown type), `system.yaml` and the generated files are restored byte for byte. The command exits 1 with the renderer's line, which names the API and the rule. A type outside the four is refused before the edit with `--provides <name>:<type>: type must be one of openapi, grpc, graphql, events`.
- `--dry-run --json` adds the planned `apis` and `provides`/`consumes` changes to `will_do`. `--pr` opens one PR, as today.

### `cplat system set --env ENV [--promote R] [--policy P] [--host H] [--pr] [--dry-run] [--json] [--repo-dir DIR] [--system NAME]` (AC-122.51)

- At least one of `--promote`, `--policy` or `--host`. `ENV` must be an environment of the system. Allowed values follow spec 114: `--promote after-dev-smoke|manual` (staging), `manual` (prod), none on dev; `--policy audit|enforce|off`; `--host` a string with the `{component}`, `{system}`, `{env}` placeholders.
- An invalid value exits 1 before any edit, naming the key and the allowed values (`environments.prod.promote: prod takes only manual`). Only `environments.<ENV>.<key>` changes, through the round-trip YAML used by `compose.py`, so comments and order survive. `render.py` then runs, and a render failure restores everything and exits 1.
- `--pr` opens one PR (branch `system/set-<env>`, title `chore(system): set <env> <keys>`). Output follows `compose.py`: will-do lines, and `{"will_do": [...], "pr": url|null}` with `--json`.
- `/system:set` (`plugins/system/commands/set.md`) runs `cplat system set $ARGUMENTS --dry-run`, shows the plan, then runs with `--pr`, as `/component:set` does.

### Console HTTP (between `console.js` and the server; binding for the acceptance tests)

Every response is refused with `421` when `Host` is not `127.0.0.1:<port>`. Every `POST` needs the header `X-Console-Token` (the per-start token in `<meta name="console-token">`), else `403`. Errors are `{"error": str, "detail": str|null}`.

| Route | Result |
|---|---|
| `GET /` | `302 /inbox` |
| `GET /inbox`, `/board?view=columns\|list\|done&period=30\|90\|all&q=…`, `/system` | full page (`text/html`) |
| `GET /panel/<kind>/<id>` (kind `need\|spec\|run\|issue\|instance\|release\|stage`) | side panel fragment; `404` for an unknown id |
| `GET /palette?q=…` | palette fragment (go-to results, matching open issues) |
| `GET /api/state` | `{"read_at", "stale": bool, "badge": n, "actions": {"running": n, "failed": n}, "sources": {name: {"ok", "read_at", "unavailable_since", "error"}}, "banner": [{"piece", "fix"}], "version": n}` |
| `POST /api/sources/<name>/retry` | `202` |
| `POST /api/preview` `{"form": "component\|api\|resource\|environment\|system", "fields": {…}}` | `{"command", "diff", "checks": [{"key", "rule", "ok"}], "valid": bool, "consequence", "way_back"}` |
| `POST /api/actions` `{"kind", "object", "args"}` | `202 {"id"}`; `409` another action on the same object runs; `412` a prerequisite is missing (`{"error", "needs": "claude\|gh\|kube:<env>\|clone:<repo>"}`); `400` invalid |
| `GET /api/actions`, `GET /api/actions/<id>` | `[{"id", "kind", "object", "command", "repo", "started_at", "ended_at", "state": "running\|done\|failed\|stopped", "step", "tail": [≤20 lines], "links": {"run", "pr"}, "reason"}]` |
| `POST /api/actions/<id>/retry` | `202 {"id"}` (a new action with the same command) |
| `POST /api/open-in-claude` `{"run_id"}` | `{"command", "started": bool}` |
| `POST /api/ask` `{"question"}` | `{"answer", "suggestions": [{"command", "repo", "diff": str\|null}]}` |
| `POST /api/shutdown` `{"confirm": bool}` | `409 {"running": [...]}` without confirm while actions run; else `202` |
| `GET /static/console.css`, `/static/console.js` | the files; no other static path |

Action kinds and the command each one runs in `cwd_repo` via `cplat headless`:

| Kind | Command |
|---|---|
| `approve` | `/<level>:spec approve <NNN>` |
| `approve-ship` | the approval, then `/<level>:ship <NNN>` with `--budget cost=<n>` |
| `request-changes` | `/<level>:spec --amend <NNN> <comment>` (the command posts the review) |
| `answer` | `/<level>:spec --amend <NNN> answers to open questions: …` |
| `promote` | `/instance:promote …` |
| `more-budget` | `/<level>:ship <NNN>` with `--budget <limit>=<n>` |
| `amend` | `/<level>:spec --amend <NNN> <text>` |
| `fix` | `/component:fix #<n>` |
| `make-spec` | `/component:spec #<n> …` |
| `dismiss` | `/issue:triage <n> dismiss as wontfix: <reason> (confirmed by the user in the console)` |
| `cut-release` | `/component:release` |
| `describe` | `/system:spec <text>`, `/component:spec <text>`, or `"Let Claude decide: …"` |
| `model` | the preview's command: `/component:add\|set\|remove …` (incl. `--provides`/`--consumes`), `/resource:add\|remove …`, `/system:set --env …`, `/system:new <manifest>` |
| `clone` | `gh repo clone <o>/<r> <workspace>/<r>`, run directly |

### Markup contract (AC-122.28, AC-122.31, AC-122.37, AC-122.38, AC-122.43)

- Sidebar: `<nav aria-label="Places">` with exactly three `<a data-place="inbox|board|system">`. The Inbox badge is `<span data-badge="inbox">n</span>`. The palette button is `<button data-action="palette" aria-keyshortcuts="Meta+K Control+K">`. The user menu is `<details data-menu="user">` with Settings, Notifications, Switch system and Stop console.
- Side panel: `<aside data-panel role="dialog" aria-modal="false" aria-label="…">`, next to the place's content (the place stays rendered).
- Freshness: `<time data-read-at="ISO">` on every page and every data part. Data older than 2 min gets `data-stale="true"` and the visible word "stale". An unavailable part: `<section data-source="<name>" data-unavailable-since="ISO">` with the error, `<button data-action="retry-source">Retry now</button>`, and `unknown` in place of health.
- A command: `<code data-command>…</code><button data-copy aria-label="Copy command">`. A decision button: `data-action="<kind>" aria-keyshortcuts="a|p|t|o"` with the key shown in `<kbd>`. A disabled action: `disabled aria-disabled="true"` plus a visible `<span data-disabled-reason>`.
- Stage names appear only as `data-stage="<one of STAGES>"` with the same visible text.
- Activity indicator: `<button data-activity data-running="n" data-failed="m">` on every page.
- `console.js` keymap: `Meta/Ctrl+K` opens the palette; `j`/`k` move in the Inbox; arrow keys move across Board columns and cards; `Enter` opens; `Escape` closes the panel; `a`/`p`/`t`/`o` click the matching `data-action` of the selected decision. Single keys are ignored while `input`, `textarea`, `select` or `[contenteditable]` has focus.
- `console.css` defines colours only as custom properties on `:root`, and every text/background pair listed in its header comment has a contrast of at least 4.5:1 (3:1 for large text). `<meta name="viewport" content="width=device-width, initial-scale=1">`. Tables sit in `<div class="scroll-x">` (`overflow-x: auto`), and below 600 px the sidebar becomes a top bar, with no horizontal page scroll at 390 px.

### `~/.config/sdlc-foundry/notify.yaml` (AC-122.22 – AC-122.27)

```yaml
preset: recommended            # the base; keys below override it
events:                        # approve answer escalation promote alert smoke run-done retro
  approve: {github: instant, slack: off, email: digest, desktop: instant}
slack: {channels: ["#shop-dev"]}      # one incoming webhook per channel
email: {to: me@example.com, from: cplat@example.com, host: smtp.example.com, port: 587, user: me, starttls: true}
digest: {at: "09:00", days: [mon, tue, wed, thu, fri]}
quiet_hours: "22:00-07:00"     # optional
```

Values are `off|instant|digest`, and `digest` is accepted only for `slack` and `email`. An unknown event, channel, value or key is an error naming the key. The keys `webhook`, `url`, `password` and `token` are refused anywhere in the file. Secrets: the Slack webhook of channel `#shop-dev` comes from `CPLAT_SLACK_WEBHOOK_SHOP_DEV`, else the keychain item (service `sdlc-foundry`, account `slack-webhook:#shop-dev`; macOS `security find-generic-password -w`, Linux `secret-tool lookup`). The SMTP password comes from `CPLAT_SMTP_PASSWORD`, else the keychain account `smtp:<user>@<host>`.

**Recommended** preset (works with no setup): `github: instant` for approve, answer, escalation, alert and smoke, `off` for the rest. `desktop: instant` for approve, answer, escalation, promote, alert and smoke. `slack` and `email` are `off`.

`notify_config.doctor_checks() -> list[dict]` returns `doctor.check(...)` rows: one `warn` per channel used with `instant`/`digest` whose webhook, address, host or password is missing, naming the channel and the setting (AC-122.27).

Delivery (`notify.py`): an event key is `<event>:<object id>`. State: `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/notify/<system>.json` (`{"events": {key: {"first_seen", "sent": {channel: {"at", "ref"}}, "resolved_at"}}, "last_digest": ISO}`). Events come from `needs` items (approve, answer, escalation, promote), open `alert`/`smoke-failure` issues (alert, smoke), runs newly `done` (run-done), and a new open `retro` issue in the platform repo (retro). GitHub: approve and answer are the review request of `spec publish` (the notifier sends nothing more). For alert, smoke and retro it assigns the user to the existing issue. For escalation, promote and run-done it opens an issue labelled `notify` assigned to the user, with a `Signature:` line (ADR-033). Resolution (the key leaves its source): close the `notify` issue, remove the assignment the notifier added, withdraw the desktop notification where the OS allows it (Linux `gdbus … CloseNotification`; macOS cannot), and mark the event done for the next digest. A Slack message is never edited. Quiet hours hold every `instant` send except an `alert` whose issue carries `env:prod`. Held events go into the next digest. The digest lists open items and what shipped since `last_digest` (runs done, releases), and an empty digest is not sent.

## Data

No repo data apart from the `system.yaml` edits the commands of AC-122.50 and AC-122.51 make through their PRs. Local files only:
- `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/console/actions.json`: actions with state, and actions running at a stop become `stopped` (AC-122.46). Logs go to `…/console/actions/<id>.log`.
- `${XDG_STATE_HOME}/sdlc-foundry/notify/<system>.json`: notification state (above).
- `${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/console/<system>/`: snapshots and form scratch copies (deleted after the preview).
- `~/.config/sdlc-foundry/settings.yml`: new optional keys `workspace` (default `~/src`, AC-122.29) and `console.links.<env>.{argocd,grafana,logs}` URL templates with `{system}`, `{component}`, `{env}` (AC-122.39).

## Risks

- GitHub rate limit: about 1 `commits/main` call per repo every 15 s, plus the source calls, stays under 1,000 per hour for 6 repos.
- `claude -p` actions need the target repo's `.claude/settings.json` (headless refuses without it). The action is then disabled with that reason (AC-122.41).
- Opening Claude Code in a terminal is platform-specific (macOS Terminal via `osascript`, Linux `$TERMINAL` or `x-terminal-emulator`). Where neither works, `started: false` and the command is shown with a copy button.
- The preview runs the real `cplat` command on a scratch copy. For `component add`, this reads the component repo's answers through `gh`, so the preview needs GitHub. Offline, the form says so and keeps the confirm disabled.
