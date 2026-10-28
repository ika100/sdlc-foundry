"""`alertsources`: where firing alerts come from (spec 092, ADR 038).

Reads `applications/<app>/system.yaml` (each environment's `observability` is one source), evaluates the declared rules and the built-in `ServiceDown` against a
Prometheus query API, reads an optional Alertmanager, and maps every series to a service, its repo and an environment.
The output is `Alert`s and `SourceError`s. Nothing here touches GitHub. The seams `http_get` and `kubectl` never raise;
tests replace them.
"""
from __future__ import annotations

import base64
import binascii
import datetime
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import autoissue
import backupstate
import feedback
import model
from model import Model

SEVERITIES = ("critical", "warning", "info")
SERVICE_DOWN = "ServiceDown"
BACKUP_FAILING = "backup failing"
LGTM_QUERY_URL = "http://lgtm.observability.svc:9090"
TIMEOUT_S = 10.0
MAX_SERIES = 10
_ENV_LABELS = ("deployment_environment_name", "deployment_environment", "environment", "env")
NO_ENV_NOTE = "no environment label (deployment_environment, environment, env, namespace or instance) maps to dev, staging or prod"


@dataclass
class Rule:
    name: str
    query: str
    severity: str
    summary: str = ""
    service: str | None = None          # built-ins only: the series map to this service ...
    environment: str | None = None      # ... and this environment, whatever their labels say


@dataclass
class Alert:
    app: str
    name: str
    severity: str
    environment: str
    service: str
    repo: str | None
    started_at: datetime.datetime
    summary: str
    source: str                         # "rule" | "alertmanager"
    query: str
    series: list[dict[str, str]]
    annotations: dict[str, str] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)

    @property
    def signature(self) -> str:
        return autoissue.raw_signature("alert", self.app, self.environment, self.service, self.name)


@dataclass
class EnvSource:
    """One environment's observability: its rules and its endpoints (AC-114.10)."""
    env: str
    rules: list[Rule] = field(default_factory=list)
    prometheus_url: str | None = None
    alertmanager_url: str | None = None
    query_secret: str | None = None
    notes: list[str] = field(default_factory=list)
    skip: str | None = None


@dataclass
class AppConfig:
    app: str
    app_dir: Path
    services: list[dict]
    envs: list[str]
    sources: list[EnvSource] = field(default_factory=list)
    skip: str | None = None
    notes: list[str] = field(default_factory=list)
    model: Model | None = None
    backups: dict[str, list[str]] = field(default_factory=dict)   # env -> databases with backup; "" = the environment itself (spec 117)

    @property
    def rules(self) -> list[Rule]:
        return [r for s in self.sources for r in s.rules]


class SourceError(Exception):
    def __init__(self, endpoint: str, reason: str):
        super().__init__(f"{endpoint}: {reason}")
        self.endpoint = endpoint
        self.reason = reason


# ---------------- seams ----------------

