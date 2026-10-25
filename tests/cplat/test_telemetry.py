"""Spec 101: run usage is exported live to OpenTelemetry (AC-101.1 .. AC-101.11). Acceptance tests, written before the code.

Contract (design.md): `telemetry.session_env(repo, run_id, kind) -> (env, note, forward)` and
`telemetry.compare(run_id, usage) -> dict | None`; settings `telemetry: {endpoint, context, allow_remote, query_url}`;
env CPLAT_OTLP_ENDPOINT, CPLAT_OTLP_ALLOW_REMOTE, CPLAT_KUBE_CONTEXT.

Seams faked here (the coder must provide them under these names in `scripts/cplat/telemetry.py`):
  telemetry.reachable(endpoint) -> bool      the one TCP check per command (1 s); default fake: True
  telemetry.start_forward(forward, ...)      starts the kubectl port-forward; a failure raises OSError or returns None/False
  telemetry.http_get(url, ...) -> str        the PromQL HTTP query; returns the Prometheus JSON body, raises on any error
Assumptions: conftest.py does not clear CPLAT_OTLP_* / CPLAT_KUBE_CONTEXT / OTEL_* / CLAUDE_CODE_ENABLE_TELEMETRY, so the autouse
fixture below does; a `Forward` value exposes its kubectl arguments in `vars(forward)`; the addon is found from
`applications/<app>/app.yaml` of a gitops-app repo.
"""
import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

import pytest

import core
import headless
import runs
import runs_bench
import ship
from test_headless import fake_claude, repo as hl_repo, set_state  # noqa: F401  (fixture)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_report import put, rec
from usage_support import SESSION, T0, call, projects, run_with_phases, stored_records, write_session  # noqa: F401

ROOT = core.PLATFORM_ROOT
DASH = ROOT / "templates" / "gitops-app" / "observability" / "dashboards"
CLUSTER_SH = ROOT / "templates" / "gitops-app" / "scripts" / "local-cluster.sh"
CONTENT = ("OTEL_LOG_USER_PROMPTS", "OTEL_LOG_TOOL_DETAILS", "OTEL_LOG_TOOL_CONTENT", "OTEL_LOG_ASSISTANT_RESPONSES", "OTEL_LOG_RAW_API_BODIES")
ENDPOINT = "http://127.0.0.1:4318"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in list(os.environ):
        if k.startswith(("OTEL_", "CPLAT_OTLP_")) or k in ("CPLAT_KUBE_CONTEXT", "CLAUDE_CODE_ENABLE_TELEMETRY"):
            monkeypatch.delenv(k)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    try:
        import telemetry
    except ImportError:
        return
    monkeypatch.setattr(telemetry, "reachable", lambda *a, **k: True, raising=False)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "shop-api"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return r


def project_settings(repo, **telemetry_keys):
    import yaml
    (repo / ".platform-settings.yml").write_text(yaml.safe_dump({"telemetry": telemetry_keys}))


def addon_repo(repo):
    app = repo / "applications" / "shop"
    app.mkdir(parents=True)
    (app / "app.yaml").write_text("observability:\n  ui: lgtm\n")
    return repo


def attrs(env):
    return dict(p.split("=", 1) for p in env["OTEL_RESOURCE_ATTRIBUTES"].split(","))


def session(repo, run_id="run-123", kind="ship"):
    import telemetry
    return telemetry.session_env(repo, run_id, kind)


def dump_env(tmp_path, monkeypatch, exit_code=0):
    """A fake `claude` that writes its environment to env.txt (in the repo, its cwd) and exits with `exit_code`."""
    fake_claude(tmp_path, monkeypatch, f"env > env.txt\nexit {exit_code}")


def seen_env(repo):
    return dict(ln.split("=", 1) for ln in (repo / "env.txt").read_text().splitlines() if "=" in ln)


def run_claude(tmp_path, monkeypatch, repo, run_id="run-123"):
    exe = tmp_path / "claude"
    log = tmp_path / "log.txt"
    return headless.run_once([str(exe)], repo, log, 1, run_id)


