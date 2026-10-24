# Design — 092 Firing alerts become issues in the owning repo

## Decisions

- **The poll is a cplat command, run by the gitops-app at its pinned platform version.** The command is
  `cplat alerts poll`, in `scripts/cplat/alerts.py`. The template's `scripts/alert-poll.sh` fetches the platform at
  `.platform-version`'s `ref`, as `scripts/spec-check.sh` already does, and runs `uv run cplat.py alerts poll`. So the
  poll imports `autoissue` (088) itself: one signature function, one `scrub`, one `GhTracker`, no copy in the template.
  ADR: [docs/adr/035-alert-poll-on-the-gitops-runner.md](../../adr/035-alert-poll-on-the-gitops-runner.md). The number
  035 is tentative: parallel specs 090/091/094/095 may also add ADRs, so it may be renumbered at merge to the next free
  number on `origin/main`.
- **A dedicated lifecycle module, not `autoissue.file()`.** `file()` comments on every repeat and offers no
  resolve, close or reopen. 092 needs those: no comment while still firing (AC-092.11), "fired again" only after a
  resolved comment (AC-092.21), resolve and close (AC-092.13), reopen within 7 days (AC-092.22), a cap per poll with a
  summary issue (AC-092.15), and routing per service. 092 reuses `autoissue.raw_signature`, `scrub`, `Issue`,
  `TrackerError`, `GhTracker`, `gh`, `now`, `BASE_LABELS`, `KIND_LABELS` and `EXTRA_LABELS`. `file()`, the cap ledger
  and `runs.filed` are never called, so nothing goes to the run store (non-goal).
- **`autoissue.py` gets additive changes only** (t1): an optional `token` on `gh()` and `GhTracker`, and four new
  `GhTracker` methods (`open_issues`, `close`, `reopen`, `ensure_labels`). `Tracker`, `file()` and every 088 code path
  keep their behaviour. `GhTracker` passes `token=` to `gh()` only when it is set, so 088's fake `gh` functions, which
  take no `token`, keep working.
- **Three modules, one job each:**
  - `alertsources.py` reads app.yaml and services.yaml and asks Prometheus and Alertmanager. Its output is `Alert`s
    and `SourceError`s.
  - `alertissues.py` turns `Alert`s into GitHub actions.
  - `alerts.py` is the CLI: the loop over apps, poll-failure state, the step summary and the exit code.
- **Alert signatures are not normalised:** `autoissue.raw_signature("alert", app, environment, service, alert name)`
  (AC-092.20, AC-092.24). These are stable identifiers, and 088's normalisation would turn `svc-1` and `svc-2` into
  `svc-<n>`.
- **The lifecycle state is read back from GitHub.** The poll's comments start with fixed markers. The "last poll
  comment" is the last comment that starts with `**Resolved** at ` or `**Fired again** `. Only the number of failed
  polls in a row (AC-092.17) lives outside the issues. It is in `.alert-poll/state.json`, carried from run to run as
  the workflow artifact `alert-poll-state`. The poll loads the newest one through `gh`, and the workflow uploads it
  with `actions/upload-artifact`, kept for 3 days. That is the only extra API, because a cache needs an action pin
  the repo does not have yet. Run history cannot tell a poll failure (AC-092.16) from a routing failure (AC-092.9).
- **Self-hosted only** (AC-092.3). The poll job has `runs-on: ${{ vars.CI_RUNNER }}` and `if: vars.CI_RUNNER != ''`.
  There is no `ubuntu-latest` fallback and no hosted summary job: that would cost about 3000 billed minutes a month
  and fail on billing-locked accounts. Without a runner every job is skipped. The run's name and the skipped job's
  name both read `alert poll skipped: needs the self-hosted runner (set the CI_RUNNER variable)`. On GitHub's run
  summary page they are the only text.
- **Where the poll reads metrics (AC-092.19).** The runner is an ARC pod in the cluster
  (docs/self-hosted-runners.md), so it uses cluster DNS:
  - `ui: lgtm`: `$ALERTS_PROMETHEUS_URL` (a repo variable, for runners outside the cluster), else
    `http://lgtm.observability.svc:9090`. `local-cluster.sh` adds port 9090 (`prometheus`) to the lgtm container and
    Service.
  - `exportTo`: the addon's `queryURL`.
