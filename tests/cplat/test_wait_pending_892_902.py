"""#892 and #902: two false RED results of `cplat system wait`.

#892: a pod of the new version in ImagePullBackOff on a tag that does not exist yet waits while the component's CI run on main is
queued or running (it builds that tag), and fails fast as before when no run builds it or the run failed. #1013: also when the
not-found pull error is not the pod's last event.
#902: a database Degraded only because WAL archiving to its in-cluster backup bucket fails waits while that bucket is not Ready and
for a short window after, then it is RED as before.

Seams: the scripted Argo CD of test_143_envwait / test_867_pod_failfast (`envwait.kubectl`), `envwait.gh` (the CI run), the clock
of `waits` and `envwait.wallclock` (cluster timestamps).
"""
import json
import subprocess
from datetime import datetime, timezone

import pytest

import envwait
from test_143_envwait import World, app, block, git
from test_867_pod_failfast import PULL_EVENT, events, stuck
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)
    return world


class CI:
    """`envwait.gh`: the newest `ci` run on main of the component's repo; `states` is a list of (from wait time, run or None)."""

    def __init__(self, w, states):
        self.w, self.states, self.calls = w, states, []
        w.mp.setattr(envwait, "gh", self)

    def __call__(self, args):
        self.calls.append((self.w.t["now"], args))
        run = next((r for at, r in reversed(self.states) if self.w.t["now"] >= at), None)
        return subprocess.CompletedProcess(args, 0, json.dumps([run] if run else []), "")


RUNNING = {"status": "in_progress", "conclusion": ""}
QUEUED = {"status": "queued", "conclusion": ""}
PASSED = {"status": "completed", "conclusion": "success"}
FAILED = {"status": "completed", "conclusion": "failure"}


# ---------------- #892 ----------------

@pytest.mark.parametrize("building", [RUNNING, QUEUED])
def test_a_missing_tag_waits_while_the_ci_run_builds_it(w, building):
    fake = stuck(w, "ImagePullBackOff")
    ci = CI(w, [(0, building), (1300, PASSED)])
    real = fake.__call__

    def pulled(args, context=None, check=False):          # the image is there once the run passed
        if "pods" in args and w.t["now"] >= 1320:
            fake.pods = []
        return real(args, context, check)
    w.mp.setattr("envwait.kubectl", pulled)
    w.argo.polls = w.argo.polls * 33 + [w.ready()]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "900")
    assert rc == 0 and not any(ln.startswith("RED:") for ln in out)
    _, args = ci.calls[0]
    assert args[:3] == ["run", "list", "-R"] and "acme/todo-api" in args and args[args.index("--branch") + 1] == "main"
    assert args[args.index("--workflow") + 1] == "ci"
    assert len(ci.calls) <= 300 / envwait.CI_RECHECK + 2           # cached: asked again at most once a minute while it runs


def test_a_missing_tag_is_red_at_once_when_the_building_run_fails(w):
    stuck(w, "ImagePullBackOff")
    CI(w, [(0, RUNNING), (1200, FAILED)])
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "900")
    assert rc == 1 and 200 <= w.t["slept"] <= 200 + envwait.CI_RECHECK + 10
    assert "the image tag does not exist in the registry" in block(out, "RED:")[0]


@pytest.mark.parametrize("run", [None, FAILED, PASSED])
def test_a_missing_tag_fails_fast_when_no_run_builds_it(w, run):
    stuck(w, "ImagePullBackOff")
    CI(w, [(0, run)])
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "900")
    assert rc == 1 and 60 < w.t["slept"] <= 80
    assert "the image tag does not exist in the registry" in block(out, "RED:")[0]


def test_a_tag_still_missing_after_the_run_passed_is_red_after_the_pull_back_off(w):
    stuck(w, "ImagePullBackOff")
    CI(w, [(0, RUNNING), (1100, PASSED)])
    rc, _, _, _ = w.wait("--env", "dev", "--timeout", "1800")
    assert rc == 1 and 100 + envwait.BUILT_GRACE <= w.t["slept"] <= 100 + envwait.BUILT_GRACE + envwait.CI_RECHECK + 10


def test_a_crash_loop_is_red_even_while_ci_runs(w):
    stuck(w, "CrashLoopBackOff")
    ci = CI(w, [(0, RUNNING)])
    rc, _, _, _ = w.wait("--env", "dev", "--timeout", "900")
    assert rc == 1 and 60 < w.t["slept"] <= 80 and not ci.calls


