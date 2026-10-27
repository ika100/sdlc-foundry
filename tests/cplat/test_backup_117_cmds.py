"""Spec 117 acceptance tests, the platform side: the model (AC-117.7), `cplat system status` (AC-117.6, .9, .18, .27), `/platform:doctor`
(AC-117.23, .29, .30), the alert poll (AC-117.28), the template's cluster scripts (AC-117.15, .26), the e2e script text (AC-117.24),
the docs and the plugins (AC-117.25, .8, .19, .31).

Contract: design.md "cplat model show", "/system:status", "/platform:doctor", "alert poll", "local cluster and bootstrap", "e2e". The cluster
is `FakeKube` behind the one seam `backupstate.kubectl(args, context)`; `gh`, the network and a real cluster are never used. Criteria that
need a cluster (AC-117.24) are covered by the text of tests/e2e/run.sh."""
import json
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

import cplat
from alerts_fakes import GITOPS, NOW, FakeTracker, iso
from backup_fixtures import kube  # noqa: F401  (fixture)
from backup_fixtures import (APP, P, bdoc, bucket, cnpg_backup, cnpg_cluster, ext_prod_bucket, objectstore, restored_state, switched_state, velero_backup,
                             write_state)
from resources_fixtures import comp, db, platform_render_module, system
from system_fixtures import ROOT, mod, write_system

DEV = {"to": "backups"}
T = ROOT / "templates" / "gitops-app"
CTX = "k3d-shop-local"


# ---------------- AC-117.7: the model ----------------

def model_repo(tmp_path):
    write_system(tmp_path, bdoc(dbb={"dev": DEV, "prod": {"to": "backups", "schedule": "30 2 * * *", "retention": "8w"}},
                                envb={"staging": {"to": "backups", "retention": "2w"}}))
    return tmp_path


def test_database_instances_carry_the_backup_with_defaults_ac_117_7(tmp_path):  # AC-117.7
    m = mod("model").load_dir(model_repo(tmp_path) / APP)
    ri = {(r.resource, r.environment): r for r in m.resource_instances}
    assert getattr(ri[("orders-db", "dev")], "backup", "missing") == {"to": "backups", "schedule": "0 3 * * *", "retention": "30d"}
    assert getattr(ri[("orders-db", "prod")], "backup", "missing") == {"to": "backups", "schedule": "30 2 * * *", "retention": "8w"}
    assert getattr(ri[("orders-db", "staging")], "backup", "missing") is None
    assert getattr(ri[("backups", "dev")], "backup", "missing") is None, "a bucket instance has no backup"


def test_environments_carry_the_backup_ac_117_7(tmp_path):  # AC-117.7
    m = mod("model").load_dir(model_repo(tmp_path) / APP)
    env = {e.name: e for e in m.environments}
    assert getattr(env["staging"], "backup", "missing") == {"to": "backups", "schedule": "0 3 * * *", "retention": "2w"}
    assert getattr(env["dev"], "backup", "missing") is None