- **The query credential comes from `ALERTS_QUERY_AUTHORIZATION` (a repo secret) when set, else from the
  `querySecret` Kubernetes Secret.** Its key is `AUTHORIZATION`, the same convention as `headersSecret`. It is read with
  `kubectl`, which uses the runner pod's in-cluster ServiceAccount. A person grants the ServiceAccount `get` on that one
  Secret (human step).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/autoissue.py` | `gh(..., token=)`, `GhTracker(token=)`, `open_issues`, `close`, `reopen`, `ensure_labels` | changed (additive) |
| `scripts/cplat/alertsources.py` | app config, skip reasons, rules + built-in `ServiceDown`, Prometheus and Alertmanager clients (seams `http_get`, `kubectl`), label → service/repo/environment mapping, `Alert` | new |
| `scripts/cplat/alertissues.py` | title/body/comments, routing with fallback, dedupe, fired again, reopen, suppress, cap of 10 + summary issue, resolve/close, dry run; seam `tracker()` | new |
| `scripts/cplat/alerts.py` | `cplat alerts poll`: per app, poll-failure state and the "alert poll is failing" alert, output lines, `$GITHUB_STEP_SUMMARY`, exit code | new |
| `scripts/cplat/cplat.py` | `"alerts": "alerts"` in `COMMANDS`, a docstring line | changed |
| `scripts/cplat/doctor.py` | `check_alerts_token` (AC-092.25) | changed |
| `tests/cplat/conftest.py` | autouse: `alertissues.tracker`, `alertsources.http_get` and `alertsources.kubectl` fail loudly | changed |
| `templates/gitops-app/scripts/render.py` | validation of `alerts`, `rules`, `queryURL`, `querySecret`, `alertmanagerURL` (AC-092.6) | changed |
| `templates/gitops-app/.github/workflows/alerts.yml` | schedule `*/15`, dispatch with `dry_run`, self-hosted only, state artifact | new (copied, not Jinja) |
| `templates/gitops-app/scripts/alert-poll.sh` | fetch the platform at `.platform-version`, run `cplat alerts poll` | new |
| `templates/gitops-app/devbox.json` | recipe `alert-poll` | changed |
| `templates/gitops-app/scripts/local-cluster.sh` | lgtm port 9090 | changed |

## Contract

### app.yaml (AC-092.4, .6, .19, .23)

```yaml
addons:
  observability:
    ui: lgtm                    # or exportTo: https://… (existing, ADR-021)
    alerts: true                # default true; false: the poll skips this app (AC-092.2)
    rules:                      # optional
      - name: HighErrorRate     # required, non-empty string, unique within rules
        query: 'sum by (job, instance) (rate(http_server_requests_seconds_count{status=~"5.."}[5m])) > 1'   # required, non-empty string
        severity: warning       # required: critical | warning | info
        summary: More than one 5xx per second   # optional string
    queryURL: https://prom.example.com/api/prom   # optional; with exportTo the rule source (base of /api/v1/query)
    querySecret: obs-query      # optional: Secret `<name>` in <app>-<first env the addon runs in>, or `<namespace>/<name>`; key AUTHORIZATION
    alertmanagerURL: https://am.example.com        # optional; base of /api/v2/alerts
```

`render.py` (`validate_addons`, AC-092.6) fails with `ERROR: app.yaml: observability.rules[<i>] (<name>): <problem>`
and exit 1, so `devbox run quality` is red. `<name>` is the rule's name, or `no name`. `<i>` counts from 0. Problems:

| Condition | `<problem>` |
|---|---|
| `rules` is not a list, or an entry is not a mapping | `rules must be a list of {name, query, severity, summary}` (no `[<i>]` part for the list itself) |
| name missing, empty or not a string | `a rule needs a name` |
| severity not in the three | `severity '<value>' must be one of critical, warning, info` |
| same name twice (the second occurrence is named) | `the name '<name>' is used twice` |
| query missing, not a string, or blank | `query must be a non-empty string (PromQL)` |
| summary present and not a string | `summary must be a string` |

Other errors: `alerts` that is not a boolean → `app.yaml: observability.alerts must be true or false`; `queryURL` or
`alertmanagerURL` that is not http(s) → `app.yaml: observability.<key> must be an http(s) URL`; `querySecret` that is
not `name` or `namespace/name` with DNS labels → `app.yaml: observability.querySecret must be <name> or <namespace>/<name>`.
The rendered manifests do not change: rules are read only by the poll.

### Sources — `scripts/cplat/alertsources.py`

```python
SEVERITIES = ("critical", "warning", "info")            # also the sort order (AC-092.15)
ENVS = ("dev", "staging", "prod")
SERVICE_DOWN = "ServiceDown"
LGTM_QUERY_URL = "http://lgtm.observability.svc:9090"
TIMEOUT_S = 10.0

