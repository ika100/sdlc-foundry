"""Spec 101: further acceptance tests the plan adds to test_telemetry.py (addon found from a service repo, when finish compares)."""
import subprocess

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
