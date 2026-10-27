"""Spec 117 fixes: after `--switch` on the apply path the new active cluster has its ScheduledBackup (AC-117.13)."""
import datetime as dt

import pytest
import yaml

import backupstate
import dbrestore
import status
from backup_fixtures import clock, cnpg_backup, cnpg_cluster, kube  # noqa: F401  (fixtures)
from test_backup_117_cmds import alert_world, ago, titles
from test_backup_117_restore import APP, DEV, NS, backup, repo, restore, switch_world  # noqa: F401  (repo is a fixture)


def test_switch_on_the_apply_path_leaves_a_scheduled_backup_for_the_new_cluster_ac_117_13(repo, kube, capsys):  # AC-117.13
    switch_world(repo, kube)
    kube.store["scheduledbackup"] = [{"metadata": {"name": "shop-orders-db", "namespace": NS}, "spec": {"cluster": {"name": "shop-orders-db"}}}]

    def apply_k(k, args):
        # a ScheduledBackup's cluster cannot change in place: applying over the old one fails; applying after the delete creates it
        doc = yaml.safe_load((repo / APP / "addons/dev/orders-db/scheduledbackup.yaml").read_text())
        have = [o for o in k.store["scheduledbackup"] if o["metadata"]["name"] == doc["metadata"]["name"]]
        assert not have, "the old ScheduledBackup must be deleted before the apply"
        k.store["scheduledbackup"].append(doc)

    def delete(args, stdin):
        if args[0] == "delete" and args[1].startswith("scheduledbackup"):
            kube.store["scheduledbackup"] = [o for o in kube.store["scheduledbackup"] if o["metadata"]["name"] != args[2]]

    kube.on_apply_k = apply_k
    kube.hooks.append(delete)
    rc, out = restore(repo, capsys, "--switch")
    assert rc == 0, out
    sbs = [o for o in kube.store["scheduledbackup"] if o["metadata"]["name"] == "shop-orders-db"]
    assert len(sbs) == 1 and sbs[0]["spec"]["cluster"] == {"name": "shop-orders-db-g1"}


# ---------------- the first base backup waits for the plugin (design decision 7) ----------------

NO_PLUGIN = "requested plugin is not available: barman-cloud.cloudnative-pg.io"
NOW = dt.datetime(2026, 10, 27, 12, 0, 0, tzinfo=dt.UTC)


def plugin_failure(cluster="shop-orders-db", name="shop-orders-db-20261027115900"):
    return cnpg_backup(name, cluster=cluster, phase="failed", stopped=ago(120), error=NO_PLUGIN)


def row(kube_):
    return backupstate.database_state("shop", "orders-db", "dev", None, backup=True)


def test_only_plugin_failures_make_the_state_pending_not_failing_ac_117_6(kube):  # AC-117.6
    kube.healthy_database(backups=[plugin_failure()])
    b = row(kube)["backup"]
    assert b["state"] == "pending" and b["error"] is None and b["archiving"] == "ok" and b["last_success"] is None


def test_another_failure_or_failing_archiving_is_still_failing_ac_117_6(kube, monkeypatch):  # AC-117.6
    kube.healthy_database(backups=[plugin_failure(), cnpg_backup("x", phase="failed", error="boom", stopped="2026-10-27T11:00:00Z")])
    assert row(kube)["backup"]["state"] == "failing"
    other = type(kube)()
    other.healthy_database(backups=[plugin_failure()], archiving="failing")
    monkeypatch.setattr(backupstate, "kubectl", other)
    assert row(other)["backup"]["state"] == "failing"


def test_status_text_for_a_pending_database_ac_117_6(kube):  # AC-117.6
    kube.healthy_database(windows={}, backups=[plugin_failure()])
    r = row(kube)
    lines = status.backup_lines({"_read": True, "_contexts": ["k3d-x"], "resource_instances": [r], "environments": []})
    assert lines[-1] == "  orders-db/dev  last base backup never (first backup pending)  archiving ok  restore points none"