@dataclass
class Rule:
    name: str; query: str; severity: str; summary: str = ""
    service: str | None = None          # set only for built-ins: the series maps to this service ...
    environment: str | None = None      # ... and this environment, whatever its labels say

@dataclass
class Alert:
    app: str
    name: str                           # rule name, or Alertmanager `alertname`
    severity: str                       # one of SEVERITIES
    environment: str                    # dev | staging | prod | "unknown"
    service: str                        # services.yaml name; else the raw label value; "" if no label
    repo: str | None                    # services.yaml `repo` of the mapped service; None → the gitops-app repo
    started_at: datetime.datetime       # Alertmanager startsAt; for rules the poll time
    summary: str                        # rule summary, or the `summary` annotation
    source: str                         # "rule" | "alertmanager"
    query: str                          # the PromQL, or "Alertmanager <alertmanagerURL>"
    series: list[dict[str, str]]        # label sets, at most 10, sorted
    annotations: dict[str, str] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)   # AC-092.8 notes, see Mapping
    @property
    def signature(self) -> str: ...     # autoissue.raw_signature("alert", app, environment, service, name)

@dataclass
class AppConfig:
    app: str; app_dir: Path
    services: list[dict]                # services.yaml entries
    envs: list[str]                     # ENVS order, those where any service runs (= where the addon runs)
    rules: list[Rule]                   # declared + built-in ServiceDown
    prometheus_url: str | None
    alertmanager_url: str | None
    query_secret: str | None            # "namespace/name", namespace already resolved
    skip: str | None                    # reason the app is skipped, see below
    notes: list[str]                    # e.g. "rules not evaluated: queryURL is missing"

class SourceError(Exception):
    def __init__(self, endpoint: str, reason: str): ...   # str(e) == f"{endpoint}: {reason}"

def load_app(app_dir: Path) -> AppConfig: ...     # raises SourceError(f"applications/{app}/app.yaml", <render.py message>) on invalid rules
def http_get(url: str, *, headers: dict[str, str], timeout: float = TIMEOUT_S) -> tuple[int, str]: ...
    # seam; never raises: (status, body), or (0, "<reason>") when the endpoint cannot be reached
def kubectl(args: list[str], *, timeout: float = TIMEOUT_S) -> tuple[int, str, str]: ...   # seam; never raises
def authorization(cfg: AppConfig) -> str | None: ...   # $ALERTS_QUERY_AUTHORIZATION, else the Secret; SourceError if unreadable
def collect(cfg: AppConfig, *, now: datetime.datetime) -> tuple[list[Alert], list[SourceError]]: ...
```

`skip` (AC-092.2, AC-092.19), checked in this order:

| Condition | `skip` |
|---|---|
| no `observability` in `addons` | `app.yaml declares no observability addon` |
| `alerts: false` | `alerts: false in the observability addon` |
| no service runs in any environment | `no service runs in any environment` |
| `exportTo`, no `queryURL`, no `alertmanagerURL` | `exportTo is set but queryURL is missing` |
| neither `ui: lgtm` nor `exportTo`, no `alertmanagerURL` | `no metrics backend: set ui: lgtm, or exportTo with queryURL` |

With `exportTo` and `alertmanagerURL` but no `queryURL`, only Alertmanager is read. `notes` then holds
`rules not evaluated: queryURL is missing`.

The built-in rule (AC-092.5) applies when no declared rule is named `ServiceDown`. It is one `Rule` per service with a
`metrics` key and per environment in `envs_of(service)`. Severity is `critical`, summary
`No metrics target of <service> in <env> has been up for 5 minutes`, and the query is:

```promql
(max(max_over_time(up{instance=~"<svc>\\.<app>-<env>\\.svc(:[0-9]+)?"}[5m])) < 1)
  or absent_over_time(up{instance=~"<svc>\\.<app>-<env>\\.svc(:[0-9]+)?"}[5m])
