"""Live OpenTelemetry export of a Claude Code session's usage (spec 101, design.md).

`session_env(repo, run_id, kind)` decides the environment of one `claude -p` session: explicit endpoint
(CPLAT_OTLP_ENDPOINT, then `telemetry.endpoint` in the settings files), else the gitops-app's lgtm addon through a
`kubectl port-forward` on a configured context (`telemetry.context` or CPLAT_KUBE_CONTEXT). Nothing found: nothing changes.
Only local endpoints export unless `telemetry.allow_remote` / CPLAT_OTLP_ALLOW_REMOTE=1. Content logging is forced off.
`session(...)` wraps it for a caller: starts and stops the forward, prints at most one warning, never raises.
`compare(run_id, usage)` reads the run's totals back from the metrics store (PromQL) after the run: the `usage.otel` note.
"""
from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

import core
import settings

CONTENT_SWITCHES = ("OTEL_LOG_USER_PROMPTS", "OTEL_LOG_TOOL_DETAILS", "OTEL_LOG_TOOL_CONTENT",
                    "OTEL_LOG_ASSISTANT_RESPONSES", "OTEL_LOG_RAW_API_BODIES")
IDENTITY_SWITCHES = ("OTEL_METRICS_INCLUDE_SESSION_ID", "OTEL_METRICS_INCLUDE_ACCOUNT_UUID", "OTEL_METRICS_INCLUDE_VERSION",
                     "OTEL_METRICS_INCLUDE_ENTRYPOINT", "OTEL_METRICS_INCLUDE_REPOSITORY")
NAMESPACE, TARGET, OTLP_PORT, QUERY_PORT = "observability", "svc/lgtm", 4318, 9090
COMPARE_SECONDS = 5.0
TYPES = {"input": "input", "output": "output", "cacheRead": "cache_read", "cacheCreation": "cache_write"}
_warned = False


@dataclass
class Forward:
    """A `kubectl port-forward` to the addon's collector (or query API) that cplat starts for one session."""
    context: str
    local_port: int
    remote_port: int = OTLP_PORT
    args: list[str] = field(default_factory=list)
    proc: subprocess.Popen | None = None

    @classmethod
    def to(cls, context: str, remote_port: int) -> "Forward":
        port = free_port()
        return cls(context, port, remote_port, ["kubectl", "--context", context, "-n", NAMESPACE, "port-forward", TARGET,
                                                f"{port}:{remote_port}"])


# ---------------- seams (tests replace these) ----------------