def test_the_model_json_has_backup_on_instances_and_environments_and_stays_schema_2_ac_117_7(tmp_path, capsys):  # AC-117.7
    repo = model_repo(tmp_path)
    assert cplat.main(["model", "show", "--repo-dir", str(repo), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["schema"] == 2
    ri = {(r["resource"], r["environment"]): r for r in d["resource_instances"]}
    assert ri[("orders-db", "dev")]["backup"] == {"to": "backups", "schedule": "0 3 * * *", "retention": "30d"}
    assert ri[("orders-db", "staging")]["backup"] is None and ri[("backups", "dev")]["backup"] is None
    assert {e["name"]: e["backup"] for e in d["environments"]}["staging"] == {"to": "backups", "schedule": "0 3 * * *", "retention": "2w"}
    assert {e["name"]: e["backup"] for e in d["environments"]}["prod"] is None


def test_the_model_json_only_adds_the_backup_field_ac_117_7(tmp_path, capsys):  # AC-117.7
    repo = model_repo(tmp_path)
    cplat.main(["model", "show", "--repo-dir", str(repo), "--json"])
    d = json.loads(capsys.readouterr().out)
    for r in d["resource_instances"]:
        assert "backup" in r and "sizing" in r and "secret" in r
        assert set(r["backup"] or {"to", "schedule", "retention"}) == {"to", "schedule", "retention"}, "no state read from the cluster"
    assert all("backup" in e for e in d["environments"])


def test_the_model_text_ends_a_line_with_the_backup_only_when_set_ac_117_7(tmp_path, capsys):  # AC-117.7
    repo = model_repo(tmp_path)
    assert cplat.main(["model", "show", "--repo-dir", str(repo)]) == 0
    lines = capsys.readouterr().out.splitlines()
    with_backup = [ln for ln in lines if "backup to" in ln]
    assert len(with_backup) == 3, with_backup   # orders-db dev and prod, the staging environment
    assert any(ln.startswith("    dev  type database") and ln.endswith('  backup to backups schedule "0 3 * * *" retention 30d') for ln in with_backup)
    assert any(ln.startswith("    prod  type database") and ln.endswith('  backup to backups schedule "30 2 * * *" retention 8w') for ln in with_backup)
    assert any(ln.startswith("  staging  host") and ln.endswith('  backup to backups schedule "0 3 * * *" retention 2w') for ln in with_backup)
    assert "    staging  type database  external false  replicas 1  version 17  storage 1Gi  argo addon-orders-db-staging  secret shop-orders-db-app" in lines


def test_a_model_without_backup_prints_as_before_ac_117_7(tmp_path, capsys):  # AC-117.7
    write_system(tmp_path, bdoc())
    cplat.main(["model", "show", "--repo-dir", str(tmp_path)])
    assert "backup" not in capsys.readouterr().out.replace("backups", "")
    cplat.main(["model", "show", "--repo-dir", str(tmp_path), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert [r["backup"] for r in d["resource_instances"]] == [None] * len(d["resource_instances"])


def test_the_renderer_and_the_model_agree_on_the_backup_ac_117_7(tmp_path):  # AC-117.7
    write_system(tmp_path, bdoc(dbb={"dev": DEV, "prod": {"to": "backups", "schedule": "30 2 * * *", "retention": "8w"}}, envb={"staging": DEV}))
    r = platform_render_module("render_117_model")
    cfg = r.load_system(tmp_path / APP)["cfg"]
    m = mod("model").load_dir(tmp_path / APP)
    for ri in m.resource_instances:
        if ri.type == "database":
            assert getattr(ri, "backup", "missing") == cfg["resources"]["orders-db"]["envs"][ri.environment]["backup"]
    assert {e.name: e.backup for e in m.environments if getattr(e, "backup", None)} == cfg["backup"]


# ---------------- AC-117.6 / .18 / .27 / .9: system status ----------------

def status(tmp_path, kube, capsys, *extra, context=CTX):
    import status as st
    argv = ["--repo-dir", str(tmp_path), *extra]
    if context:
        argv += ["--context", context]
    rc = st.main(argv)
    return rc, capsys.readouterr().out


@pytest.fixture()
def quiet(monkeypatch):
    import status as st
    monkeypatch.setattr(st, "sh", lambda cmd: None)


def status_json(tmp_path, kube, capsys, **kw):
    rc, out = status(tmp_path, kube, capsys, "--json", **kw)
    assert rc == 0, out
    return json.loads(out)["backups"]


def inst(b, db_="orders-db", env="dev"):
    return next(i for i in b["resource_instances"] if i["resource"] == db_ and i["environment"] == env)


def envb(b, env="dev"):
    return next(e for e in b["environments"] if e["environment"] == env)


def healthy(kube, **kw):
    kube.healthy_database(backups=[cnpg_backup("shop-orders-db-20261026030000", stopped="2026-10-26T03:00:12Z"),
                                   cnpg_backup("shop-orders-db-20261027030000", stopped="2026-10-27T03:00:12Z")], **kw)
    return kube


def test_status_reads_last_backup_archiving_and_restore_points_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    healthy(kube)
    b = inst(status_json(tmp_path, kube, capsys))["backup"]
    assert b["last_success"] == "2026-10-27T03:00:12Z" and b["state"] == "ok" and b["archiving"] == "ok" and b["error"] is None
    assert b["earliest"] == "2026-09-27T03:00:12Z" and b["latest"] == "2026-10-27T10:41:02Z"


def test_status_json_names_the_active_cluster_and_has_no_restored_or_previous_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    healthy(kube)
    i = inst(status_json(tmp_path, kube, capsys))
    assert i["cluster"] == "shop-orders-db" and i["restored"] is None and i["previous"] is None


def test_the_newest_completed_backup_is_the_last_success_whatever_the_order_ac_117_27(tmp_path, kube, capsys, quiet):  # AC-117.27
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    kube.healthy_database(backups=[cnpg_backup("c", stopped="2026-10-27T03:00:12Z"), cnpg_backup("a", stopped="2026-10-25T03:00:12Z"),
                                   cnpg_backup("b", stopped="2026-10-26T03:00:12Z")])
    assert inst(status_json(tmp_path, kube, capsys))["backup"]["last_success"] == "2026-10-27T03:00:12Z"


def test_last_success_counts_the_backups_of_every_cluster_of_the_database_ac_117_27(tmp_path, kube, capsys, quiet):  # AC-117.27
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    write_state(tmp_path, switched_state())
    kube.put("cluster", cnpg_cluster("shop-orders-db"), cnpg_cluster("shop-orders-db-g1"))
    kube.put("objectstore", objectstore({"shop-orders-db": "2026-09-27T03:00:12Z", "shop-orders-db-g1": "2026-10-27T09:59:00Z"}))
    kube.put("cnpg.backup", cnpg_backup("old", cluster="shop-orders-db", stopped="2026-10-27T03:00:12Z"),
             cnpg_backup("new", cluster="shop-orders-db-g1", stopped="2026-10-27T12:00:00Z"))
    i = inst(status_json(tmp_path, kube, capsys))
    assert i["backup"]["last_success"] == "2026-10-27T12:00:00Z" and i["cluster"] == "shop-orders-db-g1"
    assert i["backup"]["earliest"] == "2026-09-27T03:00:12Z", "the smallest first recoverability point over the server names"


def test_before_the_first_backup_the_last_success_is_null_and_the_text_says_never_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    kube.healthy_database(windows={})
    b = inst(status_json(tmp_path, kube, capsys))["backup"]
    assert b["last_success"] is None and b["earliest"] is None and b["state"] == "ok"
    kube.pg_latest = ""
    rc, out = status(tmp_path, kube, capsys)
    line = next(ln for ln in out.splitlines() if "orders-db/dev" in ln)
    assert " ".join(line.split()) == "orders-db/dev last base backup never archiving ok restore points none"


def test_failing_archiving_shows_failing_with_the_last_error_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    healthy(kube, archiving="failing", error="WAL archive check failed: S3 timeout")
    b = inst(status_json(tmp_path, kube, capsys))["backup"]
    assert b["state"] == "failing" and b["archiving"] == "failing" and b["error"] == "WAL archive check failed: S3 timeout"
    rc, out = status(tmp_path, kube, capsys)
    assert "archiving failing (WAL archive check failed: S3 timeout)" in " ".join(out.split())


def test_a_base_backup_that_failed_after_the_last_completed_one_is_failing_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    kube.healthy_database(backups=[cnpg_backup("ok", stopped="2026-10-26T03:00:12Z"),
                                   cnpg_backup("bad", phase="failed", stopped="2026-10-27T03:00:30Z", error="could not connect")])
    b = inst(status_json(tmp_path, kube, capsys))["backup"]
    assert b["state"] == "failing" and b["last_success"] == "2026-10-26T03:00:12Z"


def test_a_failed_backup_before_a_completed_one_is_not_failing_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    kube.healthy_database(backups=[cnpg_backup("bad", phase="failed", stopped="2026-10-26T03:00:30Z", error="x"), cnpg_backup("ok", stopped="2026-10-27T03:00:12Z")])
    assert inst(status_json(tmp_path, kube, capsys))["backup"]["state"] == "ok"


def test_an_instance_without_backup_shows_off_and_reads_nothing_for_it_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    healthy(kube)
    b = status_json(tmp_path, kube, capsys)
    assert inst(b, env="staging")["backup"]["state"] == "off" and inst(b, env="staging")["backup"]["last_success"] is None
    rc, out = status(tmp_path, kube, capsys)
    assert any(" ".join(ln.split()) == "orders-db/staging off" for ln in out.splitlines())


def test_an_external_database_shows_external_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}, db_kw={"instances": {"prod": {"external": True}}}))
    healthy(kube)
    b = status_json(tmp_path, kube, capsys)
    assert inst(b, env="prod")["backup"]["state"] == "external"
    rc, out = status(tmp_path, kube, capsys)
    assert any(" ".join(ln.split()) == "orders-db/prod external (backed up by its provider)" for ln in out.splitlines())


def test_an_unreadable_cluster_gives_unknown_with_the_reason_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}, envb={"dev": DEV}))
    kube.error = (1, "connection refused")
    b = status_json(tmp_path, kube, capsys)
    i = inst(b)["backup"]
    assert i["state"] == "unknown" and "connection refused" in i["error"] and i["last_success"] is None
    assert envb(b)["backup"]["state"] == "unknown"
    rc, out = status(tmp_path, kube, capsys)
    assert rc == 0 and re.search(r"orders-db/dev\s+unknown \(.*connection refused", out)


