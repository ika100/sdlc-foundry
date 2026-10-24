"""Spec 092: where alerts come from (app.yaml rules, the built-in ServiceDown, Prometheus, Alertmanager) and how they map to
services, repos and environments. `alertsources.http_get` and `.kubectl` are replaced by in-memory fakes."""
import base64
import datetime as dt
import json
import urllib.parse

import pytest

from alerts_fakes import APP, LGTM, NOW, FakeNet, make_app

Q = 'sum by (job) (rate(http_server_requests_seconds_count{status=~"5.."}[5m])) > 1'
RULE = {"name": "HighErrorRate", "query": Q, "severity": "warning", "summary": "More than one 5xx per second"}
TOKEN = "ghp_" + "a1b2c3d4e5" * 4


@pytest.fixture()
def net(monkeypatch):
    import alertsources
    fake = FakeNet()
    monkeypatch.setattr(alertsources, "http_get", fake)
    monkeypatch.setattr(alertsources, "kubectl", lambda args, *, timeout=10.0: (1, "", "tests never call kubectl"))
    for name in ("ALERTS_QUERY_AUTHORIZATION", "ALERTS_PROMETHEUS_URL"):
        monkeypatch.delenv(name, raising=False)
    return fake


def load(tmp_path, addon, services=None):
    import alertsources
    return alertsources.load_app(make_app(tmp_path, addon=addon, services=services))


def collect(cfg):
    import alertsources
    return alertsources.collect(cfg, now=NOW)


def by_env(alerts):
    return {a.environment: a for a in alerts}


# ---------------- AC-092.2 / AC-092.19 skip reasons ----------------

@pytest.mark.parametrize("addon, services, reason", [
    (None, None, "app.yaml declares no observability addon"),
    ({"ui": "lgtm", "alerts": False}, None, "alerts: false in the observability addon"),
    ({"ui": "lgtm"}, [], "no service runs in any environment"),
    ({"exportTo": "https://otlp.example.com"}, None, "exportTo is set but queryURL is missing"),
    ({}, None, "no metrics backend: set ui: lgtm, or exportTo with queryURL"),
])
def test_an_app_that_cannot_be_polled_says_why_it_is_skipped(net, tmp_path, addon, services, reason):
    """AC-092.2 AC-092.19: no addon, `alerts: false`, no running service, or no query source: skipped with the reason."""
    cfg = load(tmp_path, addon, services)
    assert cfg.skip == reason


def test_an_app_with_a_query_source_is_not_skipped(net, tmp_path):
    """AC-092.2 AC-092.19: ui lgtm, and exportTo with queryURL, are polled."""
    assert load(tmp_path, {"ui": "lgtm"}).skip is None
    assert load(tmp_path / "b", {"exportTo": "https://otlp.example.com", "queryURL": "https://prom.example.com/api/prom"}).skip is None


# ---------------- AC-092.19 query endpoints and credentials ----------------

def test_lgtm_queries_the_shared_stack_and_the_url_can_be_overridden(net, monkeypatch, tmp_path):
    """AC-092.19: `ui: lgtm` queries the shared stack's Prometheus API; $ALERTS_PROMETHEUS_URL moves it for runners outside the cluster."""
    cfg = load(tmp_path, {"ui": "lgtm", "rules": [RULE]})
    assert cfg.prometheus_url == LGTM == "http://lgtm.observability.svc:9090"
    collect(cfg)
    assert net.queries() and all(u.startswith(f"{LGTM}/api/v1/query?") for u in net.queries())
    assert Q in [urllib.parse.parse_qs(urllib.parse.urlparse(u).query)["query"][0] for u in net.queries()]
    monkeypatch.setenv("ALERTS_PROMETHEUS_URL", "http://localhost:9999")
    assert load(tmp_path / "b", {"ui": "lgtm"}).prometheus_url == "http://localhost:9999"