```

The collector scrapes `<svc>.<app>-<env>.svc:80` (render.py `collector_config`), and OTLP carries that target as
`instance`.

Prometheus: `GET <base>/api/v1/query?query=<urlencoded>`, with header `Authorization: <value>` when there is a
credential. A rule fires when `data.result` is non-empty. Every series is mapped. Series that map to the same signature
form one `Alert`. Alertmanager: `GET <base>/api/v2/alerts?active=true&silenced=false&inhibited=false`. Each entry with
`status.state == "active"` (or no status) becomes an alert with:
- `name` = `labels.alertname`
- `severity` = `labels.severity` if it is in `SEVERITIES`, else `warning`
- `started_at` = `startsAt`
- `summary` = `annotations.summary`
- `annotations` = all annotations

Errors become `SourceError`s:

| Condition | `endpoint` | `reason` |
|---|---|---|
| status 0 | the base URL | the transport reason |
| 401 or 403 | the base URL | `refused the credential (HTTP <code>)` |
| any other status other than 200 | the base URL | `HTTP <code>` |
| unreadable JSON, or `status != "success"` | the base URL | `unreadable answer` / `error: <error>` |
| `kubectl` failure | `querySecret <ns>/<name>` | the last stderr line |

URLs pass through `feedback.redact` before they appear in a reason.

**Mapping** (AC-092.20, AC-092.8, AC-092.24). A built-in rule's series map to its own service and environment.
Otherwise, for a series' labels:
- **service:**
  1. `service`, else `job`. A `job` of the form `<namespace>/<name>` (the OTLP translation of
     `service.namespace/service.name`) maps by `<name>`.
  2. A match with a `services.yaml` `name` gives `service` = that name and `repo` = its `repo` (or `None`).
  3. No match: `service` = the raw value (or `""`), `repo = None`, and an `unmapped` note: ``service label "<v>" (or
     job "<v>") is not a service in services.yaml``, or `the series has no service or job label`.
- **mapped service without `repo`:** `repo = None`, note `service <name> has no repo in services.yaml`.
- **environment:** the first of the labels `deployment_environment_name`, `deployment_environment`, `environment` and
  `env` whose value is in `ENVS`. Else a `namespace` of `<app>-<env>`, else an `instance` host matching
  `.<app>-<env>.svc`. Else `unknown`, with the note `no environment label (deployment_environment, environment, env,
  namespace or instance) maps to dev, staging or prod`.

### Tracker additions — `scripts/cplat/autoissue.py` (t1)

```python
def gh(args, *, input=None, timeout=10.0, token: str | None = None) -> tuple[int, str, str]:
    """As before; with token the child env gets GH_TOKEN=token (GITHUB_TOKEN removed)."""

class GhTracker:
    def __init__(self, token: str | None = None): ...      # None: the ambient gh login / GH_TOKEN (088 unchanged)
    # find / comments / create / comment unchanged; every gh() call passes token=... only when self.token is set
    def open_issues(self, repo: str, labels: list[str], timeout: float) -> list[Issue]:
        """gh api --paginate "repos/{repo}/issues?labels=<comma-joined>&state=open&per_page=100", pull requests dropped."""
    def close(self, repo: str, number: int, timeout: float) -> None:      # gh issue close N -R repo --reason completed
    def reopen(self, repo: str, number: int, timeout: float) -> None:     # gh issue reopen N -R repo
    def ensure_labels(self, repo: str, labels: dict[str, tuple[str, str]], timeout: float) -> None:
        """gh label create NAME -R repo --color C --description D, per label; 'already exists' is success."""
```

Errors map through `_check` to `TrackerError`, as in 088.

### Issues — `scripts/cplat/alertissues.py`

```python
CAP_PER_POLL = 10
REOPEN_WINDOW = datetime.timedelta(days=7)
RESOLVED = "**Resolved** at "
FIRED_AGAIN = "**Fired again** "
ISSUE_LABELS = ["triage", "auto-filed", "alert"]          # == autoissue.BASE_LABELS + KIND_LABELS["alert"]
NO_ACCESS = re.compile(r"(?i)(HTTP 40[34]|not accessible|could not resolve to a repository|must have (admin|push|triage|write))")

class AlertTracker(autoissue.Tracker, Protocol):
    def open_issues(self, repo, labels, timeout) -> list[autoissue.Issue]: ...
    def close(self, repo, number, timeout) -> None: ...
    def reopen(self, repo, number, timeout) -> None: ...
    def ensure_labels(self, repo, labels, timeout) -> None: ...

