# Unattended delivery: from an approved spec to dev

How to let Claude take a feature from spec approval to a running `dev` without you watching. This works on GitHub Free with private repos ([ADR-028](adr/028-unattended-delivery-without-branch-protection.md)).

## The flow

```
you:        /svc:spec <feature>  →  answer its questions  →  /svc:spec approve <NNN>     (the only decision)
unattended: /svc:ship <NNN>
              plan     architect writes plan.md (skipped when a valid plan exists)
              build    failing acceptance tests → coders until green → QA → reviewer (verification.md) → image
              pr       cplat ship pr: pushes feature/<spec>, opens the PR
              land     cplat ship land: waits for every check; red → logs → coder → push (≤ 3 rounds); green → squash merge
              deploy   cplat ship deploy: the service's CI publishes sha-<40>, pin-dev merges the pin PR after CI, Argo syncs
              staging  a green dev smoke dispatches pin-staging (self-merging PR), Argo syncs, staging smoke (spec 093)
you:        check staging  →  /gitops:promote <svc> staging prod   (evidence summary, reviewed PR)
```

The run stops on its own only when it is done or escalated. While it is unfinished, the shared plugin's Stop hook refuses to let the session end (spec 066). It escalates (`cplat ship escalate '<reason>'`) when a rule needs you: a merge conflict after its re-plan (a task is re-planned once, a build at most 3 times), a changed acceptance test, a security finding with no fix released, or a bump that breaks a gate, a decision the spec does not answer, red CI after three fix rounds, a closed pin PR. `/svc:ship <NNN>` resumes where it stopped. `cplat ship status` shows the phase at any time.

### Dependency patches

When the security gate is red because of dependencies with a released fix, the run bumps them itself (`cplat deps patch`, spec 095), re-runs the gates and commits the bump, or reverts it exactly. The PR body lists each bump under "Dependency patches" (a major bump is marked) and the run record has a `patches` section. At most 2 rounds; a finding without a fix, or a bump that breaks a gate, escalates.

## Run it without a terminal session

```bash
cplat headless "/svc:ship 012"                         # in the repo; resumes in fresh sessions until done or escalated
cplat headless "/svc:ship 012" --quiet 23:30-07:00     # never start inside that window (wait for it to end)
cplat headless "/svc:ship 012" --max-runs 6 --max-minutes 240 --model opus
```

Each session is `claude -p <prompt> --permission-mode acceptEdits`: file edits inside the repo are accepted, the repo's committed allowlist (`.claude/settings.json`) governs every other tool, and everything else is refused instead of prompting. (Until 4.5.0 this was `dontAsk`, which also refused every file edit, because no allowlist grants `Edit` or `Write`.) `git push origin main` and `gh pr create` are `ask` rules there, so they are refused; `cplat ship` does the narrow pushes and the PR itself. Logs are in `~/.cache/sdlc-foundry/headless/<repo>/`; `summary.log` has one line per run, and a desktop notification says how it ended (exit 0 shipped, 1 needs you, 3 inside the quiet window with `--no-wait`).

The coordinator session runs on Sonnet unless you choose otherwise (spec 100, [ADR-036](adr/036-coordinator-model-default-and-settings.md)); `cplat headless` always passes `--model`. Precedence: the `--model` flag, then `coordinator_model` in the repo's `.platform-settings.yml`, then in `~/.config/sdlc-foundry/settings.yml`, then `sonnet`. The value is `sonnet`, `opus` or `haiku`, or a map with a `default` and one entry per workflow (`build: opus`); any other name is refused before anything starts. Agents with their own model (architect, reviewer, product-manager) keep it. `--plugin-dir PATH` (repeatable) loads a plugin from a folder, and `cplat runs benchmark <workflow> --plugins <worktree>/plugins` measures a change with the worktree's plugins before it is released; the record names the plugins (`dir`, `commit`, `dirty`) and the coordinator model.

Open the repo interactively once before the first headless run: Claude Code ignores a project's allowlist in a workspace it has not trusted yet ([ADOPTING.md → Unattended runs](ADOPTING.md#unattended-runs)).

### On a schedule (macOS launchd)