def test_the_text_has_a_backups_section_with_the_designed_lines_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}, envb={"dev": DEV}))
    healthy(kube)
    for n, t in (("w1", "2026-10-25T03:00:40Z"), ("w2", "2026-10-26T03:00:40Z"), ("w3", "2026-10-27T03:00:40Z")):
        kube.put("velero.backup", velero_backup(n, done=t))
    rc, out = status(tmp_path, kube, capsys)
    lines = out.splitlines()
    i = next(n for n, ln in enumerate(lines) if ln == f"Backups (read from the cluster {CTX} now):")
    section = lines[i + 1:]
    assert section[0].startswith("  orders-db/dev ")
    assert "  orders-db/dev      last base backup 2026-10-27T03:00:12Z  archiving ok  restore points 2026-09-27T03:00:12Z … 2026-10-27T10:41:02Z" in section
    assert "  orders-db/staging  off" in section
    assert "  environment dev    last backup 2026-10-27T03:00:40Z  completed  3 kept" in section
    assert "  environment prod   off" in section


def test_status_without_any_backup_reads_no_cluster_and_prints_no_section_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc())
    rc, out = status(tmp_path, kube, capsys)
    assert rc == 0 and "Backups" not in out and kube.calls == []
    b = status_json(tmp_path, kube, capsys)
    assert kube.calls == [] and {i["backup"]["state"] for i in b["resource_instances"]} == {"off"}
    assert {e["backup"]["state"] for e in b["environments"]} == {"off"}


def test_status_reads_the_cluster_with_the_context_it_was_given_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    healthy(kube)
    status_json(tmp_path, kube, capsys)
    assert kube.calls and {c[1] for c in kube.calls} == {CTX}
    kube.calls.clear()
    status_json(tmp_path, kube, capsys, context=None)
    assert kube.calls and all(not c[1] for c in kube.calls), "without --context the current kube context is read"


def test_status_writes_nothing_to_git_or_the_tree_ac_117_6(tmp_path, kube, capsys, quiet):  # AC-117.6
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    healthy(kube)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    status_json(tmp_path, kube, capsys)
    status(tmp_path, kube, capsys)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert not kube.writes()


def test_status_through_the_launcher_has_the_backups_key_ac_117_27(tmp_path, kube, capsys, quiet):  # AC-117.27
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    healthy(kube)
    assert cplat.main(["system", "status", "--repo-dir", str(tmp_path), "--context", CTX, "--json"]) == 0
    b = json.loads(capsys.readouterr().out)["backups"]
    assert inst(b)["backup"]["last_success"] == "2026-10-27T03:00:12Z" and set(inst(b)["backup"]) >= {"last_success", "state"}


def test_environment_backup_state_completed_with_kept_count_ac_117_18(tmp_path, kube, capsys, quiet):  # AC-117.18
    write_system(tmp_path, bdoc(envb={"dev": DEV}))
    kube.put("velero.backup", velero_backup("a", done="2026-10-25T03:00:40Z"), velero_backup("b", done="2026-10-27T03:00:40Z"),
             velero_backup("other", env="staging", done="2026-10-27T05:00:00Z"))
    e = envb(status_json(tmp_path, kube, capsys))["backup"]
    assert e == {"last_success": "2026-10-27T03:00:40Z", "state": "completed", "reason": None, "kept": 2}


def test_environment_backup_never_before_the_first_one_ac_117_18(tmp_path, kube, capsys, quiet):  # AC-117.18
    write_system(tmp_path, bdoc(envb={"dev": DEV}))
    e = envb(status_json(tmp_path, kube, capsys))["backup"]
    assert e["state"] == "never" and e["last_success"] is None and e["kept"] == 0
    rc, out = status(tmp_path, kube, capsys)
    assert any(" ".join(ln.split()) == "environment dev last backup never" or " ".join(ln.split()).startswith("environment dev last backup never")
               for ln in out.splitlines())


def test_environment_backup_partially_failed_keeps_the_last_success_ac_117_18(tmp_path, kube, capsys, quiet):  # AC-117.18
    write_system(tmp_path, bdoc(envb={"dev": DEV}))
    kube.put("velero.backup", velero_backup("a", done="2026-10-26T03:00:40Z"),
             velero_backup("b", phase="PartiallyFailed", done="2026-10-27T03:00:40Z", errors=2))
    e = envb(status_json(tmp_path, kube, capsys))["backup"]
    assert e["state"] == "partially failed" and e["reason"] == "2 errors" and e["last_success"] == "2026-10-26T03:00:40Z" and e["kept"] == 2


