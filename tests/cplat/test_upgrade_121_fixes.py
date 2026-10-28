"""Spec 121 review fixes for `cplat resource upgrade`: a held environment can catch up after dev moved on (AC-121.11), a held Postgres 15 can be
released (AC-121.11), and a render error after the edit leaves the tree as it was (AC-121.7)."""
import re

import gitops
from core import PlatformError
from backup_fixtures import clock, kube  # noqa: F401  (fixtures)
from test_upgrade_121_cmds import args, fake, run_cmd, step_state  # noqa: F401  (fixture)
from upgrade_fixtures import APP, OLD_PG, PG, backed_up, snapshot


def test_a_held_staging_takes_its_pin_move_and_then_the_major_step_after_dev_moved_on_ac_121_11(fake, capsys):  # AC-121.11
    step_state(fake, dev=17, records=[("dev", 17)], held=("staging",))
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "16", "--env", "staging"))
    assert rc == 0, err
    staging = fake.repo / APP / "addons" / "staging" / "orders-db" / "cluster.yaml"
    assert PG[16] in staging.read_text() and OLD_PG[16] + "@" not in staging.read_text()
    from system_fixtures import git
    git(fake.repo, "add", "-A")
    git(fake.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "pin move")
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--env", "staging"))
    assert rc == 0, err
    assert PG[17] in staging.read_text()


def test_a_held_staging_on_15_takes_its_pin_move_then_upgrades_to_16_ac_121_11(fake, capsys):  # AC-121.11
    step_state(fake, version=15, dev=16, records=[("dev", 16)], held=("staging",))
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "15", "--env", "staging"))
    assert rc == 0, err
    assert PG[15] in (fake.repo / APP / "addons" / "staging" / "orders-db" / "cluster.yaml").read_text()
    from system_fixtures import git
    git(fake.repo, "add", "-A")
    git(fake.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "pin move")
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "16", "--env", "staging"))
    assert rc == 0, err
    assert PG[16] in (fake.repo / APP / "addons" / "staging" / "orders-db" / "cluster.yaml").read_text()


def test_a_render_error_after_the_edit_restores_the_tree_and_exits_1_ac_121_7(fake, capsys, monkeypatch):  # AC-121.7
    backed_up(fake.kube)
    before = snapshot(fake.repo)
    files = {p: p.read_bytes() for p in (fake.repo / "applications").rglob("*") if p.is_file()}

    def bad_render(repo):
        (repo / APP / "addons" / "dev" / "orders-db" / "cluster.yaml").write_text("half written")
        (repo / APP / "addons" / "dev" / "orders-db" / "stray.yaml").write_text("stray")
        raise PlatformError("render failed: boom")

    monkeypatch.setattr(gitops, "render", bad_render)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--pr"))
    assert rc == 1 and re.search(r"render failed: boom", err), err
    assert snapshot(fake.repo) == before, "HEAD, branches and the tree are as before"
    assert {p: p.read_bytes() for p in (fake.repo / "applications").rglob("*") if p.is_file()} == files
    assert fake.prs() == []
