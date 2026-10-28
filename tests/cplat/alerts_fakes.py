"""Shared in-memory fakes for the spec 092 acceptance tests (not a test module, never collected).

Nothing here reaches GitHub, Prometheus, Alertmanager, kubectl or the network: the tests install these in place of the
seams `alertissues.tracker`, `alertsources.http_get`, `alertsources.kubectl` and `autoissue.now`."""
import datetime as dt
import json
import urllib.parse
from pathlib import Path

import yaml

import autoissue

NOW = dt.datetime(2026, 10, 24, 8, 0, 0, tzinfo=dt.timezone.utc)
GITOPS = "acme/shop-gitops"
APP = "shop"
LGTM = "http://lgtm.observability.svc:9090"
WRITES = ("create", "comment", "close", "reopen", "ensure_labels")
SERVICES = [
    {"name": "shop-api", "repo": "acme/shop-api", "metrics": "/metrics", "environments": ["dev", "prod"]},
    {"name": "shop-web", "repo": "acme/shop-web", "environments": ["dev"]},
    {"name": "shop-batch", "environments": ["dev"]},
]


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeTracker:
    """An in-memory GitHub with the AlertTracker methods. `raises[repo] = message` makes every call for that repo fail."""

    def __init__(self):
        self.issues: dict[str, list] = {}
        self.cmts: dict[tuple[str, int], list[str]] = {}
        self.labels: dict[str, set[str]] = {}
        self.calls: list[tuple] = []
        self.raises: dict[str, str] = {}
        self.n = 0

    def _enter(self, what, repo, *args):
        self.calls.append((what, repo, *args))
        if repo in self.raises:
            raise autoissue.TrackerError(self.raises[repo])

    # ---- Tracker protocol
    def find(self, repo, signature, timeout):
        self._enter("find", repo, signature)
        found = [i for i in self.issues.get(repo, []) if autoissue._has_signature(i.body, signature)]
        opened = [i for i in found if i.state == "open"]
        return opened or found

    def comments(self, repo, number, timeout):
        self._enter("comments", repo, number)
        return list(self.cmts.get((repo, number), []))

    def create(self, repo, title, body, labels, timeout):
        self._enter("create", repo, title, body, list(labels))
        return self.add(repo, title=title, body=body, labels=labels).url

    def comment(self, repo, number, body, timeout):
        self._enter("comment", repo, number, body)
        self.cmts.setdefault((repo, number), []).append(body)
        return f"https://github.com/{repo}/issues/{number}#issuecomment-{len(self.cmts[(repo, number)])}"

    # ---- AlertTracker additions
    def open_issues(self, repo, labels, timeout):
        self._enter("open_issues", repo, list(labels))
        return [i for i in self.issues.get(repo, []) if i.state == "open" and set(labels) <= set(i.labels)]

    def close(self, repo, number, timeout):
        self._enter("close", repo, number)
        issue = self.get(repo, number)
        issue.state, issue.closed_at = "closed", iso(NOW)

    def reopen(self, repo, number, timeout):
        self._enter("reopen", repo, number)
        issue = self.get(repo, number)
        issue.state, issue.closed_at = "open", None

    def ensure_labels(self, repo, labels, timeout):
        self._enter("ensure_labels", repo, dict(labels))
        self.labels.setdefault(repo, set()).update(labels)

    # ---- test helpers
    def add(self, repo, *, title, body, labels=("triage", "auto-filed", "alert", "env:prod"), state="open", created_at=None,
            closed_at=None, comments=()):
        self.n += 1
        issue = autoissue.Issue(number=self.n, url=f"https://github.com/{repo}/issues/{self.n}", state=state, labels=list(labels),
                                created_at=created_at or iso(NOW - dt.timedelta(hours=1) + dt.timedelta(seconds=self.n)),
                                closed_at=closed_at, body=body)
        issue.title = title
        self.issues.setdefault(repo, []).append(issue)
        if comments:
            self.cmts[(repo, issue.number)] = list(comments)
        return issue

    def get(self, repo, number):
        return next(i for i in self.issues[repo] if i.number == number)

    def of(self, what, repo=None):
        return [c for c in self.calls if c[0] == what and (repo is None or c[1] == repo)]

    def writes(self):
        return [c for c in self.calls if c[0] in WRITES]

    def created(self, repo=None):
        return self.of("create", repo)

    def commented(self, repo=None):
        return self.of("comment", repo)