# ---------------- AC-101.1 ----------------

def test_endpoint_by_env_turns_telemetry_on():  # AC-101.1
    """AC-101.1: CPLAT_OTLP_ENDPOINT alone turns the session's native telemetry on, exporting to that endpoint."""
    os.environ["CPLAT_OTLP_ENDPOINT"] = ENDPOINT
    try:
        env, note, forward = session(Path("."))
    finally:
        del os.environ["CPLAT_OTLP_ENDPOINT"]
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_METRICS_EXPORTER"] == "otlp" and env["OTEL_LOGS_EXPORTER"] == "otlp"
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == ENDPOINT
    assert env["OTEL_METRIC_EXPORT_INTERVAL"] == "10000"
    assert env["OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"] == "cumulative"
    assert note is None and forward is None


def test_endpoint_by_project_setting_turns_telemetry_on(repo):  # AC-101.1
    """AC-101.1: `telemetry.endpoint` in the settings files does the same; the environment variable wins over it."""
    project_settings(repo, endpoint="http://localhost:4999")
    env, _, _ = session(repo)
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4999" and env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    os.environ["CPLAT_OTLP_ENDPOINT"] = ENDPOINT
    try:
        env, _, _ = session(repo)
    finally:
        del os.environ["CPLAT_OTLP_ENDPOINT"]
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == ENDPOINT


def test_endpoint_by_user_setting_turns_telemetry_on(repo, tmp_path):  # AC-101.1
    """AC-101.1: the user settings file counts too."""
    f = tmp_path / "xdg" / "sdlc-foundry" / "settings.yml"
    f.parent.mkdir(parents=True)
    f.write_text("telemetry:\n  endpoint: http://localhost:4777\n")
    env, _, _ = session(repo)
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4777"


def test_a_headless_session_gets_the_telemetry_environment(hl_repo, tmp_path, monkeypatch):  # AC-101.1
    """AC-101.1: `cplat headless` starts claude -p with the variables, and the run record names the backend."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "env > env.txt\nf=$(git rev-parse --git-common-dir)/cplat-ship.json\n"
                                       "sed -i.bak 's/\"phase\": \"[a-z]*\"/\"phase\": \"done\"/' \"$f\"")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo)]) == 0
    e = seen_env(hl_repo)
    assert e["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1" and e["OTEL_EXPORTER_OTLP_ENDPOINT"] == ENDPOINT
    assert attrs(e)["cplat.run_id"]


def test_a_headless_run_record_has_the_telemetry_section(hl_repo, tmp_path, monkeypatch, store, clock):  # AC-101.1
    """AC-101.1 (contract): record `telemetry: {backend: "endpoint", endpoint}`."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "f=$(git rev-parse --git-common-dir)/cplat-ship.json\n"
                                       "sed -i.bak 's/\"phase\": \"[a-z]*\"/\"phase\": \"done\"/' \"$f\"")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo)]) == 0
    (r,) = [x for x in stored(store) if x["kind"] == "headless"]
    assert r["telemetry"] == {"backend": "endpoint", "endpoint": ENDPOINT}