def test_environment_backup_failed_has_the_reason_ac_117_18(tmp_path, kube, capsys, quiet):  # AC-117.18
    write_system(tmp_path, bdoc(envb={"dev": DEV}))
    kube.put("velero.backup", velero_backup("a", phase="Failed", done="2026-10-27T03:00:40Z", reason="BackupStorageLocation shop-dev is unavailable"))
    e = envb(status_json(tmp_path, kube, capsys))["backup"]
    assert e["state"] == "failed" and e["reason"] == "BackupStorageLocation shop-dev is unavailable" and e["last_success"] is None
    rc, out = status(tmp_path, kube, capsys)
    assert "failed" in out and "BackupStorageLocation shop-dev is unavailable" in out


def test_an_environment_without_backup_shows_off_ac_117_18(tmp_path, kube, capsys, quiet):  # AC-117.18
    write_system(tmp_path, bdoc(envb={"dev": DEV}))
    b = status_json(tmp_path, kube, capsys)
    assert envb(b, "prod")["backup"]["state"] == "off" and envb(b, "prod")["backup"]["last_success"] is None
    assert sorted(e["environment"] for e in b["environments"]) == ["dev", "prod", "staging"]


def test_status_shows_a_restored_instance_and_whether_it_is_ready_ac_117_9(tmp_path, kube, capsys, quiet):  # AC-117.9
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    write_state(tmp_path, restored_state())
    kube.put("cluster", cnpg_cluster("shop-orders-db"), cnpg_cluster("shop-orders-db-g1", ready=False, message="Setting up primary"))
    kube.put("objectstore", objectstore({"shop-orders-db": "2026-09-27T03:00:12Z"}))
    i = inst(status_json(tmp_path, kube, capsys))
    assert i["restored"] == {"name": "shop-orders-db-g1", "ready": False} and i["previous"] is None and i["cluster"] == "shop-orders-db"
    rc, out = status(tmp_path, kube, capsys)
    assert "restored shop-orders-db-g1 (not ready: Setting up primary)" in " ".join(out.split())


def test_status_shows_the_old_instance_as_previous_after_a_switch_ac_117_9(tmp_path, kube, capsys, quiet):  # AC-117.9
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    write_state(tmp_path, switched_state())
    kube.put("cluster", cnpg_cluster("shop-orders-db"), cnpg_cluster("shop-orders-db-g1"))
    kube.put("objectstore", objectstore({"shop-orders-db": "2026-09-27T03:00:12Z"}))
    i = inst(status_json(tmp_path, kube, capsys))
    assert i["cluster"] == "shop-orders-db-g1" and i["restored"] is None and "shop-orders-db" in json.dumps(i["previous"])
    rc, out = status(tmp_path, kube, capsys)
    assert re.search(r"orders-db/dev\s+previous shop-orders-db\b", out)


# ---------------- AC-117.23 / .29 / .30: doctor ----------------

def rows(repo, name):
    import doctor
    fn = getattr(doctor, "check_backups", None)
    assert fn is not None, "doctor.check_backups exists"
    return [c for c in fn(repo) if c["name"] == name]


PROD = {"to": "backups"}


def test_doctor_warns_prod_has_no_backup_and_lists_each_item_ac_117_23(tmp_path):  # AC-117.23
    write_system(tmp_path, bdoc())
    [row] = rows(tmp_path, "backup prod")
    assert row["status"] == "warn" and row["detail"] == "prod has no backup: environment prod, orders-db/prod"
    assert row["fix"] == "set environments.prod.backup and resources.orders-db.instances.prod.backup in system.yaml (docs/BACKUP-AND-RESTORE.md)"


def test_doctor_lists_only_the_database_when_the_environment_has_backup_ac_117_23(tmp_path):  # AC-117.23
    write_system(tmp_path, bdoc(envb={"prod": PROD}))
    [row] = rows(tmp_path, "backup prod")
    assert row["detail"] == "prod has no backup: orders-db/prod"


def test_doctor_lists_only_the_environment_when_every_database_has_backup_ac_117_23(tmp_path):  # AC-117.23
    write_system(tmp_path, bdoc(dbb={"prod": PROD}))
    [row] = rows(tmp_path, "backup prod")
    assert row["detail"] == "prod has no backup: environment prod"


def test_doctor_is_quiet_when_prod_is_fully_backed_up_ac_117_23(tmp_path):  # AC-117.23
    write_system(tmp_path, bdoc(dbb={"prod": PROD}, envb={"prod": PROD}))
    assert rows(tmp_path, "backup prod") == []


def test_doctor_does_not_list_an_external_database_ac_117_23(tmp_path):  # AC-117.23
    write_system(tmp_path, bdoc(db_kw={"instances": {"prod": {"external": True}}}, envb={"prod": PROD}))
    assert rows(tmp_path, "backup prod") == []


def test_doctor_does_not_warn_when_nothing_runs_in_prod_ac_117_23(tmp_path):  # AC-117.23
    comps = {"api": comp("api", ["orders-db", "backups"], envs=("dev", "staging"))}
    write_system(tmp_path, bdoc(comps=comps))
    assert rows(tmp_path, "backup prod") == []


def test_the_render_still_succeeds_when_prod_has_no_backup_ac_117_23(tmp_path):  # AC-117.23
    from resources_fixtures import ok
    ok(tmp_path, bdoc(dbb={"dev": DEV}))
    assert rows(tmp_path, "backup prod")


def test_doctor_warns_when_prod_backups_live_in_the_same_cluster_ac_117_29(tmp_path):  # AC-117.29
    write_system(tmp_path, bdoc(dbb={"prod": PROD}, envb={"prod": PROD}))
    [row] = rows(tmp_path, "backup location")
    assert row["status"] == "warn" and row["detail"].startswith("prod backups live in the same cluster: ")
    items = set(row["detail"].split(": ", 1)[1].split(", "))
    assert items == {"orders-db/prod (to backups)", "environment prod (to backups)"}
    assert row["fix"] == "use an external bucket as to for prod"


