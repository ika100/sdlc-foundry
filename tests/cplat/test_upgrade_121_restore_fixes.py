"""Spec 121 review fixes: restore after a major upgrade (AC-121.16).

(a) `--to latest` restores from the current archive; (b) each archive's window closes where the next archive starts, so a time picks one
archive; (c) a switched generation archives to a server of its own. Contract: design.md, "A backed-up database's archive per major"."""
import subprocess
import sys

import yaml

import backupstate
import cplat
from backup_fixtures import bdoc, clock, cnpg_cluster, kube, make_repo, objectstore, state_path, write_state  # noqa: F401  (fixtures)
from test_backup_117_restore import DEV, NS, switch_world, with_state
from upgrade_fixtures import APP, PG, commit_all

OLD, NEW = "shop-orders-db", "shop-orders-db-pg17"
ARCH = [{"server": OLD, "major": 16}, {"server": NEW, "major": 17}]
WINDOWS = {OLD: "2026-09-27T03:00:12Z", NEW: "2026-10-27T09:00:00Z"}
BEFORE, AFTER = "2026-10-10T00:00:00Z", "2026-10-27T09:30:00Z"


def run_cmd(capsys, *argv):
    rc = cplat.main([*map(str, argv)])
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


def upgraded_repo(tmp_path, clusters=None):
    repo = make_repo(tmp_path, bdoc(dbb={"dev": DEV}, db_kw={"version": 17}))
    write_state(repo, {"next": 1, "clusters": clusters or [{"name": OLD, "role": "active"}], "archives": ARCH})
    subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    commit_all(repo, "archives")
    return repo


def restore_to(tmp_path, kube, capsys, to):
    repo = upgraded_repo(tmp_path)
    # the old archive's window stays open in the object store: it is the active cluster's name and runs to `latest`
    kube.healthy_database(windows=dict(WINDOWS))
    kube.pg_latest = "2026-10-27T10:41:02Z"
    kube.on_apply_k = lambda k, args: k.put("cluster", cnpg_cluster("shop-orders-db-g1"))
    rc, out = run_cmd(capsys, "resource", "restore", "orders-db", "--env", "dev", "--to", to, "--repo-dir", repo)
    assert rc == 0, out
    state = yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])
    return repo, state, out


def test_latest_restores_from_the_current_archive_ac_121_16(tmp_path, kube, clock, capsys):  # AC-121.16
    repo, state, _ = restore_to(tmp_path, kube, capsys, "latest")
    assert state["clusters"][-1]["from"]["server"] == NEW and state["archives"] == ARCH
    assert yaml.safe_load((repo / APP / "addons/dev/orders-db/cluster-g1.yaml").read_text())["spec"]["imageName"] == PG[17]


def test_a_time_after_the_upgrade_restores_from_the_new_archive_with_both_windows_ac_121_16(tmp_path, kube, clock, capsys):  # AC-121.16
    _, state, out = restore_to(tmp_path, kube, capsys, AFTER)
    assert state["clusters"][-1]["from"]["server"] == NEW
    assert "the data from before the upgrade" not in out


def test_a_time_before_the_upgrade_restores_the_old_major_with_both_windows_ac_121_16(tmp_path, kube, clock, capsys):  # AC-121.16
    repo, state, out = restore_to(tmp_path, kube, capsys, BEFORE)
    assert state["clusters"][-1]["from"]["server"] == OLD
    assert "the restored instance runs orders-db 16 (the data from before the upgrade to 17)" in out.splitlines()
    assert yaml.safe_load((repo / APP / "addons/dev/orders-db/cluster-g1.yaml").read_text())["spec"]["imageName"] == PG[16]


def test_each_window_closes_where_the_next_archive_starts_ac_121_16():  # AC-121.16
    row = {"backup": {"latest": "2026-10-27T10:41:02Z"}, "windows": dict(WINDOWS)}
    state = {"next": 1, "clusters": [{"name": OLD, "role": "active"}], "archives": ARCH}
    pick = lambda when: backupstate.source_server(row, state, when, "shop", "orders-db")  # noqa: E731
    assert pick("2026-10-27T08:59:59Z") == OLD
    assert pick("2026-10-27T09:00:00Z") == NEW
    assert pick("2026-10-27T10:00:00Z") == NEW
    assert pick("2026-09-01T00:00:00Z") is None
    assert pick("latest") == NEW


def test_without_archives_latest_and_windows_are_as_in_spec_117_ac_121_16():  # AC-121.16
    row = {"backup": {"latest": "2026-10-27T10:41:02Z"}, "windows": {OLD: WINDOWS[OLD]}}
    state = {"next": 1, "clusters": [{"name": OLD, "role": "active"}]}
    assert backupstate.source_server(row, state, "latest", "shop", "orders-db") == OLD
    assert backupstate.source_server(row, state, "2026-10-27T10:41:02Z", "shop", "orders-db") == OLD


def plugin_params(repo, file="cluster.yaml"):
    doc = yaml.safe_load((repo / APP / "addons/dev/orders-db" / file).read_text())
    return doc["spec"]["plugins"][0]["parameters"]


def test_a_switch_after_an_upgrade_gives_the_generation_its_own_server_name_ac_121_16(tmp_path, kube, clock, capsys):  # AC-121.16
    repo = upgraded_repo(tmp_path)
    state = {"next": 2, "archives": ARCH, "clusters": [{"name": OLD, "role": "active"},
                                                        {"name": "shop-orders-db-g1", "role": "restored", "from": {"server": OLD, "to": BEFORE}}]}
    switch_world(repo, kube)
    with_state(repo, state)      # after switch_world: it writes spec 117's state, this one carries the archives
    kube.put("objectstore", objectstore(dict(WINDOWS)))
    rc, out = run_cmd(capsys, "resource", "restore", "orders-db", "--env", "dev", "--switch", "--repo-dir", repo)
    assert rc == 0, out
    new = yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])
    assert new["archives"] == [*ARCH, {"server": "shop-orders-db-g1", "major": 16}], "the generation's archive is recorded with its major"
    previous = next(c for c in new["clusters"] if c["role"] == "previous")
    assert previous["archive"] == NEW
    active_server = plugin_params(repo, "cluster-g1.yaml").get("serverName", "shop-orders-db-g1")
    previous_server = plugin_params(repo).get("serverName", OLD)
    assert active_server == "shop-orders-db-g1" and previous_server == NEW and active_server != previous_server


def test_a_hand_written_switched_state_renders_distinct_server_names_ac_121_16(tmp_path):  # AC-121.16
    repo = upgraded_repo(tmp_path)
    state = {"next": 2, "archives": [*ARCH, {"server": "shop-orders-db-g1", "major": 16}],
             "clusters": [{"name": OLD, "role": "previous", "until": "2026-10-27T11:02:13Z", "archive": NEW},
                          {"name": "shop-orders-db-g1", "role": "active", "from": {"server": OLD, "to": BEFORE}}]}
    write_state(repo, state)
    p = subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert plugin_params(repo).get("serverName") == NEW
    assert "serverName" not in plugin_params(repo, "cluster-g1.yaml"), "the generation archives to its own name"
    assert NS == "shop-dev"