def test_export_to_queries_the_addons_query_url_with_the_credential_from_the_env(net, monkeypatch, tmp_path):
    """AC-092.19: with exportTo the rules go to queryURL; $ALERTS_QUERY_AUTHORIZATION is sent as the Authorization header."""
    monkeypatch.setenv("ALERTS_QUERY_AUTHORIZATION", "Bearer from-env")
    cfg = load(tmp_path, {"exportTo": "https://otlp.example.com", "queryURL": "https://prom.example.com/api/prom", "rules": [RULE]})
    assert cfg.prometheus_url == "https://prom.example.com/api/prom"
    collect(cfg)
    assert net.calls and all(u.startswith("https://prom.example.com/api/prom/api/v1/query?") for u, _ in net.calls)
    assert all(h.get("Authorization") == "Bearer from-env" for _, h in net.calls)


def test_the_credential_can_come_from_the_query_secret(net, monkeypatch, tmp_path):
    """AC-092.19: without the env var the optional `querySecret` Secret (key AUTHORIZATION) is read with kubectl and base64-decoded."""
    import alertsources
    seen = []

    def kubectl(args, *, timeout=10.0):
        seen.append(args)
        return 0, base64.b64encode(b"Bearer from-secret").decode(), ""

    monkeypatch.setattr(alertsources, "kubectl", kubectl)
    cfg = load(tmp_path, {"exportTo": "https://otlp.example.com", "queryURL": "https://prom.example.com", "querySecret": "obs-query",
                          "rules": [RULE]})
    assert cfg.query_secret == "shop-dev/obs-query"          # <app>-<first environment the addon runs in>
    collect(cfg)
    assert seen and {"get", "secret", "obs-query"} <= set(seen[0]) and "shop-dev" in seen[0]
    assert all(h.get("Authorization") == "Bearer from-secret" for _, h in net.calls)


def test_a_namespaced_query_secret_is_kept_and_the_env_credential_wins(net, monkeypatch, tmp_path):
    """AC-092.19: `<namespace>/<name>` is used as given; $ALERTS_QUERY_AUTHORIZATION wins over the Secret (kubectl is not called)."""
    import alertsources
    monkeypatch.setattr(alertsources, "kubectl", lambda *a, **k: pytest.fail("the env credential must win"))
    monkeypatch.setenv("ALERTS_QUERY_AUTHORIZATION", "Bearer env")
    cfg = load(tmp_path, {"exportTo": "https://o.example.com", "queryURL": "https://prom.example.com", "querySecret": "obs/query"})
    assert cfg.query_secret == "obs/query"
    assert alertsources.authorization(cfg) == "Bearer env"


def test_an_unreadable_query_secret_is_a_source_error(net, tmp_path):
    """AC-092.19 AC-092.16: kubectl failing makes a SourceError naming the Secret and the last stderr line; nothing is queried."""
    import alertsources
    cfg = load(tmp_path, {"exportTo": "https://o.example.com", "queryURL": "https://prom.example.com", "querySecret": "obs-query",
                          "rules": [RULE]})
    with pytest.raises(alertsources.SourceError) as e:
        alertsources.authorization(cfg)
    assert str(e.value).startswith("querySecret shop-dev/obs-query: ") and "tests never call kubectl" in str(e.value)


def test_no_credential_means_no_authorization_header(net, tmp_path):
    """AC-092.19: lgtm without any credential sends no Authorization header."""
    collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))
    assert net.calls and all("Authorization" not in h for _, h in net.calls)


def test_export_to_with_only_alertmanager_reads_only_alertmanager(net, tmp_path):
    """AC-092.19 AC-092.23: exportTo without queryURL but with alertmanagerURL is not skipped; rules are not evaluated, and a note says so."""
    cfg = load(tmp_path, {"exportTo": "https://o.example.com", "alertmanagerURL": "https://am.example.com", "rules": [RULE]})
    assert cfg.skip is None and cfg.alertmanager_url == "https://am.example.com"
    assert "rules not evaluated: queryURL is missing" in cfg.notes
    collect(cfg)
    assert net.queries() == [] and net.am_calls()


