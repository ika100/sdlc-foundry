"""#925: a database pod that cannot pull its image is named on the wait's progress line, and cluster-up pre-pulls the Postgres image.

1. `cplat system wait`: a pod of a database (add-on) app in ErrImagePull/ImagePullBackOff/InvalidImageName/CrashLoopBackOff for more
   than 60 s is named on the app's progress line (reason, image, last event); a pull failing on the network reads "image pull failing:
   <cause>" on every progress line and keeps waiting; a missing tag or manifest is RED as for a component.
2. `local-cluster.sh up` (gitops-app and cluster-gitops) pulls the pinned Postgres image into each node in the background with
   `crictl pull`, never failing cluster-up.

Seams: the scripted Argo CD of test_143_envwait (`envwait.kubectl`) with `get pods` / `get events` answers, the clock of `waits` and
`envwait.wallclock`; the real `local-cluster.sh` against fake `k3d`, `gh`, `kubectl` and a `docker` that records its calls.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import envwait
from test_143_envwait import World, app, block
from test_186_templates import FAKE_KUBECTL
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from waiting import wait_for, with_prelude

NS = "shop-dev"
PG = "ghcr.io/cloudnative-pg/postgresql:17.11-202610260819-standard-trixie@sha256:" + "e" * 64
REFUSED = (f'Failed to pull image "{PG}": rpc error: code = Unavailable desc = failed to pull and unpack image: '
           'dial tcp 140.82.121.33:443: connect: connection refused')
MISSING = f'Failed to pull image "{PG}": rpc error: code = NotFound desc = {PG}: not found'


def db_pod(reason, name="shop-postgres-1-initdb-x7k2p", image=PG, message="Back-off pulling image"):
    return {"metadata": {"name": name}, "spec": {"initContainers": [{"name": "bootstrap-controller", "image": "ghcr.io/cloudnative-pg/cnpg:1"}],
                                                  "containers": [{"name": "initdb", "image": image}]},
            "status": {"containerStatuses": [{"name": "initdb", "image": image, "state": {"waiting": {"reason": reason, "message": message}}}]}}


def evs(*messages):
    return {"items": [{"type": "Normal", "message": f'Pulling image "{PG}"', "lastTimestamp": "2026-11-21T10:00:00Z"},
                      *({"type": "Warning", "message": m, "lastTimestamp": f"2026-11-21T10:0{i + 1}:00Z"} for i, m in enumerate(messages))]}


def progressing_db(head):
    st = app(head, health="Progressing")
    st["resources"] = [{"group": "postgresql.cnpg.io", "kind": "Cluster", "namespace": NS, "name": "shop-postgres"},
                       {"group": "", "kind": "Secret", "namespace": NS, "name": "shop-postgres-app"}]
    return st


class Pods:
    """Wraps the scripted Argo CD: `get pods` answers `pods` (a callable of the wait's time, or a list), `get events` answers `events`."""

    def __init__(self, w, pods, events):
        self.w, self.pods, self.events, self.asked = w, pods, events, []
        w.mp.setattr("envwait.kubectl", self)
        w.mp.setattr(envwait, "gh", lambda args: subprocess.CompletedProcess(args, 0, "[]", ""))

    def __call__(self, args, context=None, check=False):
        if "get" in args and ("pods" in args or "events" in args):
            self.asked.append((self.w.t["now"], args))
            pods = self.pods(self.w.t["now"]) if callable(self.pods) else self.pods
            doc = {"items": pods} if "pods" in args else self.events
            return subprocess.CompletedProcess(args, 0, json.dumps(doc), "")
        return self.w.argo(args, context, check)


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)
    return world


def db_waits(w):
    w.argo.polls = [{"todo-api-dev": app(w.head, images=[w.image]), "addon-postgres-dev": progressing_db(w.head)}]


def db_lines(out):
    return [ln for ln in out if ln.startswith("addon-postgres-dev:")]


# ---------------- part 1: the wait ----------------