def tracker(gitops_repo: str) -> AlertTracker:
    """Seam (tests replace it). Default: a router. The gitops repo is written with GhTracker() (the workflow's GH_TOKEN).
    Any other repo uses GhTracker(token=$ALERTS_TOKEN) when ALERTS_TOKEN is set, else GhTracker() (AC-092.9)."""

@dataclass
class Action:
    verb: str          # file | fired-again | reopen | suppressed | resolve | close | defer | summary | summary-comment
    repo: str
    title: str
    number: int | None = None
    url: str | None = None
    detail: str = ""   # e.g. "suppressed by #12", the intended repo and reason

@dataclass
class Result:
    actions: list[Action]
    lines: list[str]               # what the poll prints, in order
    errors: list[str]              # AC-092.16 GitHub failures: "<repo>: <reason>"
    rerouted: list[str]            # AC-092.9: "<intended repo>: <reason>"

def title(alert: Alert) -> str
def render_body(alert: Alert, *, gitops_repo: str, closed: Issue | None = None, intended: tuple[str, str] | None = None) -> str
def render_fired_again(alert: Alert, occurrence: int, at: datetime.datetime) -> str
def render_resolved(alert_title: str, at: datetime.datetime, *, closed: bool) -> str
def reconcile(alerts: list[Alert], *, app: str, gitops_repo: str, repos: list[str], tr: AlertTracker,
              now: datetime.datetime, dry_run: bool, resolve: bool) -> Result:
    """Never raises. `repos`: the services' repos + gitops_repo (where resolved issues are looked for).
    resolve=False (a source failed): no resolve and no close at all (AC-092.16)."""
```

**Title** (AC-092.20): `"[auto] [alert] " + f"{name}: {service or 'unknown'} in {environment}"`. Each value goes
through `autoissue.scrub` and is made one line. A title longer than 100 characters becomes `title[:99] + "…"`.

**Body**, in this order:

~~~markdown
Seen again after #<n> was closed.                 ← only with closed; then one blank line

## Alert
- alert: <name>
- severity: <severity>
- environment: <environment>
- service: <service or "unknown">
- started firing: <started_at, UTC, YYYY-MM-DDTHH:MM:SSZ>
- source: Prometheus rule | Alertmanager
- application: <app> (<gitops_repo>)             ← the line the resolve phase scopes by

## Summary
<summary or "(none)">

## Query
````promql
<query>                                           ← for Alertmanager: "Alertmanager <alertmanagerURL>" in a text fence
````

## Labels
````text
<one series per line: key="value", key="value"; at most 10 series; values JSON-escaped>
````

## Annotations                                     ← Alertmanager only
````text
key="value"
````

## Not mapped                                      ← only when alert.unmapped (AC-092.8)
- <note>

## Intended repo                                   ← only when rerouted (AC-092.9)
This alert belongs to <intended repo>, but the poll's credential cannot write issues there: <reason>.
Set the ALERTS_TOKEN secret (`cplat doctor` shows how).

_Filed automatically by the alert poll (spec 092). Secrets were removed. Route it with /shared:triage._

Signature: alert:<16 hex>
~~~

Every piece, and the fence contents too, goes through `autoissue.scrub` (AC-092.10). Label and annotation values
appear only inside the fences. Fences use `autoissue._fence`, so the fence is longer than any backtick run inside.
Name, service and environment in the list are label values too: there, `` ` ``, `*`, `_`, `[`, `]`, `<`, `>` and `@`
are replaced by `'`, `·`, `·`, `(`, `)`, `‹`, `›` and `＠`, so they never become Markdown, links or mentions.

**Comments:**
- Fired again (AC-092.21): ``**Fired again** (occurrence <n>) at <time>`` then a blank line and `- severity: <s>`,
  `- environment: <e>`. `<n>` = 2 + the number of earlier comments starting with `FIRED_AGAIN`.
- Resolved (AC-092.13): ``**Resolved** at <time>: no longer firing.`` With a close, the sentence
  `Closed by the alert poll because it was still untriaged.` follows on the same line.
- The time is `now`, UTC, `YYYY-MM-DDTHH:MM:SSZ`.

**`reconcile` algorithm:**

1. Group by signature: one `Alert` per signature, the highest severity and earliest `started_at` win. Sort by
   `(SEVERITIES.index(severity), started_at, signature)`.