def test_a_pull_error_other_than_a_missing_tag_does_not_ask_github(w):
    stuck(w, "ImagePullBackOff", evs=events("Failed to pull image: unauthorized: authentication required"))
    ci = CI(w, [(0, RUNNING)])
    rc, _, _, _ = w.wait("--env", "dev", "--timeout", "900")
    assert rc == 1 and not ci.calls


# #1013: the kubelet's events for a missing tag, newest last: the not-found pull error is followed by generic ones
BACK_OFF = events(PULL_EVENT, "Error: ErrImagePull", "Error: ImagePullBackOff")


def test_a_missing_tag_waits_while_ci_builds_it_when_a_generic_event_is_the_last(w):
    fake = stuck(w, "ImagePullBackOff", evs=BACK_OFF)
    ci = CI(w, [(0, RUNNING), (1300, PASSED)])
    real = fake.__call__

    def pulled(args, context=None, check=False):
        if "pods" in args and w.t["now"] >= 1320:
            fake.pods = []
        return real(args, context, check)
    w.mp.setattr("envwait.kubectl", pulled)
    w.argo.polls = w.argo.polls * 33 + [w.ready()]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "900")
    assert rc == 0 and not any(ln.startswith("RED:") for ln in out) and ci.calls


def test_a_missing_tag_under_a_generic_last_event_still_fails_fast_without_a_run(w):
    stuck(w, "ImagePullBackOff", evs=BACK_OFF)
    CI(w, [(0, None)])
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "900")
    assert rc == 1 and 60 < w.t["slept"] <= 80
    (red,) = block(out, "RED:")
    assert "the image tag does not exist in the registry" in red and "last event: Error: ImagePullBackOff" in red


# ---------------- #902 ----------------

BACKUP_YAML = """system: shop
owner: acme
environments:
  dev: {host: '{component}.localhost'}
components:
  todo-api: {type: service, lang: python, repo: acme/todo-api, uses: [postgres], instances: {dev: {}}}
resources:
  backups: {type: bucket}
  postgres:
    type: database
    instances:
      dev:
        backup: {to: backups, schedule: "0 3 * * *", retention: 30d}
"""
NS = "shop-dev"
T0 = datetime(2026, 11, 20, 10, 25, tzinfo=timezone.utc).timestamp()   # the cluster's time when the wait starts
ARCHIVE_MSG = "unexpected failure invoking barman-cloud-wal-archive: exit status 4"


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Cluster:
    """Argo CD plus the database's CloudNativePG Cluster and the bucket's SeaweedFS pods. `ready_at`: cluster time each bucket pod is
    Ready from (None: never); `failing_since`: when ContinuousArchiving turned False."""

    def __init__(self, w, ready_at, failing_since, other_degraded=False, message=ARCHIVE_MSG):
        self.w, self.ready_at, self.failing_since, self.message = w, ready_at, failing_since, message
        self.other_degraded = other_degraded
        w.mp.setattr(envwait, "wallclock", self.now)
        w.mp.setattr("envwait.kubectl", self)
        w.mp.setattr(envwait, "gh", lambda args: pytest.fail("the database wait asked GitHub"))

    def now(self):
        return T0 + self.w.t["now"] - 1000.0

    def degraded(self):
        st = app(self.w.head, health="Degraded")
        st["resources"] = [{"group": "postgresql.cnpg.io", "kind": "Cluster", "namespace": NS, "name": "shop-postgres",
                            "health": {"status": "Degraded"}},
                           {"group": "batch", "kind": "Job", "namespace": NS, "name": "shop-postgres-bucket-wait"}]
        if self.other_degraded:
            st["resources"].append({"group": "apps", "kind": "StatefulSet", "namespace": NS, "name": "x", "health": {"status": "Degraded"}})
        return st

    def __call__(self, args, context=None, check=False):
        if args[2:4] == ["get", "clusters.postgresql.cnpg.io"]:
            cond = {"type": "ContinuousArchiving", "status": "False", "message": self.message,
                    "lastTransitionTime": iso(self.failing_since)}
            return subprocess.CompletedProcess(args, 0, json.dumps({"status": {"conditions": [cond]}}), "")
        if "pods" in args:
            pods = [{"metadata": {"name": "shop-backups-credentials-abc"}, "status": {"phase": "Succeeded"}}]
            for name, at in self.ready_at.items():
                ok = at is not None and self.now() >= at
                cond = {"type": "Ready", "status": "True" if ok else "False", "lastTransitionTime": iso(at if ok else T0 - 31)}
                pods.append({"metadata": {"name": name}, "status": {"phase": "Running", "conditions": [cond]}})
            return subprocess.CompletedProcess(args, 0, json.dumps({"items": pods}), "")
        return self.w.argo(args, context, check)


