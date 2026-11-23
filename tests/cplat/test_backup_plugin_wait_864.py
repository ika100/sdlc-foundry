"""#864: the first backup PR installs the Barman Cloud plugin (operators application) and sets the database's WAL archiving through
it in one PR. Argo CD applied the Cluster before the plugin ran; CloudNativePG restarted the primary into "wal archive plugin is not
available" and prod was Degraded until the plugin came up, while `/system:status` said "archiving failing". The rendered database now
waits for the plugin in a PreSync hook, and the status calls the short gap "waiting for the backup plugin to start"."""
import datetime as dt
import socket
import subprocess
import sys

import backupstate
import status
from backup_fixtures import bdoc, kube  # noqa: F401  (kube is a fixture)
from resources_fixtures import APP, ok, platform_render_module, y

DEV = {"to": "backups"}
PLUGIN_DOWN = "wal archive plugin is not available: barman-cloud.cloudnative-pg.io"


def dd(env="dev") -> str:
    return f"{APP}/addons/{env}/orders-db"


# ---------------- the render ----------------

def test_a_backed_up_database_waits_for_the_plugin_before_its_cluster_864(tmp_path):
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    j = y(g, f"{dd()}/plugin-wait-job.yaml")
    ann = j["metadata"]["annotations"]
    assert ann["argocd.argoproj.io/hook"] == "PreSync", "before the Sync phase that applies the Cluster"
    assert "argocd.argoproj.io/hook" not in (y(g, f"{dd()}/cluster.yaml")["metadata"].get("annotations") or {})
    env = {e["name"]: e.get("value") for e in j["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["PLUGIN_HOST"] == "barman-cloud.cnpg-system.svc" and env["PLUGIN_PORT"] == "9090"
    assert "plugin-wait-job.yaml" in y(g, f"{dd()}/kustomization.yaml")["resources"]
    assert f"{dd('prod')}/plugin-wait-job.yaml" not in g, "only a backed-up database waits"


def test_the_plugin_wait_runs_like_the_bucket_wait_864(tmp_path):
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    r = platform_render_module("render_864")
    plug, bucket = y(g, f"{dd()}/plugin-wait-job.yaml"), y(g, f"{dd()}/bucket-wait-job.yaml")
    pc, bc = plug["spec"]["template"]["spec"]["containers"][0], bucket["spec"]["template"]["spec"]["containers"][0]
    assert pc["image"] == bc["image"] == r.CREDENTIALS_IMAGE and pc["command"][2] == r.PLUGIN_WAIT_SCRIPT
    assert pc["securityContext"] == bc["securityContext"]
    assert plug["spec"]["activeDeadlineSeconds"] > r.PLUGIN_WAIT_SECONDS
    assert plug["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/name"] != "orders-db"


def test_an_environment_whose_operators_are_owned_renders_no_plugin_wait_864(tmp_path):
    doc = bdoc(dbb={"dev": DEV})
    doc["environments"]["dev"]["operators"] = "owner"
    g = ok(tmp_path, doc)
    assert f"{dd()}/plugin-wait-job.yaml" not in g, "the owner's plugin may run under another Service name"


def test_removing_the_backup_removes_the_plugin_wait_864(tmp_path):
    ok(tmp_path, bdoc(dbb={"dev": DEV}))
    ok(tmp_path, bdoc())
    assert not (tmp_path / dd() / "plugin-wait-job.yaml").exists()


def run_wait(tmp_path, port: int, seconds: str) -> subprocess.CompletedProcess:
    script = tmp_path / "wait.py"
    script.write_text(platform_render_module("render_864s").PLUGIN_WAIT_SCRIPT)
    env = {"PLUGIN_HOST": "127.0.0.1", "PLUGIN_PORT": str(port), "PLUGIN_WAIT_SECONDS": seconds, "PLUGIN_WAIT_INTERVAL": "0.05"}
    return subprocess.run([sys.executable, "-I", str(script)], env=env, capture_output=True, text=True, timeout=60, check=False)


def test_the_wait_ends_when_the_plugin_accepts_a_connection_864(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        p = run_wait(tmp_path, s.getsockname()[1], "30")
    assert p.returncode == 0 and "answers" in p.stdout


def test_a_plugin_that_never_answers_lets_the_sync_go_on_864(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]          # bound, not listening: refused
        p = run_wait(tmp_path, port, "0.3")
    assert p.returncode == 0 and "going on without it" in p.stdout
    assert p.stdout.count("waiting for the backup plugin") == 1


# ---------------- the status ----------------

def _at(monkeypatch, when):
    monkeypatch.setattr(backupstate, "now", lambda: dt.datetime.fromisoformat(when.replace("Z", "+00:00")))


def test_a_starting_plugin_is_pending_not_failing_864(kube, monkeypatch):  # noqa: F811
    kube.healthy_database(windows={}, archiving="failing", error=PLUGIN_DOWN, archiving_since="2026-10-27T01:00:00Z")
    _at(monkeypatch, "2026-10-27T01:05:00Z")
    r = backupstate.database_state("shop", "orders-db", "dev", None, backup=True)
    assert r["backup"]["state"] == "pending" and r["backup"]["archiving"] == "starting"
    line = status.backup_lines({"_read": True, "_contexts": ["k3d-x"], "resource_instances": [r], "environments": []})[-1]
    assert "waiting for the backup plugin to start" in line and "failing" not in line


def test_a_plugin_missing_for_long_is_failing_864(kube, monkeypatch):  # noqa: F811
    kube.healthy_database(windows={}, archiving="failing", error=PLUGIN_DOWN, archiving_since="2026-10-27T01:00:00Z")
    _at(monkeypatch, "2026-10-27T02:00:00Z")
    r = backupstate.database_state("shop", "orders-db", "dev", None, backup=True)
    assert r["backup"]["state"] == "failing" and PLUGIN_DOWN in r["backup"]["error"]


def test_other_archiving_failures_stay_failing_864(kube, monkeypatch):  # noqa: F811
    kube.healthy_database(windows={}, archiving="failing", archiving_since="2026-10-27T01:00:00Z")
    _at(monkeypatch, "2026-10-27T01:05:00Z")
    assert backupstate.database_state("shop", "orders-db", "dev", None, backup=True)["backup"]["state"] == "failing"


def test_the_plugin_wait_targets_the_charts_fixed_service_not_the_release_885():
    """#885: the chart names its Service from values `service.name` (default `barman-cloud`, fixed because the plugin's TLS
    certificate is issued for it), not from the release. The wait job and the operator install share that constant, the
    install does not override it, and renaming the release leaves the wait's host alone."""
    r = platform_render_module("render_885")
    op = r.OPERATORS["plugin-barman-cloud"]
    assert (op["service"], op["service_port"]) == ("barman-cloud", 9090)
    assert ((op.get("values") or {}).get("service") or {}).get("name") in (None, op["service"])
    op["release"] = "plugin-barman-cloud"                    # the local cluster's release name (scripts/local-cluster.sh)
    job = r.plugin_wait_job("orders-db", {})
    env = {e["name"]: e.get("value") for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["PLUGIN_HOST"] == "barman-cloud.cnpg-system.svc" and env["PLUGIN_PORT"] == "9090"