def test_a_benchmark_session_gets_the_telemetry_environment(hl_repo, tmp_path, monkeypatch):  # AC-101.1
    """AC-101.1: the session `cplat runs benchmark` starts (through its headless driver) exports too."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "env > env.txt\nf=$(git rev-parse --git-common-dir)/cplat-ship.json\n"
                                       "sed -i.bak 's/\"phase\": \"[a-z]*\"/\"phase\": \"done\"/' \"$f\"")
    assert runs_bench._run_headless(["/svc:ship 7", "--repo", str(hl_repo)], "bench-1") == "done"
    e = seen_env(hl_repo)
    assert e["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1" and e["OTEL_EXPORTER_OTLP_ENDPOINT"] == ENDPOINT


# ---------------- AC-101.2 ----------------

def test_the_addon_with_a_context_exports_through_a_port_forward(repo, monkeypatch):  # AC-101.2
    """AC-101.2: gitops-app with `observability: {ui: lgtm}` plus a configured context: a kubectl port-forward to svc/lgtm
    in namespace observability, exporting to 127.0.0.1:<port>."""
    addon_repo(repo)
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "kind-dev")
    env, _, forward = session(repo)
    assert forward is not None
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", env["OTEL_EXPORTER_OTLP_ENDPOINT"])
    text = repr(vars(forward))
    for part in ("kubectl", "kind-dev", "observability", "port-forward", "svc/lgtm", "4318"):
        assert part in text
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"


def test_the_context_may_come_from_the_settings(repo):  # AC-101.2
    """AC-101.2: `telemetry.context` in the settings files is a configured context."""
    addon_repo(repo)
    project_settings(repo, context="kind-from-settings")
    _, _, forward = session(repo)
    assert forward is not None and "kind-from-settings" in repr(vars(forward))


def test_an_explicit_endpoint_wins_and_no_forward_starts(repo, monkeypatch):  # AC-101.2
    """AC-101.2: with an explicit endpoint the addon's collector is not used."""
    addon_repo(repo)
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "kind-dev")
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "http://localhost:4999")
    env, _, forward = session(repo)
    assert forward is None and env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4999"


def test_the_addon_without_a_context_stays_off_and_a_context_is_never_guessed(repo, monkeypatch):  # AC-101.2
    """AC-101.2 (design): no configured context: no variables, no forward."""
    addon_repo(repo)
    env, note, forward = session(repo)
    assert env == {} and forward is None


def test_a_context_without_the_addon_stays_off(repo, monkeypatch):  # AC-101.2
    """AC-101.2: the addon is the trigger; a context alone does nothing."""
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "kind-dev")
    env, _, forward = session(repo)
    assert env == {} and forward is None


def test_an_app_without_the_lgtm_ui_is_not_the_addon(repo, monkeypatch):  # AC-101.2
    """AC-101.2: `observability` without `ui: lgtm` is not the addon."""
    app = repo / "applications" / "shop"
    app.mkdir(parents=True)
    (app / "app.yaml").write_text("observability:\n  collector: true\n")
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "kind-dev")
    env, _, forward = session(repo)
    assert env == {} and forward is None


# ---------------- AC-101.3 ----------------

def test_resource_attributes_carry_run_kind_repo_and_version(repo):  # AC-101.3
    """AC-101.3: cplat.run_id, cplat.kind, cplat.repo and cplat.platform_version on everything exported."""
    os.environ["CPLAT_OTLP_ENDPOINT"] = ENDPOINT
    try:
        env, _, _ = session(repo, "run-abc", "build")
    finally:
        del os.environ["CPLAT_OTLP_ENDPOINT"]
    a = attrs(env)
    assert a["cplat.run_id"] == "run-abc" and a["cplat.kind"] == "build"
    assert "shop-api" in urllib.parse.unquote(a["cplat.repo"])
    assert urllib.parse.unquote(a["cplat.platform_version"]) == core.platform_version()


def test_the_users_own_resource_attributes_are_kept_after_ours(repo, monkeypatch):  # AC-101.3
    """AC-101.3: the user's OTEL_RESOURCE_ATTRIBUTES pairs stay, after ours."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "team=blue,env=dev")
    env, _, _ = session(repo)
    value = env["OTEL_RESOURCE_ATTRIBUTES"]
    assert value.startswith("cplat.run_id=") and value.endswith("team=blue,env=dev")
    assert attrs(env)["cplat.run_id"] == "run-123"


def test_attribute_values_are_percent_encoded(repo, monkeypatch):  # AC-101.3
    """AC-101.3: no spaces or commas in a value (OTEL_RESOURCE_ATTRIBUTES is key=value pairs)."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    env, _, _ = session(repo, "run 1,2", "ship it")
    assert len(env["OTEL_RESOURCE_ATTRIBUTES"].split(",")) == 4
    assert " " not in env["OTEL_RESOURCE_ATTRIBUTES"].split("cplat.platform_version")[0]