@pytest.fixture()
def b(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    (world.repo / "applications" / "shop" / "system.yaml").write_text(BACKUP_YAML)
    git(world.repo, "commit", "-qam", "backups")
    git(world.repo, "push", "-q", "origin", "main")
    world.head = git(world.repo, "rev-parse", "HEAD")
    return world


def apps(b, db, bucket="Healthy"):
    return {"todo-api-dev": app(b.head, images=[b.image]), "addon-postgres-dev": db, "addon-backups-dev": app(b.head, health=bucket)}


def test_the_database_waits_for_its_backup_bucket_to_start(b):
    """Journey 23: the filer started 31 s ago, the volume pod is not Ready yet; archiving works about 60 s later."""
    c = Cluster(b, {"shop-backups-master-0": T0 - 60, "shop-backups-filer-0": T0 - 31, "shop-backups-volume-0": T0 + 40},
                failing_since=T0 - 30)
    b.argo.polls = [apps(b, c.degraded(), bucket="Progressing")] + [apps(b, c.degraded())] * 6 + [apps(b, app(b.head))]
    rc, out, _, _ = b.wait("--env", "dev", "--timeout", "600")
    assert rc == 0 and not any(ln.startswith("RED:") for ln in out)
    assert any("addon-postgres-dev: Synced/Degraded" in ln for ln in out)
    assert b.t["slept"] >= 60


def test_the_wait_names_the_bucket_it_waits_for_at_the_timeout(b):
    c = Cluster(b, {"shop-backups-volume-0": None}, failing_since=T0 - 30)
    b.argo.polls = [apps(b, c.degraded())]
    rc, out, _, _ = b.wait("--env", "dev", "--timeout", "120")
    assert rc == 2
    (line,) = [ln for ln in out if ln.strip().startswith("addon-postgres-dev:") and "archiving" in ln]
    assert "backup bucket shop-backups" in line and "shop-backups-volume-0 not Ready" in line and "exit status 4" in line


def test_a_bucket_ready_for_longer_than_the_window_leaves_the_database_red(b):
    c = Cluster(b, {"shop-backups-filer-0": T0 - 900, "shop-backups-volume-0": T0 - 900}, failing_since=T0 - 900)
    b.argo.polls = [apps(b, c.degraded())]
    rc, out, _, _ = b.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and b.t["slept"] == 0 and "addon-postgres-dev" in block(out, "RED:")[0]


def test_archiving_still_failing_after_the_window_is_red(b):
    c = Cluster(b, {"shop-backups-filer-0": T0 - 60, "shop-backups-volume-0": T0 - 10}, failing_since=T0 - 30)
    b.argo.polls = [apps(b, c.degraded())]
    rc, out, _, _ = b.wait("--env", "dev", "--timeout", "900")
    assert rc == 1 and "health Degraded" in block(out, "RED:")[0]
    assert envwait.ARCHIVE_GRACE - 10 <= b.t["slept"] <= envwait.ARCHIVE_GRACE + 10


def test_another_degraded_resource_is_red_at_once(b):
    c = Cluster(b, {"shop-backups-volume-0": None}, failing_since=T0 - 30, other_degraded=True)
    b.argo.polls = [apps(b, c.degraded())]
    rc, _, _, _ = b.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and b.t["slept"] == 0


def test_an_archiving_failure_of_another_kind_is_red_at_once(b):
    c = Cluster(b, {"shop-backups-volume-0": None}, failing_since=T0 - 30, message="the WAL archive is not empty: expected empty archive")
    b.argo.polls = [apps(b, c.degraded())]
    rc, _, _, _ = b.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and b.t["slept"] == 0


def test_only_a_database_with_an_in_cluster_backup_bucket_waits(b):
    _, targets, _ = envwait.env_targets(b.repo, None, b.head, "dev", [])
    by = {t.app: t for t in targets}
    assert by["addon-postgres-dev"].bucket == "shop-backups" and by["addon-postgres-dev"].bucket_app == "addon-backups-dev"
    assert not by["addon-backups-dev"].bucket and by["todo-api-dev"].repo == "acme/todo-api"