# ---------------- AC-092.6 (poll side) invalid rules ----------------

@pytest.mark.parametrize("rules, fragment", [
    ([{"query": "up == 0", "severity": "warning"}], "a rule needs a name"),
    ([{"name": "A", "query": "up == 0", "severity": "urgent"}], "severity 'urgent' must be one of critical, warning, info"),
    ([{"name": "A", "query": "up == 0", "severity": "info"}, {"name": "A", "query": "up == 1", "severity": "info"}], "the name 'A' is used twice"),
    ([{"name": "A", "severity": "info"}], "query must be a non-empty string (PromQL)"),
])
def test_invalid_rules_are_a_source_error_naming_the_rule_and_the_problem(net, tmp_path, rules, fragment):
    """AC-092.6: the poll refuses invalid rules as render.py does, naming the file and the problem."""
    import alertsources
    with pytest.raises(alertsources.SourceError) as e:
        load(tmp_path, {"ui": "lgtm", "rules": rules})
    assert str(e.value).startswith(f"applications/{APP}/app.yaml: ") and fragment in str(e.value)


# ---------------- AC-092.4 rules fire per environment and service ----------------

def test_a_rule_that_returns_series_fires_for_each_environment_and_service(net, tmp_path):
    """AC-092.4: a query with series fires for each environment and service they belong to, with the rule's fields."""
    net.on(Q, [{"job": "shop-api", "deployment_environment_name": "prod"}, {"job": "shop-api", "deployment_environment_name": "dev"},
               {"job": "shop-web", "deployment_environment_name": "dev"}])
    alerts, errors = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))
    assert errors == []
    keys = {(a.environment, a.service) for a in alerts}
    assert keys == {("prod", "shop-api"), ("dev", "shop-api"), ("dev", "shop-web")}
    a = next(x for x in alerts if (x.environment, x.service) == ("prod", "shop-api"))
    assert (a.app, a.name, a.severity, a.summary, a.query, a.source) == (APP, "HighErrorRate", "warning", "More than one 5xx per second", Q, "rule")
    assert a.repo == "acme/shop-api" and a.started_at == NOW and a.unmapped == []
    assert a.series == [{"job": "shop-api", "deployment_environment_name": "prod"}]


def test_a_rule_whose_query_returns_nothing_is_not_firing(net, tmp_path):
    """AC-092.4: an empty result means no alert and no error."""
    assert collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]})) == ([], [])


def test_series_of_one_alert_are_collected_sorted_and_capped_at_ten(net, tmp_path):
    """AC-092.4: series with the same service and environment form one alert; at most 10 label sets are kept."""
    net.on(Q, [{"job": "shop-api", "deployment_environment_name": "prod", "instance": f"pod-{i:02d}"} for i in range(12, 0, -1)])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))[0]
    assert len(a.series) == 10 and a.series == sorted(a.series, key=lambda s: sorted(s.items()))


def test_a_rule_without_a_summary_has_an_empty_summary(net, tmp_path):
    """AC-092.4: the summary is optional."""
    net.on(Q, [{"job": "shop-api", "deployment_environment_name": "dev"}])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [{"name": "R", "query": Q, "severity": "info"}]}))[0]
    assert a.summary == "" and a.severity == "info"


# ---------------- AC-092.24 every environment ----------------

def test_every_environment_where_the_addon_runs_is_evaluated(net, tmp_path):
    """AC-092.24: the environments are those where a service runs, in dev, staging, prod order."""
    services = [{"name": "shop-api", "repo": "acme/shop-api", "environments": ["prod", "dev", "staging"]}]
    assert load(tmp_path, {"ui": "lgtm"}, services).envs == ["dev", "staging", "prod"]
    assert load(tmp_path / "b", {"ui": "lgtm"}).envs == ["dev", "prod"]