# ---------------- AC-101.4 ----------------

def test_nothing_configured_is_silent_and_starts_nothing(repo, monkeypatch, capsys):  # AC-101.4
    """AC-101.4: no endpoint, no addon: no variables, no note, no output, no subprocess, no socket, no reachability check."""
    import telemetry
    def boom(*a, **k):
        raise AssertionError("telemetry started something")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr("socket.create_connection", boom)
    monkeypatch.setattr(telemetry, "reachable", boom)
    assert telemetry.session_env(repo, "run-1", "ship") == ({}, None, None)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_nothing_configured_leaves_the_session_environment_alone(hl_repo, tmp_path, monkeypatch, capsys):  # AC-101.4
    """AC-101.4: the session sees no OTEL variables and the command prints no telemetry line."""
    dump_env(tmp_path, monkeypatch)
    assert run_claude(tmp_path, monkeypatch, hl_repo) == 0
    e = seen_env(hl_repo)
    assert not [k for k in e if k.startswith("OTEL_")] and "CLAUDE_CODE_ENABLE_TELEMETRY" not in e
    out = capsys.readouterr()
    assert "telemetry" not in (out.out + out.err).lower()


# ---------------- AC-101.5 ----------------

def test_an_unreachable_endpoint_changes_neither_result_nor_record(hl_repo, tmp_path, monkeypatch, capsys):  # AC-101.5
    """AC-101.5: unreachable endpoint: same exit code as without telemetry, at most one warning line."""
    import telemetry
    dump_env(tmp_path, monkeypatch, exit_code=3)
    assert run_claude(tmp_path, monkeypatch, hl_repo) == 3
    capsys.readouterr()
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "http://localhost:4999")
    monkeypatch.setattr(telemetry, "reachable", lambda *a, **k: False)
    assert run_claude(tmp_path, monkeypatch, hl_repo) == 3
    out = capsys.readouterr()
    lines = [ln for ln in (out.out + out.err).splitlines() if "localhost:4999" in ln or "telemetry" in ln.lower()]
    assert len(lines) <= 1


def test_an_unreachable_endpoint_gives_one_note_line(repo, monkeypatch):  # AC-101.5
    """AC-101.5 (design): one single-line note naming the endpoint; the variables are still set."""
    import telemetry
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "http://localhost:4999")
    monkeypatch.setattr(telemetry, "reachable", lambda *a, **k: False)
    env, note, _ = session(repo)
    assert note and "\n" not in note and "localhost:4999" in note
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4999"


@pytest.mark.parametrize("failure", ["raises", "none"])
def test_a_failed_port_forward_is_one_warning_and_the_run_goes_on(hl_repo, tmp_path, monkeypatch, capsys, failure):  # AC-101.5
    """AC-101.5: the forward cannot start: same result, no telemetry variables, at most one warning."""
    import telemetry
    addon_repo(hl_repo)
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "kind-dev")

    def failing(*a, **k):
        if failure == "raises":
            raise OSError("kubectl: not found")
        return None
    monkeypatch.setattr(telemetry, "start_forward", failing, raising=False)
    dump_env(tmp_path, monkeypatch, exit_code=4)
    assert run_claude(tmp_path, monkeypatch, hl_repo) == 4
    e = seen_env(hl_repo)
    assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in e
    out = capsys.readouterr()
    assert len([ln for ln in (out.out + out.err).splitlines() if "forward" in ln.lower() or "telemetry" in ln.lower()]) <= 1


def test_the_record_is_still_written_with_an_unreachable_endpoint(clock, store, monkeypatch):  # AC-101.5
    """AC-101.5: a failing comparison (backend down) never stops the record."""
    import telemetry
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "http://localhost:4999")
    monkeypatch.setattr(telemetry, "http_get", lambda *a, **k: (_ for _ in ()).throw(OSError("down")), raising=False)
    rid = runs.start("ship", repo="acme/a")
    runs.finish(rid, "done")
    (r,) = stored(store)
    assert r["outcome"] == "done"


