"""#867: the deploy wait stops at a stuck pod of the new version and asks Argo CD for a refresh when it starts.

Seams: the scripted Argo CD of test_143_envwait (`envwait.kubectl`), extended with `get pods` / `get events` answers, the clock of
`waits`, and `envwait.wallclock` (a pod's start time); for the ship's deploy wait `ship.run`, `ship.now` / `ship.sleep` / `ship.say`.
"""
import json
import subprocess

import pytest

import envwait
import ship
from core import PlatformError
from test_143_envwait import World, app, block
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

NS = "shop-dev"
RESOURCES = [{"group": "apps", "kind": "Deployment", "namespace": NS, "name": "todo-api"}]
PULL_EVENT = 'Failed to pull image "ghcr.io/acme/todo-api:sha-4f2a91c": ghcr.io/acme/todo-api:sha-4f2a91c: not found'


def pod(image, reason, name="todo-api-7d9-abc", started=None):
    status = {"containerStatuses": [{"name": "api", "image": image, "state": {"waiting": {"reason": reason, "message": "Back-off"}}}]}
    if started:
        status["startTime"] = started
    return {"metadata": {"name": name}, "spec": {"containers": [{"name": "api", "image": image}]}, "status": status}


def events(*messages):
    return {"items": [{"type": "Normal", "message": "Pulling image", "lastTimestamp": "2026-11-20T10:00:00Z"},
                      *({"type": "Warning", "message": m, "lastTimestamp": f"2026-11-20T10:0{i + 1}:00Z"} for i, m in enumerate(messages))]}


class PodArgo:
    """Wraps the scripted Argo CD: `get pods` and `get events` answer from `pods` / `events`."""

    def __init__(self, argo, pods, evs):
        self.argo, self.pods, self.events, self.asked = argo, pods, evs, []

    def __call__(self, args, context=None, check=False):
        if "get" in args and ("pods" in args or "events" in args):
            self.asked.append([context or "", *args])
            doc = {"items": self.pods} if "pods" in args else self.events
            return subprocess.CompletedProcess(args, 0, json.dumps(doc), "")
        return self.argo(args, context, check)


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)        # no pod start time counts unless a test sets one
    return world


def stuck(w, reason, image=None, evs=None, started=None):
    image = image or w.image
    progressing = app(w.head, sync="Synced", health="Progressing", images=[image])
    progressing["resources"] = RESOURCES
    w.argo.polls = [{"todo-api-dev": progressing, "addon-postgres-dev": app(w.head)}]
    fake = PodArgo(w.argo, [pod("ghcr.io/acme/todo-api:sha-" + "9" * 40, "CrashLoopBackOff", name="old-pod"),
                            pod(image, reason, started=started)], evs or events(PULL_EVENT))
    w.mp.setattr("envwait.kubectl", fake)
    return fake


@pytest.mark.parametrize("reason", ["ImagePullBackOff", "ErrImagePull", "InvalidImageName", "CrashLoopBackOff"])
def test_a_stuck_pod_of_the_new_version_ends_the_wait_red_after_60_seconds(w, reason):
    fake = stuck(w, reason)
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and 60 < w.t["slept"] <= 80                     # not the 600 s timeout
    (red,) = block(out, "RED:")
    assert f"pod {NS}/todo-api-7d9-abc: {reason}" in red and w.image in red and "old-pod" not in red
    assert f"last event: {PULL_EVENT}" in red
    assert all(c[0] == "k3d-shop" for c in fake.asked)              # the wait's context


def test_a_missing_image_tag_is_named(w):
    stuck(w, "ImagePullBackOff")
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and "the image tag does not exist in the registry" in block(out, "RED:")[0]


def test_a_pod_that_started_more_than_60_seconds_ago_ends_the_wait_at_once(w):
    stuck(w, "ImagePullBackOff", started="2026-11-20T12:00:00Z")
    w.mp.setattr(envwait, "wallclock", lambda: envwait._stamp("2026-11-20T12:05:00Z"))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and w.t["slept"] == 0 and "ImagePullBackOff for 300s" in block(out, "RED:")[0]


def test_a_pod_that_recovers_within_60_seconds_does_not_stop_the_wait(w):
    fake = stuck(w, "ErrImagePull")
    polls = {"n": 0}
    real = fake.__call__

    def recovering(args, context=None, check=False):
        if "pods" in args:
            polls["n"] += 1
            if polls["n"] > 3:
                fake.pods = []
        return real(args, context, check)
    w.mp.setattr("envwait.kubectl", recovering)
    w.argo.polls = w.argo.polls * 5 + [w.ready()]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 0 and not any(ln.startswith("RED:") for ln in out)


def test_the_wait_asks_argo_cd_for_a_refresh_when_it_starts(w):
    w.argo.polls = [{"todo-api-dev": app(w.old, images=[w.image]), "addon-postgres-dev": app(w.head)}, w.ready()]
    rc, out, _, _ = w.wait("--env", "dev")
    assert rc == 0 and w.argo.refreshed == ["todo-api-dev"] and w.t["slept"] <= 10
    assert any("hard refresh of todo-api-dev" in ln for ln in out)


# ---------------- the ship's deploy wait (ship.argo_health) ----------------

class ShipArgo:
    def __init__(self, monkeypatch, reason):
        self.t, self.calls, self.said, self.reason = 0.0, [], [], reason
        monkeypatch.setattr(ship, "run", self.run)
        monkeypatch.setattr(ship, "now", lambda: self.t)
        monkeypatch.setattr(ship, "sleep", self.sleep)
        monkeypatch.setattr(ship, "say", self.said.append)
        monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)

    def sleep(self, s):
        self.t += s

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        if "annotate" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "pods" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"items": [pod("ghcr.io/acme/api:sha-4f2a91c", self.reason)]}), "")
        if "events" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(events(PULL_EVENT)), "")
        st = {"summary": {"images": ["ghcr.io/acme/api:sha-4f2a91c"]}, "sync": {"status": "Synced", "revision": "abc"},
              "health": {"status": "Progressing"}, "resources": RESOURCES}
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"status": st}), "")


def test_the_ship_deploy_wait_stops_at_a_stuck_pod(monkeypatch):
    argo = ShipArgo(monkeypatch, "ImagePullBackOff")
    health = ship.argo_health("k3d-x", "todo-api-dev", 600, 10, images={"sha-4f2a91c"})
    assert health.startswith(f"pod {NS}/todo-api-7d9-abc: ImagePullBackOff") and 60 < argo.t <= 80
    assert "ghcr.io/acme/api:sha-4f2a91c" in health and "not found" in health
    assert all(c[:3] == ["kubectl", "--context", "k3d-x"] for c in argo.calls)
    with pytest.raises(PlatformError, match="ImagePullBackOff"):          # reported as any other red deploy: escalate
        ship._healthy("k3d-x", {"todo-api-dev": {"images": {"sha-4f2a91c"}}}, 600, 10)


def test_the_ship_deploy_wait_ignores_a_pod_that_is_only_starting(monkeypatch):
    argo = ShipArgo(monkeypatch, "ContainerCreating")
    assert ship.argo_health("k3d-x", "todo-api-dev", 100, 10, images={"sha-4f2a91c"}) == "Synced/Progressing" and argo.t > 100