@pytest.mark.parametrize("labels, env", [
    ({"job": "shop-api", "deployment_environment_name": "staging"}, "staging"),
    ({"job": "shop-api", "deployment_environment": "prod"}, "prod"),
    ({"job": "shop-api", "environment": "dev"}, "dev"),
    ({"job": "shop-api", "env": "prod"}, "prod"),
    ({"job": "shop-api", "namespace": "shop-prod"}, "prod"),
    ({"job": "shop-api", "instance": "shop-api.shop-dev.svc:80"}, "dev"),
])
def test_the_environment_comes_from_the_series_labels(net, tmp_path, labels, env):
    """AC-092.24: deployment_environment_name/deployment_environment/environment/env, else namespace <app>-<env>, else the instance host."""
    net.on(Q, [labels])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))[0]
    assert a.environment == env


def test_a_series_without_an_environment_is_unknown_with_a_note(net, tmp_path):
    """AC-092.24 AC-092.8: no label maps to dev, staging or prod: environment `unknown` and a note that says so."""
    net.on(Q, [{"job": "shop-api"}])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))[0]
    assert a.environment == "unknown" and any("no environment label" in n for n in a.unmapped)


# ---------------- AC-092.5 built-in ServiceDown ----------------

def service_down(cfg):
    return [r for r in cfg.rules if r.name == "ServiceDown"]


def test_service_down_exists_per_service_with_metrics_and_environment(net, tmp_path):
    """AC-092.5: a built-in critical ServiceDown for each service that declares metrics, in each of its environments."""
    cfg = load(tmp_path, {"ui": "lgtm"})
    rules = service_down(cfg)
    assert {(r.service, r.environment) for r in rules} == {("shop-api", "dev"), ("shop-api", "prod")}      # shop-web has no metrics
    r = next(x for x in rules if x.environment == "dev")
    assert r.severity == "critical" and r.summary == "No metrics target of shop-api in dev has been up for 5 minutes"
    flat = " ".join(r.query.split())
    assert "absent_over_time" in flat and "[5m]" in flat and "< 1" in flat
    assert 'instance=~"shop-api\\\\.shop-dev\\\\.svc(:[0-9]+)?"' in flat


def test_service_down_fires_for_the_service_and_environment_whatever_the_series_labels(net, tmp_path):
    """AC-092.5: a ServiceDown series maps to its own service and environment, even when it has no labels."""
    cfg = load(tmp_path, {"ui": "lgtm"})
    dev = next(r for r in service_down(cfg) if r.environment == "dev")
    net.on(dev.query, [{}])
    alerts, errors = collect(cfg)
    assert errors == []
    (a,) = alerts
    assert (a.name, a.service, a.environment, a.severity, a.repo) == ("ServiceDown", "shop-api", "dev", "critical", "acme/shop-api")
    assert a.summary == "No metrics target of shop-api in dev has been up for 5 minutes"


def test_a_declared_service_down_rule_replaces_the_built_in(net, tmp_path):
    """AC-092.5: when a rule of that name is declared the built-in one is not added."""
    own = {"name": "ServiceDown", "query": "up == 0", "severity": "warning"}
    cfg = load(tmp_path, {"ui": "lgtm", "rules": [own]})
    assert [(r.query, r.service) for r in service_down(cfg)] == [("up == 0", None)]


def test_no_service_down_without_services_that_declare_metrics(net, tmp_path):
    """AC-092.5: services without `metrics` get no built-in rule."""
    cfg = load(tmp_path, {"ui": "lgtm"}, [{"name": "shop-web", "repo": "acme/shop-web", "environments": ["dev"]}])
    assert service_down(cfg) == []


# ---------------- AC-092.20 / AC-092.8 mapping ----------------