class FakeNet:
    """`alertsources.http_get` over canned Prometheus and Alertmanager answers."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.rules: list = []                      # (match(query) -> bool, [metric label dicts])
        self.am: list | None = None                # Alertmanager /api/v2/alerts answer
        self.prom_error: tuple[int, str] | None = None
        self.am_error: tuple[int, str] | None = None

    def on(self, match, metrics):
        """`match` is a PromQL string (exact) or a predicate on the query."""
        self.rules.append(((lambda q: q == match) if isinstance(match, str) else match, list(metrics)))

    def __call__(self, url, *, headers=None, timeout=10.0):
        headers = dict(headers or {})
        self.calls.append((url, headers))
        parsed = urllib.parse.urlparse(url)
        if parsed.path.endswith("/api/v1/query"):
            if self.prom_error:
                return self.prom_error
            query = urllib.parse.parse_qs(parsed.query).get("query", [""])[0]
            metrics = next((m for match, m in self.rules if match(query)), [])
            result = [{"metric": m, "value": [0, "1"]} for m in metrics]
            return 200, json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}})
        if parsed.path.endswith("/api/v2/alerts"):
            if self.am_error:
                return self.am_error
            return 200, json.dumps(self.am or [])
        return 0, "no route in the fake network"

    def queries(self):
        return [u for u, _ in self.calls if "/api/v1/query" in u]

    def am_calls(self):
        return [u for u, _ in self.calls if "/api/v2/alerts" in u]


def make_app(root: Path, *, addon, services=None, app: str = APP, envs=None) -> Path:
    """applications/<app>/system.yaml (5.0); `addon` is the observability setting of the environments `envs` (default: all three;
    None: no environment declares observability); `services` are the components in the 4.x vocabulary of model_fixtures.system_doc."""
    from model_fixtures import system_doc
    d = root / "applications" / app
    d.mkdir(parents=True, exist_ok=True)
    cfg = {"addons": {"observability": addon}} if addon is not None else {}
    doc = system_doc(SERVICES if services is None else services, cfg, app)
    for e, conf in doc["environments"].items():
        if envs is not None and e not in envs:
            conf.pop("observability", None)
    (d / "system.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    return d


def mkalert(**kw):
    import alertsources
    base = dict(app=APP, name="HighErrorRate", severity="warning", environment="prod", service="shop-api", repo="acme/shop-api",
                started_at=NOW - dt.timedelta(minutes=10), summary="More than one 5xx per second", source="rule",
                query='sum by (job) (rate(http_server_requests_seconds_count{status=~"5.."}[5m])) > 1',
                series=[{"job": "shop-api"}])
    base.update(kw)
    return alertsources.Alert(**base)


def seed(tr: FakeTracker, alert, *, repo=None, comments=(), labels=None, state="open", closed_at=None, created_at=None, gitops=GITOPS):
    """An issue as the poll itself would have filed it for `alert`."""
    import alertissues
    labels = labels if labels is not None else [*alertissues.ISSUE_LABELS, *([f"env:{alert.environment}"] if alert.environment != "*" else [])]
    return tr.add(repo or alert.repo or gitops, title=alertissues.title(alert), body=alertissues.render_body(alert, gitops_repo=gitops),
                  labels=labels, state=state, closed_at=closed_at, created_at=created_at, comments=comments)


def resolved_comment(alert, at=NOW, *, closed=False):
    import alertissues
    return alertissues.render_resolved(alertissues.title(alert), at, closed=closed)
