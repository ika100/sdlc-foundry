"""Spec 182 acceptance tests, the log tailer (`render.LOG_TAILER_SCRIPT`, program tail.py): AC-182.1, AC-182.2, AC-182.4.

The tailer runs end to end as a subprocess against a fake Kubernetes API server and a fake OTLP receiver (both on localhost, in threads),
and its pure functions `to_record(line, ts)` and `workload(pod)` are executed from the script text.
Contract: docs/specs/182-logs-reach-loki/design.md "`tail.py` behaviour". A test names its criterion in a `# AC-182.n` comment.

Assumed shape of `to_record(line, ts)`: `line` is the text after the kubelet timestamp, `ts` the RFC3339Nano string; it returns the OTLP
`logRecord` dict."""
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from system_fixtures import RENDER5

NS = "shop-dev"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN = "00f067aa0ba902b7"
T0 = "2026-11-10T10:00:00.123456789Z"


def load_script() -> str:
    spec = importlib.util.spec_from_file_location("render_under_test_182_tailer", RENDER5)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "LOG_TAILER_SCRIPT"), "render.py has no LOG_TAILER_SCRIPT"
    return mod.LOG_TAILER_SCRIPT


def functions() -> dict:
    ns = {"__name__": "tail_functions_182"}
    exec(compile(load_script(), "tail.py", "exec"), ns)
    return ns


def pod(name, *, owner=None, labels=None, containers=("app",), running=True, uid=None):
    meta = {"name": name, "uid": uid or f"uid-{name}", "namespace": NS, "labels": labels or {}}
    if owner:
        meta["ownerReferences"] = [{"kind": owner[0], "name": owner[1], "controller": True}]
    states = [{"name": c, "restartCount": 0, "state": {"running": {"startedAt": "2026-11-10T09:00:00Z"}} if running else {"waiting": {}}}
              for c in containers]
    return {"metadata": meta, "spec": {"containers": [{"name": c} for c in containers]}, "status": {"containerStatuses": states}}


def js(**kw):
    return json.dumps(kw)


def ts(n):
    return f"2026-11-10T10:00:{n:02d}.000000001Z"


