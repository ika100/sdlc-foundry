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
from upgrade_fixtures import APP, PG, backed_up, commit_all, make_world, rerender_commit, upgrade_doc

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


def test_a_major_step_after_a_restore_and_a_switch_writes_a_new_archive_ac_121_16(tmp_path, monkeypatch, kube, clock, capsys):  # AC-121.16
    w = make_world(tmp_path, monkeypatch, upgrade_doc(16))
    g1_archive = {"server": "shop-orders-db-g1", "major": 16}
    switched = {"next": 2, "archives": [*ARCH, g1_archive],
                "clusters": [{"name": OLD, "role": "previous", "until": "2026-10-27T11:02:13Z", "archive": NEW},
                             {"name": "shop-orders-db-g1", "role": "active", "from": {"server": OLD, "to": BEFORE}}]}
    write_state(w.repo, switched)
    rerender_commit(w.repo, upgrade_doc(16))        # the owner set instances/version back to 16
    backed_up(kube, name="shop-orders-db-g1")        # the active generation is the cluster that is read
    backed_up(kube, clusters=False)                  # the object store keeps the system name
    rc, out = run_cmd(capsys, "resource", "upgrade", "orders-db", "--to", "17", "--repo-dir", w.repo, "--context", "kind-test")
    assert rc == 0, out
    new = yaml.safe_load(state_path(w.repo).read_text().split("\n", 1)[1])
    servers = [a["server"] for a in new["archives"]]
    assert new["archives"][:3] == [*ARCH, g1_archive], "every earlier entry is kept"
    assert new["archives"][-1] == {"server": "shop-orders-db-g1-pg17", "major": 17}
    assert len(servers) == len(set(servers)) == 4
    p = subprocess.run([sys.executable, "scripts/render.py"], cwd=w.repo, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert plugin_params(w.repo, "cluster-g1.yaml").get("serverName") == "shop-orders-db-g1-pg17"


def test_a_taken_archive_name_gets_the_smallest_free_numeric_suffix_ac_121_16(tmp_path):  # AC-121.16
    import upgrade
    repo = tmp_path / APP
    state = {"next": 1, "clusters": [{"name": OLD, "role": "active"}],
             "archives": [{"server": OLD, "major": 16}, {"server": NEW, "major": 17}, {"server": NEW + "-2", "major": 17}]}
    (repo / "addons/dev/orders-db").mkdir(parents=True)
    backupstate.write_restore_state(repo, "dev", "orders-db", state)
    plan = upgrade.Plan.__new__(upgrade.Plan)
    plan.name, plan.env, plan.cur, plan.to = "orders-db", "dev", 17, 17
    assert upgrade.write_archives(repo, plan) == NEW + "-3"


def test_the_note_offers_only_the_working_way_forward_ac_121_16(tmp_path):  # AC-121.16
    repo = upgraded_repo(tmp_path)
    state = {"next": 2, "archives": [*ARCH, {"server": "shop-orders-db-g1", "major": 16}],
             "clusters": [{"name": OLD, "role": "previous", "until": "2026-10-27T11:02:13Z", "archive": NEW},
                          {"name": "shop-orders-db-g1", "role": "active", "from": {"server": OLD, "to": BEFORE}}]}
    write_state(repo, state)
    p = subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    note = next(ln for ln in (p.stdout + p.stderr).splitlines() if ln.startswith("note: applications/shop: orders-db in dev runs"))
    assert "instances.dev.version: 16, then /resource:upgrade orders-db --to 17 --env dev" in note
    assert "or upgrade it again" not in note