@pytest.mark.parametrize("labels, service, repo", [
    ({"service": "shop-web", "job": "shop-api"}, "shop-web", "acme/shop-web"),           # `service` wins over `job`
    ({"job": "shop-api"}, "shop-api", "acme/shop-api"),
    ({"job": "shop/shop-api"}, "shop-api", "acme/shop-api"),                            # OTLP service.namespace/service.name
])
def test_a_series_maps_to_the_services_yaml_entry_by_service_or_job(net, tmp_path, labels, service, repo):
    """AC-092.20: the `service` label (else `job`, also as <namespace>/<name>) names a services.yaml entry; its repo is the target."""
    net.on(Q, [{**labels, "deployment_environment_name": "dev"}])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))[0]
    assert (a.service, a.repo, a.unmapped) == (service, repo, [])


def test_a_series_that_matches_no_service_keeps_its_label_and_has_no_repo(net, tmp_path):
    """AC-092.8: an unknown service value is kept, there is no repo (so the gitops repo is the target), and a note names it."""
    net.on(Q, [{"service": "billing", "deployment_environment_name": "dev"}])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))[0]
    assert a.service == "billing" and a.repo is None
    assert any('"billing"' in n and "not a service in services.yaml" in n for n in a.unmapped)


def test_a_series_without_service_or_job_has_an_empty_service_and_a_note(net, tmp_path):
    """AC-092.8: no service or job label: service is empty and the note says so."""
    net.on(Q, [{"deployment_environment_name": "dev"}])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))[0]
    assert a.service == "" and a.repo is None and any("no service or job label" in n for n in a.unmapped)


def test_a_service_without_a_repo_maps_to_the_gitops_repo_with_a_note(net, tmp_path):
    """AC-092.8: a services.yaml entry without `repo`: no repo, and the note says the service has none."""
    net.on(Q, [{"job": "shop-batch", "deployment_environment_name": "dev"}])
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))[0]
    assert a.service == "shop-batch" and a.repo is None and any("shop-batch has no repo in services.yaml" in n for n in a.unmapped)


# ---------------- AC-092.23 Alertmanager ----------------

def am_entry(name, **labels):
    return {"labels": {"alertname": name, **labels}, "annotations": {"summary": f"{name} summary", "runbook": "https://wiki/x"},
            "startsAt": "2026-10-24T07:00:00Z", "status": {"state": "active", "silencedBy": [], "inhibitedBy": []}}


def test_active_alertmanager_alerts_are_read_and_mapped(net, tmp_path):
    """AC-092.23: every active alert is mapped like a rule alert; severity is the label, name the alertname, start the startsAt."""
    net.am = [am_entry("DiskFull", severity="critical", service="shop-api", deployment_environment_name="prod")]
    cfg = load(tmp_path, {"ui": "lgtm", "alertmanagerURL": "https://am.example.com"})
    alerts, errors = collect(cfg)
    assert errors == []
    (a,) = alerts
    assert (a.source, a.name, a.severity, a.environment, a.service, a.repo) == ("alertmanager", "DiskFull", "critical", "prod", "shop-api", "acme/shop-api")
    assert a.started_at == dt.datetime(2026, 10, 24, 7, 0, tzinfo=dt.timezone.utc) and a.summary == "DiskFull summary"
    assert a.query == "Alertmanager https://am.example.com" and a.annotations["runbook"] == "https://wiki/x"
    (url,) = net.am_calls()
    parsed = urllib.parse.urlparse(url)
    assert parsed.netloc == "am.example.com" and parsed.path == "/api/v2/alerts"
    assert urllib.parse.parse_qs(parsed.query)["active"] == ["true"]


@pytest.mark.parametrize("labels", [{}, {"severity": "page"}, {"severity": "CRITICAL!"}])
def test_a_missing_or_unknown_alertmanager_severity_is_warning(net, tmp_path, labels):
    """AC-092.23: a severity label that is missing or not critical/warning/info becomes `warning`."""
    net.am = [am_entry("X", service="shop-api", deployment_environment_name="dev", **labels)]
    (a,) = collect(load(tmp_path, {"ui": "lgtm", "alertmanagerURL": "https://am.example.com"}))[0]
    assert a.severity == "warning"