```xml
<!-- ~/Library/LaunchAgents/com.me.shop-api-ship.plist -->
<plist version="1.0"><dict>
  <key>Label</key><string>com.me.shop-api-ship</string>
  <key>WorkingDirectory</key><string>/Users/me/Dev/shop-api</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-lc</string>
    <string>cplat headless "/svc:ship 012" --quiet 23:30-07:00 --no-wait</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
</dict></plist>
```

Outside a Claude session `cplat` is not on the PATH: use the plugin's launcher (`~/.claude/plugins/marketplaces/sdlc-foundry/plugins/shared/bin/cplat`), or `uv run <sdlc-foundry checkout>/scripts/cplat/cplat.py`.

## What has to be in place

| Piece | Why | Check |
|---|---|---|
| The repo is a platform repo (`.copier-answers.yml`) | shape routing, recipes, allowlist | `/shared:doctor`; existing repos: `cplat adopt --type <shape>` |
| CI on pull requests reports checks | `land` never merges without a check | a PR shows checks; self-hosted runners: `vars.CI_RUNNER` ([guide](self-hosted-runners.md)) |
| `.platform-app.yml` and the `GITOPS_TOKEN` secret | the service's CI asks the gitops-app for the dev pin (ADR-027) | the `pin-dev` job on `main` does not print a notice |
| The `SERVICE_REPOS_READ_TOKEN` secret in each gitops-app (spec 098) | `cplat ship gitops pr` marks its PRs with `Service-ref: <owner>/<repo>@<branch>`; the gitops CI reads that branch's CRDs with this token (fine-grained, Contents: read on the service repos) and validates the Components against them. Without it a marked PR fails its check | `cplat doctor` in the gitops-app (a warning when missing) |
| The service is in the gitops-app's `services.yaml` | pin-dev pins only composed services; for services the generator cannot express, use an `external` entry ([ADR-029](adr/029-external-services.md)) | `/shared:status` in the gitops-app |
| Actions may open PRs in the gitops-app | pin-dev opens the pin PR | `gh api repos/<org>/<gitops>/actions/permissions/workflow` |
| Optional: a kube context | `cplat ship deploy --context <ctx>` also waits for Argo `Synced/Healthy` | `kubectl --context <ctx> -n argocd get applications` |

## Feedback loops

Eight loops bring what happens in runs and in running systems back as data or as deduplicated issues. They file and propose; you route issues in `/shared:triage` and approve specs.