def http_get(url: str, *, headers: dict[str, str], timeout: float = TIMEOUT_S) -> tuple[int, str]:
    """(status, body); (0, reason) when the endpoint cannot be reached. Never raises. Tests replace this."""
    try:
        req = urllib.request.Request(url, headers=dict(headers or {}))
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  (http(s) URLs from system.yaml)
            return int(resp.status), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return int(e.code), body
    except urllib.error.URLError as e:
        return 0, str(e.reason or e)
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def kubectl(args: list[str], *, timeout: float = TIMEOUT_S) -> tuple[int, str, str]:
    """(exit code, stdout, stderr). Never raises. Tests replace this."""
    try:
        p = subprocess.run(["kubectl", *args], capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "kubectl timed out"
    except FileNotFoundError:
        return 127, "", "kubectl is missing"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"


# ---------------- config ----------------

def _rule_problem(rules: object) -> str | None:
    if not isinstance(rules, list):
        return "observability.rules: rules must be a list of {name, query, severity, summary}"
    seen: set[str] = set()
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            return "observability.rules: rules must be a list of {name, query, severity, summary}"
        name = r.get("name")
        shown = name if isinstance(name, str) and name.strip() else "no name"
        head = f"observability.rules[{i}] ({shown}): "
        if not isinstance(name, str) or not name.strip():
            return head + "a rule needs a name"
        if r.get("severity") not in SEVERITIES:
            return head + f"severity '{r.get('severity')}' must be one of {', '.join(SEVERITIES)}"
        if name in seen:
            return head + f"the name '{name}' is used twice"
        seen.add(name)
        if not isinstance(r.get("query"), str) or not r["query"].strip():
            return head + "query must be a non-empty string (PromQL)"
        if "summary" in r and not isinstance(r["summary"], str):
            return head + "summary must be a string"
    return None


def _read_yaml(path: Path) -> dict:
    import yaml
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _service_down(app: str, svc: str, env: str) -> Rule:
    host = re.escape(svc).replace("\\-", "-").replace("\\", "\\\\")
    inst = f'instance=~"{host}\\\\.{app}-{env}\\\\.svc(:[0-9]+)?"'
    return Rule(SERVICE_DOWN, f"(max(max_over_time(up{{{inst}}}[5m])) < 1)\n  or absent_over_time(up{{{inst}}}[5m])", "critical",
                f"No metrics target of {svc} in {env} has been up for 5 minutes", service=svc, environment=env)


def _source(m: Model, app: str, env: str, obs: model.Observability) -> EnvSource:
    src = EnvSource(env=env)
    if obs.alerts is False:
        src.skip = f"{env}: alerts: false in observability"
        return src
    query_url = obs.query_url if isinstance(obs.query_url, str) else None
    am_url = obs.alertmanager_url if isinstance(obs.alertmanager_url, str) else None
    export_to = obs.export_to
    lgtm = obs.ui == "lgtm"
    if export_to and not query_url and not am_url:
        src.skip = f"{env}: exportTo is set but queryURL is missing"
        return src
    if not lgtm and not export_to and not am_url:
        src.skip = f"{env}: no metrics backend: set ui: lgtm, or exportTo with queryURL"
        return src
    if obs.rules is not None:
        problem = _rule_problem(obs.rules)
        if problem:
            raise SourceError(f"applications/{app}/system.yaml",
                              problem.replace("observability.", f"environments.{env}.observability.", 1))
    src.alertmanager_url = am_url.rstrip("/") if am_url else None
    if query_url:
        src.prometheus_url = query_url.rstrip("/")
    elif lgtm:
        src.prometheus_url = (os.environ.get("ALERTS_PROMETHEUS_URL", "").strip() or LGTM_QUERY_URL).rstrip("/")
    else:
        src.notes.append(f"{env}: rules not evaluated: queryURL is missing")
    secret = obs.query_secret
    if isinstance(secret, str) and secret:
        first = next((i.namespace for i in m.instances), f"{app}-{env}")
        src.query_secret = secret if "/" in secret else f"{first}/{secret}"
    declared = [Rule(r["name"], r["query"], r["severity"], r.get("summary") or "") for r in obs.rules or []]
    src.rules = list(declared)
    if not any(r.name == SERVICE_DOWN for r in declared):
        with_metrics = {c.name for c in m.components if c.metrics}
        src.rules += [_service_down(app, i.component, i.environment) for i in m.instances
                      if i.environment == env and i.component in with_metrics]
    return src


def load_app(app_dir: Path) -> AppConfig:
    app_dir = Path(app_dir)
    app = app_dir.name
    if not (app_dir / "system.yaml").exists() and ((app_dir / "app.yaml").exists() or (app_dir / "services.yaml").exists()):
        raise SourceError(f"applications/{app}", model.NOT_MIGRATED)
    doc = _read_yaml(app_dir / "system.yaml")
    comps = doc.get("components") if isinstance(doc.get("components"), dict) else {}
    services = [{"name": n, "repo": c.get("repo")} for n, c in comps.items() if isinstance(c, dict) and c.get("type") != "library"]
    m = model.build(doc, app)
    envs = [e.name for e in m.environments if m.instances_in(e.name)]
    out = AppConfig(app=app, app_dir=app_dir, services=services, envs=envs, model=m)
    skipped: list[str] = []
    for e in m.environments:
        if e.name not in envs or e.observability is None:
            continue
        if e.observability.alerts is not False:
            subjects = ([""] if e.backup else []) + [r.resource for r in m.resource_instances
                                                    if r.environment == e.name and r.type == "database" and r.backup]
            if subjects:
                out.backups[e.name] = subjects
        src = _source(m, app, e.name, e.observability)
        if src.skip:
            skipped.append(src.skip)
        else:
            out.sources.append(src)
    if not out.sources and not out.backups:
        out.skip = "; ".join(skipped) if skipped else "no environment declares observability"
    else:
        out.notes += [f"skipped {s}" for s in skipped] + [n for src in out.sources for n in src.notes]
    return out


# ---------------- reading ----------------

def authorization(cfg: EnvSource) -> str | None:
    env = os.environ.get("ALERTS_QUERY_AUTHORIZATION", "").strip()
    if env:
        return env
    if not cfg.query_secret:
        return None
    ns, name = cfg.query_secret.split("/", 1)
    endpoint = f"querySecret {cfg.query_secret}"
    code, out, err = kubectl(["get", "secret", name, "-n", ns, "-o", "jsonpath={.data.AUTHORIZATION}"])
    if code != 0:
        last = next((ln.strip() for ln in reversed(err.strip().splitlines()) if ln.strip()), "kubectl failed")
        raise SourceError(endpoint, feedback.redact(last))
    try:
        value = base64.b64decode(out.strip(), validate=True).decode().strip()
    except (binascii.Error, ValueError):
        raise SourceError(endpoint, "key AUTHORIZATION is missing or not base64") from None
    if not value:
        raise SourceError(endpoint, "key AUTHORIZATION is missing or empty")
    return value


def _fetch(base: str, url: str, headers: dict[str, str]) -> tuple[object | None, SourceError | None]:
    endpoint = feedback.redact(base)
    status, body = http_get(url, headers=headers, timeout=TIMEOUT_S)
    if status == 0:
        return None, SourceError(endpoint, feedback.redact(body))
    if status in (401, 403):
        return None, SourceError(endpoint, f"refused the credential (HTTP {status})")
    if status != 200:
        return None, SourceError(endpoint, f"HTTP {status}")
    try:
        return json.loads(body), None
    except ValueError:
        return None, SourceError(endpoint, "unreadable answer")


def _service_of(cfg: AppConfig, labels: dict[str, str]) -> tuple[str, str | None, list[str]]:
    raw = labels.get("service") or labels.get("job") or ""
    if not raw:
        return "", None, ["the series has no service or job label"]
    names = {s["name"]: s for s in cfg.services}
    for cand in (raw, raw.rsplit("/", 1)[-1]):
        if cand in names:
            repo = names[cand].get("repo") or None
            return cand, repo, ([] if repo else [f"service {cand} has no repo in system.yaml"])
    return raw, None, [f'service label "{raw}" (or job "{raw}") is not a service in system.yaml']


def _env_of(cfg: AppConfig, labels: dict[str, str]) -> tuple[str, list[str]]:
    for key in _ENV_LABELS:
        if labels.get(key) in model.ENVIRONMENTS:
            return labels[key], []
    envs = "|".join(model.ENVIRONMENTS)
    m = re.fullmatch(rf"{re.escape(cfg.app)}-({envs})", labels.get("namespace", ""))
    if m:
        return m.group(1), []
    m = re.search(rf"\.{re.escape(cfg.app)}-({envs})\.svc", labels.get("instance", ""))
    if m:
        return m.group(1), []
    return "unknown", [NO_ENV_NOTE]


def _merge(into: dict[str, Alert], alert: Alert) -> None:
    sig = alert.signature
    old = into.get(sig)
    if old is None:
        into[sig] = alert
        return
    for s in alert.series:
        if s not in old.series:
            old.series.append(s)
    old.started_at = min(old.started_at, alert.started_at)
    if SEVERITIES.index(alert.severity) < SEVERITIES.index(old.severity):
        old.severity = alert.severity
    for n in alert.unmapped:
        if n not in old.unmapped:
            old.unmapped.append(n)


def _finish(alerts: dict[str, Alert]) -> list[Alert]:
    for a in alerts.values():
        a.series = sorted(a.series, key=lambda s: sorted(s.items()))[:MAX_SERIES]
    return list(alerts.values())


def _parse_time(text: object, default: datetime.datetime) -> datetime.datetime:
    try:
        s = re.sub(r"(\.\d{6})\d+", r"\1", str(text).replace("Z", "+00:00"))
        t = datetime.datetime.fromisoformat(s)
        return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return default


def _mine(src: EnvSource, first: bool, env: str) -> bool:
    """A series belongs to the source of its environment; one that maps to no environment is kept once, by the first source."""
    return env == src.env or (first and env not in model.ENVIRONMENTS)


def collect(cfg: AppConfig, *, now: datetime.datetime) -> tuple[list[Alert], list[SourceError]]:
    errors: list[SourceError] = []
    found: dict[str, Alert] = {}
    for n, src in enumerate(cfg.sources):
        _collect_source(cfg, src, n == 0, now, found, errors)
    _collect_backups(cfg, now, found, errors)
    return _finish(found), errors


def _collect_backups(cfg: AppConfig, now: datetime.datetime, found: dict[str, Alert], errors: list[SourceError]) -> None:
    """Database and environment backups failing for more than an hour (AC-117.28); the current kube context is read."""
    for env, subjects in cfg.backups.items():
        endpoint = f"{cfg.app}-{env} backup"
        try:
            for subject in subjects:
                if subject:
                    try:
                        state = backupstate.restore_state(cfg.app_dir, env, subject)
                    except backupstate.StateError:
                        state = None
                    try:
                        backupstate.take_first_backup(cfg.app, subject, env, None, now, state)
                    except backupstate.ReadError as e:
                        errors.append(SourceError(endpoint, feedback.redact(f"first base backup of {subject}: {e}")))
                    fails = [(f["since"], f["error"]) for f in
                             backupstate.database_failing_since(cfg.app, subject, env, None, now, state=state)]
                else:
                    f = backupstate.environment_failing_since(cfg.app, env, None, now)
                    fails = [(f["since"], f["error"])] if f else []
                if not fails:
                    continue
                since = min(x[0] for x in fails)
                _merge(found, Alert(app=cfg.app, name=BACKUP_FAILING, severity="critical", environment=env,
                                    service=subject or "environment", repo=None, started_at=_parse_time(since, now),
                                    summary=fails[0][1], source="rule", query=f"backup state of {cfg.app}-{env} (kubectl)",
                                    series=[{"since": x[0], "error": x[1]} for x in fails]))
        except backupstate.ReadError as e:
            errors.append(SourceError(endpoint, feedback.redact(str(e))))


def _collect_source(cfg: AppConfig, src: EnvSource, first: bool, now: datetime.datetime, found: dict[str, Alert],
                    errors: list[SourceError]) -> None:
    use_prom = bool(src.prometheus_url and src.rules)
    if not use_prom and not src.alertmanager_url:
        return
    try:
        auth = authorization(src)
    except SourceError as e:
        errors.append(e)
        return
    headers = {"Authorization": auth} if auth else {}
    if use_prom:
        base = src.prometheus_url or ""
        for rule in src.rules:
            data, err = _fetch(base, f"{base}/api/v1/query?" + urllib.parse.urlencode({"query": rule.query}), headers)
            if err is None and not (isinstance(data, dict) and data.get("status") == "success"):
                err = SourceError(feedback.redact(base), f"error: {data.get('error') or 'unreadable answer'}"
                                  if isinstance(data, dict) and data.get("status") else "unreadable answer")
            if err is not None:
                errors.append(err)
                break
            result = ((data.get("data") or {}).get("result") or []) if isinstance(data, dict) else []
            for item in result:
                labels = {str(k): str(v) for k, v in ((item or {}).get("metric") or {}).items()}
                if rule.service is not None:
                    service, env, notes = rule.service, rule.environment or "unknown", []
                    repo = next((s.get("repo") or None for s in cfg.services if s["name"] == service), None)
                else:
                    service, repo, notes = _service_of(cfg, labels)
                    env, env_notes = _env_of(cfg, labels)
                    notes = notes + env_notes
                if not _mine(src, first, env):
                    continue
                _merge(found, Alert(app=cfg.app, name=rule.name, severity=rule.severity, environment=env, service=service, repo=repo,
                                    started_at=now, summary=rule.summary, source="rule", query=rule.query, series=[labels],
                                    unmapped=list(notes)))
    if src.alertmanager_url:
        base = src.alertmanager_url
        data, err = _fetch(base, f"{base}/api/v2/alerts?active=true&silenced=false&inhibited=false", headers)
        if err is None and not isinstance(data, list):
            err = SourceError(feedback.redact(base), "unreadable answer")
        if err is not None:
            errors.append(err)
            return
        for entry in data:  # type: ignore[union-attr]
            if not isinstance(entry, dict):
                continue
            state = (entry.get("status") or {}).get("state", "active")
            if state != "active":
                continue
            labels = {str(k): str(v) for k, v in (entry.get("labels") or {}).items()}
            ann = {str(k): str(v) for k, v in (entry.get("annotations") or {}).items()}
            sev = labels.get("severity")
            service, repo, notes = _service_of(cfg, labels)
            env, env_notes = _env_of(cfg, labels)
            if not _mine(src, first, env):
                continue
            _merge(found, Alert(app=cfg.app, name=labels.get("alertname", "unnamed"), severity=sev if sev in SEVERITIES else "warning",
                                environment=env, service=service, repo=repo, started_at=_parse_time(entry.get("startsAt"), now),
                                summary=ann.get("summary", ""), source="alertmanager", query=f"Alertmanager {feedback.redact(base)}",
                                series=[labels], annotations=ann, unmapped=notes + env_notes))