def test_doctor_names_only_the_backups_that_are_in_cluster_ac_117_29(tmp_path):  # AC-117.29
    write_system(tmp_path, bdoc(dbb={"prod": PROD}, envb={"prod": PROD}, bucket_kw=ext_prod_bucket()))
    assert rows(tmp_path, "backup location") == []


def test_doctor_does_not_warn_about_dev_or_staging_locations_ac_117_29(tmp_path):  # AC-117.29
    write_system(tmp_path, bdoc(dbb={"dev": PROD, "staging": PROD}, envb={"dev": PROD, "staging": PROD}))
    assert rows(tmp_path, "backup location") == []


def test_a_same_cluster_prod_backup_renders_ac_117_29(tmp_path):  # AC-117.29
    from resources_fixtures import ok
    g = ok(tmp_path, bdoc(dbb={"prod": PROD}, envb={"prod": PROD}))
    assert f"{APP}/addons/prod/orders-db/objectstore.yaml" in g and f"{APP}/backup/prod/schedule.yaml" in g


IMAGES = {"plugin-barman-cloud": "ghcr.io/cloudnative-pg/plugin-barman-cloud:v{}", "cert-manager": "quay.io/jetstack/cert-manager-controller:v{}",
          "velero": "velero/velero:v{}"}


def fake_cluster(monkeypatch, installed: dict, kubectl=True):
    import doctor
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}" if kubectl else None)

    def fake_run(cmd, *a, **k):
        text = " ".join(str(c) for c in cmd)
        out = ""
        for name, image in IMAGES.items():
            if f"app.kubernetes.io/name={name}" in text and installed.get(name):
                out = image.format(installed[name])
        return SimpleNamespace(stdout=out, stderr="", returncode=0)
    monkeypatch.setattr(doctor, "run", fake_run)


def op_rows(repo):
    import doctor
    return [c for c in doctor.check_operators(repo) if c["name"].split(" ", 1)[1] in IMAGES]


def want(name):
    return platform_render_module("render_117_doctor").OPERATORS[name]


def op_repo(tmp_path, owner=()):
    doc = bdoc(dbb={"dev": DEV}, envb={"dev": DEV})
    for e in owner:
        doc["environments"][e]["operators"] = "owner"
    write_system(tmp_path, doc)
    return tmp_path


def test_doctor_is_ok_when_all_three_operators_match_ac_117_30(tmp_path, monkeypatch):  # AC-117.30
    v = {n: want(n)["operator_version"] for n in IMAGES}
    fake_cluster(monkeypatch, v)
    got = op_rows(op_repo(tmp_path))
    assert [c["name"] for c in got] == ["operator plugin-barman-cloud", "operator cert-manager", "operator velero"]
    for c in got:
        n = c["name"].split(" ", 1)[1]
        assert c["status"] == "ok" and c["detail"] == f"installed {v[n]}, expected {v[n]} (Argo CD application operator-{n})"


def test_doctor_lists_the_five_operators_in_order_ac_117_30(tmp_path, monkeypatch):  # AC-117.30
    import doctor
    fake_cluster(monkeypatch, {})
    names = [c["name"] for c in doctor.check_operators(op_repo(tmp_path))]
    assert names == ["operator cloudnative-pg", "operator seaweedfs", "operator plugin-barman-cloud", "operator cert-manager", "operator velero"]


def test_doctor_warns_naming_a_missing_operator_ac_117_30(tmp_path, monkeypatch):  # AC-117.30
    fake_cluster(monkeypatch, {"plugin-barman-cloud": want("plugin-barman-cloud")["operator_version"], "cert-manager": want("cert-manager")["operator_version"]})
    [velero] = [c for c in op_rows(op_repo(tmp_path)) if c["name"] == "operator velero"]
    assert velero["status"] == "warn"
    assert velero["detail"] == f"not installed in the current kube context, expected {want('velero')['operator_version']} (Argo CD application operator-velero)"
    assert "apply operators/root.yaml once: KUBE_CONTEXT=" in velero["fix"]


def test_doctor_warns_naming_both_versions_when_one_differs_ac_117_30(tmp_path, monkeypatch):  # AC-117.30
    v = {n: want(n)["operator_version"] for n in IMAGES}
    v["velero"] = "1.17.0"
    fake_cluster(monkeypatch, v)
    [velero] = [c for c in op_rows(op_repo(tmp_path)) if c["name"] == "operator velero"]
    assert velero["status"] == "warn" and velero["detail"] == f"installed 1.17.0, expected {want('velero')['operator_version']} (Argo CD application operator-velero)"
    assert velero["fix"] == "sync operator-velero in Argo CD"


def test_doctor_compares_versions_without_a_leading_v_ac_117_30(tmp_path, monkeypatch):  # AC-117.30
    fake_cluster(monkeypatch, {n: want(n)["operator_version"] for n in IMAGES})
    cm = [c for c in op_rows(op_repo(tmp_path)) if c["name"] == "operator cert-manager"][0]
    assert cm["status"] == "ok" and "v1" not in cm["detail"].split("expected")[1].split("(")[0]


def test_doctor_checks_owner_managed_environments_too_ac_117_30(tmp_path, monkeypatch):  # AC-117.30
    repo = op_repo(tmp_path, owner=("dev", "staging", "prod"))
    fake_cluster(monkeypatch, {})
    got = op_rows(repo)
    assert len(got) == 3 and all(c["status"] == "warn" and "operators: owner in dev" in c["detail"] and "not installed" in c["detail"] for c in got)
    fake_cluster(monkeypatch, {n: want(n)["operator_version"] for n in IMAGES})
    assert all(c["status"] == "ok" and "operators: owner in dev" in c["detail"] for c in op_rows(repo))