| Loop | Signal | Lands in | Setup |
|---|---|---|---|
| [Run records](#run-records) (087, 099) | phases, CI rounds, escalations, tokens and cost of every run | the private run store | `cplat runs init <owner/name>` |
| [Agent quality](#agent-metrics) (089) | fix rounds, red CI, review findings, re-plans per agent, shape and model | the run store | none |
| [Weekly retro](#weekly-retro) (090) | the last complete week against the one before | a `Weekly retro` issue with evidence-checked spec proposals | store workflow, runner and two secrets |
| [Platform failures](#auto-filed-platform-issues) (088) | escalations with cause `platform`, `cplat` crashes | one issue per signature in `ika100/sdlc-foundry` | `cplat triage setup-labels` |
| [Smoke in dev](#smoke-in-dev) (091) | `(smoke)` criteria against the deployed service | the run record; a `smoke-failure` issue in the service repo | `expose:` and `hosts.dev` in `app.yaml` |
| [Firing alerts](adr/038-alert-poll-on-the-gitops-runner.md) (092) | alert rules of the `observability` addon and `ServiceDown` | an issue with an `env:` label in the owning repo | `ALERTS_TOKEN` in the gitops-app, self-hosted runner |
| Report an issue (`/shared:report-issue`) | anything a person or agent hits, secrets removed | an issue, filed after your OK | `gh` logged in |
| Triage (`/shared:triage`, spec 035) | new issues from all of the above | a spec, quick-task, fix-bug or reply | none |

## Run records

Every run is recorded as one JSON record in a private GitHub repo (spec 087, [ADR-032](adr/032-private-run-store.md)).

- **Setup:** `cplat runs init <owner/name>` creates the repo private (or checks an existing one) and prints `export CPLAT_RUNS_REPO=<owner/name>`. Put that line in the shell profile your Claude sessions read.
- **A record holds** kind, repo, spec, phases with durations, CI rounds, reruns, the escalation reason and cause, and the outcome. **It never holds** secrets (redacted), file contents or logs.
- **Offline:** without a store, or when it is unreachable, records wait in a local buffer (1000) and one warning line says so. The run itself is never affected. `cplat runs flush` writes the buffer; `cplat doctor` shows what is waiting.
- **Read it:** `cplat runs report [--json] [--since DAYS]`.
- **Why a `pr wait` ended:** its own record carries `pr_wait.result` (`green`, `merged`, `red`, `budget-refused`, `timeout`, `no-checks`, `closed`, `merge-failed` or `error`) with the failing or pending check names. The report and the weekly retro show the count per result and the 5 checks that fail most, and count a red result as `red-ci` instead of `failed`: red CI means the gate worked, not that the wait broke. Records from before this have no result and count as `unrecorded`.

### Token usage and cost

A record also holds a `usage` section (spec 099, [ADR-035](adr/035-token-usage-from-session-transcripts.md)): calls and tokens (input, output, cache read, cache write) and an estimated cost, in total and by phase, role and model. It is read from the local Claude Code session transcripts, so it needs Claude Code 2.1.132 or later and the machine that ran the session. Nothing but numbers and names of phases, roles and models is stored.

- **Read it:** `cplat runs usage <run_id>` (or `--session <id>`, `--json`); `cplat runs report` adds usage per kind.
- **As reported:** output tokens are shown as the transcripts report them, so the output cost is a lower bound. Costs are estimates from the price table in the repo (its date is printed); a model without a price shows `unknown` and marks the cost incomplete.
- **Delivered vs. gate-failed:** a run is delivered when its outcome is `done` and neither gate (`cplat runs gate acceptance|security`, set by `/svc:build`) failed. A `done` run with a failed gate counts as gate-failed, next to the failed, escalated and abandoned runs.
- **Benchmark:** `cplat runs benchmark <quick-task|build|ship>` runs one fixed task headless against `ika100/todo-api` at a pinned revision (`build` is two phases: `/svc:plan 900`, then `/svc:build 900`) and appends a `benchmark` record; `cplat runs report --benchmarks` shows median tokens and cost per workflow and platform version. `ship` merges and deploys to the sample's dev, so the command resets the sample repo to the pinned revision afterwards (force-push of its main branch); `--reset-first` repairs a sample left in a bad state by an earlier failed reset. Benchmark runs never count in the normal report. Each workflow reuses one clone, `~/.local/state/sdlc-foundry/runs/benchmark/<workflow>`, reset before every run; Claude Code ignores a repo's permission rules in an untrusted folder, so trust it once (`cd` there, run `claude`, accept the dialog) — the benchmark refuses to start until you have. A run counts as `done` only when it produced its result: a new open PR for `quick-task` and `build`, a new merged PR for `ship`; otherwise it is `failed` and `result_check` says why. The reset leaves PRs, branches and tags that existed before the run alone.

### Agent metrics

A build record also says how each agent did (spec 089), per agent, shape and model: `cplat runs report --agents [--json] [--since DAYS] [--repo R] [--agent NAME] [--shape SHAPE]`.

- **What is counted, against whom:**
  - coder: hand-backs (`fix rounds` by cause lint/type, test, ci, verification), red PR CI rounds (`cplat ship land` records them, always against the coder), review findings (first pass and after a fix) and refused acceptance-test diffs;
  - architect: files outside the plan, merge conflicts (and the share that was resolved) and re-plans;
  - quality: refused test diffs; tester: untraced criteria and tests that failed for the wrong reason.
- **Not measured:** a metric whose point the run never reached (an escalated Phase 0, a ship that never built, a record from before spec 089) is `n/a`, never 0, and is left out of the averages.
- **`few runs`** marks a row with fewer than 5 runs: do not read a trend into it.
- **Releases:** `--by-version` splits every row by platform version, versions side by side, so you can compare before and after a release.
- **Incomplete:** a recording call that failed or was malformed never stops the build; it marks the run `incomplete` (counted in the row) and the report still shows what was recorded.

### Weekly retro

Every Monday the platform looks back at the last complete week and proposes what to build next (spec 090, [ADR-039](adr/039-weekly-retro-evidence-checked-proposals.md)).

- **Three steps, one directory:** `cplat retro --out DIR` builds the report (`report.json`, `report.md`, `prompt.md`), `cplat retro propose --dir DIR` lets headless Claude write `proposals.json`, `cplat retro post --dir DIR` checks and posts. A failed proposal step still posts the report with `Proposals: not generated (<reason>)`.
- **The report** covers ISO week Monday to Sunday UTC, every figure next to the week before: runs per kind and outcome, phase durations, CI rounds and reruns, escalations by cause with the top reasons, reruns by check, platform issues counted again in the week, and the per-agent metrics of spec 089.
- **Proposals are checked:** each cites evidence refs of the report with their exact values. A proposal without a matching ref, with a bad format, or over the limit (5 specs, 3 prompt changes) is refused and counted. A finding an open spec or issue already covers is shown as `amends spec NNN` or `see #N`.
- **Public and private:** the issue `Weekly retro <week>` in `ika100/sdlc-foundry` has counts and placeholders only. A leak check stops the post if a repo, spec or store name remains. The full report goes to `retros/<week>.md` and `.json` in the run store. An earlier week's open retro issue is commented on and closed.
- **Setup:** `cplat runs init <owner/name>` adds `.github/workflows/cplat-retro.yml` to the store (it needs `gh auth refresh -h github.com -s workflow` once). Give the store repo a self-hosted runner (variable `CI_RUNNER`) and the secrets `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) and `RETRO_GH_TOKEN` (fine-grained: Issues read/write on the platform repo, Contents read/write on the store). `cplat doctor` warns about what is missing.
- **By hand:** `cplat retro` prints the report and writes nothing; `cplat retro --week 2026-W42` picks another complete week.

## Auto-filed platform issues

When a run stops because the platform itself misbehaves, the failure is filed as an issue in `ika100/sdlc-foundry` (spec 088, [ADR-033](adr/033-auto-filed-issues-with-signatures.md)).

- **What is filed:** an escalation with `--cause platform`, and a crash (stack trace) of any `cplat` command inside a recorded run. **Never filed:** causes `code`, `decision`, `environment` and `unknown`, and crashes outside a recorded run (those print the `/shared:report-issue` hint).
- **One issue per failure:** the body has a `Signature:` line. A repeat adds a +1 comment (occurrence number, date, platform version, shape, run id) to the oldest open issue. After the issue was closed, a repeat files a new issue that says `Seen again after #<n> was closed`, unless the closed one is labelled `wontfix`: then nothing is filed and the run record notes `suppressed by #<n>`.
- **Redaction:** tokens, passwords, e-mail addresses and home paths are removed, and your repo, spec and branch are replaced by `<repo>`, `<spec>` and `<branch>`. The issue names the run id but never links the private run store.
- **Cap:** at most 10 new issues per 24 h per machine. +1 comments are not capped.
- **Offline:** if filing fails (`gh` missing or not logged in, no network) or the cap is reached, the escalation still completes with the same exit status, prints `not filed: <reason>`, and the filing is retried at the next `cplat runs flush`.
- **Off switch:** `CPLAT_AUTO_ISSUES=off` sends nothing and prints the draft instead. `CPLAT_FEEDBACK_REPO=<owner/name>` files in another repo. Run `cplat triage setup-labels` once so the `auto-filed` label exists.

## Smoke in dev

The deploy step needs the product's kube context to check Argo, run smoke and read the image digest. Pass `--context`, or set it once: `export CPLAT_KUBE_CONTEXT=<context>` or `kube_context: <context>` in `.platform-settings.yml` or `~/.config/sdlc-foundry/settings.yml`. Without one, smoke is reported as not run.

After dev is healthy, `cplat ship deploy` checks the spec in dev (spec 091, [ADR-040](adr/040-smoke-tests-against-a-deployed-environment.md)).

- **The marker:** end a criterion line with `(smoke)` when its behaviour is observable through the service's public URL. The tester writes a smoke-tagged test for it (`cplat spec trace` reports `smoke: no smoke-tagged test` until there is one).
- **The recipe:** every deployable template has `devbox run smoke`. It runs only the smoke-tagged tests against `SMOKE_BASE_URL` (exit 2 without it) and prints `PASS|FAIL|SKIP  <path>::<name>` lines, then `smoke: <p> passed, <f> failed, <s> skipped` (or `0 smoke tests`). Web repos use standard Playwright tests in `e2e/` tagged `@smoke`.
- **Retry and limit:** a red run is repeated once after 30 s; a pass on retry is reported as `passed on retry`. A run is killed after 600 s and counts as red.
- **Red:** deploy escalates with cause `code` (`smoke red in dev: <n> failing (<spec>)`), prints the failing tests and the last 60 output lines (secrets redacted), and files one `smoke-failure` issue in the service repo (one issue per failing set, a repeat adds a +1 comment). Dev is not rolled back. `/svc:ship <spec>` resumes with smoke only.
- **Not run:** no `--context`, a service not exposed in dev, an unreachable URL, a repo without the recipe or without a gitops-app link. Deploy finishes `done`, never reports "passed", and lists the unchecked `(smoke)` criteria.
- **The record:** the run record has a `smoke` section (outcome, counts, duration, retry, per-criterion result, failing tests, filed issue).
- **By hand:** `cplat smoke run [--env dev] [--base-url URL] [--spec SPEC] [--json]` in a service repo (exit 0 passed, 1 red, 3 not run); it files no issue.
- **The dev URL** comes from the linked gitops-app: the service must have `expose:` and a `hosts.dev` template in `app.yaml`. An optional `urls.dev` in `app.yaml` overrides it (`{host}` is the host from `hosts`). For `*.localhost` hosts the port is `LOCAL_HTTP_PORT`, default 8088.

## Deploy gate

A deploy counts only after every step below. Each step is enforced by `code` (a test pins it) or by an `agent` (a rule in a prompt, no test). Spec 105 added the digest, the failure classes and the environment retries.

| step | enforced by | check | test |
|---|---|---|---|
| pin confirmed | code | the pin PR for the merge commit is merged and its pin-dev run is not red | `test_deploy_fails_at_once_on_a_red_pin_dev_run` |
| Argo healthy | code | Argo CD runs the pinned build and reports Synced/Healthy | `test_argo_old_image_is_waiting_not_healthy` |
| smoke | code | the spec's smoke tests pass in dev and the record names the image digest the cluster runs | `test_deploy_runs_every_smoke_test_against_the_published_dev_url_ac_091_6`, `test_the_smoke_record_holds_the_digest_dev_runs_ac_105_1` |
| retry | code | an application failure is retried once, an environment failure up to three times in total, 30 s apart | `test_an_application_failure_keeps_the_single_retry_ac_105_5`, `test_an_environment_failure_is_tried_three_times_30_seconds_apart_ac_105_5` |
| escalation | code | a red smoke escalates: cause `code` with an issue, cause `environment` without one | `test_an_application_failure_still_escalates_with_cause_code_ac_105_5`, `test_a_persistent_environment_failure_escalates_without_an_issue_ac_105_5` |
| digest match | code | staging is pinned only while the registry digest of the tag equals the smoked digest | `test_a_changed_digest_pins_nothing_and_says_so_ac_105_2` |
| promotion | code | a smoke that was not run is reported `NOT VERIFIED` and promotes nothing | `test_a_not_run_smoke_reports_not_verified_and_promotes_nothing_ac_105_6`, `test_a_dev_smoke_that_was_not_run_promotes_nothing_ac_093_3` |

A replay of `cplat ship deploy` skips the dev smoke only when the record holds a pass for the digest dev runs now (`test_a_replay_with_the_same_digest_does_not_smoke_dev_again_ac_105_7`). `cplat promote … staging prod` prints the checked digest and flags `digest differs from what staging runs`.

### Prod runs what staging tested

`cplat promote <svc> staging prod` compares the registry digest of the `sha-<40>` image staging runs with the release `X.Y.Z` image (spec 106) before it writes anything, for all services first. Equal digests: the promotion goes on and the evidence and the PR body say `image digest: <digest> (same in staging and prod)`. A mismatch refuses with "prod would not run what staging tested", both tags and both digests, and the fix: re-publish the release from the tested image (the release job re-tags the `sha-<40>` image instead of rebuilding it), or promote the release whose image is the staging one. A missing tag, a failed lookup (`gh auth refresh -s read:packages`) and a staging tag that is not a `sha-<40>` build refuse too.

`--dry-run` prints `staging: <tag> <digest>`, `prod: <tag> <digest>` and `match` or `mismatch` per service (`data.digests` with `--json`); a mismatch exits 1. `--accept-digest-mismatch "<reason>"` (a sentence of 3 or more words ending in `.`, `!` or `?`) accepts a mismatch only, and is recorded in the output and the PR body. `--no-verify` skips the check and prints `image identity not verified (--no-verify)`.

## Budgets and repeated failures

Every unattended run tree shares one budget (spec 102, [ADR-043](adr/043-one-budget-per-run-tree.md)): wall-clock minutes, agent invocations (sessions and subagents), CI reruns and estimated cost. The outermost run owns it (`cplat headless`, `/app:ship`, or a ship or build started by hand); every ship, build and CI wait below it counts against the same budget.

| Limit | Per ship | Counted by |
|---|---|---|
| `minutes` | 180 | wall clock from the root's start, carried across resumes |
| `invocations` | 60 | each headless session, and each subagent (the shared plugin's `PreToolUse` hook runs `cplat budget gate --invocation`) |
| `reruns` | 6 | each CI rerun of `cplat ship land` and `cplat pr wait` |
| `cost` | $15 | estimated from the local transcripts (spec 099); `unknown` when a price is missing, then only the other three apply |

A root that covers several ships multiplies the defaults: `cplat headless "/svc:ship 102 103"` gets twice the limits, a product ship one set per repo in its plan. Change a limit with `--budget minutes=240` (repeatable, `off` turns one off) on `cplat headless`, `cplat ship start`, `cplat app-ship start` or `cplat runs begin`, or set `budget:` in `.platform-settings.yml` or `~/.config/sdlc-foundry/settings.yml`. `cplat budget show` prints the limits and what is used.

Limits are checked at safe points (before a session, a subagent or a CI rerun, at the end of a phase, before a product ship starts a repo). A run that hits one starts nothing new, escalates with cause `decision` and reason `budget exhausted: <limit>`, and stays resumable: run it again with a higher limit, and the usage continues from where it stopped. Running work is never killed, and no gate is skipped or counted as passed (`not run`).

A stage that fails twice in a row with the same error (timestamps, paths, ids, line numbers and durations removed) and no fewer failing checks stops with `no progress: <stage>`. Every escalation leaves a recovery snapshot in `<git dir>/cplat-recovery.json` (stage, a redacted excerpt, changed files, criteria, earlier attempts; never uploaded), and `cplat budget resume` shows which stages are still verified for the current HEAD, so a resumed run starts at the failing one. Run state (`cplat-ship.json`, the recovery snapshot) lives in the worktree's own git dir, so a run in one worktree never blocks or attaches to another checkout's session ([ADR-051](adr/051-run-state-is-per-worktree.md)).
## Change-aware validation in fix rounds

Inside a build or ship, fix rounds run only what the change can affect (spec 103, [ADR-044](adr/044-change-aware-validation-in-the-inner-loop.md)): `cplat validate run` plans every check of `devbox run ci` as `run`, `reused` or `skipped` and names the rule that decided it. A change to dependencies, the Dockerfile, CI, secrets or auth, a spec or an acceptance test (and per shape: the API contract or migrations of a service, a gitops-app's manifests, a web repo's routes or build config) runs the full suite and the security scan. A change that touches only documentation runs lint and the secret scan. A mapped change runs the tests of its criteria and its component's unit tests. Anything the rules cannot place runs everything. A passed check is reused only when its inputs are byte-for-byte unchanged, and only on this machine.

The final gate is never selective: before a PR is marked ready or landed, `devbox run ci` runs in full, and the PR's CI is unchanged. A check that the loop skipped or reused and the final gate then finds red is counted as a `miss` for its rule; `cplat runs report` shows the counts and misses per rule. The same holds for the red checks of the PR's CI (`cplat ship land` records them). `--full` (also as an argument of `/svc:build` and `/svc:ship`), `validation: full` in `.platform-settings.yml` or `CPLAT_VALIDATION=full` turn selection off. Every spec file under `docs/specs/` counts as a spec change, never as documentation; checks that never started because an earlier one was red are reported as `not started`. Java, Go and gitops-app repos have no test selector yet and always run everything.

## Live usage in Grafana (optional)

`cplat headless` and `cplat runs benchmark` can turn on Claude Code's own OpenTelemetry export for the sessions they start (spec 101), so tokens and estimated cost show up live, per run, model and day. The run store stays the system of record: phases, roles and the figures in `cplat runs report` always come from the transcripts.

- **Explicit endpoint:** `export CPLAT_OTLP_ENDPOINT=http://localhost:4318`, or `telemetry: {endpoint: …}` in `.platform-settings.yml` or `~/.config/sdlc-foundry/settings.yml`. It must be local (`localhost`, `127.x`, `::1`, `*.localhost`, a cluster `*.svc` name). A remote backend needs `telemetry: {allow_remote: true}` (or `CPLAT_OTLP_ALLOW_REMOTE=1`); without it the endpoint is refused with one line.
- **The observability addon:** when the product's gitops-app has `observability: {ui: lgtm}` and a kube context is set (`telemetry: {context: k3d-<app>-local}` or `CPLAT_KUBE_CONTEXT`), cplat port-forwards to the local Grafana stack for the session. The context is never guessed. Grafana gets a **Claude Code usage** dashboard: tokens and cost per run, per model, per day, and the coordinator's share.
- Nothing configured means telemetry stays off, with no output and no delay. An unreachable backend shows one warning and never changes the run's result.
- cplat forces every content switch off (`OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_DETAILS`, `OTEL_LOG_TOOL_CONTENT`, `OTEL_LOG_ASSISTANT_RESPONSES`, `OTEL_LOG_RAW_API_BODIES`), even if your shell sets them. Only metrics are exported (no events, logs or traces): counts, model, cost, the attributes `cplat.run_id`, `cplat.kind`, `cplat.repo` and `cplat.platform_version`, and the attributes Claude Code always attaches without a switch (`user.id`, `user.email`, `organization.id`, `terminal.type`). Every attribute that has a switch (session id, account UUID, version, entrypoint, repository) is turned off, and your own `OTEL_*` variables (endpoints, headers, exporters) do not reach the session. Because the always-attached identity leaves the machine, the endpoint must be local unless `allow_remote` is set.
- After a run with telemetry, the record gets `usage.otel`: the OTel totals queried by run id and their difference from the transcript totals per token type. Use it to check the transcript counting.

## What an unattended session can reach

Sessions that cplat starts (`cplat headless`, `cplat runs benchmark`, the weekly retro) load only the repo's own MCP servers: `--strict-mcp-config` with the repo's `.mcp.json` (none when there is none), and claude.ai connectors are off (`disableClaudeAiConnectors`). Your personal MCP servers and connectors (mail, calendar, drive, home automation, browser) are never available to a run nobody watches, and the session starts with less context (spec 111). A repo that needs one more server declares it in `.platform-settings.yml`: `headless: {mcp_config: <file>}`. Interactive sessions are unchanged.

## Watching runs live (optional)

To see running sessions, their status and a way to step in while a run works, you can use [dot-agent-deck](agent-deck.md) next to the platform. It is optional and only shows activity: outcomes, costs and gates still come from the run store, CI and the ship gates.

## Safety on the free plan

`main` cannot be protected on GitHub Free for private repos, so a human with write access can still push to it. Unattended runs cannot: the allowlist refuses `git push origin main`. Every automated merge (feature PRs through `cplat ship land`, pin PRs through `pin-dev`) happens only after its checks passed. A merge happens without a human review of the PR. The approved spec, the acceptance tests written before the code, and the reviewer's `verification.md` (required for `done`, spec 068) are the review. Use `/svc:ship <NNN> --no-merge` to read the PR yourself first.