2. For each alert, the target is `alert.repo or gitops_repo`. `issues = tr.find(target, sig)`, keeping only issues
   with the exact `Signature:` line.
   - A `TrackerError` matching `NO_ACCESS` in a repo other than the gitops repo means: retarget to `gitops_repo` with
     `intended = (repo, reason)`, add to `rerouted`, and look up again there.
   - Any other `TrackerError` goes to `errors`, and the alert is skipped.
3. Decide:
   - **Open issues:** take the oldest by `(created_at, number)` and read its comments. If its last poll comment starts
     with `RESOLVED` → `fired-again` comment. Otherwise there is nothing to do (AC-092.11).
   - **Only closed issues:** `last` = the latest by `closed_at`.
     - `wontfix` in its labels → `suppressed` (detail `suppressed by #<n>`, AC-092.22).
     - Else, if its last poll comment starts with `RESOLVED` and contains `Closed by the alert poll`, and
       `closed_at >= now - REOPEN_WINDOW` → `reopen` + `fired-again`.
     - Else → new, with `closed=last`.
   - **None:** → new.
4. Cap (AC-092.15): the first `CAP_PER_POLL` new ones in sort order are filed, the rest are `defer`. Reopens and
   comments are not capped. With any deferred alert there is the summary alert: name `AlertsDeferred`, service
   `alert-poll`, environment `*`, severity `info`, target `gitops_repo`. Its signature is
   `raw_signature("alert", app, "*", "alert-poll", "AlertsDeferred")` and its title
   `[auto] [alert] more than 10 new alerts: <app>`. When it has an open issue, the poll comments
   `**Deferred** at <time>: <k> alerts wait for the next poll` plus one `- <title> (<target repo>)` line per deferred
   alert. Otherwise it is filed, with the same list in its Summary. It is never itself capped.
5. Apply in sort order. Before the first `create` in a repo, call
   `ensure_labels(repo, {triage, auto-filed, alert, env:<env>…})` once per poll and repo, for the environments being
   filed there. Colours and descriptions: `triage.LABELS` and `autoissue.EXTRA_LABELS`; `env:<env>` is `"5319e7"`,
   `"Environment <env> (spec 092)"`. Labels are `ISSUE_LABELS + [f"env:{environment}"]`. Meta alerts (environment `*`)
   get no env label. A `NO_ACCESS` error on create, comment or reopen in a non-gitops repo reroutes as in step 2. The
   rerouted issue goes into the gitops repo with the Intended repo section, and this is checked again at every poll.
6. Resolve (only with `resolve=True`), for every repo in `repos`:
   - `tr.open_issues(repo, ["auto-filed", "alert"])`, keeping issues that have the line
     `- application: <app> (<gitops_repo>)` and a `Signature: alert:` line.
   - Skip issues whose signature fires in this poll; the summary issue counts as firing while anything is deferred.
   - If the last poll comment does not start with `RESOLVED`: add the `resolve` comment, and close the issue
     (`close`) when `triage` is in its labels.
   - If the last poll comment is already Resolved but `triage` is still on and the issue is open: close the issue, with
     no new comment.
   - A `NO_ACCESS` error on `open_issues` means the repo is skipped (the poll cannot have filed there). Other errors go
     to `errors`.
7. `dry_run`: reads happen. `create`, `comment`, `reopen`, `close` and `ensure_labels` are never called. Every action
   is a `DRY RUN:` line instead (AC-092.18).

**Output lines** (`Result.lines`, printed by `alerts.py`):

| Action | Line | Dry run |
|---|---|---|
| file | `filed <issue url>: <title>` | `DRY RUN: would file in <repo>: <title>` |
| fired-again | `fired again <issue url>: <title>` | `DRY RUN: would comment on <repo>#<n> (fired again): <title>` |
| reopen | `reopened <issue url>: <title>` | `DRY RUN: would reopen <repo>#<n>: <title>` |
| suppressed | `suppressed by #<n> (wontfix): <title>` | the same |
| resolve | `resolved <issue url>: <title>` | `DRY RUN: would comment on <repo>#<n> (resolved): <title>` |
| close | `closed <issue url>: <title>` | `DRY RUN: would close <repo>#<n>: <title>` |
| defer | `deferred (cap of 10 new issues per poll): <title>` | the same |
| reroute | `filed in <gitops repo> instead of <repo>: <reason>` | `DRY RUN: would file in <gitops repo> instead of <repo>: <reason>` |
| summary comment | `deferred list on <issue url>` | `DRY RUN: would comment on <repo>#<n> (deferred list)` |

