---
spec_id: 092-firing-alerts-become-issues-in-the
spec_hash: 2c008cf4e568
summary: cplat alerts poll (run every 15 min on the gitops-app's self-hosted runner at its pinned platform version) evaluates app.yaml rules, the built-in ServiceDown and an optional Alertmanager per environment, and files 088-convention issues in the owning service repo (fallback gitops repo) with fired-again, resolve/close, reopen within 7 days, wontfix suppression, a cap of 10 per poll and an "alert poll is failing" issue; render validates rules, doctor warns about ALERTS_TOKEN
tasks:
- id: t1
  title: autoissue tracker additions (token, open_issues, close, reopen, ensure_labels)
  files: [scripts/cplat/autoissue.py]
  covers: [AC-092.9, AC-092.13, AC-092.20, AC-092.22]
  parallel_safe: true
  depends_on: []
  done: false
- id: t2
  title: render.py validates alert rules and alert settings in app.yaml
  files: [templates/gitops-app/scripts/render.py, "templates/gitops-app/applications/{{ app_name }}/app.yaml.jinja"]
  covers: [AC-092.4, AC-092.6]
  parallel_safe: true
  depends_on: []
  done: false
- id: t3
  title: alertsources (config, skip reasons, rules + ServiceDown, Prometheus and Alertmanager, label mapping)
  files: [scripts/cplat/alertsources.py]
  covers: [AC-092.2, AC-092.4, AC-092.5, AC-092.8, AC-092.16, AC-092.19, AC-092.20, AC-092.23, AC-092.24]
  parallel_safe: true
  depends_on: []
  done: false
- id: t4
  title: gitops-app alert workflow, alert-poll.sh, devbox recipe, lgtm Prometheus port
  files: [templates/gitops-app/.github/workflows/alerts.yml, templates/gitops-app/scripts/alert-poll.sh, templates/gitops-app/devbox.json, templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/.gitignore]
  covers: [AC-092.1, AC-092.3, AC-092.17, AC-092.18, AC-092.19]
  parallel_safe: true
  depends_on: []
  done: false
- id: t5
  title: doctor warns when ALERTS_TOKEN is missing
  files: [scripts/cplat/doctor.py]
  covers: [AC-092.25]
  parallel_safe: true
  depends_on: []
  done: false
- id: t6
  title: docs for alert issues (gitops-app CLAUDE.md and README, self-hosted runners, CHANGELOG)
  files: [templates/gitops-app/CLAUDE.md.jinja, templates/gitops-app/README.md.jinja, docs/self-hosted-runners.md, docs/CHANGELOG.md]
  covers: [AC-092.1, AC-092.3, AC-092.25]
  parallel_safe: true
  depends_on: []
  done: false
- id: t7
  title: alertissues lifecycle (title/body/comments, routing, dedupe, fired again, reopen, cap, resolve/close, dry run)
  files: [scripts/cplat/alertissues.py, tests/cplat/conftest.py]
  covers: [AC-092.8, AC-092.9, AC-092.10, AC-092.11, AC-092.13, AC-092.15, AC-092.16, AC-092.18, AC-092.20, AC-092.21, AC-092.22, AC-092.23, AC-092.24]
  parallel_safe: true
  depends_on: [t1, t3]
  done: false
- id: t8
  title: cplat alerts poll (per-app loop, poll-failure state, failing-poll issue, summary, exit code)
  files: [scripts/cplat/alerts.py, scripts/cplat/cplat.py]
  covers: [AC-092.2, AC-092.9, AC-092.16, AC-092.17, AC-092.18, AC-092.19]
  parallel_safe: true
  depends_on: [t3, t7]
  done: false
human_steps:
- "Per gitops-app repo: create a fine-grained token with Issues: read and write on every service repo in services.yaml and run `gh secret set ALERTS_TOKEN -R <owner>/<gitops-repo>` (cplat doctor warns until then)"
- "With `exportTo` + `querySecret`: grant the self-hosted runner's ServiceAccount `get` on that one Secret (a Role with resourceNames), or set the repo secret ALERTS_QUERY_AUTHORIZATION instead"
- "Rerun `devbox run cluster-up` in existing local clusters with `ui: lgtm` so the lgtm Service exposes Prometheus on 9090"
---

The contract for every task is [design.md](design.md). ADR: [036](../../adr/036-alert-poll-on-the-gitops-runner.md)
(the number may change at merge if a parallel spec takes it first). No test may reach GitHub, Prometheus,
Alertmanager or a cluster:
- GitHub access goes through `alertissues.tracker()` / `autoissue.gh()`.
- Metrics and alerts go through `alertsources.http_get()`.
- Secrets go through `alertsources.kubectl()`.
- The clock is `autoissue.now()`.

Acceptance tests live in `tests/cplat/` and name the criteria (`AC-092.n`) in their docstrings, as
`tests/cplat/test_autoissue.py` does. Coders do not edit them. No plugin or marketplace version bumps.

## t1 — autoissue tracker additions (token, open_issues, close, reopen, ensure_labels)

**Files:** scripts/cplat/autoissue.py
**Covers:** AC-092.9, AC-092.13, AC-092.20, AC-092.22
**Goal:** `GhTracker` can write with a chosen token, list open issues by label, close, reopen and create arbitrary
labels. Every 088 behaviour stays the same (design.md "Tracker additions").

**Implementation notes:**
- `gh(args, *, input=None, timeout=10.0, token=None)`. With a token, the child env is `os.environ` plus
  `GH_TOKEN=token`, minus `GITHUB_TOKEN`. Without one, the call is exactly as today.
- `GhTracker.__init__(self, token=None)`. In every method, pass `token=` to `gh()` only when `self.token` is set, so
  088's fakes (no `token` parameter) still work. `_create_labels` passes it too.
- `open_issues` uses the REST list with comma-joined labels and `state=open`, drops pull requests, and reuses
  `_items` / `_to_issue`.
- `close` is `gh issue close N -R repo --reason completed`, `reopen` is `gh issue reopen N -R repo`. Both go through
  `_check`.
- `ensure_labels(repo, {name: (color, description)})` runs `gh label create` per label without `--force`. An exit
  whose stderr says `already exists` is success; anything else goes through `_check`.
- Docstring: name spec 092 as a user of these methods. Leave `Tracker`, `file()`, the ledger and `retry_filing`
  unchanged.

**Done when:** the t1 parts of the AC-092.9/.13/.20/.22 tests pass against a fake `gh`. They check that the token
reaches the env, the exact gh argument lists, and that "already exists" is ignored. `tests/cplat/test_autoissue.py`
and every other 088 test stay green.

## t2 — render.py validates alert rules and alert settings in app.yaml

**Files:** templates/gitops-app/scripts/render.py, templates/gitops-app/applications/{{ app_name }}/app.yaml.jinja
**Covers:** AC-092.4, AC-092.6
**Goal:** an invalid rule fails the render and the quality gate, naming the rule and the problem. A valid rule set
renders exactly the same manifests as before.

**Implementation notes:**
- Extend `validate_addons`'s observability block with the checks and messages of the table in design.md
  "app.yaml". Rules are numbered from 0, `<name>` is `no name` when it is absent, and a duplicate names its second
  occurrence.
- Also validate `alerts` (bool), `queryURL` / `alertmanagerURL` (http/https) and `querySecret`
  (`name` or `namespace/name`, DNS labels).
- No change to `collector_config` or any rendered file.
- Docstring: add the `rules` / `alerts` / `queryURL` / `querySecret` / `alertmanagerURL` keys to the app.yaml section.
- app.yaml.jinja comment block, plain text (this is a Jinja file: no `{{`):
  - a commented example of `alerts`, one rule, `queryURL`, `querySecret` and `alertmanagerURL`
  - the built-in `ServiceDown`
  - that issues go to the service's `repo` (or this repo), and that rules on OTLP-pushed metrics need the environment
    from `target_info`

**Done when:** the AC-092.6 tests pass: each invalid case gives exit 1, the rule name and the problem, and
`render.py --check` is red. A valid rule set gives exit 0 and an unchanged tree (AC-092.4 declaration part).
`test_addons.py` stays green.

## t3 — alertsources (config, skip reasons, rules + ServiceDown, Prometheus and Alertmanager, label mapping)

**Files:** scripts/cplat/alertsources.py
**Covers:** AC-092.2, AC-092.4, AC-092.5, AC-092.8, AC-092.16, AC-092.19, AC-092.20, AC-092.23, AC-092.24
**Goal:** `load_app` and `collect` from design.md "Sources": a list of mapped `Alert`s plus `SourceError`s, with no
GitHub access.

**Implementation notes:**
- `load_app` reads app.yaml and services.yaml with `yaml.safe_load`:
  - `envs` = the environments where any service runs, in `ENVS` order
  - the skip reasons in table order
  - rule validation with the same messages as render.py (`SourceError("applications/<app>/app.yaml", msg)`)
  - `querySecret` resolved to `namespace/name`
  - the URLs: lgtm → `$ALERTS_PROMETHEUS_URL` or `LGTM_QUERY_URL`; exportTo → `queryURL`
- Built-in `ServiceDown` applies per service with `metrics` and per environment in its `environments` (default
  `[dev]`), only when no declared rule has that name. Use the exact PromQL of design.md, with `.` in names
  regex-escaped.
- `http_get` uses `urllib.request` and never raises: `(0, reason)` on a transport error. `kubectl` uses `subprocess`
  and never raises.
- `authorization`: `ALERTS_QUERY_AUTHORIZATION` wins. Otherwise
  `kubectl get secret <name> -n <ns> -o jsonpath={.data.AUTHORIZATION}`, base64-decoded. A failure is a `SourceError`.
  It is sent to Prometheus and Alertmanager.
- `collect`:
  - each rule is one instant query; a non-empty vector fires
  - series map as in "Mapping", and one `Alert` per signature collects up to 10 sorted label sets
  - Alertmanager is read when `alertmanager_url` is set, with severity coercion to `warning`
  - a failing endpoint gives one `SourceError` and is not retried within the run
- The error reasons are those of the table. URLs go through `feedback.redact`.
- Rule alerts get `started_at = now`; Alertmanager alerts get `startsAt` (ISO, `Z` accepted).

**Done when:** with a fake `http_get` / `kubectl`, the module-level tests pass:
- the skip reasons (AC-092.2, .19)
- a firing and a silent rule per environment and service (AC-092.4, .24)
- `ServiceDown` per service/env, and suppressed by a declared rule of that name (AC-092.5)
- the lgtm and exportTo URLs, and the credential header from the env or the Secret (AC-092.19)
- Alertmanager alerts and their severity fallback (AC-092.23)
- mapping by `service` / `job` / `ns/name`, and the unmapped notes (AC-092.8, .20)
- unreachable and 401 endpoints as `SourceError`s (AC-092.16)

## t4 — gitops-app alert workflow, alert-poll.sh, devbox recipe, lgtm Prometheus port

**Files:** templates/gitops-app/.github/workflows/alerts.yml, templates/gitops-app/scripts/alert-poll.sh, templates/gitops-app/devbox.json, templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/.gitignore
**Covers:** AC-092.1, AC-092.3, AC-092.17, AC-092.18, AC-092.19
**Goal:** a generated or updated gitops-app repo has the 15-minute poll, which only ever runs on the self-hosted
runner, can be started by hand with `dry_run`, and carries the poll state from run to run.

**Implementation notes:**
- `alerts.yml` as in design.md "Workflow". The file is copied verbatim (no `.jinja`), so `${{ }}` stays unescaped.
  Pin `actions/checkout` to the SHA `ci.yml` uses, and `actions/upload-artifact` to
  `ea165f8d65b6e75b540449e92b4886f43607fa02 # v4` (already used by the service templates). It has no `ubuntu-latest`
  anywhere.
- `scripts/alert-poll.sh`: `set -euo pipefail`, the platform fetch/caching of `spec-check.sh`, the `ALERTS_PLATFORM`
  override, the "predates 092" exit 0 with summary, then `exec uv run --quiet … alerts poll --repo-dir .` plus
  `--dry-run` when `ALERTS_DRY_RUN` is set.
- `devbox.json`: the recipe `"alert-poll": "bash scripts/alert-poll.sh"`.
- `.gitignore`: `.alert-poll/`.
- `local-cluster.sh`: in the lgtm Deployment add the container port `{name: prometheus, containerPort: 9090}`, and in
  the Service `{name: prometheus, port: 9090, targetPort: prometheus}`.
- Keep `copier.yml` unchanged: the workflow and the script must not be in `_skip_if_exists`, so
  `/shared:update-service` delivers them.

**Done when:** the template tests for AC-092.1 and .3 pass:
- a copier copy of the template has `alerts.yml` with cron `*/15 * * * *` and `workflow_dispatch` input `dry_run`
- `runs-on: ${{ vars.CI_RUNNER }}` with `if: vars.CI_RUNNER != ''`
- the run name and job name name the self-hosted runner
- neither file is skipped on update

Also the artifact step is skipped on a dry run (AC-092.17/.18 workflow part), and `alert-poll.sh` runs a local
platform through `ALERTS_PLATFORM`. `test_cluster_ports.py`, `devbox run validate` and the pinned-Actions check stay
green.

## t5 — doctor warns when ALERTS_TOKEN is missing

**Files:** scripts/cplat/doctor.py
**Covers:** AC-092.25
**Goal:** `cplat doctor` in a gitops-app with the observability addon and a service `repo` warns when the repo secret
`ALERTS_TOKEN` is missing, and gives the fix command.

**Implementation notes:**
- `ALERTS_TOKEN_FIX` and `check_alerts_token(repo)` as in design.md "Doctor", modelled on
  `check_service_repos_token`: shape via `detect-shape.sh`, and the secret list via `ship.gh(["secret", "list", "--json", "name"], cwd=repo, check=False)`.
- No warning without the addon, with `alerts: false`, without any service `repo`, or with the secret set.
- Add it to `run_checks` after `check_service_repos_token`.

**Done when:** the AC-092.25 tests pass with a mocked `ship.gh` / shape (as in `tests/cplat/test_update_doctor.py`):
a warning with `gh secret set ALERTS_TOKEN -R <slug>` when the secret is missing, and none when it is set or the addon
is absent. The existing doctor tests stay green.

## t6 — docs for alert issues (gitops-app CLAUDE.md and README, self-hosted runners, CHANGELOG)

**Files:** templates/gitops-app/CLAUDE.md.jinja, templates/gitops-app/README.md.jinja, docs/self-hosted-runners.md, docs/CHANGELOG.md
**Covers:** AC-092.1, AC-092.3, AC-092.25
**Goal:** operators know the poll exists, what it needs (self-hosted runner, `ALERTS_TOKEN`, Prometheus reachable),
how to declare rules, and how to dry-run it.

**Implementation notes:**
- The gitops-app `CLAUDE.md.jinja` and `README.md.jinja` get a short "Alert issues (spec 092)" section:
  - the 15-minute poll on `CI_RUNNER`, which never runs on GitHub-hosted runners
  - `gh workflow run alerts.yml -f dry_run=true`
  - rules under the observability addon, `ServiceDown`, `alerts: false`
  - where issues land, `ALERTS_TOKEN`, `ALERTS_QUERY_AUTHORIZATION`, `ALERTS_PROMETHEUS_URL`
  - that every issue goes through `/shared:triage`

  These are Jinja files: write any `${{ … }}` as `${{ '{{' }} … {{ '}}' }}`, or avoid it.
- `docs/self-hosted-runners.md`: the runner must reach the query API (`lgtm.observability.svc:9090` in-cluster). For
  `querySecret`, the ServiceAccount needs `get` on that Secret.
- `docs/CHANGELOG.md`, one bullet under `## [Unreleased]` in the style of the 088 entry:
  **Feature (092): firing alerts become issues in the owning repo.** [ADR-036](adr/036-alert-poll-on-the-gitops-runner.md). Sub-bullets:
  - the poll and the runner requirement
  - rules in app.yaml and `ServiceDown`
  - the 088 convention with `env:<env>`, fired again / resolved / closed while untriaged / reopen within 7 days, and
    `wontfix`
  - the cap of 10 per poll and the summary issue
  - the "alert poll is failing" issue
  - `ALERTS_TOKEN` and the doctor warning
  - run `/shared:update-service` in gitops-app repos

**Done when:** `devbox run validate` and the Markdown link check pass, and a copier copy of the gitops-app template
renders both Jinja files.

## t7 — alertissues lifecycle (title/body/comments, routing, dedupe, fired again, reopen, cap, resolve/close, dry run)

**Files:** scripts/cplat/alertissues.py, tests/cplat/conftest.py
**Covers:** AC-092.8, AC-092.9, AC-092.10, AC-092.11, AC-092.13, AC-092.15, AC-092.16, AC-092.18, AC-092.20, AC-092.21, AC-092.22, AC-092.23, AC-092.24
**Goal:** `reconcile()` from design.md "Issues": every GitHub action for one app's poll, exactly as the contract states,
and nothing sent in a dry run.

**Implementation notes:**
- `title`, `render_body`, `render_fired_again` and `render_resolved` produce the exact text of the contract:
  - `autoissue.scrub` on every piece, and the label and annotation fences via `autoissue._fence`
  - the Markdown-neutral replacement in the list values
  - one `Signature:` line, last
- `tracker(gitops_repo)`: a router over `GhTracker()` and `GhTracker(token=$ALERTS_TOKEN)`, reading the env at call
  time.
- The `reconcile` steps 1–7 in order:
  - the "last poll comment" helper (last comment starting with `RESOLVED` / `FIRED_AGAIN`)
  - the occurrence count
  - `NO_ACCESS` rerouting at lookup, create, comment and reopen
  - the ensure_labels set once per repo and poll
- Cap: `CAP_PER_POLL` new issues in severity order, then oldest first. The `AlertsDeferred` summary issue is filed,
  or its open issue gets a comment.
- Resolve only when `resolve=True`. It is scoped by the `- application: <app> (<gitops_repo>)` line. Close only with
  `triage`, and never comment twice.
- Every tracker call is wrapped. `TrackerError`s that are not `NO_ACCESS` go to `errors`, and `reconcile` never
  raises.
- `conftest.py`, in the existing autouse fixture: replace `alertissues.tracker` with a factory whose tracker raises
  `TrackerError("tests never call GitHub")` on every method. Replace `alertsources.http_get` with one returning
  `(0, "tests never call the network")`, and `alertsources.kubectl` with one returning `(1, "", "tests never call kubectl")`.
  Unset `ALERTS_TOKEN`, `ALERTS_QUERY_AUTHORIZATION`, `ALERTS_PROMETHEUS_URL` and `GITHUB_STEP_SUMMARY`. Import
  inside the fixture.

**Done when:** with a fake tracker and clock, the module-level tests pass:
- title, labels incl. `env:<env>`, body sections and the signature (AC-092.20, .24)
- the unmapped note and the gitops fallback (AC-092.8)
- rerouting on 403/404 with the Intended repo section (AC-092.9)
- redaction and quoted labels (AC-092.10)
- no comment while firing (AC-092.11)
- fired again with occurrence numbers (AC-092.21)
- resolve and close only with `triage` (AC-092.13)
- reopen within 7 days, `wontfix` suppressed, and Seen again (AC-092.22)
- 10 most severe plus the summary issue or comment (AC-092.15)
- `resolve=False` closes nothing (AC-092.16)
- dry-run lines with no write calls (AC-092.18)
- Alertmanager alerts handled like rule alerts (AC-092.23)

## t8 — cplat alerts poll (per-app loop, poll-failure state, failing-poll issue, summary, exit code)

**Files:** scripts/cplat/alerts.py, scripts/cplat/cplat.py
**Covers:** AC-092.2, AC-092.9, AC-092.16, AC-092.17, AC-092.18, AC-092.19
**Goal:** `cplat alerts poll` as in design.md "CLI": one red or green run per poll, with the step summary, the
poll-failure counter and the "alert poll is failing" issue.

**Implementation notes:**
- argparse `alerts poll` with `--repo-dir`, `--app`, `--gitops-repo`, `--state-file`, `--dry-run`. The
  `--gitops-repo` fallback is `$GITHUB_REPOSITORY`, then `.copier-answers.yml`.
- `poll()` follows per-app steps 1–6:
  - skipped apps make no network or GitHub call
  - the state is loaded lazily, once, through `autoissue.gh` (artifact list + `gh run download`)
  - the counter per app, with the `AlertPollFailing` alert at `failures >= 3`
  - `reconcile(..., resolve=not src_errors and state_loaded)`
- The output lines of the contract go to stdout, and the same lines go to `$GITHUB_STEP_SUMMARY` under
  `## Alert poll` when it is set.
- Exit 1 on source errors, GitHub errors or rerouting. The state file is written only when the run is not a dry run
  and the state loaded. An unexpected exception is caught in `main` (exit 1, no state written).
- `cplat.py`: `"alerts": "alerts"` in `COMMANDS` and the docstring line
  `cplat.py alerts poll [--dry-run] [--app APP]   firing alerts become issues (spec 092; run by the gitops-app's alerts workflow)`.

**Done when:** the CLI tests pass through `alerts.main([...])` with fake sources and tracker:
- skip lines and no calls (AC-092.2, .19)
- exit 1 plus the `ERROR:` line and "no issue was resolved or closed" on an unreachable or refused endpoint
  (AC-092.16)
- the third failure in a row files or comments the poll-failing issue, and the next success resolves it (AC-092.17)
- `--dry-run` prints `DRY RUN:` lines, makes no write calls and writes no state (AC-092.18)
- exit 1 after a reroute (AC-092.9)
- the step summary is written

`cplat --help` lists `alerts`.
