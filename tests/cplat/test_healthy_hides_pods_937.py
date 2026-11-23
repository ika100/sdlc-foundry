"""#937: a Healthy app no longer hides a pod that cannot start.

1. A database or add-on app that reads Synced/Healthy (a SeaweedFS bucket's `Seaweed` has no Argo CD health check) with a pod stuck
   longer than 60 s keeps the wait behind, the pod named on its progress line; a missing image is RED as in #925.
2. An environment with `observability: {ui: lgtm}` also looks at the cluster's shared Grafana app (`operator-lgtm`): a stuck pod there
   never holds the wait, but READY carries a WARNING line naming it. A cluster without that app waits as before.

Seams as in test_db_pull_visible_925 (the scripted Argo CD with `get pods` / `get events` answers).
"""
import pytest

import envwait
from test_143_envwait import World, app, block, git
from test_db_pull_visible_925 import MISSING, NS, Pods, evs
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

SEAWEED = "chrislusf/seaweedfs:4.51"
LGTM = "grafana/otel-lgtm:0.35.0"
EOF_PULL = f'Failed to pull image "{SEAWEED}": failed to copy: read tcp 10.0.0.2:4512->104.16.0.1:443: unexpected EOF'


def pod(name, image, reason, message="Back-off pulling image"):
    return {"metadata": {"name": name}, "spec": {"containers": [{"name": "c", "image": image}]},
            "status": {"containerStatuses": [{"name": "c", "image": image, "state": {"waiting": {"reason": reason, "message": message}}}]}}


def healthy_bucket(head):
    st = app(head)
    st["resources"] = [{"group": "seaweed.seaweedfs.com", "kind": "Seaweed", "namespace": NS, "name": "shop-postgres-backups"}]
    return st


def starting(out, first):
    return [ln for ln in out if ln.startswith(first)]


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)
    return world


def bucket_polls(w):
    return [{**w.ready(), "addon-postgres-dev": healthy_bucket(w.head)}]


# ---------------- part 1: a Healthy add-on with a stuck pod ----------------

def test_a_healthy_bucket_whose_pod_cannot_pull_keeps_the_wait_behind(w):
    w.argo.polls = bucket_polls(w)
    Pods(w, [pod("shop-postgres-backups-master-0", SEAWEED, "ImagePullBackOff")], evs(EOF_PULL))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 2 and not any(ln.startswith("READY") for ln in out)
    named = [ln for ln in out if ln.startswith("addon-postgres-dev:") and "image pull failing: unexpected EOF" in ln]
    assert named and f"pod {NS}/shop-postgres-backups-master-0: ImagePullBackOff, image {SEAWEED}" in named[-1]
    timeout = [ln for ln in block(out, "TIMEOUT:") if ln.strip().startswith("addon-postgres-dev:")]
    assert timeout and "unexpected EOF" in timeout[0]


def test_a_healthy_bucket_ends_ready_once_its_pod_starts(w):
    w.argo.polls = bucket_polls(w)
    Pods(w, lambda now: [pod("shop-postgres-backups-master-0", SEAWEED, "ImagePullBackOff")] if now < 1200 else [], evs(EOF_PULL))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 0 and w.t["slept"] >= 200 and any("unexpected EOF" in ln for ln in out)


def test_a_healthy_bucket_with_a_missing_image_is_red(w):
    w.argo.polls = bucket_polls(w)
    Pods(w, [pod("shop-postgres-backups-master-0", SEAWEED, "ImagePullBackOff")], evs(MISSING))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 1
    (red,) = block(out, "RED:")
    assert red.startswith("RED: addon-postgres-dev") and "the image tag does not exist in the registry" in red


def test_a_healthy_database_with_running_pods_is_ready_at_once(w):
    w.argo.polls = bucket_polls(w)
    Pods(w, [], evs())
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "200")
    assert rc == 0 and w.t["slept"] == 0 and starting(out, "READY:")


# ---------------- part 2: the shared Grafana ----------------

def with_lgtm(w):
    path = w.repo / "applications" / "shop" / "system.yaml"
    path.write_text(path.read_text().replace("dev: {host: '{component}.localhost'}",
                                             "dev: {host: '{component}.localhost', observability: {ui: lgtm}}"))
    git(w.repo, "commit", "-qam", "observability")
    git(w.repo, "push", "-q", "origin", "main")
    w.head = git(w.repo, "rev-parse", "HEAD")


def lgtm_app(rev, health="Progressing"):
    st = app(rev, health=health)
    st["resources"] = [{"group": "apps", "kind": "Deployment", "namespace": "observability", "name": "lgtm"}]
    return st


def test_a_grafana_that_cannot_pull_is_a_warning_and_never_holds_the_wait(w):
    with_lgtm(w)
    w.argo.polls = [{**w.ready(), "addon-observability-dev": app(w.head), "operator-lgtm": lgtm_app("cluster-rev")}]
    lgtm_pull = f'Failed to pull image "{LGTM}": unexpected EOF'
    Pods(w, [pod("lgtm-6f9c7d-x2k4", LGTM, "ErrImagePull", message=lgtm_pull)], evs(lgtm_pull))
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 0 and w.t["slept"] == 0
    (ready,) = starting(out, "READY:")
    assert ready.startswith("READY: 3 app(s)")       # the API, the database, the collector: not the shared Grafana
    (warn,) = starting(out, "WARNING:")
    assert warn.startswith("WARNING: operator-lgtm (shared by the cluster) is not ready")
    assert f"pod observability/lgtm-6f9c7d-x2k4: ErrImagePull, image {LGTM}" in warn and "unexpected EOF" in warn


def test_a_healthy_grafana_adds_no_warning(w):
    with_lgtm(w)
    w.argo.polls = [{**w.ready(), "addon-observability-dev": app(w.head), "operator-lgtm": lgtm_app("cluster-rev", "Healthy")}]
    Pods(w, [], evs())
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 0 and not starting(out, "WARNING:")


def test_a_cluster_without_the_grafana_app_waits_as_before(w):
    with_lgtm(w)
    w.argo.polls = [{**w.ready(), "addon-observability-dev": app(w.head)}]
    Pods(w, [], evs())
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 0 and not starting(out, "WARNING:") and not any("operator-lgtm" in ln for ln in out)