The issue URL is `https://github.com/<repo>/issues/<n>`. The title in a line is the issue's title (for an existing
issue, the current alert's title).

### CLI — `cplat alerts poll` (`scripts/cplat/alerts.py`)

```
cplat alerts poll [--repo-dir DIR] [--app APP] [--gitops-repo OWNER/NAME] [--state-file PATH] [--dry-run]
```

- `--gitops-repo` defaults to `$GITHUB_REPOSITORY`, else `<github_org>/<project_name>` from `.copier-answers.yml`.
- `--state-file` defaults to `.alert-poll/state.json`.
- Apps are `applications/*/services.yaml` (or `--app`), and each is polled on its own.

```python
def poll(repo_dir: Path, *, gitops_repo: str, state_file: Path, dry_run: bool, app: str | None = None) -> tuple[int, list[str]]
def load_state(gitops_repo: str, state_file: Path) -> dict:
    """The state file if it exists; else the newest unexpired artifact `alert-poll-state`:
    gh api "repos/{repo}/actions/artifacts?name=alert-poll-state&per_page=20" (largest created_at), then
    gh run download <workflow_run.id> -R repo -n alert-poll-state -D <state_file.parent>. Nothing found → {}.
    A gh failure raises TrackerError."""
def main(argv: list[str]) -> int
```

State file: `{"version": 1, "apps": {"<app>": {"failures": <int>, "last_reason": "<str>", "at": "<ISO>"}}}`.

Per app:
1. `cfg = load_app(...)`. If `cfg.skip` → `alert poll <app>: skipped: <skip>`. That app makes no GitHub or network
   call (AC-092.2). When every app is skipped, the state is not loaded, nothing is written, and the exit code is 0.
2. `alerts, src_errors = collect(cfg, now=...)`. A `SourceError` from `load_app` (invalid rules) counts as a
   source error.
3. The state is loaded once per run. If it cannot be loaded, that is a GitHub error. It then counts as 0 failures, and
   the state is not saved, so a GitHub outage does not reset the counter.
4. With `src_errors`: `failures = previous + 1`, `last_reason` = the first error. When `failures >= 3`, the poll-failing
   alert joins `alerts`:
   - name `AlertPollFailing`, service `alert-poll`, environment `*`, severity `critical`
   - title `[auto] [alert] alert poll is failing: <app>`, target `gitops_repo`
   - summary `The alert poll failed <failures> times in a row. Last reason: <last_reason>`
   - signature `raw_signature("alert", app, "*", "alert-poll", "AlertPollFailing")`

   Without `src_errors`: `failures = 0`. The poll-failing alert does not fire, so step 6 of `reconcile` resolves its
   issue (AC-092.17).
5. `result = reconcile(..., resolve=not src_errors and the state loaded)`, with
   `repos = sorted({s["repo"] for s in services if s.get("repo")} | {gitops_repo})` and `tr = alertissues.tracker(gitops_repo)`.
6. Lines:
   - `alert poll <app>: <n> firing in <env, …> (<r> from rules, <m> from Alertmanager)`
   - the notes
   - `result.lines`
   - `ERROR: <endpoint>: <reason>` per source error and per `result.errors`
   - with source errors also `no issue was resolved or closed in this run`
   - when the poll-failing alert fires: `alert poll is failing for <n> polls in a row`

Then, unless `--dry-run`, the state file is written. Every line is printed. When `$GITHUB_STEP_SUMMARY` is set, a
`## Alert poll` section with the same lines as a list is appended to it.

Exit code: 1 with any source error, any `result.errors` or any `result.rerouted` (AC-092.9, .16); otherwise 0. The
poll never raises out of `main`. An unexpected exception is `ERROR: unexpected failure: <Type>: <msg>`, exit 1, and the
state is not saved.

### Workflow — `templates/gitops-app/.github/workflows/alerts.yml` (copied verbatim, AC-092.1, .3, .18)