def test_only_active_alertmanager_alerts_count(net, tmp_path):
    """AC-092.23: suppressed alerts are not treated as firing."""
    gone = am_entry("Silenced", service="shop-api", deployment_environment_name="dev")
    gone["status"]["state"] = "suppressed"
    net.am = [gone, am_entry("Live", service="shop-api", deployment_environment_name="dev")]
    alerts, _ = collect(load(tmp_path, {"ui": "lgtm", "alertmanagerURL": "https://am.example.com"}))
    assert [a.name for a in alerts] == ["Live"]


def test_alertmanager_alerts_use_the_same_credential(net, monkeypatch, tmp_path):
    """AC-092.23 AC-092.19: the credential is sent to Alertmanager too."""
    monkeypatch.setenv("ALERTS_QUERY_AUTHORIZATION", "Bearer am")
    net.am = []
    collect(load(tmp_path, {"ui": "lgtm", "alertmanagerURL": "https://am.example.com"}))
    assert net.am_calls() and all(h.get("Authorization") == "Bearer am" for u, h in net.calls if "/api/v2/" in u)


# ---------------- AC-092.16 unreachable endpoints ----------------

@pytest.mark.parametrize("answer, reason", [
    ((0, "connection refused"), "connection refused"),
    ((401, "no"), "refused the credential (HTTP 401)"),
    ((403, "no"), "refused the credential (HTTP 403)"),
    ((500, "boom"), "HTTP 500"),
    ((200, "not json"), "unreadable answer"),
    ((200, json.dumps({"status": "error", "error": "bad query"})), "error: bad query"),
])
def test_an_unreachable_or_refusing_prometheus_is_one_source_error(net, tmp_path, answer, reason):
    """AC-092.16: the endpoint and the reason are reported as one SourceError; no alert comes out of a failed read."""
    import alertsources
    net.prom_error = answer
    alerts, errors = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE]}))
    assert alerts == [] and len(errors) == 1 and isinstance(errors[0], alertsources.SourceError)
    assert errors[0].endpoint == LGTM and reason in errors[0].reason
    assert str(errors[0]) == f"{LGTM}: {errors[0].reason}"


def test_an_unreachable_alertmanager_is_a_source_error_and_rules_still_run(net, tmp_path):
    """AC-092.16 AC-092.23: a failing Alertmanager does not hide what Prometheus reports, and is reported."""
    net.am_error = (503, "down")
    net.on(Q, [{"job": "shop-api", "deployment_environment_name": "dev"}])
    alerts, errors = collect(load(tmp_path, {"ui": "lgtm", "rules": [RULE], "alertmanagerURL": "https://am.example.com"}))
    assert [a.name for a in alerts] == ["HighErrorRate"]
    assert len(errors) == 1 and errors[0].endpoint == "https://am.example.com" and "HTTP 503" in errors[0].reason


def test_urls_are_redacted_in_source_errors(net, tmp_path):
    """AC-092.16 AC-092.10: a secret inside an endpoint URL never appears in the error."""
    net.prom_error = (0, "refused")
    cfg = load(tmp_path, {"exportTo": "https://o.example.com", "queryURL": f"https://prom.example.com/{TOKEN}", "rules": [RULE]})
    _, errors = collect(cfg)
    assert errors and TOKEN not in str(errors[0])


def test_the_default_http_get_and_kubectl_never_raise(monkeypatch):
    """AC-092.16: transport failures come back as (0, reason) and a missing kubectl as a failing exit code (both stubbed here)."""
    import urllib.error
    import urllib.request

    import alertsources

    def refuse(*a, **k):
        raise urllib.error.URLError("connection refused")

    def missing(*a, **k):
        raise FileNotFoundError("kubectl")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    status, reason = alertsources.http_get("http://prom.invalid/api/v1/query", headers={}, timeout=0.5)
    assert status == 0 and "refused" in reason
    monkeypatch.setattr(alertsources.subprocess, "run", missing)
    code, _, err = alertsources.kubectl(["version"], timeout=1.0)
    assert code != 0 and err
