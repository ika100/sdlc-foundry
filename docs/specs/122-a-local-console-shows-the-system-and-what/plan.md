---
spec_id: 122-a-local-console-shows-the-system-and-what
spec_hash: b71f519f6577
summary: A local console (`cplat ui`, stdlib server on 127.0.0.1, server-rendered HTML, one dependency-free script) over
  cplat JSON with three places, side panels and a palette; new `cplat needs` and the verb-less `cplat runs --json`; richer
  `system status` and `spec list --detail`; one stage vocabulary; actions through `cplat headless`; draft spec PRs with a
  review request; local notifications (GitHub, Slack webhook, e-mail, desktop); `/platform:ui`; API flags on
  `/component:add|set` and the new `/system:set` behind the model forms
tasks:
  - id: t1
    title: stages.py — the eight stages, the mapping rules and the column explanations
    files: [scripts/cplat/stages.py]
    covers: [AC-122.32, AC-122.10, AC-122.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: releases.py — commits, specs, fixes, migrations and next version between two refs; digests
    files: [scripts/cplat/releases.py]
    covers: [AC-122.34, AC-122.35, AC-122.47]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: runlist.py and the dispatcher — `cplat runs [--json]`, `cplat needs`, `cplat ui`, `cplat platform ui`, `cplat system set`
    files: [scripts/cplat/runlist.py, scripts/cplat/cplat.py]
    covers: [AC-122.5, AC-122.9, AC-122.33, AC-122.36, AC-122.48, AC-122.51]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: spec list --detail — criteria with tests and verdicts, questions with options, check, slices, contract change
    files: [scripts/cplat/spec.py]
    covers: [AC-122.13, AC-122.14, AC-122.15, AC-122.16, AC-122.17]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: system status --json — cell version and state, environment rules, per-env contexts, libraries, release candidate, unavailable
    files: [scripts/cplat/status.py]
    covers: [AC-122.7, AC-122.8, AC-122.42, AC-122.47]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t6
    title: needs.py — `cplat needs --json` with the five kinds, consequence and way back
    files: [scripts/cplat/needs.py]
    covers: [AC-122.4, AC-122.6, AC-122.34, AC-122.35]
    parallel_safe: true
    depends_on: [t1, t2, t3, t4, t5]
    done: true
  - id: t7
    title: draft spec pull requests — spec publish|land|review and the two spec commands
    files: [scripts/cplat/spec_pr.py, scripts/cplat/spec.py, plugins/component/commands/spec.md, plugins/system/commands/spec.md]
    covers: [AC-122.30, AC-122.23, AC-122.16, AC-122.17]
    parallel_safe: true
    depends_on: [t4]
    done: true
  - id: t8
    title: console/actions.py — run, track, lock, stop and persist actions through cplat headless; prerequisites
    files: [scripts/cplat/console/__init__.py, scripts/cplat/console/actions.py]
    covers: [AC-122.18, AC-122.41, AC-122.44, AC-122.45, AC-122.46]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: console/preview.py — forms to commands, the command on a scratch copy checked by render.py, system.yaml diff, consequence
    files: [scripts/cplat/console/preview.py]
    covers: [AC-122.20, AC-122.18, AC-122.34, AC-122.35, AC-122.50, AC-122.51]
    parallel_safe: true
    depends_on: [t22, t23]
    done: true
  - id: t10
    title: console/handoff.py — Open in Claude Code and the deep links to evidence
    files: [scripts/cplat/console/handoff.py]
    covers: [AC-122.36, AC-122.39]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t11
    title: console shell — layout, shared fragments, console.css and console.js (keys, palette, panels, polling)
    files: [scripts/cplat/console/layout.py, scripts/cplat/console/html.py, scripts/cplat/console/static/console.css, scripts/cplat/console/static/console.js]
    covers: [AC-122.28, AC-122.31, AC-122.37, AC-122.38, AC-122.41, AC-122.43, AC-122.44]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t12
    title: cplat ui and the server — system.yaml lookup, 127.0.0.1, routes, sources cache, mirror of main, stop
    files: [scripts/cplat/ui.py, scripts/cplat/console/server.py, scripts/cplat/console/sources.py, scripts/cplat/console/mirror.py]
    covers: [AC-122.1, AC-122.2, AC-122.3, AC-122.41, AC-122.42, AC-122.43, AC-122.46]
    parallel_safe: true
    depends_on: [t8, t9, t10]
  - id: t13
    title: Inbox — decision list, detail with answer, approve, promote, take over, fix, dismiss; first-run steps
    files: [scripts/cplat/console/inbox.py]
    covers: [AC-122.6, AC-122.16, AC-122.17, AC-122.34, AC-122.35, AC-122.40]
    parallel_safe: true
    depends_on: [t1, t8, t11, t12]
  - id: t14
    title: Board — stage columns, list, column explanations, Done view and search
    files: [scripts/cplat/console/board.py]
    covers: [AC-122.9, AC-122.10, AC-122.11, AC-122.12, AC-122.40, AC-122.48, AC-122.49]
    parallel_safe: true
    depends_on: [t1, t11, t12]
  - id: t15
    title: side panels — spec, run, issue, instance, release; failures, evidence chain, criteria, links, Cut release
    files: [scripts/cplat/console/panels.py]
    covers: [AC-122.13, AC-122.14, AC-122.15, AC-122.33, AC-122.34, AC-122.35, AC-122.36, AC-122.39, AC-122.47]
    parallel_safe: true
    depends_on: [t1, t8, t10, t11, t12]
  - id: t16
    title: System — where it runs, Promote and Cut release on cells, parts and relations, Add to the model forms
    files: [scripts/cplat/console/system_page.py]
    covers: [AC-122.7, AC-122.8, AC-122.20, AC-122.40, AC-122.47, AC-122.50, AC-122.51]
    parallel_safe: true
    depends_on: [t1, t8, t9, t11, t12, t22, t23]
  - id: t17
    title: New or ask palette — describe a change, add to the model, go to, ask with read-only Claude
    files: [scripts/cplat/console/palette.py]
    covers: [AC-122.19, AC-122.21, AC-122.31, AC-122.38, AC-122.50, AC-122.51]
    parallel_safe: true
    depends_on: [t8, t9, t11, t12, t22, t23]
  - id: t18
    title: system switcher and settings page (notifications, workspace)
    files: [scripts/cplat/console/switcher.py, scripts/cplat/console/settings_page.py]
    covers: [AC-122.29, AC-122.22]
    parallel_safe: true
    depends_on: [t11, t12, t19]
  - id: t19
    title: notify_config.py and doctor — notify.yaml schema, Recommended preset, secrets, channel and claude checks
    files: [scripts/cplat/notify_config.py, scripts/cplat/doctor.py]
    covers: [AC-122.22, AC-122.27, AC-122.41]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t20
    title: notify.py — `cplat ui notify` with events, channels, quiet hours, digest and resolution
    files: [scripts/cplat/notify.py]
    covers: [AC-122.2, AC-122.23, AC-122.24, AC-122.25, AC-122.26]
    parallel_safe: true
    depends_on: [t3, t6, t19]
  - id: t21
    title: /platform:ui, docs, CHANGELOG and plugin versions
    files: [plugins/platform/commands/ui.md, plugins/platform/README.md, plugins/system/README.md, plugins/component/README.md, plugins/platform/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/console.md, docs/DOMAIN-MODEL.md, README.md, docs/CHANGELOG.md]
    covers: [AC-122.1, AC-122.30, AC-122.50, AC-122.51]
    parallel_safe: false
    depends_on: [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17, t18, t19, t20, t22, t23]
  - id: t22
    title: component add|set --provides NAME[:TYPE] and --consumes NAME
    files: [scripts/cplat/compose.py, plugins/component/commands/add.md, plugins/component/commands/set.md]
    covers: [AC-122.50]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t23
    title: system set --env with --promote, --policy and --host, and the /system:set command
    files: [scripts/cplat/systemset.py, plugins/system/commands/set.md]
    covers: [AC-122.51]
    parallel_safe: true
    depends_on: []
    done: true
human_steps:
  - "Optional: to get notifications and digests while the console is closed, schedule `cplat ui notify --once` every few minutes (cron or launchd)"
  - "Optional: put Slack webhooks and the SMTP password in the environment or the OS keychain (service sdlc-foundry) as docs/console.md describes; /platform:doctor names what is missing"
---

# Plan — 122 A local console shows the system, its process and what needs you

The contract is in [design.md](design.md) and binds every task. It covers the JSON of `cplat runs` and `cplat needs`, the `system status` and `spec list --detail` additions, `component add|set --provides|--consumes`, `system set`, the console HTTP routes, the markup contract and `notify.yaml`. The levels are:

- **0:** t1, t2, t4, t8, t10, t11, t19, t22, t23
- **1:** t3, t5, t7, t9
- **2:** t6, t12
- **3:** t13–t18, t20
- **4:** t21

The views (t13–t17) do not import `needs.py`, `status.py` or `runlist.py`. They read the JSON through `console/sources.py`, and their tests use fixtures of the contract.

**Acceptance tests outside this spec:** adding `/platform:ui` and `/system:set` changes AC-114.59's command count. The tester updates `WORKING` in `tests/cplat/test_plugins_114.py` in the red commit: `"set"` goes under `system` and `"ui"` under `platform`, and the count in `test_exactly_the_30_working_commands_exist_ac_114_59` becomes 32. Coders do not touch it. AC-114.52 scans the commands, READMEs and `docs/*.md`. No in-scope file may contain the words `cplat runs`, and in-scope prose avoids "addon" and "product" as nouns.

## t1 — stages.py

**Files:** scripts/cplat/stages.py
**Covers:** AC-122.32, AC-122.10, AC-122.12
**Goal:** one pure module that names every item's stage and explains each stage, so no other module maps a status or a phase.

**Implementation notes:**
- `STAGES`, `DECISION`, and `stage_of_spec`, `stage_of_run`, `stage_of_issue`, `stage_of_release`, `earliest(stages)`, `explain(stage)` exactly as design.md "Stage vocabulary".
- `stage_of_run("escalated", stopped_in)` returns the stage of `stopped_in` and `stopped=True`. An unknown phase raises `ValueError` instead of returning a free-text name.
- `explain` returns:
  - `what`;
  - `agents`, e.g. for Build: `svc:tester`, the shape's coder, `shared:quality`, `shared:security`, `svc:reviewer`;
  - `commands`, e.g. `/component:build`, `/component:ship`;
  - `decision`, only for Spec, Build and Prod (approve, escalations, promote).
- No I/O. Standard library only.

**Done when:** the AC-122.32 mapping tests and the stage-explanation tests of AC-122.12 pass.

## t2 — releases.py

**Files:** scripts/cplat/releases.py
**Covers:** AC-122.34, AC-122.35, AC-122.47
**Goal:** what lies between two refs of a component repo, for the promotion consequence, the way back and Cut release.

**Implementation notes:**
- `between(repo_slug, base, head) -> dict` returns:
  - `commits`: the count, via `gh api repos/<r>/compare/<base>...<head>`;
  - `specs`: ids of `docs/specs/<id>/` folders touched, or named in `spec:`/`Refs` lines of the commit messages;
  - `fixes`: `#N` from `fix:` commits;
  - `criteria`: the count of active criteria of those specs;
  - `migrations`: files added under `migrations/`, `src/main/resources/db/migration/` or `db/migrations/`. A file gets `additive: false` when it drops or renames a column or table, or alters a type (fixed regexes over the added lines).
- `next_version(last_tag, commit_subjects)` follows conventional commits: `!`/`BREAKING` → major, `feat` → minor, otherwise patch.
- `previous_release(repo_slug, current)` returns the tag before `current`, for the way back.
- `gh` goes through one replaceable `gh()` function, as in `evidence.py`. It never raises: what it cannot read becomes `None` with a reason.

**Done when:** the release-diff tests for AC-122.34, AC-122.35 and AC-122.47 pass with a stubbed `gh`.

## t3 — runlist.py and the dispatcher

**Files:** scripts/cplat/runlist.py, scripts/cplat/cplat.py
**Covers:** AC-122.5, AC-122.9, AC-122.33, AC-122.36, AC-122.48, AC-122.51
**Goal:** the verb-less `cplat runs` lists active and recent runs in the design's JSON, and `cplat.py` dispatches the new names.

**Implementation notes:**
- `collect(since_days, repo=None, spec=None) -> dict` reads active records (`runs.state_dir()/active`), the buffer, and the store through `runs.open_store`, reusing the reading code of `runs_report`. The store state comes from `runs.store_status`.
- Phase, `stopped_in`, `stage` and `stopped` follow design.md "Run phase derivation". The stage comes from `stages.stage_of_run`.
- Where the other fields come from:
  - `budget`: the ledger of the run's root in `budget` (used and limits; `exhausted` from `stop`);
  - `activity`: the last 10 entries, newest first;
  - `session_id`/`repo_dir`: the `runs_usage` ledger;
  - `failure`: the escalation and `cplat-recovery.json` of `repo_dir` when it is local.
- `--since 0` means all; the Done view uses it (AC-122.48). The table output has one line per run.
- Changes to `cplat.py`:
  - `PLUMBING["needs"] = "needs"` and `PLUMBING["ui"] = "ui"`;
  - `NOUNS["platform"]["ui"] = ("ui", [])` and `NOUNS["system"]["set"] = ("systemset", [])`. The module comes from t23 and is imported only when called.
  - In `_resolve`, `runs` with no positional argument (only `--json`, `--since`, `--repo`, `--spec`) routes to `runlist`. Any other `runs …` keeps the moved-name exit 2 (AC-114.26).
  - Add the new forms to the module docstring.

**Done when:** the AC-122.5 run-list tests pass, and the AC-114.26 and AC-114.60 tests still pass.

## t4 — spec list --detail

**Files:** scripts/cplat/spec.py
**Covers:** AC-122.13, AC-122.14, AC-122.15, AC-122.16, AC-122.17
**Goal:** `cplat spec list --json --detail` returns everything a spec panel and the approve detail show (design.md "spec list --json --detail").

**Implementation notes:**
- Per criterion: the text, the `(smoke)` flag, the tests from `trace` (the shape's globs; smoke globs for smoke criteria), and the verdict from `verification.md` (table row `| AC-… | met |…`), else `not judged`.
- `questions`: the unstruck open questions, with `options` parsed from `(suggested: …)` and any listed alternatives.
- `check`: `check(spec, shape=…)` as `{"ok", "errors"}`, so "Approve & ship" can say why it is disabled (AC-122.17).
- `slices` comes from `docs/plan/<id>.md` (system specs only), and `contract_change` from the `## Contract` section. `draft_pr` comes from `docs/specs/<id>/.cplat-draft-pr.json` when that file exists.
- `--detail` changes nothing without `--json`. The existing row keys stay as they are.

**Done when:** the spec-detail tests of AC-122.14, AC-122.16 and AC-122.17 pass, and the existing `spec` tests still pass.

## t5 — system status --json

**Files:** scripts/cplat/status.py
**Covers:** AC-122.7, AC-122.8, AC-122.42, AC-122.47
**Goal:** status reports per cell the version and one of `pinned`, `healthy`, `verified`, `NOT VERIFIED`, `alert`, `unknown`, plus the environment rules, libraries and release candidates.

**Implementation notes:**
- Contexts: `--context ENV=CTX` (repeatable) next to the existing `--context CTX`, defaulting to the current kube context. Call `argo_state` once per distinct context. A context that fails adds `unavailable: [{"source": "cluster:<env>", …}]` and makes its cells `unknown`, never the last known value.
- The state follows the precedence in design.md:
  - the smoke outcome per pinned commit comes from the run store (the reading in `evidence.py`);
  - alerts are open `alert` issues with `env:<env>` in the component repo.
- `environment_rules` lists `promote` and `policy` per environment from `model`, in promotion order. `version` is the release tag when the pin is a release, else the short sha. `digest` and `release` come from the pin.
- `libraries` are listed with `used_by`, and libraries leave `rows`.
- `release_candidate` is set when the staging cell is `verified` and its commit is newer than the last release. It comes from `releases.between(last_tag, staging_commit)` and `releases.next_version`.
- The text table stays as it is, except that each cell gets its state word.

**Done when:** the status tests of AC-122.7, AC-122.8, AC-122.42 (unknown health) and AC-122.47 (candidate) pass, and the existing status tests still pass.

## t6 — needs.py

**Files:** scripts/cplat/needs.py
**Covers:** AC-122.4, AC-122.6, AC-122.34, AC-122.35
**Goal:** `cplat needs [--json]` lists every open decision point of the system, exactly as design.md "cplat needs" says.

**Implementation notes:**
- Find the system the way `cplat ui` does. Without a `system.yaml`, exit 1, naming `applications/<system>/system.yaml` and the directory searched.
- Draft specs per system repo come from `main` (`gh api` contents of `docs/specs/`) and from open draft PRs with the `<!-- cplat:spec <id> -->` marker. Parse each with `spec.Spec` from text, then classify it as `answer` or `approve`.
- Escalations come from `runlist.collect(30)`, promotions from `status.collect` and `releases`, and triage items from `gh issue list --label triage` filtered on `alert`/`smoke-failure`.
- `consequence` and `way_back` per kind are as in design.md. The estimate is the median of at least 3 comparable done runs, else `null`.
- A source that fails adds an `unavailable` entry naming the kinds it hides; the other kinds are still listed. Items are sorted oldest first. The text output has one line per item, then the count.

**Done when:** the AC-122.4 tests pass (each kind, and routing removes a triage item), along with the consequence and way-back tests.

## t7 — draft spec pull requests

**Files:** scripts/cplat/spec_pr.py, scripts/cplat/spec.py, plugins/component/commands/spec.md, plugins/system/commands/spec.md
**Covers:** AC-122.30, AC-122.23, AC-122.16, AC-122.17
**Goal:**
- A new or amended draft is pushed as a draft PR holding `spec.md`, and the owner is asked to review it.
- Approval approves that review and merges the PR.
- "Request changes" leaves a review comment that the amend reads.

**Implementation notes:**
- `spec_pr.publish(root, spec)`, `land(root, spec)` and `review(root, spec, …)` work as in design.md "cplat spec publish|land|review". In `spec.py`, only the `spec publish|land|review` subparsers are added.
- `publish`:
  - stages only `docs/specs/<id>/` and pushes only the spec's branch (`feature/<id>` or `docs/spec-<id>`), never with force;
  - is idempotent: an open PR with the marker is updated, not opened a second time;
  - takes the owner from `system.yaml` (the gitops repo's, or the one `.platform-app.yml` names). When the owner is the author, it assigns the author instead of requesting a review, and says so in a note.
- `land` merges through `pr.wait(…, merge=True)` and refuses a spec that is not `approved`.
- Changes to `/component:spec` and `/system:spec`:
  - after B, C and Q commit a draft, run `cplat spec publish <id>`;
  - A runs `cplat spec approve <id>`, then `cplat spec land <id>`;
  - C reads `cplat spec review <id> --comments --json` and passes the comments to the product-manager;
  - a request that carries a review comment (the console's "Request changes") first posts it with `cplat spec review <id> --request-changes`;
  - update the "Commits stay local" lines in the rules.
- Keep both command descriptions at most 260 characters, with `Usage:` and `$ARGUMENTS` as before (AC-114.59 tests).

**Done when:** the AC-122.30 tests (publish, idempotence, self-review fallback, land, review comments) pass with stubbed `git`/`gh`, and the AC-114.59 command tests still pass.

## t8 — console/actions.py

**Files:** scripts/cplat/console/__init__.py, scripts/cplat/console/actions.py
**Covers:** AC-122.18, AC-122.41, AC-122.44, AC-122.45, AC-122.46
**Goal:** the one place that runs a confirmed command, tracks it, and refuses a second action on the same object.

**Implementation notes:**
- `console/__init__.py` holds only a docstring. It makes `console` a regular package.
- `command_for(kind, object, args) -> (argv, display, repo)` builds the commands of design.md's action table. Every kind that changes something runs `cplat headless "<slash command>" --repo <clone> [--max-runs 1] [--budget …]`. Only `clone` runs `gh repo clone` directly.
- `prerequisites(kind, object, env) -> list[str]` checks:
  - `claude`, via `shutil.which` or `CPLAT_CLAUDE`;
  - `gh`, logged in;
  - `kube:<env>`, for promote;
  - `clone:<repo>`, a local clone under the workspace with `.claude/settings.json`.

  A missing one gives HTTP 412 with `needs`.
- `start(...)` starts the process in its own process group, logs to `…/console/actions/<id>.log` and holds a lock per object (a second action gets 409).
  - The current step is the last non-empty output line, or the last `=== ` line of the headless log.
  - On exit it records `done` or `failed`, with links parsed from the output (a `/pull/<n>` URL, the `run_id`). A failure also records the reason and the last 20 lines.
  - `retry(id)` starts the same command again.
- `running()` and `stop_all()` stop running actions (SIGTERM, then SIGKILL after 10 s) and mark them `stopped` in `actions.json`. At the next start, `load()` marks any `running` entry whose PID is gone as `stopped`.
- Nothing runs without an explicit `start` call. The confirmation is the HTTP request sent by the confirm button.

**Done when:** these tests pass with a stub `CPLAT_CLAUDE`: AC-122.18 (exact command), AC-122.44, AC-122.45, AC-122.46, and the prerequisite part of AC-122.41.

## t9 — console/preview.py

**Files:** scripts/cplat/console/preview.py
**Covers:** AC-122.20, AC-122.18, AC-122.34, AC-122.35, AC-122.50, AC-122.51
**Goal:** a form's fields become the exact command, and the preview shows that command's `system.yaml` diff and the renderer's checks without touching the repo.

**Implementation notes:**
- `preview(snapshot_dir, form, fields) -> dict` returns the `/api/preview` shape in design.md. It copies `applications/` and `scripts/render.py` of the snapshot to a scratch dir and runs the real command there with `--repo-dir <scratch>` and without `--pr`:

  | Form | Command |
  |---|---|
  | `component` | `cplat component add\|set\|remove` |
  | `api` | `cplat component add\|set <c> --provides NAME[:TYPE] / --consumes NAME` (t22) |
  | `resource` | `cplat resource add\|remove` |
  | `environment` | `cplat system set --env ENV …` (t23) |
  | `system` | writes a `/system:new` manifest to the cache; the command is `/system:new <manifest>` |

- The command's own error and `python scripts/render.py --check` in the scratch dir become `{"key", "rule", "ok": false}` checks, with the key and rule as the renderer or command names them. The preview applies no rule of its own (ADR-054).
- `diff` is the unified diff of `system.yaml`.
- `consequence` lists the repos and PRs the command creates (one gitops PR, plus a component repo for `new`) and the environments whose generated overlays change in the scratch render.
- `way_back` is "close its pull request", or the matching `remove` command (for `system set`, the same command with the previous values).
- `valid` is `false` when any check fails.

**Done when:**
- the AC-122.20 tests pass: an invalid value names the key and the rule, the confirm stays disabled, and the preview is recomputed on every change;
- the API and environment-form tests of AC-122.50 and AC-122.51 pass, showing the exact command;
- the model-change parts of AC-122.34 and AC-122.35 pass.

## t10 — console/handoff.py

**Files:** scripts/cplat/console/handoff.py
**Covers:** AC-122.36, AC-122.39
**Goal:** "Open in Claude Code" and every evidence link come from one module.

**Implementation notes:**
- `claude_command(run, spec_path, failure) -> list[str]`:
  - with a `session_id`, it runs `claude --resume <id> "<failure summary prompt>"` in `repo_dir`;
  - without one, it runs `claude "<prompt naming the spec, the run record and the failure summary>"` in the repo's clone.
- `open_terminal(argv, cwd) -> bool` uses `osascript` on macOS (Terminal `do script`), and `$TERMINAL -e` or `x-terminal-emulator -e` on Linux. It returns `False` when neither is available, and the console then shows the command with a copy button.
- `links_for_work(run)` returns the PR, the CI run and the run record (store URL).
- `links_for_instance(system, component, env, settings)` returns Argo CD, Grafana and logs from the `console.links.<env>` templates, else `None` with a reason.

**Done when:** the AC-122.36 tests (resume vs new session) and the AC-122.39 link tests pass.

## t11 — console shell

**Files:** scripts/cplat/console/layout.py, scripts/cplat/console/html.py, scripts/cplat/console/static/console.css, scripts/cplat/console/static/console.js
**Covers:** AC-122.28, AC-122.31, AC-122.37, AC-122.38, AC-122.41, AC-122.43, AC-122.44
**Goal:** the page shell and shared fragments that every place uses, and the browser behaviour, following design.md's markup contract.

**Implementation notes:**
- `layout.page(title, place, body, *, panel=None, state) -> str` renders:
  - the sidebar with exactly three places and the Inbox badge;
  - "New or ask" (⌘K);
  - the user menu (Settings, Notifications, Switch system, Stop console);
  - the activity indicator and its panel container;
  - the banner of missing prerequisites, with the doctor fix;
  - the read-at stamp;
  - `<meta name="console-token">` and the viewport meta.
- `html.py` provides `esc`, `command_block(cmd)` (with a copy button), `action_button(kind, label, key, disabled_reason=None)`, `stage_badge(stage)`, `freshness(read_at, now)` (stale after 2 min), `unavailable(source, since, error)`, and `table(rows, cols)` inside `.scroll-x`.
- `console.css` defines the colours as custom properties, lists the contrast pairs in its header comment (each at least 4.5:1), keeps the layout working down to 390 px, and has a focus ring.
- `console.js` has no dependencies and no network access except same-origin `fetch`. It handles:
  - the keymap of design.md, with single keys ignored in text fields;
  - opening and closing the panel via `/panel/…`, returning focus;
  - opening and closing the palette;
  - polling `/api/state` every 5 s (badge, stale marks, re-fetch when `version` changes);
  - the actions panel, polling `/api/actions` every 2 s;
  - copy buttons;
  - POSTs with `X-Console-Token`.
- Neither static file contains an external URL.

**Done when:** the markup and static-file tests of AC-122.28, AC-122.31, AC-122.37, AC-122.38, AC-122.43 and AC-122.44 pass.

## t12 — cplat ui and the server

**Files:** scripts/cplat/ui.py, scripts/cplat/console/server.py, scripts/cplat/console/sources.py, scripts/cplat/console/mirror.py
**Covers:** AC-122.1, AC-122.2, AC-122.3, AC-122.41, AC-122.42, AC-122.43, AC-122.46
**Goal:** `cplat ui` starts the local server over the sources and serves the routes of design.md.

**Implementation notes:**
- `ui.main` runs `cplat ui [--repo-dir DIR] [--port N] [--no-open] [--no-notify]`:
  - find `applications/<system>/system.yaml` with `gitops.find_app`; if there is none, exit 1 with "no applications/<system>/system.yaml in <dir>";
  - bind `127.0.0.1` on port 0 (or `--port`) and print `console: http://127.0.0.1:<port>/`;
  - open the URL with `webbrowser` unless `--no-open`;
  - start `cplat ui notify --loop` as a child unless `--no-notify`. `cplat ui notify …` routes to `notify.main` (imported only when called).
- Stop (SIGINT, SIGTERM or `POST /api/shutdown`): if actions are running, list them and ask `stop N actions? [y/N]` on the terminal (over HTTP: 409 without `confirm`). On yes, call `actions.stop_all()`, then exit.
- `server.py` holds the route table of design.md:
  - views are named as strings like `"console.inbox:page"` and imported on first use;
  - a wrong `Host` gets 421, and a POST without the token gets 403;
  - static files are served only from `console/static/`;
  - errors are JSON.
- `sources.py` defines `Source(name, argv)`:
  - `read()` runs the subprocess with a timeout and parses the JSON;
  - it keeps `data`, `read_at`, `error` and `unavailable_since`, retries every 30 s, and marks data `stale` after 2 min;
  - a failing source never clears its last data;
  - `state()` builds `/api/state` (badge = `len(needs.items)`), and the doctor rows give the banner.
- `mirror.py`:
  - takes snapshots of each system repo's `main` and of the draft spec PR folders, including `.cplat-draft-pr.json`;
  - polls the `main` sha every 15 s and watches the mtime of the active run records;
  - calls an `on_change` callback that refreshes the affected sources.
- Outgoing traffic goes only through `gh` and the cplat subprocesses (AC-122.2).

**Done when:** these tests pass:
- AC-122.1;
- AC-122.2: no listener outside localhost, no HTTP except through `gh`;
- AC-122.3: refresh within 30 s of a change, with fake clocks;
- AC-122.42, AC-122.43 and AC-122.46;
- the banner part of AC-122.41.

## t13 — Inbox

**Files:** scripts/cplat/console/inbox.py
**Covers:** AC-122.6, AC-122.16, AC-122.17, AC-122.34, AC-122.35, AC-122.40
**Goal:** the Inbox lists the `needs` items oldest first, and the selected item's detail lets the user decide there.

**Implementation notes:**
- `page(ctx, query)`: one row per item (kind, `stage_badge`, age, reason), selectable with `j`/`k`. The detail opens as the side panel (`panel_need(ctx, id)`).
- `answer`: each question with its options as radio buttons, plus free text. Submit starts the `answer` action; the amend records the answers.
- `approve`:
  - "Approve & ship" with a budget field (default from settings). It is disabled, with the reason, while a question is open or `check.ok` is false.
  - "Approve only", and "Request changes" with a comment field.
  - The consequence and the way back come from the item.
- `promote`, `escalation`, `triage`: the consequence, the way back, and the buttons Promote, Take over, More budget, Amend the spec, Fix now, Make a spec, and Dismiss with a reason. Each button shows its command (`command_block`), its key and any disabled reason (AC-122.45, AC-122.41).
- Empty state (AC-122.40): what already runs (from status), "Describe your first change" (opens the palette), and "Choose notifications" (settings).

**Done when:** the Inbox tests of AC-122.6, AC-122.16, AC-122.17 and AC-122.40 pass with fixture JSON.

## t14 — Board

**Files:** scripts/cplat/console/board.py
**Covers:** AC-122.9, AC-122.10, AC-122.11, AC-122.12, AC-122.40, AC-122.48, AC-122.49
**Goal:** the Board shows every open item in exactly one stage column, plus the List and Done views and search.

**Implementation notes:**
- Items come from the `specs:*`, `runs` and `needs` sources and from the issues: the `needs` triage items plus the open untracked issues in the spec rows. There is one item per:
  - spec (a system spec merges its slices with `stages.earliest`);
  - fix run without a spec;
  - open issue;
  - release waiting for prod.
- Columns follow the order of `STAGES`. Spec, Build and Prod carry `data-decision`. A column header opens `/panel/stage/<name>` (`stages.explain`).
- A run card shows the repo, the stage and `used of limit`. A stopped run also shows the one-line `escalation.summary` (AC-122.9).
- `view=list`: one table of the same items, with stage and current state.
- `view=done&period=30|90|all`: closed specs, fix runs, issues and releases, newest first, each with date, stage reached, release and links.
- `q=` matches the id, a title word, a component name or `#n`, across open and done items.
- An empty board shows every column with its one-line explanation.

**Done when:** the Board tests of AC-122.9 – AC-122.12, AC-122.48, AC-122.49 and the Board part of AC-122.40 pass.

## t15 — side panels

**Files:** scripts/cplat/console/panels.py
**Covers:** AC-122.13, AC-122.14, AC-122.15, AC-122.33, AC-122.34, AC-122.35, AC-122.36, AC-122.39, AC-122.47
**Goal:** the detail of a spec, run, issue, instance or release, opened next to the place it was selected in.

**Implementation notes:**
- A spec or card panel shows:
  - the stage strip (8 stages, with the current one and a stop marked);
  - one line per slice, with stage and budget (one line for a component spec);
  - the criteria at a glance;
  - the selected slice's activity.
- Each criterion shows its id, text, tests, and verdict or `not judged`. A `(smoke)` criterion also shows the instance and smoke result from `runs.smoke`.
- The evidence chain issue → spec → plan → run → PR → image → instance, each a link or "not yet", plus `contract_change` when it is set.
- A failure (an escalated run, a failed or not-run smoke, a triage issue) shows:
  - why it stopped, in one sentence;
  - the failing test or check, with its criterion;
  - the last error and the diagnosis;
  - the ways forward, with their commands.
- "Open in Claude Code" (`o`) goes through `/api/open-in-claude`. Links come from `handoff`.
- "Cut release" on a release candidate shows the version, the specs, the fixes, the release PR and the tag note, and the way back (closing the release PR).

**Done when:** the panel tests of AC-122.13, AC-122.14, AC-122.15, AC-122.33, AC-122.36, AC-122.39 and the card part of AC-122.47 pass.

## t16 — System

**Files:** scripts/cplat/console/system_page.py
**Covers:** AC-122.7, AC-122.8, AC-122.20, AC-122.40, AC-122.47, AC-122.50, AC-122.51
**Goal:** "Where it runs" and the system's parts, with Promote, Cut release and "Add to the model" in place.

**Implementation notes:**
- The grid has one row per component with instances and one per resource. It has one column per environment, in `environment_rules` order, with `promote` and `policy` in the header. Cells show `version` and `state` exactly as status reports them, and `unknown` for unavailable clusters.
- Libraries are listed with `used_by`, without cells. Components, APIs and resources are listed with provides, consumes and uses.
- "Promote" appears on a `verified` cell whose next environment promotes `manual`. It is disabled while either cell is `unknown` (AC-122.42). "Cut release" appears when `release_candidate` is set.
- "Add to the model" offers five forms: component, API, resource, environment rules and new system. Each change posts to `/api/preview` and shows the diff, the checks, the command, the consequence and the way back; the confirm is disabled while the form is invalid.
  - The API form runs `/component:add|set --provides|--consumes` (AC-122.50).
  - The environment-rules form, opened from an environment's column header, runs `/system:set --env` (AC-122.51).
- An empty system shows the parts and instances that exist.

**Done when:** these System tests pass: AC-122.7, AC-122.8, the form parts of AC-122.20, AC-122.50 and AC-122.51, AC-122.40, and the cell part of AC-122.47.

## t17 — New or ask palette

**Files:** scripts/cplat/console/palette.py
**Covers:** AC-122.19, AC-122.21, AC-122.31, AC-122.38, AC-122.50, AC-122.51
**Goal:** one palette for describing a change, adding to the model, going to an object and asking.

**Implementation notes:**
- `fragment(ctx, q)` shows:
  - go-to results (specs, runs, issues, components, instances);
  - "Describe a change";
  - the "Add to the model" forms, the same five as System (API → AC-122.50, environment rules → AC-122.51, via `preview`);
  - Ask.
- Describe offers a level choice: system, component (with a repo picker) or "Let Claude decide". It lists the open issues whose title shares words with the sentence (from the issues in the sources), so the user can link one. Confirm starts the `describe` action.
- `ask(ctx, question)` runs `claude -p` in the gitops clone, with `--allowedTools` limited to Read, Grep, Glob, and Bash for the read-only `cplat` reads (`model show`, `spec list`, `needs`, `system status`, the run list).
  - The prompt asks Claude to end its answer with fenced `command` blocks. Each block becomes a suggestion with a confirm button that goes through actions (and through preview for model changes).
  - Nothing starts without that confirm.

**Done when:** the palette tests of AC-122.19 and AC-122.21, and the palette parts of AC-122.31 and AC-122.38, pass.

## t18 — switcher and settings page

**Files:** scripts/cplat/console/switcher.py, scripts/cplat/console/settings_page.py
**Covers:** AC-122.29, AC-122.22
**Goal:** open another system's console, and show and explain the notification settings.

**Implementation notes:**
- Switcher:
  - lists repos with the topic `gitops-app` from `gh repo list` for the user and from the organisations in `gh api user/orgs`;
  - opens a local clone under `workspace` with `cplat ui --repo-dir <clone>`, a new server on its own port whose URL is shown;
  - without a clone, offers the `clone` action first.
- Settings page shows:
  - the event × channel matrix from `notify_config.load()`, with the preset applied;
  - the missing secrets per channel;
  - the digest time and the quiet hours;
  - the path of `notify.yaml` and the snippet that changes it. The console never writes the file.

**Done when:** the AC-122.29 tests and the settings-view part of AC-122.22 pass.

## t19 — notify_config.py and doctor

**Files:** scripts/cplat/notify_config.py, scripts/cplat/doctor.py
**Covers:** AC-122.22, AC-122.27, AC-122.41
**Goal:** read and validate `notify.yaml` with the Recommended preset and secret lookup, and let `/platform:doctor` report what a channel or the console is missing.

**Implementation notes:**
- `load(path=None) -> Config` reads the events × channels, digest, quiet hours, Slack channels and email settings as in design.md. Errors name the key, and secret keys are refused.
- `secret(name) -> str | None` reads the environment first, then the keychain (`security` or `secret-tool`). It never logs a value.
- `doctor_checks()` returns one `warn` per channel in use whose setting is missing, naming the channel and the setting.
- In `doctor.py`, add `claude` to `check_tools` (a warning with the fix "install Claude Code: https://docs.anthropic.com/claude-code"), and add the notify checks to `run_checks`.

**Done when:** the AC-122.22 config tests, the AC-122.27 doctor tests and the doctor part of AC-122.41 pass, and the existing doctor tests still pass.

## t20 — notify.py

**Files:** scripts/cplat/notify.py
**Covers:** AC-122.2, AC-122.23, AC-122.24, AC-122.25, AC-122.26
**Goal:** `cplat ui notify [--once | --loop] [--repo-dir DIR]` turns events into one notification per `instant` channel, resolves them everywhere, holds them during quiet hours, and sends the digest.

**Implementation notes:**
- Events and the state file are as in design.md. Event keys are stable, and each channel gets one `instant` send per key.
- Channels:
  - GitHub: assign the user, or open a `notify` issue with a signature. Approve and answer are left to the review request.
  - Slack: a `urllib.request` POST to the webhook.
  - E-mail: `smtplib` with STARTTLS.
  - Desktop: `osascript` or `notify-send -p`, keeping the id.
- Resolution: when a key leaves its source, close the `notify` issue, remove the assignment the notifier added, and withdraw the desktop notification (Linux only). The digest marks the event done.
- Quiet hours hold everything except an `alert` on a prod instance.
- The digest is sent at `digest.at` on `digest.days`. It lists the open items and what shipped since `last_digest`, and is skipped when empty.
- Network traffic goes only to `gh`, the configured webhook and the SMTP host (AC-122.2). The clock, `gh`, HTTP and SMTP sit behind replaceable functions for the tests.

**Done when:** the tests of AC-122.23 – AC-122.26 and the notification part of AC-122.2 pass.

## t21 — /platform:ui, docs, CHANGELOG and versions

**Files:** plugins/platform/commands/ui.md, plugins/platform/README.md, plugins/system/README.md, plugins/component/README.md, plugins/platform/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/console.md, docs/DOMAIN-MODEL.md, README.md, docs/CHANGELOG.md
**Covers:** AC-122.1, AC-122.30, AC-122.50, AC-122.51
**Goal:** `/platform:ui` exists and runs `cplat platform ui`. The console, the spec PR flow, the API flags and `/system:set` are documented and released.

**Implementation notes:**
- `ui.md` has a `description` with `Usage: /platform:ui [--no-open] [--port N]` (at most 260 characters) and `$ARGUMENTS` in the body. It runs `cplat platform ui $ARGUMENTS` in the background and relays the URL.
- `docs/console.md` covers:
  - starting the console;
  - the three places;
  - stages;
  - actions;
  - notifications (`notify.yaml`, secrets, the `--once` schedule);
  - troubleshooting with doctor.

  It refers to "the run list" and never writes the words `cplat runs` (AC-114.52).
- `DOMAIN-MODEL.md`: add `set` to the `system` verbs and `ui` to the `platform` verbs. Add `--provides`/`--consumes` where the doc describes the component verbs.
- Plugin READMEs: list `/system:set` and `/platform:ui`, and the new `/component:add|set` flags.
- `README.md` gets one line on the console.
- `CHANGELOG.md` `[Unreleased]` lists:
  - the console;
  - `cplat needs` and the run list;
  - the status and spec additions;
  - draft spec PRs;
  - notifications;
  - `--provides`/`--consumes`;
  - `/system:set`.
- Minor version bumps for `platform`, `system` and `component`, in both `plugin.json` and `marketplace.json`.

**Done when:** `devbox run quality` and `devbox run test-fast` pass, including the updated AC-114.59 test (32 commands) and AC-114.52.

## t22 — component add|set --provides and --consumes

**Files:** scripts/cplat/compose.py, plugins/component/commands/add.md, plugins/component/commands/set.md
**Covers:** AC-122.50
**Goal:** `/component:add|set` declare which APIs a component provides and consumes. A new API goes into `apis:`, and one PR carries the change.

**Implementation notes:**
- `--provides NAME[:TYPE]` and `--consumes NAME` are repeatable and apply to exactly one component (refuse several, as `--env` does). `TYPE` is one of `openapi`, `grpc`, `graphql`, `events`, default `openapi`. Any other type is refused before the edit, naming the API and the allowed types.
- The edit:
  - goes through the round-trip YAML, so comments and order survive;
  - adds a new API under `apis:` with its type;
  - refuses a different type for an existing API, naming it;
  - appends the name to `provides`/`consumes` with no duplicate.
- Validation is `render.py` (ADR-054). If the render fails (a second provider, an API nobody provides, an unknown type), restore `system.yaml` and the generated files byte for byte, and exit 1 with the renderer's line naming the API and the rule.
- `--dry-run --json` lists the planned `apis` and `provides`/`consumes` changes in `will_do`. `--pr` opens one PR, as today.
- `add.md` and `set.md`: add the flags to the usage line (at most 260 characters, `Usage:` kept) and one sentence on when to use them.

**Done when:** the AC-122.50 tests pass (new API, default type, existing API, second provider, unknown type, consuming an unprovided API, nothing changed on failure, one PR), and the existing `component add|set` and AC-114.59 tests still pass.

## t23 — system set and /system:set

**Files:** scripts/cplat/systemset.py, plugins/system/commands/set.md
**Covers:** AC-122.51
**Goal:** `cplat system set --env ENV [--promote R] [--policy P] [--host H]` changes only that environment's keys in `system.yaml`, in one PR, and `/system:set` runs it.

**Implementation notes:**
- Arguments are as in design.md. `main(argv)` is the entry point that `cplat.py` dispatches to; t3 registers it.
- Validate before any edit, with spec 114's values:
  - `promote`: dev none; staging `after-dev-smoke|manual`; prod `manual`;
  - `policy`: `audit|enforce|off`;
  - `host`: a non-empty string, with the placeholders `{component}`, `{system}`, `{env}` only.

  An invalid value exits 1 and names the key (`environments.<env>.<key>`) and the allowed values. An unknown environment names the system's environments.
- The edit changes only `environments.<ENV>.<key>`, through the round-trip YAML, and then runs `gitops.render`. A render failure restores everything and exits 1. Nothing else in `system.yaml` changes.
- `--pr` opens one PR (`system/set-<env>`) through `gitops.open_pr`. `--dry-run` and `--json` follow `compose.py`.
- `set.md` has a `description` with `Usage: /system:set --env <env> [--promote <rule>] [--policy <policy>] [--host <host>]` (at most 260 characters) and `$ARGUMENTS` in the body. It runs `--dry-run`, shows the plan, then runs with `--pr`, the same way as `/component:set`.

**Done when:** the AC-122.51 tests pass (each key, prod promote only `manual`, none on dev, invalid value names the key and the allowed values, only that environment changes, one PR) when dispatched through `cplat system set` (after t3 merges). The updated AC-114.59 command tests pass for `/system:set`.
