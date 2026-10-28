"""Spec 121 review fixes: an open restore meets a major step (AC-121.16).

(a)(b) a major step is refused while restore-state.yaml has a `restored` or `previous` instance; a pin move is not. (c) a server missing from
a non-empty `archives` predates the first major step and ran `archives[0]`'s major. Contract: design.md, check 11a and the archive paragraphs."""
import subprocess
import sys

import yaml

import cplat
from backup_fixtures import clock, cnpg_cluster, kube, state_path, write_state  # noqa: F401  (fixtures)
from test_upgrade_121_restore_fixes import ARCH, NEW, OLD, WINDOWS, plugin_params, run_cmd, upgraded_repo
from upgrade_fixtures import APP, PG, backed_up, commit_all, make_world, rerender_commit, snapshot, upgrade_doc

G1 = "shop-orders-db-g1"
UNTIL = "2026-10-27T11:02:13Z"


def refuse_step(tmp_path, monkeypatch, kube, capsys, clusters, *needles, hint):
    w = make_world(tmp_path, monkeypatch, upgrade_doc(16))
    write_state(w.repo, {"next": 2, "clusters": clusters})
    commit_all(w.repo, "an open restore")
    backed_up(kube)
    before, calls = snapshot(w.repo), len(w.calls())
    rc = cplat.main(["resource", "upgrade", "orders-db", "--to", "17", "--repo-dir", str(w.repo), "--context", "kind-test"])
    err = capsys.readouterr().err
    assert rc == 1, err
    for n in needles:
        assert n in err, f"{n!r} not in: {err}"
    assert f"  fix: {hint}" in err.splitlines(), err
    assert snapshot(w.repo) == before and len(w.calls()) == calls, "a refusal changes nothing"
    return w


def test_a_major_step_is_refused_with_a_previous_instance_ac_121_16(tmp_path, monkeypatch, kube, clock, capsys):  # AC-121.16
    # a spec 117 switch leaves the old cluster `previous` without an `archive` field
    refuse_step(tmp_path, monkeypatch, kube, capsys,
                [{"name": "shop-orders-db", "role": "previous", "until": UNTIL}, {"name": G1, "role": "active", "from": {"server": "shop-orders-db", "to": "latest"}}],
                "orders-db in dev has the previous instance shop-orders-db from a restore; switch to it or discard it first",
                hint="/resource:restore orders-db --env dev --discard")


def test_a_major_step_is_refused_with_a_restored_instance_ac_121_16(tmp_path, monkeypatch, kube, clock, capsys):  # AC-121.16
    refuse_step(tmp_path, monkeypatch, kube, capsys,
                [{"name": "shop-orders-db", "role": "active"}, {"name": G1, "role": "restored", "from": {"server": "shop-orders-db", "to": "latest"}}],
                f"orders-db in dev has the restored instance {G1} from a restore; switch to it or discard it first",
                hint=f"/resource:restore orders-db --env dev --discard (or --switch to {G1})")


def test_a_pin_move_with_a_previous_instance_is_still_allowed_ac_121_16(tmp_path, monkeypatch, kube, clock, capsys):  # AC-121.16
    w = make_world(tmp_path, monkeypatch, upgrade_doc(16))
    write_state(w.repo, {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "previous", "until": UNTIL},
                                                  {"name": G1, "role": "active", "from": {"server": "shop-orders-db", "to": "latest"}}]})
    commit_all(w.repo, "an open restore")
    rc, out = run_cmd(capsys, "resource", "upgrade", "orders-db", "--to", "16", "--repo-dir", w.repo, "--context", "kind-test")
    assert "from a restore; switch to it or discard it first" not in out, out
    assert rc == 0, out


def test_a_restore_from_a_server_before_the_first_archive_runs_the_first_major_ac_121_16(tmp_path, kube, clock, capsys):  # AC-121.16
    # spec 117 switched to g1 before the 16 -> 17 step: its servers (OLD) are absent from archives, which start at g1
    repo = upgraded_repo(tmp_path, clusters=[{"name": G1, "role": "active", "from": {"server": OLD, "to": "latest"}}])
    write_state(repo, {"next": 2, "clusters": [{"name": G1, "role": "active", "from": {"server": OLD, "to": "latest"}}],
                       "archives": [{"server": G1, "major": 16}, {"server": G1 + "-pg17", "major": 17}]})
    subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    commit_all(repo, "pre-archive server")
    windows = {OLD: WINDOWS[OLD], G1: "2026-10-05T00:00:00Z", G1 + "-pg17": WINDOWS[NEW]}
    kube.healthy_database(windows=windows, cluster=G1)
    kube.pg_latest = "2026-10-27T10:41:02Z"
    kube.on_apply_k = lambda k, args: k.put("cluster", cnpg_cluster("shop-orders-db-g2"), cnpg_cluster(G1))
    rc, out = run_cmd(capsys, "resource", "restore", "orders-db", "--env", "dev", "--to", "2026-10-01T00:00:00Z", "--repo-dir", repo)
    assert rc == 0, out
    state = yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])
    assert state["clusters"][-1]["from"]["server"] == OLD
    assert "the restored instance runs orders-db 16 (the data from before the upgrade to 17)" in out.splitlines()
    assert yaml.safe_load((repo / APP / "addons/dev/orders-db/cluster-g2.yaml").read_text())["spec"]["imageName"] == PG[16]


def test_the_renderer_treats_a_missing_server_as_the_first_archive_ac_121_16(tmp_path):  # AC-121.16
    repo = upgraded_repo(tmp_path)
    write_state(repo, {"next": 3, "archives": [{"server": G1, "major": 16}, {"server": G1 + "-pg17", "major": 17}],
                       "clusters": [{"name": G1, "role": "previous", "until": UNTIL, "archive": "shop-orders-db-old", "from": {"server": OLD, "to": "latest"}},
                                    {"name": "shop-orders-db-g2", "role": "active", "from": {"server": OLD, "to": "2026-10-01T00:00:00Z"}}]})
    p = subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    image = lambda f: yaml.safe_load((repo / APP / "addons/dev/orders-db" / f).read_text())["spec"]["imageName"]  # noqa: E731
    assert image("cluster-g2.yaml") == PG[16], "the source server predates the first major step"
    assert image("cluster-g1.yaml") == PG[16], "so does the previous cluster's archive"
    assert plugin_params(repo, "cluster-g1.yaml")