def test_doctor_has_no_row_for_an_operator_nothing_needs_and_none_without_kubectl_ac_117_30(tmp_path, monkeypatch):  # AC-117.30
    fake_cluster(monkeypatch, {})
    write_system(tmp_path / "a", bdoc(dbb={"dev": DEV}))
    assert [c["name"] for c in op_rows(tmp_path / "a")] == ["operator plugin-barman-cloud", "operator cert-manager"]
    write_system(tmp_path / "b", bdoc(envb={"dev": DEV}))
    assert [c["name"] for c in op_rows(tmp_path / "b")] == ["operator velero"]
    write_system(tmp_path / "c", bdoc())
    assert op_rows(tmp_path / "c") == []
    fake_cluster(monkeypatch, {}, kubectl=False)
    assert op_rows(op_repo(tmp_path / "d")) == []


# ---------------- AC-117.28: the alert poll ----------------

def alert_world(tmp_path, monkeypatch, capsys, kube, *, observability=None, dbb=True, envb=True):
    from test_alerts_poll import World
    w = World(tmp_path, monkeypatch, capsys)
    doc = bdoc(dbb={"dev": DEV} if dbb else None, envb={"dev": DEV} if envb else None)
    for e in doc["environments"].values():
        e["observability"] = dict(observability or {"ui": "lgtm"})
    d = tmp_path / "applications" / "shop"
    d.mkdir(parents=True, exist_ok=True)
    (d / "system.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    return w


def ago(minutes):
    import datetime as dt
    return iso(NOW - dt.timedelta(minutes=minutes))


def titles(w):
    return [c[2] for c in w.tr.created()]


def test_archiving_failing_for_more_than_an_hour_files_one_issue_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube)
    kube.healthy_database(archiving="failing", archiving_since=ago(61), error="WAL archive failed: S3 timeout")
    code, out = w.poll()
    assert titles(w) == ["[auto] [alert] backup failing: orders-db/dev"], out
    created = w.tr.created()[0]
    assert created[1] == GITOPS and "WAL archive failed: S3 timeout" in created[3]


def test_archiving_failing_for_less_than_an_hour_files_nothing_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube)
    kube.healthy_database(archiving="failing", archiving_since=ago(59), error="WAL archive failed: S3 timeout")
    w.poll()
    assert not [t for t in titles(w) if "backup failing" in t] and kube.calls, "the cluster was read, nothing was due"


def test_a_second_poll_files_no_second_issue_while_the_first_is_open_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube)
    kube.healthy_database(archiving="failing", archiving_since=ago(120), error="boom")
    w.poll()
    w.poll()
    assert titles(w) == ["[auto] [alert] backup failing: orders-db/dev"]


def test_a_failed_scheduled_base_backup_older_than_an_hour_files_an_issue_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, envb=False)
    kube.healthy_database(backups=[cnpg_backup("shop-orders-db-20261023030000", stopped="2026-10-23T03:00:12Z"),
                                   cnpg_backup("shop-orders-db-20261024060000", phase="failed", stopped=ago(120), error="could not connect to S3")])
    w.poll()
    assert titles(w) == ["[auto] [alert] backup failing: orders-db/dev"] and "could not connect to S3" in w.tr.created()[0][3]


def test_a_failed_backup_followed_by_a_completed_one_files_nothing_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, envb=False)
    kube.healthy_database(backups=[cnpg_backup("a", phase="failed", stopped=ago(300), error="x"), cnpg_backup("b", stopped=ago(100))])
    w.poll()
    assert kube.calls, "the cluster was read, nothing was due"
    assert not [t for t in titles(w) if "backup failing" in t]


def test_a_failed_backup_younger_than_an_hour_files_nothing_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, envb=False)
    kube.healthy_database(backups=[cnpg_backup("a", phase="failed", stopped=ago(30), error="x")])
    w.poll()
    assert kube.calls, "the cluster was read, nothing was due"
    assert not [t for t in titles(w) if "backup failing" in t]


@pytest.mark.parametrize("phase", ["Failed", "PartiallyFailed"])
def test_a_failing_environment_backup_older_than_an_hour_files_an_issue_ac_117_28(tmp_path, monkeypatch, capsys, kube, phase):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, dbb=False)
    kube.put("velero.backup", velero_backup("a", done=ago(24 * 60)), velero_backup("b", phase=phase, done=ago(90), errors=3, reason="BSL unavailable"))
    w.poll()
    assert titles(w) == ["[auto] [alert] backup failing: environment/dev"]


def test_an_environment_backup_that_completed_since_files_nothing_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, dbb=False)
    kube.put("velero.backup", velero_backup("a", phase="Failed", done=ago(300), reason="x"), velero_backup("b", done=ago(100)))
    w.poll()
    assert kube.calls, "the cluster was read, nothing was due"
    assert not [t for t in titles(w) if "backup failing" in t]


def test_no_issue_is_filed_in_an_environment_whose_alerts_are_off_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, observability={"ui": "lgtm", "alerts": False})
    kube.healthy_database(archiving="failing", archiving_since=ago(300), error="boom")
    kube.put("velero.backup", velero_backup("b", phase="Failed", done=ago(200), reason="x"))
    w.poll()
    assert w.tr.calls == [] or not [t for t in titles(w) if "backup failing" in t]
    assert not w.tr.created()


def test_the_backup_alert_is_filed_even_when_the_metrics_source_is_skipped_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube, observability={"exportTo": "https://otlp.example.com"})
    kube.healthy_database(archiving="failing", archiving_since=ago(200), error="boom")
    code, out = w.poll()
    assert titles(w) == ["[auto] [alert] backup failing: orders-db/dev"], out


def test_an_unreadable_cluster_turns_the_poll_red_without_an_issue_ac_117_28(tmp_path, monkeypatch, capsys, kube):  # AC-117.28
    w = alert_world(tmp_path, monkeypatch, capsys, kube)
    kube.error = (1, "connection refused")
    code, out = w.poll()
    assert code == 1 and "connection refused" in out and not [t for t in titles(w) if "backup failing" in t]