class Fake:
    """A Kubernetes API with a pod list and per-(pod, container) log text, and an OTLP receiver."""

    def __init__(self, pods, logs):
        self.pods, self.logs = pods, logs
        self.requests, self.log_requests, self.posts, self.auth = [], [], [], set()
        self.lock = threading.Lock()
        fake = self

        class Api(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urlparse(self.path)
                with fake.lock:
                    fake.requests.append(self.path)
                    fake.auth.add(self.headers.get("Authorization"))
                if u.path == f"/api/v1/namespaces/{NS}/pods":
                    body = json.dumps({"kind": "PodList", "items": fake.pods}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                parts = u.path.strip("/").split("/")   # api v1 namespaces <ns> pods <pod> log
                if len(parts) == 7 and parts[4] == "pods" and parts[6] == "log":
                    q = parse_qs(u.query)
                    with fake.lock:
                        fake.log_requests.append((parts[5], q))
                    body = fake.logs.get((parts[5], q.get("container", [""])[0]), "").encode()
                    self.send_response(200)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    self.close_connection = True
                    return
                self.send_response(404)
                self.end_headers()

        class Otlp(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                data = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                with fake.lock:
                    fake.posts.append((self.path, self.headers.get("Content-Type"), json.loads(data)))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
        self.otlp = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Otlp)
        for s in (self.api, self.otlp):
            threading.Thread(target=s.serve_forever, daemon=True).start()

    def records(self):
        """[(resource attributes as a dict, logRecord)] in arrival order."""
        out = []
        with self.lock:
            posts = list(self.posts)
        for _path, _ctype, body in posts:
            for rl in body["resourceLogs"]:
                attrs = {a["key"]: a["value"].get("stringValue") for a in rl["resource"]["attributes"]}
                for sl in rl["scopeLogs"]:
                    for rec in sl["logRecords"]:
                        out.append((attrs, rec))
        return out

    def close(self):
        for s in (self.api, self.otlp):
            s.shutdown()
            s.server_close()


def run_tailer(tmp_path, pods, logs, want, *, own_pod="otel-collector-7c9d-xyz", settle=lambda f: True, timeout=25):
    """Runs tail.py until `want` records arrived and `settle(fake)` holds; returns (fake, stderr). Always stops the process."""
    script = tmp_path / "tail.py"
    script.write_text(load_script())
    sa = tmp_path / "sa"
    sa.mkdir()
    (sa / "token").write_text("secret-token-182")
    fake = Fake(pods, logs)
    env = {**os.environ, "TAILER_API_URL": f"http://127.0.0.1:{fake.api.server_address[1]}", "TAILER_SA_DIR": str(sa),
           "TAILER_POLL_SECONDS": "0.2", "TAILER_FLUSH_SECONDS": "0.2", "TAILER_NAMESPACE": NS, "TAILER_POD": own_pod,
           "TAILER_ENVIRONMENT": "dev", "TAILER_SYSTEM": "shop", "TAILER_OTLP_URL": f"http://127.0.0.1:{fake.otlp.server_address[1]}/v1/logs",
           "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen([sys.executable, str(script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        end = time.time() + timeout
        while time.time() < end and not (len(fake.records()) >= want and settle(fake)):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        time.sleep(0.5)   # a duplicate or an extra record would arrive in this time
        alive = proc.poll() is None
    finally:
        if proc.poll() is None:
            proc.terminate()
        out, err = proc.communicate(timeout=10)
        fake.close()
    assert alive, f"the tailer exited early: {err}"
    return fake, out + err


WEB_LINES = [
    (1, js(level="info", msg="first", trace_id=TRACE, span_id=SPAN)),
    (2, js(level="WARNING", msg="second")),
    (3, "plain text line, not json"),
    (4, js(level="Error", msg="bad trace", trace_id="not-a-trace-id", span_id=SPAN)),
    (5, js(level="info", msg="zero trace", trace_id="0" * 32)),
    (6, js(level="debug", msg="span without trace", span_id=SPAN)),
    (7, js(level="critical", msg="fatal kind")),
    (8, js(level="verbose", msg="unknown level")),
    (9, "[1, 2, 3]"),
    (10, js(level="info", msg="upper hex", trace_id=TRACE.upper(), span_id=SPAN.upper())),
    (11, js(level="trace", msg="t")),
    (12, js(msg="no level at all")),
]


def stream(lines):
    return "".join(f"{ts(n)} {text}\n" for n, text in lines)


class Scenario:
    """(fake, output) of one tailer run. A run that cannot start (the script does not exist yet) fails each test that reads it with the
    reason, instead of erroring in the fixture."""

    def __init__(self, run):
        try:
            self.result, self.problem = run(), None
        except BaseException as err:   # noqa: BLE001 - reported by the tests
            self.result, self.problem = None, f"{type(err).__name__}: {err}"

    def __getitem__(self, i):
        assert self.problem is None, f"the tailer could not run: {self.problem}"
        return self.result[i]


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    pods = [
        pod("shop-api-5d9f7c8b6-abcde", owner=("ReplicaSet", "shop-api-5d9f7c8b6"), labels={"pod-template-hash": "5d9f7c8b6", "app": "shop-api"}),
        pod("shop-db-0", owner=("StatefulSet", "shop-db")),
        pod("lonely-tool", labels={"app.kubernetes.io/name": "tool"}),
        pod("nameless-pod"),
        pod("otel-collector-7c9d-aaaaa", owner=("ReplicaSet", "otel-collector-7c9d"),
            labels={"app.kubernetes.io/name": "otel-collector", "pod-template-hash": "7c9d"}, containers=("collector", "log-tailer")),
        pod("otel-collector-7c9d-xyz", owner=("ReplicaSet", "otel-collector-7c9d"), labels={"pod-template-hash": "7c9d"}),   # the tailer's own pod
        pod("pending-pod", running=False),
    ]
    logs = {
        ("shop-api-5d9f7c8b6-abcde", "app"): stream(WEB_LINES),
        ("shop-db-0", "app"): stream([(1, "db ready"), (2, js(level="info", msg="checkpoint"))]),
        ("lonely-tool", "app"): stream([(1, "tool line")]),
        ("nameless-pod", "app"): stream([(1, "nameless line")]),
        ("otel-collector-7c9d-aaaaa", "collector"): stream([(1, "COLLECTOR-OWN-OUTPUT")]),
        ("otel-collector-7c9d-aaaaa", "log-tailer"): stream([(1, "COLLECTOR-OWN-OUTPUT")]),
        ("otel-collector-7c9d-xyz", "app"): stream([(1, "COLLECTOR-OWN-OUTPUT")]),
        ("pending-pod", "app"): stream([(1, "PENDING-LINE")]),
    }
    want = len(WEB_LINES) + 2 + 1 + 1
    web_requests = lambda f: len([r for r in f.log_requests if r[0] == "shop-api-5d9f7c8b6-abcde"]) >= 2   # noqa: E731  one reconnect
    return Scenario(lambda: run_tailer(tmp_path_factory.mktemp("tailer"), pods, logs, want, settle=web_requests))


def by_msg(fake):
    out = {}
    for attrs, rec in fake.records():
        body = rec["body"]["stringValue"]
        try:
            msg = json.loads(body).get("msg") if body.startswith("{") else body
        except ValueError:
            msg = body
        out.setdefault(msg, []).append((attrs, rec))
    return out


def one(fake, msg):
    found = by_msg(fake).get(msg)
    assert found, f"no record with msg {msg!r}; got {sorted(map(str, by_msg(fake)))}"
    assert len(found) == 1, f"{msg!r} arrived {len(found)} times"
    return found[0]


# ---------------- AC-182.1: labels, severity, plain text ----------------

def test_a_line_arrives_with_the_four_resource_labels_ac_182_1(scenario):  # AC-182.1
    attrs, rec = one(scenario[0], "first")
    assert attrs["service.name"] == "shop-api"
    assert attrs["k8s.namespace.name"] == NS
    assert attrs["k8s.pod.name"] == "shop-api-5d9f7c8b6-abcde"
    assert attrs["k8s.container.name"] == "app"
    assert attrs["deployment.environment"] == "dev"
    assert attrs["service.namespace"] == "shop"


def test_the_batch_is_posted_as_json_to_the_collector_url_ac_182_1(scenario):  # AC-182.1
    fake = scenario[0]
    assert fake.posts
    for path, ctype, _body in fake.posts:
        assert path == "/v1/logs" and ctype.startswith("application/json")


def test_the_tailer_sends_the_service_account_token_to_the_api_ac_182_1(scenario):  # AC-182.1
    assert scenario[0].auth == {"Bearer secret-token-182"}


def test_the_log_is_followed_with_timestamps_per_running_container_ac_182_1(scenario):  # AC-182.1
    qs = [q for p, q in scenario[0].log_requests if p == "shop-api-5d9f7c8b6-abcde"]
    assert qs and all(q["container"] == ["app"] and q["follow"] == ["true"] and q["timestamps"] == ["true"] for q in qs)
    assert all("sinceTime" in q for q in qs)


def test_the_body_is_the_text_unchanged_and_the_time_is_the_kubelets_ac_182_1(scenario):  # AC-182.1
    _a, rec = one(scenario[0], "plain text line, not json")
    assert rec["body"]["stringValue"] == "plain text line, not json"
    _a, rec = one(scenario[0], "first")
    assert rec["body"]["stringValue"] == js(level="info", msg="first", trace_id=TRACE, span_id=SPAN)


def test_the_kubelet_timestamp_is_kept_to_the_nanosecond_ac_182_1(scenario):  # AC-182.1
    _a, rec = one(scenario[0], "plain text line, not json")
    base = int(datetime(2026, 11, 10, 10, 0, 3, tzinfo=timezone.utc).timestamp())
    assert int(rec["timeUnixNano"]) == base * 1_000_000_000 + 1


@pytest.mark.parametrize("msg, text, number", [("first", "INFO", 9), ("second", "WARNING", 13), ("bad trace", "ERROR", 17),
                                               ("fatal kind", "CRITICAL", 21), ("t", "TRACE", 1), ("span without trace", "DEBUG", 5),
                                               ("unknown level", "VERBOSE", 0)])
def test_a_json_level_becomes_the_severity_ac_182_1(scenario, msg, text, number):  # AC-182.1
    _a, rec = one(scenario[0], msg)
    assert rec["severityText"] == text
    assert int(rec["severityNumber"]) == number


def test_a_json_line_without_a_level_has_no_severity_ac_182_1(scenario):  # AC-182.1
    _a, rec = one(scenario[0], "no level at all")
    assert not rec.get("severityText") and not int(rec.get("severityNumber") or 0)


def test_a_line_that_is_not_a_json_object_arrives_as_plain_text_ac_182_1(scenario):  # AC-182.1
    for msg in ("plain text line, not json", "[1, 2, 3]"):
        _a, rec = one(scenario[0], msg)
        assert rec["body"]["stringValue"] == msg
        assert not rec.get("severityText") and not rec.get("traceId") and not rec.get("spanId")


@pytest.mark.parametrize("pod_name, service", [("shop-db-0", "shop-db"), ("lonely-tool", "tool"), ("nameless-pod", "nameless-pod")])
def test_every_pod_of_the_namespace_is_collected_under_its_workload_name_ac_182_1(scenario, pod_name, service):  # AC-182.1
    got = [a for a, _r in scenario[0].records() if a["k8s.pod.name"] == pod_name]
    assert got and all(a["service.name"] == service for a in got)


def test_a_container_that_is_not_running_is_not_read_ac_182_1(scenario):  # AC-182.1
    assert not [p for p, _q in scenario[0].log_requests if p == "pending-pod"]
    assert "PENDING-LINE" not in by_msg(scenario[0])


def test_a_reconnect_does_not_duplicate_lines_ac_182_1(scenario):  # AC-182.1
    fake = scenario[0]
    assert len([p for p, _q in fake.log_requests if p == "shop-api-5d9f7c8b6-abcde"]) >= 2, "the scenario reconnected"
    bodies = [r["body"]["stringValue"] for a, r in fake.records() if a["k8s.pod.name"] == "shop-api-5d9f7c8b6-abcde"]
    assert len(bodies) == len(WEB_LINES) == len(set(bodies))


# ---------------- AC-182.2: trace context ----------------

def test_a_valid_trace_and_span_id_become_the_records_trace_context_ac_182_2(scenario):  # AC-182.2
    _a, rec = one(scenario[0], "first")
    assert rec["traceId"] == TRACE and rec["spanId"] == SPAN


def test_upper_case_hex_ids_are_lower_cased_ac_182_2(scenario):  # AC-182.2
    _a, rec = one(scenario[0], "upper hex")
    assert rec["traceId"] == TRACE and rec["spanId"] == SPAN


def test_an_invalid_or_all_zero_trace_id_is_not_carried_and_a_span_id_needs_a_trace_id_ac_182_2(scenario):  # AC-182.2
    for msg in ("bad trace", "zero trace", "span without trace", "second"):
        _a, rec = one(scenario[0], msg)
        assert not rec.get("traceId") and not rec.get("spanId"), msg


# ---------------- AC-182.4: the collector's own output is not collected ----------------

def test_the_collector_pods_and_the_tailers_own_pod_are_never_read_ac_182_4(scenario):  # AC-182.4
    fake = scenario[0]
    read = {p for p, _q in fake.log_requests}
    assert "otel-collector-7c9d-aaaaa" not in read and "otel-collector-7c9d-xyz" not in read
    assert "COLLECTOR-OWN-OUTPUT" not in by_msg(fake)
    assert read, "other pods are read"


def test_the_tailer_prints_no_log_content_ac_182_4(scenario):  # AC-182.4
    assert scenario[0].records(), "records arrived"
    assert "plain text line" not in scenario[1] and "checkpoint" not in scenario[1]


# ---------------- pure functions ----------------

def test_to_record_maps_level_and_trace_context_ac_182_2():  # AC-182.2
    to_record = functions()["to_record"]
    rec = to_record(js(level="warn", trace_id=TRACE, span_id=SPAN), T0)
    assert rec["severityText"] == "WARN" and int(rec["severityNumber"]) == 13
    assert rec["traceId"] == TRACE and rec["spanId"] == SPAN
    rec = to_record("hello", T0)
    assert rec["body"]["stringValue"] == "hello" and not rec.get("traceId") and not rec.get("severityText")


@pytest.mark.parametrize("level, number", [("trace", 1), ("DEBUG", 5), ("Info", 9), ("warn", 13), ("warning", 13), ("error", 17),
                                           ("fatal", 21), ("critical", 21), ("panic", 21), ("other", 0)])
def test_to_record_severity_numbers_ac_182_1(level, number):  # AC-182.1
    rec = functions()["to_record"](js(level=level), T0)
    assert rec["severityText"] == level.upper() and int(rec["severityNumber"]) == number


def test_workload_names_follow_the_controller_the_replica_set_hash_and_the_labels_ac_182_1():  # AC-182.1
    workload = functions()["workload"]
    assert workload(pod("p-1", owner=("ReplicaSet", "api-5d9f7c8b6"), labels={"pod-template-hash": "5d9f7c8b6"})) == "api"
    assert workload(pod("p-2", owner=("ReplicaSet", "odd-name"), labels={})) == "odd-name"
    assert workload(pod("p-3", owner=("StatefulSet", "db"))) == "db"
    assert workload(pod("p-4", labels={"app.kubernetes.io/name": "tool"})) == "tool"
    assert workload(pod("p-5")) == "p-5"


def test_the_shipped_timing_defaults_deliver_a_line_well_within_60_seconds_ac_182_1():  # AC-182.1
    ns = functions()
    # a line waits at most one pod poll (a new container is found on the next poll), one reconnect pause and one flush interval
    worst = ns["POLL_SECONDS"] + ns["RECONNECT_SECONDS"] + ns["FLUSH_SECONDS"]
    assert ns["POLL_SECONDS"] <= 10 and ns["FLUSH_SECONDS"] <= 5 and ns["RECONNECT_SECONDS"] <= 10
    assert worst <= 30, f"poll+reconnect+flush = {worst} s leaves too little of the 60 s limit"
    assert ns["LOOKBACK_SECONDS"] >= 60, "a container that started before the tailer is still read from at least 60 s back"
    # the rendered container does not override the defaults with slower values
    source = Path(RENDER5).read_text()
    assert '"name": "TAILER_POLL_SECONDS"' not in source and '"name": "TAILER_FLUSH_SECONDS"' not in source