# ---------------- AC-101.6 ----------------

@pytest.mark.parametrize("url", ["https://otel.example.com:4318", "http://203.0.113.9:4318", "http://10.0.0.5:4318",
                                 "http://localhost.evil.com:4318", "http://evilsvc.com:4318", "http://grafana.localhost.org:4318"])
def test_a_remote_endpoint_is_refused_without_opt_in(repo, monkeypatch, url):  # AC-101.6
    """AC-101.6: not local and no opt-in: telemetry stays off, one message names the endpoint and the opt-in setting."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", url)
    env, note, forward = session(repo)
    assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in env and "OTEL_EXPORTER_OTLP_ENDPOINT" not in env and forward is None
    assert note and "\n" not in note and url in note and "allow_remote" in note


def test_setting_the_endpoint_never_implies_the_opt_in(repo):  # AC-101.6
    """AC-101.6: a remote endpoint in the settings file without `allow_remote` is refused."""
    project_settings(repo, endpoint="https://otel.example.com:4318")
    env, note, _ = session(repo)
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env and note and "otel.example.com" in note


def test_a_remote_endpoint_exports_with_the_opt_in_by_setting(repo):  # AC-101.6
    """AC-101.6: `telemetry.allow_remote: true`."""
    project_settings(repo, endpoint="https://otel.example.com:4318", allow_remote=True)
    env, note, _ = session(repo)
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://otel.example.com:4318" and env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"


def test_a_remote_endpoint_exports_with_the_opt_in_by_env(repo, monkeypatch):  # AC-101.6
    """AC-101.6: CPLAT_OTLP_ALLOW_REMOTE=1."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", "https://otel.example.com:4318")
    monkeypatch.setenv("CPLAT_OTLP_ALLOW_REMOTE", "1")
    env, _, _ = session(repo)
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://otel.example.com:4318"


@pytest.mark.parametrize("url", ["http://localhost:4318", "http://127.0.0.1:4318", "http://127.5.6.7:4318", "http://[::1]:4318",
                                 "http://lgtm.observability.svc:4318", "http://lgtm.observability.svc.cluster.local:4318",
                                 "http://grafana.localhost:4318"])
def test_local_hosts_need_no_opt_in(repo, monkeypatch, url):  # AC-101.6
    """AC-101.6: localhost, 127/8, ::1, *.svc, *.svc.cluster.local and *.localhost are local."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", url)
    env, note, _ = session(repo)
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == url and note is None


# ---------------- AC-101.7 ----------------

def test_content_switches_are_off(repo, monkeypatch):  # AC-101.7
    """AC-101.7: all five content switches are 0 when telemetry is on."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    env, _, _ = session(repo)
    assert {k: env[k] for k in CONTENT} == {k: "0" for k in CONTENT}


def test_content_switches_win_over_the_users_environment(hl_repo, tmp_path, monkeypatch):  # AC-101.7
    """AC-101.7: even when the user's environment turned prompt logging on, the session sees 0."""
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    for k in CONTENT:
        monkeypatch.setenv(k, "1")
    dump_env(tmp_path, monkeypatch)
    assert run_claude(tmp_path, monkeypatch, hl_repo) == 0
    e = seen_env(hl_repo)
    assert {k: e[k] for k in CONTENT} == {k: "0" for k in CONTENT}


# ---------------- AC-101.8 ----------------

def panels(node):
    if isinstance(node, dict):
        if "title" in node and ("targets" in node or "type" in node):
            yield node
        for v in node.values():
            yield from panels(v)
    elif isinstance(node, list):
        for v in node:
            yield from panels(v)


def dashboard():
    files = sorted(DASH.glob("*.json"))
    assert files, f"no dashboard JSON in {DASH}"
    return json.loads((DASH / "claude-code-usage.json").read_text())