def test_the_issue_title_is_the_designed_one_ac_117_28():  # AC-117.28
    import alertissues
    from alerts_fakes import mkalert
    a = mkalert(name="backup failing", service="orders-db", environment="dev", repo=GITOPS, severity="critical", summary="boom")
    assert alertissues.title(a) == "[auto] [alert] backup failing: orders-db/dev"
    e = mkalert(name="backup failing", service="environment", environment="prod", repo=GITOPS, severity="critical", summary="boom")
    assert alertissues.title(e) == "[auto] [alert] backup failing: environment/prod"


# ---------------- AC-117.15 / .26: the template's cluster scripts ----------------

def test_bootstrap_waits_for_the_three_new_crds_ac_117_26():  # AC-117.26
    text = (T / "scripts" / "bootstrap.sh").read_text()
    for needle in ("plugin-barman-cloud) crd=objectstores.barmancloud.cnpg.io", "cert-manager) crd=certificates.cert-manager.io", "velero) crd=schedules.velero.io",
                   "cloudnative-pg) crd=clusters.postgresql.cnpg.io", "seaweedfs) crd=buckets.seaweed.seaweedfs.com"):
        assert needle in text, needle


def test_cluster_up_installs_or_waits_for_the_backup_operators_ac_117_26():  # AC-117.26
    text = (T / "scripts" / "local-cluster.sh").read_text()
    for needle in ("WITH_BARMAN_CLOUD", "BARMAN_CLOUD_VERSION", "CERT_MANAGER_VERSION", "WITH_VELERO", "VELERO_VERSION", "VELERO_AWS_PLUGIN_IMAGE",
                   "operators/apps/plugin-barman-cloud.yaml", "operators/apps/velero.yaml", "operators/apps/cert-manager.yaml", "0.8.1", "v1.21.3", "12.2.1",
                   "velero/velero-plugin-for-aws:v1.14.4", "https://cloudnative-pg.github.io/charts", "https://charts.jetstack.io",
                   "https://vmware-tanzu.github.io/helm-charts", "objectstores.barmancloud.cnpg.io", "certificates.cert-manager.io", "schedules.velero.io",
                   "deploy/velero", "daemonset/node-agent"):
        assert needle in text, f"local-cluster.sh lacks {needle!r}"


def test_the_cluster_script_installs_velero_with_the_versions_table_values_ac_117_15():  # AC-117.15
    text = (T / "scripts" / "local-cluster.sh").read_text()
    for needle in ("deployNodeAgent", "snapshotsEnabled", "uploaderType", "kopia", "velero-plugin-for-aws", "useSecret"):
        assert needle in text, needle


def test_the_gitops_claude_md_names_the_new_operators_and_files_ac_117_15():  # AC-117.15
    text = (T / "CLAUDE.md.jinja").read_text()
    for needle in ("plugin-barman-cloud", "cert-manager", "velero", "restore-state.yaml", "backup/"):
        assert needle in text, needle


