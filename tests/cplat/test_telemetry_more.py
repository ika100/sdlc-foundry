"""Spec 101: further acceptance tests the plan adds to test_telemetry.py (addon found from a service repo, when finish compares)."""

import pytest

import runs
import smoke
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_telemetry import repo  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def service_repo(repo, slugs="  - acme/shop-gitops\n"):
    (repo / ".platform-app.yml").write_text("gitops_apps:\n" + slugs)
    return repo


def fake_gh(monkeypatch, apps):
    """`gh api` answers for the gitops-app repo: applications/ listing and each app.yaml."""
    import json
    calls = []

    def gh(args, *, cwd, check=True):
        path = args[1]
        calls.append(path)
        if path.endswith("/applications"):
            return json.dumps([{"name": a, "type": "dir"} for a in apps])
        for a, text in apps.items():
            if path.endswith(f"/applications/{a}/app.yaml"):
                return text
        return ""
    monkeypatch.setattr(smoke, "gh", gh)
    return calls


def test_the_addon_is_found_from_a_service_repo(repo, monkeypatch):
    """AC-101.2: `.platform-app.yml` names the gitops-app; its app.yaml (read as the platform reads it) has `ui: lgtm`."""
    import telemetry
    service_repo(repo)
    fake_gh(monkeypatch, {"shop": "observability:\n  ui: lgtm\n"})
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "kind-dev")
    env, _, forward = telemetry.session_env(repo, "run-1", "ship")
    assert forward is not None and "kind-dev" in repr(vars(forward)) and env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"


def test_a_linked_gitops_app_without_the_addon_stays_off(repo, monkeypatch):
    """AC-101.2: the linked gitops-app has no lgtm UI: nothing starts."""
    import telemetry
    service_repo(repo)
    fake_gh(monkeypatch, {"shop": "observability:\n  collector: true\n"})
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "kind-dev")
    assert telemetry.session_env(repo, "run-1", "ship") == ({}, None, None)


def test_gitops_is_not_asked_without_a_context(repo, monkeypatch):
    """AC-101.4: no configured context: the linked repo is not even read (no gh call, no delay)."""
    import telemetry
    service_repo(repo)
    calls = fake_gh(monkeypatch, {"shop": "observability:\n  ui: lgtm\n"})
    assert telemetry.session_env(repo, "run-1", "ship") == ({}, None, None) and calls == []


def started(monkeypatch, telemetry_section):
    import telemetry
    seen = []
    monkeypatch.setattr(telemetry, "compare", lambda run_id, usage: seen.append(run_id) or {"totals": {}, "difference": {}})
    rid = runs.start("ship", repo="acme/a")
    if telemetry_section:
        runs.set_section(rid, "telemetry", {"backend": "endpoint", "endpoint": "http://localhost:4318"})
    return rid, seen


def test_finish_compares_when_the_record_has_a_telemetry_section(clock, store, monkeypatch, tmp_path):  # noqa: F811
    """AC-101.10: a run with telemetry on gets the comparison."""
    import runs_usage
    rid, seen = started(monkeypatch, True)
    monkeypatch.setattr(runs_usage, "for_run", lambda rec, **k: {"totals": {}})
    runs.finish(rid, "done")
    assert seen == [rid]
    (r,) = stored(store)
    assert r["usage"]["otel"] == {"totals": {}, "difference": {}}


def test_finish_never_compares_without_telemetry(clock, store, monkeypatch):  # noqa: F811
    """AC-101.10: telemetry off (no section, no endpoint): compare is not called and the record has no `otel`."""
    import runs_usage
    rid, seen = started(monkeypatch, False)
    monkeypatch.setattr(runs_usage, "for_run", lambda rec, **k: {"totals": {}})
    runs.finish(rid, "done")
    assert seen == []
    (r,) = stored(store)
    assert "otel" not in r["usage"]


def test_compare_never_takes_more_than_its_budget(monkeypatch, tmp_path):
    """AC-101.10: a store that answers slowly is given up after 5 s in total, across both queries."""
    import telemetry
    (tmp_path / "xdg" / "sdlc-foundry").mkdir(parents=True)
    (tmp_path / "xdg" / "sdlc-foundry" / "settings.yml").write_text("telemetry:\n  query_url: http://localhost:9090\n")
    timeouts = []

    def slow(url, timeout=0, **k):
        timeouts.append(timeout)
        raise TimeoutError()
    monkeypatch.setattr(telemetry, "http_get", slow)
    assert telemetry.compare("run-1", {"totals": {}}) is None
    assert timeouts and all(t <= telemetry.COMPARE_SECONDS for t in timeouts)


# ---------------- AC-101.7 (metrics only, no identity switches, user OTEL_* cannot widen) ----------------

def test_only_metrics_are_exported(repo, monkeypatch):
    """AC-101.7: no logs/events and no traces exporter; metrics stay on."""
    import telemetry
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    env, _, _ = telemetry.session_env(repo, "r1", "ship")
    assert env["OTEL_LOGS_EXPORTER"] == "none" and env["OTEL_TRACES_EXPORTER"] == "none" and env["OTEL_METRICS_EXPORTER"] == "otlp"


@pytest.mark.parametrize("name", ["SESSION_ID", "ACCOUNT_UUID", "VERSION", "ENTRYPOINT", "REPOSITORY"])
def test_each_identity_switch_is_false(repo, monkeypatch, name):
    """AC-101.7: every switchable identity attribute is off; resource attributes stay on so cplat_run_id is a label."""
    import telemetry
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    env, _, _ = telemetry.session_env(repo, "r1", "ship")
    assert env[f"OTEL_METRICS_INCLUDE_{name}"] == "false" and env["OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES"] == "true"


USER_OTEL = {"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://evil.example.com", "OTEL_EXPORTER_OTLP_HEADERS": "authorization=x",
             "OTEL_TRACES_EXPORTER": "otlp", "CLAUDE_CODE_OTEL_FLUSH_TIMEOUT_MS": "1"}


def test_user_otel_variables_do_not_reach_a_session_with_telemetry(repo, monkeypatch):
    """AC-101.7: with telemetry on, the user's OTEL_* / CLAUDE_CODE_OTEL_* variables are dropped; ours and the user's resource pairs stay."""
    import telemetry
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "team=blue")
    otel, _, _ = telemetry.session_env(repo, "r1", "ship")
    merged = telemetry.merge_env({**USER_OTEL, "PATH": "/bin", "OTEL_RESOURCE_ATTRIBUTES": "team=blue"}, otel)
    assert "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT" not in merged and "OTEL_EXPORTER_OTLP_HEADERS" not in merged
    assert "CLAUDE_CODE_OTEL_FLUSH_TIMEOUT_MS" not in merged and merged["OTEL_TRACES_EXPORTER"] == "none"
    assert merged["PATH"] == "/bin" and merged["OTEL_RESOURCE_ATTRIBUTES"].endswith("team=blue")


def test_user_otel_variables_are_untouched_with_telemetry_off():
    """AC-101.4/101.7: telemetry off: the environment is exactly as it was."""
    import telemetry
    base = {**USER_OTEL, "PATH": "/bin"}
    assert telemetry.merge_env(base, {}) == base