def test_the_dashboard_has_the_four_views():  # AC-101.8
    """AC-101.8: panels for tokens and cost per run, per model, per day and the coordinator's share."""
    ps = list(panels(dashboard()))
    titles = " | ".join(p["title"].lower() for p in ps)
    for word in ("run", "model", "day", "coordinator"):
        assert word in titles
    exprs = " ".join(t.get("expr", "") for p in ps for t in p.get("targets", []))
    assert "claude_code_token_usage_tokens_total" in exprs and "claude_code_cost_usage_USD_total" in exprs
    assert "cplat_run_id" in exprs and "model" in exprs and "agent_name" in exprs


def test_the_local_cluster_script_provisions_the_dashboard():  # AC-101.8
    """AC-101.8: local-cluster.sh ships the dashboard file into the otel-lgtm pod."""
    text = CLUSTER_SH.read_text()
    assert "claude-code-usage.json" in text and "dashboards" in text


# ---------------- AC-101.9 / 101.10 ----------------

TRANSCRIPT = {"input": 1000, "output": 100, "cache_read": 9000, "cache_write": 50, "cost_usd": 1.0}
OTEL_TYPES = {"input": 1500, "output": 400, "cacheRead": 9000, "cacheCreation": 70}


def prom(result):
    return json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}})


class Backend:
    def __init__(self, tokens=None, cost="1.25"):
        self.tokens = OTEL_TYPES if tokens is None else tokens
        self.cost = cost
        self.urls = []

    def __call__(self, url, *a, **k):
        self.urls.append(url)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("query", [""])[0]
        if "cost" in q:
            return prom([{"metric": {}, "value": [1, self.cost]}] if self.cost is not None else [])
        return prom([{"metric": {"type": t}, "value": [1, str(v)]} for t, v in self.tokens.items()])


@pytest.fixture()
def backend(monkeypatch, repo):
    f = Path(os.environ["XDG_CONFIG_HOME"]) / "sdlc-foundry" / "settings.yml"
    f.parent.mkdir(parents=True)
    f.write_text("telemetry:\n  query_url: http://localhost:9090\n")
    b = Backend()
    try:
        import telemetry
        monkeypatch.setattr(telemetry, "http_get", b, raising=False)
    except ImportError:
        pass
    return b


def test_compare_queries_by_run_id_and_returns_totals_and_difference(backend):  # AC-101.9
    """AC-101.9: PromQL by cplat_run_id; totals per token type and cost, and otel minus transcript per type."""
    import telemetry
    out = telemetry.compare("run-9", {"totals": dict(TRANSCRIPT)})
    queries = [urllib.parse.unquote_plus(u) for u in backend.urls]
    assert queries and all('cplat_run_id="run-9"' in q for q in queries) and all(u.startswith("http://localhost:9090") for u in backend.urls)
    assert out["totals"] == {"input": 1500, "output": 400, "cache_read": 9000, "cache_write": 70, "cost_usd": 1.25}
    d = out["difference"]
    assert (d["input"], d["output"], d["cache_read"], d["cache_write"]) == (500, 300, 0, 20)
    assert d["cost_usd"] == pytest.approx(0.25)


def test_compare_without_a_configured_backend_is_none(monkeypatch):  # AC-101.10
    """AC-101.10: no query_url and no addon: no figures, and no query is made."""
    import telemetry
    def boom(*a, **k):
        raise AssertionError("queried without a backend")
    monkeypatch.setattr(telemetry, "http_get", boom, raising=False)
    assert telemetry.compare("run-9", {"totals": dict(TRANSCRIPT)}) is None