@pytest.mark.parametrize("reason", ["ErrImagePull", "ImagePullBackOff"])
def test_a_pull_failing_on_the_network_is_named_and_keeps_waiting(w, reason):
    db_waits(w)
    Pods(w, [db_pod(reason, message=REFUSED if reason == "ErrImagePull" else "Back-off pulling image")], evs(REFUSED))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 2 and w.t["slept"] >= 300                          # waits: the network may come back
    lines = db_lines(out)
    assert "image pull failing" not in lines[0]                      # not before 60 s
    named = [ln for ln in lines if "image pull failing: connection refused" in ln]
    assert named and lines[-1] == named[-1]
    assert f"pod {NS}/shop-postgres-1-initdb-x7k2p: {reason}, image {PG}" in named[0] and "last event: Failed to pull image" in named[0]
    timeout = [ln for ln in block(out, "TIMEOUT:") if ln.strip().startswith("addon-postgres-dev:")]
    assert timeout and "image pull failing: connection refused" in timeout[0]


def test_a_pull_that_recovers_ends_ready(w):
    db_waits(w)
    w.argo.polls = w.argo.polls * 20 + [w.ready()]
    Pods(w, lambda now: [db_pod("ErrImagePull", message=REFUSED)] if now < 1150 else [], evs(REFUSED))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 0 and any("image pull failing" in ln for ln in db_lines(out))


@pytest.mark.parametrize("reason,message,events", [
    ("ImagePullBackOff", "Back-off pulling image", evs(MISSING)),
    ("ErrImagePull", "manifest unknown", evs()),
    ("InvalidImageName", 'Failed to apply default image tag "x::y": couldn\'t parse image name', evs())])
def test_a_missing_image_is_red_after_60_seconds(w, reason, message, events):
    db_waits(w)
    Pods(w, [db_pod(reason, message=message)], events)
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and 60 < w.t["slept"] <= 80
    (red,) = block(out, "RED:")
    assert red.startswith("RED: addon-postgres-dev") and f"{reason} for " in red and PG in red
    assert "the image tag does not exist in the registry" in red


def test_a_crash_loop_is_named_and_keeps_waiting(w):
    db_waits(w)
    Pods(w, [db_pod("CrashLoopBackOff", name="shop-postgres-1")], evs("Back-off restarting failed container postgres"))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "200")
    assert rc == 2
    assert f"pod {NS}/shop-postgres-1: CrashLoopBackOff, image {PG}" in db_lines(out)[-1]


def test_a_pod_of_another_app_in_the_namespace_is_not_the_databases(w):
    db_waits(w)
    Pods(w, [db_pod("ErrImagePull", name="todo-api-7d9-abc", message=REFUSED)], evs(REFUSED))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "200")
    assert rc == 2 and not any("image pull failing" in ln or "todo-api-7d9-abc" in ln for ln in out)


def test_a_healthy_database_reads_no_pods(w):
    fake = Pods(w, [db_pod("ErrImagePull", message=REFUSED)], evs(REFUSED))
    w.argo.polls = [w.ready()]
    rc, _, _, _ = w.wait("--env", "dev", "--timeout", "200")
    assert rc == 0 and not fake.asked


def test_each_poll_lists_the_namespace_once(w):
    """The component and the database share the namespace: one `get pods` per poll for both."""
    progressing = app(w.head, health="Progressing", images=[w.image])
    progressing["resources"] = [{"group": "apps", "kind": "Deployment", "namespace": NS, "name": "todo-api"}]
    w.argo.polls = [{"todo-api-dev": progressing, "addon-postgres-dev": progressing_db(w.head)}]
    fake = Pods(w, [db_pod("ErrImagePull", message=REFUSED)], evs(REFUSED))
    rc, _, _, _ = w.wait("--env", "dev", "--timeout", "120")
    assert rc == 2
    per_poll: dict[float, int] = {}
    for at, args in fake.asked:
        if "pods" in args:
            per_poll[at] = per_poll.get(at, 0) + 1
    assert per_poll and set(per_poll.values()) == {1}


# ---------------- part 2: cluster-up pre-pulls the Postgres image ----------------

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$DLOG"
case "$1" in
  port) echo "0.0.0.0:8123" ;;
  ps) case "$*" in *k3d.role=server*) echo "k3d-demo-local-server-0" ;; esac ;;
  exec) [ -z "$DOCKER_EXEC_FAILS" ] || { echo "dial tcp: connect: connection refused" >&2; exit 1; } ;;