def reachable(endpoint: str, timeout: float = 1.0) -> bool:
    u = urllib.parse.urlparse(endpoint)
    try:
        with socket.create_connection((u.hostname or "", u.port or (443 if u.scheme == "https" else 80)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_forward(forward: Forward, wait: float = 5.0) -> subprocess.Popen | None:
    """Start the port-forward and wait until its local port answers; None when it does not (raises OSError if kubectl is missing)."""
    proc = subprocess.Popen(forward.args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    forward.proc = proc
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None
        if reachable(f"http://127.0.0.1:{forward.local_port}", 0.2):
            return proc
        time.sleep(0.2)
    stop_forward(forward)
    return None


def stop_forward(forward: Forward | None) -> None:
    proc = forward.proc if forward else None
    if proc is None:
        return
    with contextlib.suppress(Exception):
        proc.terminate()
        proc.wait(timeout=3)
    if proc.poll() is None:
        with contextlib.suppress(Exception):
            proc.kill()
    forward.proc = None


def http_get(url: str, timeout: float = COMPARE_SECONDS) -> str:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"not an http(s) URL: {url}")
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310  (scheme checked above)
        return r.read().decode()


# ---------------- configuration ----------------

def _settings_value(repo: Path, key: str):
    """`telemetry.<key>` from the settings files, project over user; None when absent or unreadable."""
    for path in (repo / settings.PROJECT_FILE, settings.user_file()):
        try:
            data = yaml.safe_load(path.read_text()) if path.is_file() else None
        except (OSError, yaml.YAMLError):
            continue
        block = data.get("telemetry") if isinstance(data, dict) else None
        if isinstance(block, dict) and block.get(key) not in (None, ""):
            return block[key]
    return None


def is_local(endpoint: str) -> bool:
    host = (urllib.parse.urlparse(endpoint).hostname or "").lower()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        pass
    return host == "localhost" or host.endswith((".localhost", ".svc", ".svc.cluster.local"))


def _allow_remote(repo: Path) -> bool:
    env = os.environ.get("CPLAT_OTLP_ALLOW_REMOTE")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return _settings_value(repo, "allow_remote") in (True, "true", "1", 1)


def kube_context(repo: Path) -> str | None:
    return os.environ.get("CPLAT_KUBE_CONTEXT") or _settings_value(repo, "context") or None


def _has_lgtm(doc: dict | None) -> bool:
    """Any environment of the system.yaml has `observability: {ui: lgtm}`."""
    envs = (doc or {}).get("environments")
    return isinstance(envs, dict) and any(isinstance(e, dict) and isinstance(e.get("observability"), dict)
                                          and e["observability"].get("ui") == "lgtm" for e in envs.values())


def has_addon(repo: Path) -> bool:
    """The repo is a gitops-app with an environment whose `observability.ui` is lgtm, or `.platform-app.yml` names one that has (read through gh)."""
    apps = repo / "applications"
    if apps.is_dir():
        for f in sorted(apps.glob("*/system.yaml")):
            try:
                if _has_lgtm(yaml.safe_load(f.read_text())):
                    return True
            except (OSError, yaml.YAMLError):
                continue
        return False
    import ship
    import smoke
    for slug in ship.gitops_apps(repo):
        for name in smoke._app_dirs(slug, repo) or []:
            if _has_lgtm(smoke._read(slug, f"applications/{name}/system.yaml", repo)):
                return True
    return False


def _attributes(repo: Path, run_id: str | None, kind: str) -> str:
    import runs
    q = lambda v: urllib.parse.quote(str(v), safe="")  # noqa: E731
    pairs = ([("cplat.run_id", run_id)] if run_id else []) + [
        ("cplat.kind", kind), ("cplat.repo", runs.repo_slug(repo) or repo.resolve().name), ("cplat.platform_version", core.platform_version())]
    mine = ",".join(f"{k}={q(v)}" for k, v in pairs)
    theirs = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "").strip(",")
    return f"{mine},{theirs}" if theirs else mine


def session_env(repo: Path, run_id: str | None, kind: str) -> tuple[dict[str, str], str | None, Forward | None]:
    """(variables to add to the session, one note line or None, the port-forward to start or None). Starts nothing."""
    endpoint = os.environ.get("CPLAT_OTLP_ENDPOINT") or _settings_value(repo, "endpoint")
    forward: Forward | None = None
    note: str | None = None
    if endpoint:
        endpoint = str(endpoint)
        if not is_local(endpoint) and not _allow_remote(repo):
            return {}, (f"telemetry stays off: {endpoint} is not local; set telemetry.allow_remote: true "
                        "(or CPLAT_OTLP_ALLOW_REMOTE=1) to export there"), None
        if not reachable(endpoint):
            note = f"telemetry: {endpoint} is not reachable; the run goes on, its usage may not be exported"
    else:
        ctx = kube_context(repo)
        if not ctx or not has_addon(repo):
            return {}, None, None
        forward = Forward.to(str(ctx), OTLP_PORT)
        endpoint = f"http://127.0.0.1:{forward.local_port}"
    env = {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_METRICS_EXPORTER": "otlp", "OTEL_LOGS_EXPORTER": "none",
        "OTEL_TRACES_EXPORTER": "none", "OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES": "true",
        **{k: "false" for k in IDENTITY_SWITCHES},
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf", "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_METRIC_EXPORT_INTERVAL": "10000", "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "cumulative",
        **{k: "0" for k in CONTENT_SWITCHES},
        "OTEL_RESOURCE_ATTRIBUTES": _attributes(repo, run_id, kind),
    }
    return env, note, forward


def merge_env(base: dict[str, str], otel: dict[str, str]) -> dict[str, str]:
    """The session's environment: `base` unchanged when telemetry is off; else without the user's own OTEL_* / CLAUDE_CODE_OTEL_*
    variables (endpoints, headers, exporters, content switches), plus ours. Their OTEL_RESOURCE_ATTRIBUTES pairs are already in ours."""
    if not otel:
        return dict(base)
    kept = {k: v for k, v in base.items() if not k.startswith(("OTEL_", "CLAUDE_CODE_OTEL_"))}
    return {**kept, **otel}


def reset() -> None:
    """A new command: its one warning may print."""
    global _warned
    _warned = False


def _warn(line: str | None) -> None:
    global _warned
    if line and not _warned:
        _warned = True
        print(line, file=sys.stderr, flush=True)


@contextlib.contextmanager
def session(repo: Path, run_id: str | None, kind: str) -> Iterator[dict[str, str]]:
    """The variables for one session (empty when telemetry is off or failed); the forward lives as long as the block. Never raises."""
    env: dict[str, str] = {}
    forward: Forward | None = None
    try:
        env, note, forward = session_env(repo, run_id, kind)
        if forward is not None:
            try:
                ok = start_forward(forward)
            except Exception:  # noqa: BLE001
                ok = None
            if not ok:
                env, note = {}, f"telemetry off: the port-forward to {TARGET} on context {forward.context} could not start"
                stop_forward(forward)
                forward = None
        _warn(note)
        if env:
            _record(run_id, env, forward)
    except Exception:  # noqa: BLE001
        env = {}
    try:
        yield env
    finally:
        stop_forward(forward)


def _record(run_id: str | None, env: dict[str, str], forward: Forward | None) -> None:
    try:
        import runs
        runs.set_section(run_id, "telemetry", {"backend": "addon" if forward else "endpoint",
                                               "endpoint": env["OTEL_EXPORTER_OTLP_ENDPOINT"]})
    except Exception:  # noqa: BLE001
        pass


# ---------------- the difference note ----------------

def _vector(body: str) -> list[dict]:
    data = json.loads(body)
    if data.get("status") != "success":
        raise ValueError("query failed")
    return data["data"]["result"]


def _number(v) -> float:
    f = float(v)
    return int(f) if f == int(f) else f


def _seconds_since_start(run_id: str) -> int:
    try:
        import runs
        rec = runs._read_active(run_id) or {}
        began = runs.datetime.datetime.strptime(rec["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=runs.datetime.timezone.utc)
        return max(60, int((runs.utcnow() - began).total_seconds()) + 120)
    except Exception:  # noqa: BLE001
        return 7 * 86400


def compare(run_id: str, usage: dict) -> dict | None:
    """The `usage.otel` value: the metrics store's totals for the run and `otel - transcript` per figure; None without figures.
    5 s in total, never raises."""
    forward: Forward | None = None
    try:
        deadline = time.monotonic() + COMPARE_SECONDS
        left = lambda: max(0.1, deadline - time.monotonic())  # noqa: E731
        base = _settings_value(Path.cwd(), "query_url")
        if not base:
            import runs
            rec = runs._read_active(run_id) or {}
            ctx = kube_context(Path.cwd())
            if (rec.get("telemetry") or {}).get("backend") != "addon" or not ctx:
                return None
            forward = Forward.to(str(ctx), QUERY_PORT)
            if not start_forward(forward, wait=min(3.0, left())):
                return None
            base = f"http://127.0.0.1:{forward.local_port}"
        window = f"{_seconds_since_start(run_id)}s"
        sel = '{cplat_run_id="' + run_id.replace("\\", "\\\\").replace('"', '\\"') + '"}'
        queries = {
            "tokens": f"sum by (type) (max_over_time(claude_code_token_usage_tokens_total{sel}[{window}]))",
            "cost": f"sum(max_over_time(claude_code_cost_usage_USD_total{sel}[{window}]))",
        }
        got = {}
        for name, q in queries.items():
            url = f"{base.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode({"query": q})
            got[name] = _vector(http_get(url, timeout=left()))
        totals: dict = {}
        if got["tokens"]:
            totals = {key: 0 for key in TYPES.values()}
            for s in got["tokens"]:
                key = TYPES.get(s["metric"].get("type"))
                if key:
                    totals[key] += _number(s["value"][1])
        if got["cost"]:
            totals["cost_usd"] = float(got["cost"][0]["value"][1])
        if not totals:
            return None
        mine = usage.get("totals") or {}
        diff = {k: (round(v - mine[k], 6) if isinstance(v, float) or isinstance(mine[k], float) else v - mine[k])
                for k, v in totals.items() if isinstance(mine.get(k), (int, float))}
        return {"totals": totals, "difference": diff}
    except Exception:  # noqa: BLE001
        return None
    finally:
        stop_forward(forward)