@pytest.mark.parametrize("how", ["error", "timeout", "garbage", "no-series"])
def test_compare_without_figures_is_none(backend, monkeypatch, how):  # AC-101.10
    """AC-101.10: metrics store unreachable, slow, answering rubbish, or no figures for the run id: None."""
    import telemetry
    if how == "error":
        monkeypatch.setattr(telemetry, "http_get", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")), raising=False)
    elif how == "timeout":
        monkeypatch.setattr(telemetry, "http_get", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()), raising=False)
    elif how == "garbage":
        monkeypatch.setattr(telemetry, "http_get", lambda *a, **k: "<html>", raising=False)
    else:
        monkeypatch.setattr(telemetry, "http_get", Backend(tokens={}, cost=None), raising=False)
    assert telemetry.compare("run-9", {"totals": dict(TRANSCRIPT)}) is None


CANNED = {"totals": {"input": 1500, "output": 400, "cache_read": 9000, "cache_write": 70, "cost_usd": 1.25},
          "difference": {"input": 500, "output": 300, "cache_read": 0, "cache_write": 20, "cost_usd": 0.25}}
PHASES = [("plan", 10), ("build", 60)]


def finished(clock, store, projects, monkeypatch, canned):
    import telemetry
    monkeypatch.setenv("CPLAT_OTLP_ENDPOINT", ENDPOINT)
    monkeypatch.setattr(telemetry, "compare", lambda run_id, usage: canned, raising=False)
    main = [call(f"m{n}", 20 + n * 30) for n in range(4)]
    write_session(projects, SESSION, main, {"a1": ({"agentType": "svc:coder"}, [call("c1", 70, o=33)])})
    return run_with_phases(clock, store, PHASES, 200)


def test_finish_notes_the_otel_totals_and_difference(clock, store, projects, monkeypatch):  # AC-101.9
    """AC-101.9: the record's usage.otel is the comparison; the transcript totals stay beside it."""
    r = finished(clock, store, projects, monkeypatch, CANNED)
    assert r["usage"]["otel"] == CANNED
    assert r["usage"]["totals"]["calls"] == 5


def test_finish_without_figures_has_no_otel_key(clock, store, projects, monkeypatch):  # AC-101.10
    """AC-101.10: compare returns None: no `otel` key in usage."""
    r = finished(clock, store, projects, monkeypatch, None)
    assert "otel" not in r["usage"] and r["usage"]["totals"]["calls"] == 5


def test_the_report_output_is_the_same_with_or_without_otel(store, capsys):  # AC-101.10
    """AC-101.10: `cplat runs report` (text and --json) ignores usage.otel, so output is as before this spec."""
    z = {"calls": 1, "failed_calls": 0, "input": 10, "output": 5, "cache_read": 0, "cache_write": 0, "cost_usd": 0.5}
    usage = {"sessions": ["s"], "price_table": "2026-10-25", "incomplete": None,
             "totals": {**z, "cost_complete": True, "models_without_price": []},
             "by_phase": {"unphased": z}, "by_role": {"main": z}, "by_model": {"m": z}}
    outputs = []
    for extra in ({}, {"otel": CANNED}):
        store.files.clear()
        put(store, rec("r1", "2026-10-20T10:00:00Z", usage={**usage, **extra}))
        row = []
        for args in (["report"], ["report", "--json"]):
            assert runs.main(args) == 0
            row.append(capsys.readouterr().out)
        outputs.append(row)
    assert outputs[0] == outputs[1]


# ---------------- AC-101.11 ----------------

def test_transcript_figures_phases_and_roles_do_not_change(clock, store, projects, monkeypatch):  # AC-101.11
    """AC-101.11: with OTel figures the record's transcript-derived totals, by_phase, by_role and by_model equal a run without them."""
    with_otel = finished(clock, store, projects, monkeypatch, CANNED)["usage"]
    store.files.clear()
    # setup: separate claims per run (099 shares calls between overlapping claims)
    import runs_usage
    runs_usage._save([])
    without = finished(clock, store, projects, monkeypatch, None)["usage"]
    with_otel = {k: v for k, v in with_otel.items() if k != "otel"}
    assert with_otel == without
    assert set(with_otel["by_role"]) >= {"main", "svc:coder"} and "build" in with_otel["by_phase"]