```yaml
name: alerts
run-name: ${{ vars.CI_RUNNER == '' && 'alert poll skipped: needs the self-hosted runner (set the CI_RUNNER variable)' || (inputs.dry_run && 'alert poll (dry run)' || 'alert poll') }}
on:
  schedule: [{cron: "*/15 * * * *"}]
  workflow_dispatch:
    inputs:
      dry_run: {description: "print what would be filed, commented, reopened or closed; change nothing", type: boolean, default: false}
permissions: {contents: read, issues: write, actions: read}
concurrency: {group: alert-poll, cancel-in-progress: false}
jobs:
  poll:
    name: ${{ vars.CI_RUNNER == '' && 'alert poll skipped: needs the self-hosted runner (set the CI_RUNNER variable)' || 'alert poll' }}
    if: vars.CI_RUNNER != ''
    runs-on: ${{ vars.CI_RUNNER }}           # never a GitHub-hosted runner (ADR-035)
    steps:
      - uses: actions/checkout@<the pinned sha ci.yml uses> # v7.0.1
      - name: Poll
        env:
          GH_TOKEN: ${{ github.token }}
          ALERTS_TOKEN: ${{ secrets.ALERTS_TOKEN }}
          ALERTS_QUERY_AUTHORIZATION: ${{ secrets.ALERTS_QUERY_AUTHORIZATION }}
          ALERTS_PROMETHEUS_URL: ${{ vars.ALERTS_PROMETHEUS_URL }}
          ALERTS_DRY_RUN: ${{ inputs.dry_run && '1' || '' }}
        run: devbox run alert-poll
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        if: always() && !inputs.dry_run
        with: {name: alert-poll-state, path: .alert-poll/state.json, retention-days: 3, if-no-files-found: ignore}
```

`devbox.json` gets the recipe `"alert-poll": "bash scripts/alert-poll.sh"`. `scripts/alert-poll.sh`:
- Platform dir: `$ALERTS_PLATFORM`, else the fetched `.platform-version` ref. This is the `spec-check.sh` logic: a tag
  is cached, a branch is fetched.
- If `scripts/cplat/alerts.py` is missing there: print `alert poll: platform <ref> has no alert poll (spec 092); run /shared:update-service`, append it to `$GITHUB_STEP_SUMMARY`, exit 0.
- Otherwise `exec uv run --quiet "$dir/scripts/cplat/cplat.py" alerts poll --repo-dir . ${ALERTS_DRY_RUN:+--dry-run}`.

The workflow is not in `_skip_if_exists`, so `/shared:update-service` adds it to existing repos (AC-092.1).
`.alert-poll/` goes in the template's `.gitignore`.

### Doctor (AC-092.25)

`check_alerts_token(repo)`, added to `run_checks` after `check_service_repos_token`:
- It applies only to the `gitops-app` shape with some `applications/*/app.yaml` that declares `observability` with
  `alerts` not `false`, and some `services.yaml` entry with a `repo`. Otherwise it returns `[]`.
- It reads `gh secret list --json name` through `ship.gh`, as `check_service_repos_token` does.
- Missing secret → `check(WARN, "secret ALERTS_TOKEN", "not set: alert issues for the service repos land in <slug> instead", ALERTS_TOKEN_FIX)`.
  `ALERTS_TOKEN_FIX` is `create a fine-grained token with Issues: read and write on every service repo in services.yaml, then: gh secret set ALERTS_TOKEN -R <slug>`.
- A list it cannot read → `WARN`, `could not be read with this gh login`, with the same fix.
- Secret set → `OK`, `set: alert issues go to the service repos`.

## Data

- No schema changes in the run store. Nothing is recorded there (non-goal).
- `.alert-poll/state.json` (local, git-ignored) and the artifact `alert-poll-state` (3 days).
- GitHub labels per target repo: `triage`, `auto-filed`, `alert`, `env:<env>`.

## Risks

- **`otel-lgtm` Prometheus on 9090.** The image runs Prometheus on 9090 inside the pod. The Service did not expose it
  until now. With a runner outside the cluster, `ALERTS_PROMETHEUS_URL` must point at a port-forward or route.
- **The environment of OTLP-pushed metrics.** OTLP puts `deployment.environment` into `target_info`, not on every
  series. Scraped series carry it through `instance`. Rules on pushed metrics should join `target_info` or aggregate
  `by (job, instance)`. The template's app.yaml comment says so, and unmapped ones still land in the gitops repo with
  the note.
- **ServiceDown right after the addon is enabled.** `absent_over_time` fires when no sample exists yet in 5 minutes.
  The first poll after a fresh deploy may file one issue, which the next poll resolves and closes (still untriaged).
- **Artifact load on a GitHub outage.** The counter does not advance while the state cannot be read. Filing is
  impossible during the outage anyway. Unreachable GitHub (AC-092.16) still makes the run red.
- **Two runs at once** are prevented by `concurrency: alert-poll`. A hand-started dry run waits for the scheduled run.