esac
exit 0
"""


def cluster_up(tmp_path, template, rendered=True, operator=False, env=None):
    """Run `local-cluster.sh up` on a reused cluster (it must succeed); returns (output, the docker calls once the background pull
    ended, the pull's log)."""
    skeleton = tmp_path / "gitops"
    (skeleton / "applications" / "demo").mkdir(parents=True)
    (skeleton / "scripts").mkdir()
    for f in ("local-cluster.sh", "ports.sh"):
        shutil.copy(TEMPLATES / template / "scripts" / f, skeleton / "scripts" / f)
    renderer = "render.py" if template == "gitops-app" else "system_render.py"       # the one holding the versions table
    shutil.copy(TEMPLATES / template / "scripts" / renderer, skeleton / "scripts" / renderer)
    (skeleton / ".copier-answers.yml").write_text("github_org: acme\n")
    if rendered:
        d = skeleton / "applications" / "demo" / "addons" / "dev" / "postgres"
        d.mkdir(parents=True)
        (d / "cluster.yaml").write_text(f"kind: Cluster\nspec:\n  imageName: {PG}\n")
    if operator:                    # a cluster repo's CloudNativePG operator (cluster/operators/<op>.yaml)
        (skeleton / "cluster" / "operators").mkdir(parents=True)
        (skeleton / "cluster" / "operators" / "cloudnative-pg.yaml").write_text("spec:\n  source:\n    targetRevision: 0.29.1\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    dlog = tmp_path / "docker.log"
    dlog.touch()
    for tool in ("k3d", "gh", "helm"):
        (bin_dir / tool).write_text(with_prelude("#!/bin/sh\nexit 0\n"))
    (bin_dir / "kubectl").write_text(with_prelude(FAKE_KUBECTL))
    (bin_dir / "docker").write_text(with_prelude(FAKE_DOCKER))
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    environ = {k: v for k, v in os.environ.items() if k not in ("LOCAL_HTTP_PORT", "PREPULL_POSTGRES")}
    environ |= {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_TOKEN": "x", "WITH_ESO": "0", "WITH_CNPG": "0", "WITH_LGTM": "0",
                "WITH_ARGO": "1", "DLOG": str(dlog), "KLOG": str(tmp_path / "kubectl.log"),
                "CM_STATE": str(tmp_path / "cm-state"), "TMPDIR": str(tmp), "LOCAL_CLUSTER": "demo-local", **(env or {})}
    run = subprocess.run(["bash", str(skeleton / "scripts" / "local-cluster.sh"), "up"], capture_output=True, text=True, env=environ,
                         cwd=skeleton)
    assert run.returncode == 0, (run.stdout + run.stderr)[-1500:]
    log = tmp / "demo-local-prepull.log"
    if "Pre-pulling" in run.stdout:
        wait_for(lambda: "pre-pulled" in (log.read_text() if log.exists() else "") or "WARNING" in (log.read_text() if log.exists() else ""),
                 what="the background pre-pull")
    return run.stdout + run.stderr, dlog.read_text().splitlines(), log


@pytest.mark.parametrize("template", ["gitops-app", "cluster-gitops"])
def test_cluster_up_pulls_the_rendered_postgres_image_into_each_node(tmp_path, template):
    out, calls, log = cluster_up(tmp_path, template)
    assert "Pre-pulling the Postgres image in the background" in out and str(log) in out
    assert f"exec k3d-demo-local-server-0 crictl pull {PG}" in calls
    assert f"pre-pulled {PG} on k3d-demo-local-server-0" in log.read_text()


def test_without_a_rendered_database_a_cluster_repos_operator_brings_the_default_major(tmp_path):
    out, calls, _ = cluster_up(tmp_path, "cluster-gitops", rendered=False, operator=True)
    pulls = [c for c in calls if "crictl pull" in c]
    assert len(pulls) == 1 and "ghcr.io/cloudnative-pg/postgresql:17." in pulls[0] and "@sha256:" in pulls[0], out[-1500:]


@pytest.mark.parametrize("env,rendered", [({"PREPULL_POSTGRES": "0"}, True), ({}, False)])
def test_no_pull_when_off_or_no_database(tmp_path, env, rendered):
    out, calls, _ = cluster_up(tmp_path, "gitops-app", rendered=rendered, env=env)
    assert not [c for c in calls if "crictl" in c] and "Pre-pulling" not in out


def test_a_failed_pull_is_logged_and_cluster_up_still_succeeds(tmp_path):
    out, _, log = cluster_up(tmp_path, "gitops-app", env={"DOCKER_EXEC_FAILS": "1"})
    assert "Pre-pulling" in out
    text = log.read_text()
    assert "connection refused" in text and f"WARNING: pre-pull of {PG} on k3d-demo-local-server-0 failed" in text
