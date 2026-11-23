"""#883: the stuck-pod fail-fast (#867) also reads the pods of an external Helm entry's child Application.

An external Helm entry renders the component's app with one resource, the child Application `<svc>-<env>-chart`; the chart's pods
run in the child's destination namespace. Seams as in test_867_pod_failfast: the scripted Argo CD of test_143_envwait
(`envwait.kubectl`) with `get pods` / `get events` / `get application` answers, the clock of `waits`; for the ship's deploy wait
`ship.run`, `ship.now` / `ship.sleep` / `ship.say`.
"""
import json
import subprocess

import pytest

import envwait
import ship
from test_143_envwait import World, app, block
from test_867_pod_failfast import PULL_EVENT, events, pod
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

CHART_NS = "todo-charts"
CHILD = "todo-api-dev-chart"
RESOURCES = [{"group": "argoproj.io", "kind": "Application", "namespace": "argocd", "name": CHILD}]


def child(namespace=CHART_NS):
    return {"metadata": {"name": CHILD}, "spec": {"destination": {"server": "https://kubernetes.default.svc", "namespace": namespace}}}


def answer(args, pods, child_doc):
    """`get application <child>`, `get pods` (only in the chart's namespace) and `get events`, else None."""
    if "get" in args and "application" in args and CHILD in args:
        return subprocess.CompletedProcess(args, 0, json.dumps(child_doc), "")
    if "get" in args and "pods" in args:
        items = pods if args[args.index("-n") + 1] == CHART_NS else []
        return subprocess.CompletedProcess(args, 0, json.dumps({"items": items}), "")
    if "get" in args and "events" in args:
        return subprocess.CompletedProcess(args, 0, json.dumps(events(PULL_EVENT)), "")
    return None


class ChartArgo:
    def __init__(self, argo, pods, child_doc):
        self.argo, self.pods, self.child, self.asked = argo, pods, child_doc, []

    def __call__(self, args, context=None, check=False):
        done = answer(args, self.pods, self.child)
        if done is None:
            return self.argo(args, context, check)
        self.asked.append([context or "", *args])
        return done


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)
    monkeypatch.setattr(envwait, "gh", lambda args: subprocess.CompletedProcess(args, 0, "[]", ""))  # #892: no CI run builds it
    return world


def chart_app(w, reason, namespace=CHART_NS):
    progressing = app(w.head, sync="Synced", health="Progressing", images=[w.image])
    progressing["resources"] = RESOURCES
    w.argo.polls = [{"todo-api-dev": progressing, "addon-postgres-dev": app(w.head)}]
    fake = ChartArgo(w.argo, [pod(w.image, reason, name="todo-api-5c8-xyz")], child(namespace))
    w.mp.setattr("envwait.kubectl", fake)
    return fake


def test_a_stuck_pod_of_a_helm_entrys_child_app_ends_the_wait_red(w):
    fake = chart_app(w, "ImagePullBackOff")
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and 60 < w.t["slept"] <= 80                     # not the 600 s timeout
    (red,) = block(out, "RED:")
    assert red.startswith("RED: todo-api-dev")
    assert f"pod {CHART_NS}/todo-api-5c8-xyz: ImagePullBackOff" in red and w.image in red
    assert "the image tag does not exist in the registry" in red
    assert all(c[0] == "k3d-shop" for c in fake.asked)              # the wait's context
    assert any(c[1:5] == ["-n", "argocd", "get", "application"] for c in fake.asked)


def test_a_child_app_without_a_destination_namespace_reads_no_pods(w):
    fake = chart_app(w, "ImagePullBackOff", namespace="")
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "120")
    assert rc == 2 and not any(ln.startswith("RED:") for ln in out)
    assert not any("pods" in c for c in fake.asked)


def test_the_ship_deploy_wait_stops_at_a_stuck_pod_of_the_child_app(monkeypatch):
    t = {"now": 0.0}
    monkeypatch.setattr(ship, "now", lambda: t["now"])
    monkeypatch.setattr(ship, "sleep", lambda s: t.__setitem__("now", t["now"] + s))
    monkeypatch.setattr(ship, "say", lambda line: None)
    monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)
    image = "ghcr.io/acme/api:sha-4f2a91c"
    st = {"summary": {"images": [image]}, "sync": {"status": "Synced", "revision": "abc"}, "health": {"status": "Progressing"},
          "resources": RESOURCES}

    def run(cmd, **kw):
        done = answer(cmd, [pod(image, "CrashLoopBackOff", name="todo-api-5c8-xyz")], child())
        if done is not None:
            return done
        if "annotate" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"status": st}), "")
    monkeypatch.setattr(ship, "run", run)
    health = ship.argo_health("k3d-x", "todo-api-dev", 600, 10, images={"sha-4f2a91c"})
    assert health.startswith(f"pod {CHART_NS}/todo-api-5c8-xyz: CrashLoopBackOff") and 60 < t["now"] <= 80