def test_failing_since_ignores_plugin_failures_while_nothing_completed_ac_117_28(kube, monkeypatch):  # AC-117.28
    kube.healthy_database(backups=[plugin_failure()])
    assert backupstate.database_failing_since("shop", "orders-db", "dev", None, NOW) == []
    kube2 = type(kube)()
    kube2.healthy_database(backups=[cnpg_backup("ok", stopped="2026-10-20T03:00:00Z"), plugin_failure()])
    monkeypatch.setattr(backupstate, "kubectl", kube2)
    assert [f["rule"] for f in backupstate.database_failing_since("shop", "orders-db", "dev", None, NOW)] == ["backup"]


def test_the_poll_takes_one_first_backup_and_files_no_issue_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, envb=False)
    kube.healthy_database(backups=[plugin_failure()])
    w.poll()
    w.poll()
    made = kube.created("Backup")
    assert len(made) == 1 and made[0]["metadata"]["name"].startswith("shop-orders-db-first-")
    assert made[0]["spec"]["cluster"] == {"name": "shop-orders-db"} and made[0]["spec"]["method"] == "plugin"
    assert not [t for t in titles(w) if "backup failing" in t]


@pytest.mark.parametrize("extra,kw", [
    (cnpg_backup("run", phase="started", stopped=None), {}),
    (cnpg_backup("done", stopped="2026-10-27T11:30:00Z"), {}),
    (None, {"archiving": None}),
    (None, {"archiving": "failing", "archiving_since": "2026-10-27T11:59:00Z"}),
])
def test_the_poll_takes_no_first_backup_when_not_due_ac_117_28(tmp_path, monkeypatch, capsys, kube, extra, kw):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, envb=False)
    kube.healthy_database(backups=[plugin_failure(), *([extra] if extra else [])], **kw)
    w.poll()
    assert kube.created("Backup") == []


def test_the_switch_waits_for_the_plugin_then_takes_the_first_backup_ac_117_9(repo, kube, capsys, clock, monkeypatch):  # AC-117.9
    switch_world(repo, kube)
    monkeypatch.setattr(dbrestore, "POLL_S", 10.0)
    kube.store["cluster"][1] = cnpg_cluster("shop-orders-db-g1", ns=NS, archiving=None)
    kube.put("cnpg.backup", plugin_failure("shop-orders-db-g1", "shop-orders-db-g1-20261027115900"))
    t0 = clock.now

    def plugin_loads(args, stdin):
        if clock.now - t0 >= 30:
            kube.store["cluster"][1] = cnpg_cluster("shop-orders-db-g1", ns=NS)

    kube.hooks.append(plugin_loads)
    rc, out = restore(repo, capsys, "--switch")
    assert rc == 0, out
    [made] = kube.created("Backup")
    assert clock.now - t0 >= 30
    assert f"first base backup of shop-orders-db-g1 started (Backup {made['metadata']['name']})" in out
    assert made["metadata"]["name"].startswith("shop-orders-db-g1-first-") and made["spec"]["cluster"] == {"name": "shop-orders-db-g1"}


def test_a_switch_whose_plugin_never_loads_still_exits_0_ac_117_9(repo, kube, capsys, clock, monkeypatch):  # AC-117.9
    switch_world(repo, kube)
    monkeypatch.setattr(dbrestore, "PLUGIN_TIMEOUT_S", 60.0)
    kube.store["cluster"][1] = cnpg_cluster("shop-orders-db-g1", ns=NS, archiving=None)
    rc, out = restore(repo, capsys, "--switch")
    assert rc == 0, out
    assert "the plugin is not loaded on shop-orders-db-g1 yet; the alert poll takes the first base backup when it is" in out
    assert kube.created("Backup") == []


def test_resource_backup_creates_the_same_plugin_backup_as_before_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    kube.healthy_database()
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T12:00:00Z"}
    rc, out = backup(repo, capsys)
    assert rc == 0, out
    [made] = kube.created("Backup")
    assert made["metadata"]["name"].startswith("shop-orders-db-manual-") and made["metadata"]["namespace"] == NS
    assert made["spec"] == {"cluster": {"name": "shop-orders-db"}, "method": "plugin", "pluginConfiguration": {"name": backupstate.PLUGIN}}