@pytest.mark.parametrize("script", ["bootstrap.sh", "local-cluster.sh"])
def test_the_cluster_scripts_parse_ac_117_15(script):  # AC-117.15
    if not shutil.which("bash"):
        pytest.skip("no bash")
    p = subprocess.run(["bash", "-n", str(T / "scripts" / script)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_cluster_script_default_pins_match_the_versions_table_ac_117_26():  # AC-117.26
    r = platform_render_module("render_117_scripts")
    text = (T / "scripts" / "local-cluster.sh").read_text()
    for n in ("plugin-barman-cloud", "cert-manager", "velero"):
        assert r.OPERATORS[n]["chart_version"] in text, n
    assert r.VELERO_AWS_PLUGIN_IMAGE in text


# ---------------- AC-117.24: the e2e script text ----------------

def e2e() -> str:
    return (ROOT / "tests" / "e2e" / "run.sh").read_text()


def test_the_e2e_script_forces_the_operators_on_cluster_up_ac_117_24():  # AC-117.24 (needs a cluster)
    text = e2e()
    assert "WITH_BARMAN_CLOUD=1" in text and "WITH_VELERO=1" in text


def test_the_e2e_script_declares_the_backed_up_system_ac_117_24():  # AC-117.24 (needs a cluster)
    text = e2e()
    for needle in ("resource add backups --type bucket", "e2e-files", "backup:", "environments.dev.backup", "instances.dev.backup"):
        assert needle in text, needle if needle != "backup:" else "a backup key in system.yaml"


def test_the_e2e_script_backs_up_and_restores_a_database_to_a_point_in_time_ac_117_24():  # AC-117.24 (needs a cluster)
    text = e2e()
    for needle in ("resource backup postgres --env dev", "backup completed", "pg_switch_wal", "resource restore postgres --env dev --to",
                   "resource restore postgres --env dev --switch", "resource restore postgres --env dev --discard"):
        assert needle in text, f"tests/e2e/run.sh lacks {needle!r}"
    assert re.search(r"row A|row_a|'A'|\bA\b", text) and re.search(r"row B|row_b|'B'|\bB\b", text)


def test_the_e2e_script_checks_the_switch_reads_a_and_not_b_ac_117_24():  # AC-117.24 (needs a cluster)
    text = e2e()
    assert re.search(r"(?i)restored.*(row|read)|point.in.time|PITR", text) and re.search(r"(?i)not.*\bB\b|without B|B is (gone|absent|missing)|must not", text)


def test_the_e2e_script_restores_an_environment_with_replace_ac_117_24():  # AC-117.24 (needs a cluster)
    text = e2e()
    for needle in ("system restore dev --backup", "--replace", "databases are not part of environment backups", "kind: Backup"):
        assert needle in text, f"tests/e2e/run.sh lacks {needle!r}"
    assert re.search(r"(?i)uid", text), "the database cluster must keep its UID"
    assert "still exist" in text or "volumes of" in text, "the refusal without --replace lists the volumes"


def test_the_e2e_script_writes_a_file_and_an_object_before_the_backup_and_reads_both_back_ac_117_24():  # AC-117.24 (needs a cluster)
    text = e2e()
    assert "e2e-files-0" in text and re.search(r"(?i)content differs|differs", text)
    assert "files" in text and re.search(r"(?i)object", text)


def test_the_e2e_script_checks_status_after_the_on_demand_backup_ac_117_31():  # AC-117.31 (needs a cluster)
    text = e2e()
    assert "last_success" in text and "system status" in text


# ---------------- AC-117.25: docs ----------------

def test_the_domain_model_lists_backup_next_to_observability_and_as_a_database_instance_key_ac_117_25():  # AC-117.25
    lines = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text().splitlines()
    env = next(ln for ln in lines if ln.startswith("| `environments.<env>`"))
    assert "`observability`" in env and "`backup`" in env
    inst = [ln for ln in lines if ln.startswith("| `resources.<name>.instances.<env>`") or ln.startswith("| database `resources.<name>.instances.<env>`")]
    assert inst and any("`backup`" in ln for ln in inst)
    text = "\n".join(lines)
    assert "BACKUP-AND-RESTORE.md" in text and "spec 117" in text


def test_the_backup_guide_states_what_each_kind_of_backup_covers_ac_117_25():  # AC-117.25
    p = ROOT / "docs" / "BACKUP-AND-RESTORE.md"
    assert p.is_file(), "docs/BACKUP-AND-RESTORE.md exists"
    text = p.read_text()
    flat = " ".join(text.split()).lower()
    assert re.search(r"environment backup is not a consistent database backup", flat)
    assert "/resource:restore" in text and re.search(r"databases? (is|are) restored only with `?/resource:restore", flat)
    assert re.search(r"external databases? (is|are) backed up by (its|their) provider", flat)
    assert re.search(r"cache data is not backed up", flat)
    for needle in ("Velero", "Barman", "emptyDir", "remote.s3", "--confirm prod", "/system:restore", "/resource:backup", "point in time"):
        assert needle.lower() in flat, needle.lower()


def test_the_guide_has_a_table_of_what_each_backup_covers_ac_117_25():  # AC-117.25
    text = (ROOT / "docs" / "BACKUP-AND-RESTORE.md").read_text()
    table = [ln for ln in text.splitlines() if ln.startswith("|")]
    assert len(table) >= 4, "a table with a header, a separator and a row per kind of data"
    joined = " ".join(table).lower()
    for needle in ("database", "volume", "namespace", "cache", "bucket"):
        assert needle in joined, needle


def test_the_user_journey_and_the_site_link_the_guide_ac_117_25():  # AC-117.25
    assert "BACKUP-AND-RESTORE.md" in (ROOT / "docs" / "USER-JOURNEY.md").read_text()
    assert "backup" in (ROOT / "site/src/content/docs/concepts/addons.md").read_text().lower()


# ---------------- plugins, commands, changelog ----------------

def plugin_version(name):
    import json as j
    manifest = j.loads((ROOT / f"plugins/{name}/.claude-plugin/plugin.json").read_text())["version"]
    market = next(p["version"] for p in j.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"] if p["name"] == name)
    return manifest, market


def front(path):
    text = (ROOT / path).read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has frontmatter"
    return yaml.safe_load(m.group(1)), text


def test_the_resource_plugin_is_1_3_0_and_has_backup_and_restore_commands_ac_117_31():  # AC-117.31
    assert plugin_version("resource") == ("1.4.0", "1.4.0")  # spec 118: resource plugin 1.4.0
    meta, body = front("plugins/resource/commands/backup.md")
    assert len(meta["description"]) < 260 and "Usage: /resource:backup <db> --env <env>" in meta["description"]
    assert "cplat resource backup" in body and "$ARGUMENTS" in body


def test_the_restore_command_describes_the_three_actions_ac_117_8():  # AC-117.8
    meta, body = front("plugins/resource/commands/restore.md")
    assert len(meta["description"]) < 260
    assert "Usage: /resource:restore <db> --env <env> (--to <time|latest> | --switch | --discard) [--confirm prod]" in meta["description"]
    assert "cplat resource restore" in body and "$ARGUMENTS" in body and "--dry-run" in body


def test_the_system_plugin_is_1_1_0_and_has_the_restore_command_ac_117_19():  # AC-117.19
    assert plugin_version("system") == ("1.2.0", "1.2.0")  # spec 117: 1.1.0 went to spec 122 (/system:set) first
    meta, body = front("plugins/system/commands/restore.md")
    assert len(meta["description"]) < 260
    assert "Usage: /system:restore <env> [--backup <name|latest>] [--replace] [--confirm prod]" in meta["description"]
    assert "cplat system restore" in body and "$ARGUMENTS" in body
    assert "Backups" in (ROOT / "plugins/system/commands/status.md").read_text()


def test_the_plugin_readmes_list_the_new_commands_ac_117_31():  # AC-117.31
    assert "/resource:backup" in (ROOT / "plugins/resource/README.md").read_text() and "/resource:restore" in (ROOT / "plugins/resource/README.md").read_text()
    assert "/system:restore" in (ROOT / "plugins/system/README.md").read_text()


def test_the_changelog_announces_spec_117_as_a_minor_change_with_the_pins_ac_117_26():  # AC-117.26
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    sections = re.split(r"(?m)^(?=## \[)", text)
    hits = [s for s in sections if s.startswith("## [") and re.search(r"spec 117|ADR-061|ADR-062", s)]  # spec 117: ADR-060 went to spec 125 first
    assert hits, "the change is listed"
    first = hits[0]
    assert re.match(r"## \[(Unreleased|5\.[1-9]\d*\.0)\]", first.splitlines()[0]) and "BREAKING" not in first
    for needle in ("plugin-barman-cloud 0.8.1", "cert-manager v1.21.3", "velero 12.2.1", "velero-plugin-for-aws v1.14.4", "operators: owner"):
        assert needle in first, needle
    assert first.index("spec 117") < first.index("spec 116") if "spec 116" in first else True
