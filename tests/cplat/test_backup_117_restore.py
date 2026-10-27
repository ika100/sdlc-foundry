"""Spec 117 acceptance tests, the commands: `cplat resource backup` (AC-117.31, .32), `cplat resource restore` (AC-117.8 to .14),
`cplat system restore` (AC-117.14, .19 to .21).

Contract: design.md "cplat resource backup", "cplat resource restore" and "cplat system restore" (exact flags, texts and exit codes).
The cluster is `FakeKube` behind the one kubectl seam of `backupstate`; a restore commits to a local git repo and takes the apply path
(no Argo CD application in the fake cluster); time passes only when the code sleeps (`clock`). Nothing touches the network.

Assumptions (the design does not fix them): objects are created with `create`/`apply` and read back with `get <kind> <name> -n NS -o json`;
a restored cluster appears in the fake when `apply -k` runs; the Secret `<system>-<db>-app` is read with `get secret` and patched with
`patch`; running components' pods are deleted with `delete pod -l app=<component>`."""
import base64
import json
import re

import pytest
import yaml

import cplat
import gitops
from backup_fixtures import (PLUGIN, argo_app, bdoc, clock, cnpg_backup, cnpg_cluster, kube, make_repo, objectstore,  # noqa: F401  (fixtures)
                             pod_volume_backup, restored_state, state_path, switched_state, tree_state, velero_backup, write_state)
from resources_fixtures import APP, comp  # spec 117 slip: APP was used but not imported
from system_fixtures import git as git_cmd

DEV = {"to": "backups"}
NS = "shop-dev"
HOW = "choose one of --to <time>, --switch or --discard"


def run(*argv, capsys):
    rc = cplat.main([*map(str, argv)])
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


def commit_all(repo, msg="state"):
    git_cmd(repo, "add", "-A")
    git_cmd(repo, "commit", "-q", "-m", msg)


def log(repo) -> list[str]:
    return git_cmd(repo, "log", "--format=%s").splitlines()


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path, bdoc(dbb={"dev": DEV, "prod": DEV}))


def with_state(repo, state, env="dev"):
    """The repo as an earlier `cplat resource restore` left it: state file, re-rendered, committed."""
    import subprocess
    import sys
    write_state(repo, state, env)
    subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    commit_all(repo)
    return repo


def window(kube, first="2026-09-27T03:00:12Z", latest="2026-10-27T10:41:02Z", **kw):
    kube.healthy_database(windows={"shop-orders-db": first} if first else {}, **kw)
    kube.pg_latest = latest or ""
    return kube


def restored_appears(kube, ready=True, message=""):
    """`apply -k` of the addon directory creates the restored cluster, as Argo CD or the apply would."""
    def hook(k, args):
        k.put("cluster", cnpg_cluster("shop-orders-db-g1", ready=ready, message=message))
    kube.on_apply_k = hook


def nothing_changed(repo, kube, before):
    assert tree_state(repo) == before and kube.writes() == []


# ======================= AC-117.31 / AC-117.32: resource backup =======================

def backup(repo, capsys, *extra, env="dev", name="orders-db"):
    return run("resource", "backup", name, "--env", env, "--repo-dir", repo, *extra, capsys=capsys)


def test_a_completed_backup_prints_its_time_and_exits_0_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T10:00:00Z"}
    rc, out = backup(repo, capsys)
    assert rc == 0, out
    assert re.search(r"^backup completed: orders-db/dev at 2026-10-27T10:00:00Z \(Backup shop-orders-db-manual-\d{14}\)$", out, re.M), out


def test_the_backup_object_is_a_plugin_backup_of_the_active_cluster_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T10:00:00Z"}
    backup(repo, capsys)
    [b] = kube.created("Backup")
    assert re.fullmatch(r"shop-orders-db-manual-\d{14}", b["metadata"]["name"]) and b["metadata"].get("namespace", NS) == NS
    assert b["spec"] == {"cluster": {"name": "shop-orders-db"}, "method": "plugin", "pluginConfiguration": {"name": PLUGIN}}


def test_the_backup_of_a_switched_database_is_taken_on_the_active_generation_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    with_state(repo, switched_state())
    window(kube)
    kube.put("cluster", cnpg_cluster("shop-orders-db-g1"))
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T12:00:00Z"}
    rc, out = backup(repo, capsys)
    [b] = kube.created("Backup")
    assert rc == 0 and b["spec"]["cluster"] == {"name": "shop-orders-db-g1"} and b["metadata"]["name"].startswith("shop-orders-db-g1-manual-")


def test_a_failed_backup_prints_the_reason_and_exits_1_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "failed", "error": "could not connect to the bucket"}
    rc, out = backup(repo, capsys)
    assert rc == 1 and "backup failed: orders-db/dev: could not connect to the bucket" in out


def test_a_backup_that_does_not_end_in_30_minutes_fails_with_the_phase_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "started"}
    start = clock.now
    rc, out = backup(repo, capsys)
    assert rc == 1 and re.search(r"backup failed: orders-db/dev: not finished after 30 minutes \(Backup shop-orders-db-manual-\d{14} is started\)", out), out
    assert 30 * 60 <= clock.now - start <= 31 * 60 + 60, "it waited about 30 minutes (polling every 10 seconds)"


def test_the_backup_json_has_result_backup_at_and_reason_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T10:00:00Z"}
    rc, out = backup(repo, capsys, "--json")
    d = json.loads(out)
    assert rc == 0 and d["result"] == "completed" and d["at"] == "2026-10-27T10:00:00Z" and d["reason"] is None
    assert re.fullmatch(r"shop-orders-db-manual-\d{14}", d["backup"])
    kube.store["cnpg.backup"] = []
    kube.auto["cnpg.backup"] = {"phase": "failed", "error": "boom"}
    rc, out = backup(repo, capsys, "--json")
    d = json.loads(out)
    assert rc == 1 and d["result"] == "failed" and d["reason"] == "boom" and d["at"] is None


def test_status_shows_the_time_of_the_completed_backup_as_last_success_ac_117_31(repo, kube, capsys, clock, monkeypatch):  # AC-117.31
    import status
    monkeypatch.setattr(status, "sh", lambda cmd: None)
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T10:00:00Z"}
    assert backup(repo, capsys)[0] == 0
    assert status.main(["--repo-dir", str(repo), "--context", "ctx", "--json"]) == 0
    b = json.loads(capsys.readouterr().out)["backups"]
    i = next(x for x in b["resource_instances"] if x["resource"] == "orders-db" and x["environment"] == "dev")
    assert i["backup"]["last_success"] == "2026-10-27T10:00:00Z"


def test_the_backup_does_not_touch_the_schedule_or_the_retention_ac_117_31(repo, kube, capsys, clock):  # AC-117.31
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T10:00:00Z"}
    before = tree_state(repo)
    backup(repo, capsys)
    assert tree_state(repo) == before, "git is not touched"
    assert [w[0] for w in kube.writes()] and all(w[0] in ("create", "apply") for w in kube.writes())
    assert not kube.created("ScheduledBackup") and not kube.created("ObjectStore")


def no_instance_repo(tmp_path):
    comps = {"api": comp("api", ["orders-db", "backups"], envs=("dev",))}
    return make_repo(tmp_path, bdoc(dbb={"dev": DEV}, comps=comps))


REFUSALS = [
    ({"env": "qa"}, "--env must be dev, staging or prod"),
    ({"name": "nope"}, "nope is not a resource of the system (resources: orders-db, backups)"),
    ({"name": "backups"}, "backups is a bucket: only a database is backed up with /resource:backup"),
    ({"env": "staging"}, "orders-db has no backup in staging: set resources.orders-db.instances.staging.backup in system.yaml"),
]


@pytest.mark.parametrize("kw, text", REFUSALS)
def test_a_backup_refusal_changes_nothing_and_says_why_ac_117_32(repo, kube, capsys, kw, text):  # AC-117.32
    window(kube)
    before = tree_state(repo)
    rc, out = backup(repo, capsys, **kw)
    assert rc == 1 and text in out, out
    nothing_changed(repo, kube, before)


def test_backup_of_an_external_database_is_refused_ac_117_32(tmp_path, kube, capsys):  # AC-117.32
    repo = make_repo(tmp_path, bdoc(dbb={"dev": DEV}, db_kw={"instances": {"prod": {"external": True}}}))
    before = tree_state(repo)
    rc, out = backup(repo, capsys, env="prod")
    assert rc == 1 and "orders-db in prod: an external database is backed up by its provider" in out
    nothing_changed(repo, kube, before)


def test_backup_for_an_environment_without_an_instance_is_refused_ac_117_32(tmp_path, kube, capsys):  # AC-117.32
    repo = no_instance_repo(tmp_path)
    before = tree_state(repo)
    rc, out = backup(repo, capsys, env="prod")
    assert rc == 1 and "orders-db has no instance in prod (no component that runs in prod uses it)" in out
    nothing_changed(repo, kube, before)


def test_backup_of_an_unreadable_cluster_exits_1_with_the_reason_ac_117_32(repo, kube, capsys):  # AC-117.32
    kube.error = (1, "connection refused")
    rc, out = backup(repo, capsys)
    assert rc == 1 and "cannot read the cluster: " in out and "connection refused" in out
    assert not kube.created("Backup")


# ======================= AC-117.8 / .11: resource restore --to =======================

def restore(repo, capsys, *extra, env="dev", name="orders-db"):
    return run("resource", "restore", name, "--env", env, "--repo-dir", repo, *extra, capsys=capsys)


def test_restore_to_a_time_creates_a_restored_instance_next_to_the_running_one_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    restored_appears(kube)
    before = head_of(repo)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z")
    assert rc == 0, out
    assert yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1]) == restored_state("2026-10-27T09:59:00Z")
    assert (repo / APP / "addons/dev/orders-db/cluster-g1.yaml").is_file()
    assert head_of(repo) != before and log(repo)[0] == "chore(restore): restore orders-db/dev to 2026-10-27T09:59:00Z"
    assert git_cmd(repo, "status", "--porcelain") == "", "the change is committed"
    applied = [c for c in kube.calls if c[0][:1] == ["apply"] and "-k" in c[0]]
    assert applied and any("applications/shop/addons/dev/orders-db" in a for a in applied[0][0]) and "shop-dev" in applied[0][0]


def test_restore_prints_the_name_and_the_switch_command_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    restored_appears(kube)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert "restored orders-db/dev to 2026-10-27T09:59:00Z as shop-orders-db-g1; components still use shop-orders-db" in lines
    assert "check it: kubectl -n shop-dev exec -it shop-orders-db-g1-1 -- psql shop" in lines
    assert "switch to it: /resource:restore orders-db --env dev --switch" in lines


def test_the_running_instance_and_the_components_are_not_touched_by_a_restore_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    restored_appears(kube)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z")
    assert rc == 0, out
    bad = [w for w in kube.writes() if w[0] in ("delete", "patch", "annotate", "scale", "rollout")]
    assert bad == []
    assert "shop-orders-db-app" not in " ".join(" ".join(w) for w in kube.writes()), "the connection Secret is not touched"


def test_restore_normalises_an_offset_time_to_utc_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    restored_appears(kube)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T11:59:00+02:00")
    assert rc == 0, out
    assert yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])["clusters"][1]["from"] == {"server": "shop-orders-db", "to": "2026-10-27T09:59:00Z"}
    assert "restored orders-db/dev to 2026-10-27T09:59:00Z as shop-orders-db-g1" in out


def test_restore_to_latest_keeps_latest_in_the_state_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    restored_appears(kube)
    rc, out = restore(repo, capsys, "--to", "latest")
    assert rc == 0, out
    assert yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])["clusters"][1]["from"] == {"server": "shop-orders-db", "to": "latest"}
    assert "restored orders-db/dev to latest as shop-orders-db-g1" in out
    assert "recoveryTarget" not in (repo / APP / "addons/dev/orders-db/cluster-g1.yaml").read_text()


def test_restore_keeps_fractional_seconds_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    restored_appears(kube)
    restore(repo, capsys, "--to", "2026-10-27T09:59:00.250Z")
    assert yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])["clusters"][1]["from"]["to"] == "2026-10-27T09:59:00.250Z"


def test_a_dry_run_runs_the_checks_and_changes_nothing_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z", "--dry-run")
    assert rc == 0 and "will_do" in out
    nothing_changed(repo, kube, before)
    assert not state_path(repo).exists()


def test_the_restore_json_is_a_report_ac_117_8(repo, kube, capsys):  # AC-117.8
    window(kube)
    restored_appears(kube)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z", "--json")
    assert rc == 0 and isinstance(json.loads(out), dict)


@pytest.mark.parametrize("extra, text", [
    ([], HOW),
    (["--to", "latest", "--switch"], HOW),
    (["--switch", "--discard"], HOW),
    (["--to", "latest", "--confirm", "staging"], "--confirm takes prod"),
    (["--to", "yesterday"], "--to must be an RFC 3339 time with an offset (e.g. 2026-10-27T09:30:00Z) or latest, got 'yesterday'"),
    (["--to", "2026-10-27T09:30:00"], "--to must be an RFC 3339 time with an offset (e.g. 2026-10-27T09:30:00Z) or latest, got '2026-10-27T09:30:00'"),
    (["--to", "2026-10-27"], "--to must be an RFC 3339 time with an offset (e.g. 2026-10-27T09:30:00Z) or latest, got '2026-10-27'"),
])
def test_an_invalid_call_changes_nothing_ac_117_11(repo, kube, capsys, extra, text):  # AC-117.11
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, *extra)
    assert rc == 1 and text in out, out
    nothing_changed(repo, kube, before)


def test_a_time_before_the_earliest_restore_point_shows_both_ends_ac_117_11(repo, kube, capsys):  # AC-117.11
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "2026-01-01T00:00:00Z")
    assert rc == 1 and ("2026-01-01T00:00:00Z is outside the restore points of orders-db/dev: earliest 2026-09-27T03:00:12Z, latest 2026-10-27T10:41:02Z") in out
    nothing_changed(repo, kube, before)


def test_a_time_after_the_latest_restore_point_is_refused_ac_117_11(repo, kube, capsys):  # AC-117.11
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "2026-12-01T00:00:00Z")
    assert rc == 1 and "2026-12-01T00:00:00Z is outside the restore points of orders-db/dev: earliest 2026-09-27T03:00:12Z, latest 2026-10-27T10:41:02Z" in out
    nothing_changed(repo, kube, before)


def test_without_any_restore_point_both_ends_read_none_ac_117_11(repo, kube, capsys):  # AC-117.11
    window(kube, first=None, latest=None)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z")
    assert rc == 1 and "is outside the restore points of orders-db/dev: earliest none, latest none" in out


def test_a_database_without_backup_in_the_environment_is_refused_ac_117_11(repo, kube, capsys):  # AC-117.11
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "latest", env="staging")
    assert rc == 1 and "orders-db has no backup in staging: set resources.orders-db.instances.staging.backup in system.yaml" in out
    nothing_changed(repo, kube, before)


def test_an_external_database_cannot_be_restored_ac_117_11(tmp_path, kube, capsys):  # AC-117.11
    repo = make_repo(tmp_path, bdoc(dbb={"dev": DEV}, db_kw={"instances": {"prod": {"external": True}}}))
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "latest", env="prod")
    assert rc == 1 and "orders-db in prod: an external database is backed up by its provider" in out
    nothing_changed(repo, kube, before)


def test_an_environment_without_an_instance_is_refused_ac_117_11(tmp_path, kube, capsys):  # AC-117.11
    repo = no_instance_repo(tmp_path)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "latest", env="prod")
    assert rc == 1 and "orders-db has no instance in prod (no component that runs in prod uses it)" in out
    nothing_changed(repo, kube, before)


def test_a_second_restore_while_a_restored_instance_exists_names_discard_ac_117_11(repo, kube, capsys):  # AC-117.11
    with_state(repo, restored_state())
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "latest")
    assert rc == 1 and "orders-db/dev already has a restored instance shop-orders-db-g1; discard it first: /resource:restore orders-db --env dev --discard" in out
    nothing_changed(repo, kube, before)


def test_a_restore_while_a_previous_instance_exists_names_discard_ac_117_11(repo, kube, capsys):  # AC-117.11
    with_state(repo, switched_state())
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "latest")
    assert rc == 1 and "orders-db/dev already has a previous instance shop-orders-db; discard it first: /resource:restore orders-db --env dev --discard" in out
    nothing_changed(repo, kube, before)


def test_a_dirty_tree_is_refused_before_anything_changes_ac_117_11(repo, kube, capsys):  # AC-117.11
    window(kube)
    (repo / "stray.txt").write_text("x")
    with pytest.raises(Exception) as e:
        gitops.require_clean(repo)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--to", "latest")
    assert rc == 1 and str(e.value.args[0]) in out
    nothing_changed(repo, kube, before)


# ======================= AC-117.12: failure =======================

def test_a_restore_that_does_not_become_ready_reports_failed_and_keeps_the_instance_ac_117_12(repo, kube, capsys, clock):  # AC-117.12
    window(kube)
    restored_appears(kube, ready=False, message="Setting up primary")
    kube.wait_rc = 1
    start = clock.now
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z")
    assert rc == 1 and "restore failed: orders-db/dev: " in out, out
    assert clock.now - start >= 29 * 60 or kube.wait_rc, "it waited up to 30 minutes"
    assert (repo / APP / "addons/dev/orders-db/cluster-g1.yaml").is_file() and state_path(repo).is_file(), "the failed instance stays in git"
    deletes = [w for w in kube.writes() if w[0] == "delete"]
    assert deletes == [], "the failed instance stays in the cluster for inspection"
    assert not [w for w in kube.writes() if w[0] == "patch"], "components and the connection Secret stay unchanged"


def test_a_failed_recovery_job_reports_the_reason_ac_117_12(repo, kube, capsys, clock):  # AC-117.12
    window(kube)
    def hook(k, args):
        c = cnpg_cluster("shop-orders-db-g1", ready=False, message="Failed")
        c["status"]["phase"] = "Failed"
        c["status"]["phaseReason"] = "recovery job failed: could not restore base backup"
        k.put("cluster", c)
    kube.on_apply_k = hook
    kube.wait_rc = 1
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z")
    assert rc == 1 and "restore failed: orders-db/dev:" in out


# ======================= AC-117.9 / .13: --switch =======================

def switch_world(repo, kube, env="dev", active_ready=True):
    with_state(repo, restored_state(), env)
    kube.put("cluster", cnpg_cluster("shop-orders-db", ns="shop-" + env),  # spec 117 slip: the clusters sit in the environment's namespace
             cnpg_cluster("shop-orders-db-g1", ns="shop-" + env, ready=active_ready, message="" if active_ready else "Setting up primary"))
    kube.put("objectstore", objectstore({"shop-orders-db": "2026-09-27T03:00:12Z"}))
    b64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731
    kube.put("secret", {"metadata": {"name": "shop-orders-db-app", "namespace": "shop-" + env, "ownerReferences": [{"kind": "Cluster", "name": "shop-orders-db"}]},
                        "data": {"host": b64("shop-orders-db-rw"), "uri": b64("postgresql://shop:pw@shop-orders-db-rw:5432/shop"), "dbname": b64("shop")}})
    kube.put("pod", {"metadata": {"name": "api-1", "namespace": "shop-" + env, "labels": {"app": "api"}}})
    kube.put("scheduledbackup", {"metadata": {"name": "shop-orders-db", "namespace": "shop-" + env}})
    return repo


def test_switch_makes_the_restored_instance_the_active_one_in_git_ac_117_9(repo, kube, capsys):  # AC-117.9
    switch_world(repo, kube)
    rc, out = restore(repo, capsys, "--switch")
    assert rc == 0, out
    state = yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])
    old, new = state["clusters"]
    assert (old["name"], old["role"]) == ("shop-orders-db", "previous") and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z", old["until"])
    assert new == {"name": "shop-orders-db-g1", "role": "active", "from": {"server": "shop-orders-db", "to": "2026-10-27T09:59:00Z"}} and state["next"] == 2
    assert log(repo)[0] == "chore(restore): switch orders-db/dev to shop-orders-db-g1" and git_cmd(repo, "status", "--porcelain") == ""


def test_switch_prints_the_result_and_the_discard_command_ac_117_9(repo, kube, capsys):  # AC-117.9
    switch_world(repo, kube)
    rc, out = restore(repo, capsys, "--switch")
    assert ("switched orders-db/dev to shop-orders-db-g1; shop-orders-db is previous (no connections); "
            "discard it with /resource:restore orders-db --env dev --discard") in out


def test_switch_repoints_the_connection_secret_without_renaming_it_ac_117_9(repo, kube, capsys):  # AC-117.9
    switch_world(repo, kube)
    restore(repo, capsys, "--switch")
    patches = [c for c in kube.calls if c[0][:1] == ["patch"]]
    assert patches and all("shop-orders-db-app" in " ".join(c[0]) for c in patches)
    text = " ".join(" ".join(c[0]) + (c[2] or "") for c in patches)
    assert "ownerReferences" in text, "the Secret is detached from CloudNativePG"
    new = "shop-orders-db-g1-rw"
    assert new in text or base64.b64encode(new.encode()).decode() in text or base64.b64encode(b"postgresql://shop:pw@shop-orders-db-g1-rw:5432/shop").decode() in text


def test_switch_deletes_the_scheduled_backup_so_it_is_recreated_for_the_new_cluster_ac_117_13(repo, kube, capsys):  # AC-117.13
    switch_world(repo, kube)
    restore(repo, capsys, "--switch")
    assert any(c[0][:1] == ["delete"] and "scheduledbackup" in c[0][1].lower() and "shop-orders-db" in c[0] for c in kube.calls)
    sb = yaml.safe_load((repo / APP / "addons/dev/orders-db/scheduledbackup.yaml").read_text())
    assert sb["spec"]["cluster"] == {"name": "shop-orders-db-g1"} and sb["spec"]["schedule"] == "0 0 3 * * *"
    cl = yaml.safe_load((repo / APP / "addons/dev/orders-db/cluster-g1.yaml").read_text())
    assert cl["spec"]["plugins"][0]["name"] == PLUGIN, "the switched cluster is backed up to the same bucket"
    assert yaml.safe_load((repo / APP / "addons/dev/orders-db/objectstore.yaml").read_text())["spec"]["retentionPolicy"] == "30d"


def test_switch_restarts_the_pods_of_the_components_that_use_the_database_ac_117_9(repo, kube, capsys):  # AC-117.9
    switch_world(repo, kube)
    restore(repo, capsys, "--switch")
    deletes = [" ".join(c[0]) for c in kube.calls if c[0][:1] == ["delete"] and c[0][1].lower().startswith("pod")]
    assert any("app=api" in d and "shop-dev" in d for d in deletes), deletes


def test_switch_does_not_delete_the_old_instance_ac_117_9(repo, kube, capsys):  # AC-117.9
    switch_world(repo, kube)
    restore(repo, capsys, "--switch")
    assert not [c for c in kube.calls if c[0][:1] == ["delete"] and c[0][1].lower().startswith("cluster")]
    assert (repo / APP / "addons/dev/orders-db/cluster.yaml").is_file(), "the old instance keeps running as previous"


def test_switch_without_a_restored_instance_is_refused_ac_117_11(repo, kube, capsys):  # AC-117.11
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--switch")
    assert rc == 1 and "orders-db/dev has no restored instance to switch to; restore one first: /resource:restore orders-db --env dev --to <time>" in out
    nothing_changed(repo, kube, before)


def test_switch_to_an_instance_that_is_not_ready_is_refused_ac_117_11(repo, kube, capsys):  # AC-117.11
    switch_world(repo, kube, active_ready=False)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--switch")
    assert rc == 1 and "orders-db/dev: the restored instance shop-orders-db-g1 is not ready (" in out
    nothing_changed(repo, kube, before)


# ======================= AC-117.10: --discard =======================

def test_discard_removes_a_restored_instance_and_its_volumes_ac_117_10(repo, kube, capsys):  # AC-117.10
    switch_world(repo, kube)
    rc, out = restore(repo, capsys, "--discard")
    assert rc == 0, out
    assert "discarded shop-orders-db-g1 (restored) of orders-db/dev and its volumes; shop-orders-db stays active, the backups in the bucket are unchanged" in out
    assert yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])["clusters"] == [{"name": "shop-orders-db", "role": "active"}]
    assert not (repo / APP / "addons/dev/orders-db/cluster-g1.yaml").exists()
    assert log(repo)[0] == "chore(restore): discard shop-orders-db-g1 of orders-db/dev"
    deletes = [c[0] for c in kube.calls if c[0][:1] == ["delete"]]
    assert any(d[1].lower().startswith("cluster") and any(a.endswith("shop-orders-db-g1") for a in d) for d in deletes)
    assert not [d for d in deletes if "shop-orders-db" in d], "the active instance is not deleted"
    assert not any(k in " ".join(d).lower() for d in deletes for k in ("objectstore", "backup")), "the backups stay"


def test_discard_removes_a_previous_instance_after_a_switch_ac_117_10(repo, kube, capsys):  # AC-117.10
    with_state(repo, switched_state())
    kube.put("cluster", cnpg_cluster("shop-orders-db"), cnpg_cluster("shop-orders-db-g1"))
    rc, out = restore(repo, capsys, "--discard")
    assert rc == 0, out
    assert "discarded shop-orders-db (previous) of orders-db/dev and its volumes; shop-orders-db-g1 stays active, the backups in the bucket are unchanged" in out
    clusters = yaml.safe_load(state_path(repo).read_text().split("\n", 1)[1])["clusters"]
    assert [c["name"] for c in clusters] == ["shop-orders-db-g1"] and clusters[0]["role"] == "active"
    assert not (repo / APP / "addons/dev/orders-db/cluster.yaml").exists() and (repo / APP / "addons/dev/orders-db/cluster-g1.yaml").is_file()
    assert any(c[0][:1] == ["delete"] and "shop-orders-db" in c[0] for c in kube.calls)


def test_discard_with_nothing_to_discard_is_refused_ac_117_11(repo, kube, capsys):  # AC-117.11
    window(kube)
    before = tree_state(repo)
    rc, out = restore(repo, capsys, "--discard")
    assert rc == 1 and "orders-db/dev has no restored or previous instance to discard" in out
    nothing_changed(repo, kube, before)


# ======================= AC-117.14: prod confirmation =======================

def test_switch_in_prod_prints_the_action_and_does_nothing_without_confirm_ac_117_14(repo, kube, capsys):  # AC-117.14
    switch_world(repo, kube, env="prod")
    before = tree_state(repo)
    kube.calls.clear()
    rc, out = restore(repo, capsys, "--switch", env="prod")
    assert rc == 1 and "would switch orders-db/prod from shop-orders-db to shop-orders-db-g1; nothing was changed: add --confirm prod to do it" in out
    nothing_changed(repo, kube, before)


def test_discard_in_prod_prints_the_action_and_does_nothing_without_confirm_ac_117_14(repo, kube, capsys):  # AC-117.14
    switch_world(repo, kube, env="prod")
    before = tree_state(repo)
    kube.calls.clear()
    rc, out = restore(repo, capsys, "--discard", env="prod")
    assert rc == 1 and "would discard shop-orders-db-g1 (restored) of orders-db/prod and its volumes; nothing was changed: add --confirm prod to do it" in out
    nothing_changed(repo, kube, before)


def test_switch_and_discard_in_prod_run_with_confirm_ac_117_14(repo, kube, capsys):  # AC-117.14
    switch_world(repo, kube, env="prod")
    rc, out = restore(repo, capsys, "--switch", "--confirm", "prod", env="prod")
    assert rc == 0 and "switched orders-db/prod to shop-orders-db-g1" in out
    rc, out = restore(repo, capsys, "--discard", "--confirm", "prod", env="prod")
    assert rc == 0 and "discarded shop-orders-db (previous) of orders-db/prod" in out


def test_restore_to_in_prod_needs_no_confirmation_ac_117_14(repo, kube, capsys):  # AC-117.14
    kube.put("cluster", cnpg_cluster("shop-orders-db", ns="shop-prod"))
    kube.put("objectstore", objectstore({"shop-orders-db": "2026-09-27T03:00:12Z"}, ns="shop-prod"))
    kube.pg_latest = "2026-10-27T10:41:02Z"
    kube.on_apply_k = lambda k, args: k.put("cluster", cnpg_cluster("shop-orders-db-g1", ns="shop-prod"))
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z", env="prod")
    assert rc == 0 and "restored orders-db/prod to 2026-10-27T09:59:00Z as shop-orders-db-g1" in out


def test_the_argo_path_opens_a_pr_waits_for_it_with_merge_and_does_not_apply_ac_117_8(repo, kube, capsys, clock, monkeypatch):  # AC-117.8
    import pr
    calls = {"open": [], "wait": []}
    monkeypatch.setattr(gitops, "open_pr", lambda r, branch, title, body: calls["open"].append((branch, title)) or "https://github.com/acme/shop-gitops/pull/7")
    monkeypatch.setattr(pr, "wait", lambda *a, **k: calls["wait"].append((a, k)) or (True, ["GREEN", "merged"]))
    window(kube)
    kube.put("application", argo_app("addon-orders-db-dev"))
    restore(repo, capsys, "--to", "2026-10-27T09:59:00Z")
    assert len(calls["open"]) == 1 and calls["open"][0][0].startswith("restore/orders-db-dev-")
    assert calls["open"][0][1] == "chore(restore): restore orders-db/dev to 2026-10-27T09:59:00Z"
    assert len(calls["wait"]) == 1 and (True in calls["wait"][0][0] or calls["wait"][0][1].get("merge") is True)
    assert not [c for c in kube.calls if c[0][:1] == ["apply"] and "-k" in c[0]]


def head_of(repo):
    return git_cmd(repo, "rev-parse", "HEAD").strip()


# ======================= system restore =======================

@pytest.fixture()
def erepo(tmp_path):
    return make_repo(tmp_path, bdoc(envb={"dev": DEV, "prod": DEV}))


DB_LINE = "databases are not part of environment backups: restore them with /resource:restore"


def srestore(repo, capsys, *extra, env="dev"):
    return run("system", "restore", env, "--repo-dir", repo, *extra, capsys=capsys)


def three(kube):
    kube.put("velero.backup", velero_backup("b1", done="2026-10-25T03:00:40Z"),
             velero_backup("b2", phase="PartiallyFailed", done="2026-10-26T03:00:40Z", errors=2),
             velero_backup("b3", done="2026-10-27T03:00:40Z"))
    return kube


def last_line(out):
    return [ln for ln in out.splitlines() if ln.strip()][-1].strip()


def test_without_backup_the_command_lists_the_backups_newest_first_ac_117_19(erepo, kube, capsys):  # AC-117.19
    three(kube)
    kube.put("velero.backup", velero_backup("b0", phase="Failed", done="2026-10-24T03:00:40Z", reason="BSL unavailable"),
             velero_backup("b4", phase="InProgress", done=None))
    before = tree_state(erepo)
    rc, out = srestore(erepo, capsys)
    assert rc == 0, out
    lines = out.splitlines()
    assert lines[0] == "backups of shop-dev (newest first):"
    rows = [" ".join(ln.split()) for ln in lines[1:] if ln.strip()]
    assert [r.split()[0] for r in rows] == ["b3", "b2", "b1", "b0", "b4"] or [r.split()[0] for r in rows] == ["b4", "b3", "b2", "b1", "b0"]
    by = {r.split()[0]: r for r in rows}
    assert by["b3"] == "b3 2026-10-27T03:00:40Z completed"
    assert by["b2"] == "b2 2026-10-26T03:00:40Z partially failed (2 errors)"
    assert by["b0"] == "b0 2026-10-24T03:00:40Z failed (BSL unavailable)"
    assert by["b4"].endswith("in progress")
    nothing_changed(erepo, kube, before)


@pytest.mark.parametrize("env, text", [
    ("qa", "qa is not an environment (dev, staging, prod)"),
    ("staging", "staging has no backup: set environments.staging.backup in system.yaml"),
    ("dev", "dev has no backups yet: the first scheduled backup has not finished"),
])
def test_a_refused_environment_restore_changes_nothing_ac_117_21(erepo, kube, capsys, env, text):  # AC-117.21
    before = tree_state(erepo)
    rc, out = srestore(erepo, capsys, "--backup", "latest", env=env)
    assert rc == 1 and text in out, out
    nothing_changed(erepo, kube, before)


def test_an_unknown_backup_name_lists_the_available_ones_ac_117_21(erepo, kube, capsys):  # AC-117.21
    three(kube)
    before = tree_state(erepo)
    rc, out = srestore(erepo, capsys, "--backup", "nope")
    assert rc == 1 and "no backup nope in dev; available: b3, b2, b1" in out
    nothing_changed(erepo, kube, before)


def test_restoring_restores_what_is_missing_from_the_namespace_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    three(kube)
    kube.auto["velero.restore"] = {"phase": "Completed", "progress": {"itemsRestored": 12, "totalItems": 12}}
    rc, out = srestore(erepo, capsys, "--backup", "b3")
    assert rc == 0, out
    [r] = kube.created("Restore")
    assert re.fullmatch(r"b3-\d{14}", r["metadata"]["name"]) and r["metadata"].get("namespace", "velero") == "velero"
    assert r["spec"] == {"backupName": "b3", "includedNamespaces": ["shop-dev"], "existingResourcePolicy": "none", "restorePVs": True}
    assert "restored b3 into shop-dev: 12 items" in out and last_line(out) == DB_LINE


def test_latest_means_the_newest_completed_backup_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    three(kube)
    kube.put("velero.backup", velero_backup("b9", phase="PartiallyFailed", done="2026-10-28T03:00:40Z", errors=1))
    kube.auto["velero.restore"] = {"phase": "Completed", "progress": {"itemsRestored": 1}}
    rc, out = srestore(erepo, capsys, "--backup", "latest")
    assert rc == 0 and kube.created("Restore")[0]["spec"]["backupName"] == "b3", out


def volumes_world(kube):
    three(kube)
    kube.put("podvolumebackup", pod_volume_backup("b3", "files-0", "data", workload="files"))
    kube.put("pod", {"metadata": {"name": "files-0", "namespace": NS, "ownerReferences": [{"kind": "StatefulSet", "name": "files"}]},
                     "spec": {"volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "data-files-0"}}]}})
    kube.put("pvc", {"metadata": {"name": "data-files-0", "namespace": NS}})
    kube.put("statefulset", {"metadata": {"name": "files", "namespace": NS}})
    kube.auto["velero.restore"] = {"phase": "Completed", "progress": {"itemsRestored": 7}}
    return kube


def test_existing_volumes_are_listed_and_nothing_is_restored_without_replace_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    volumes_world(kube)
    before = tree_state(erepo)
    kube.calls.clear()
    rc, out = srestore(erepo, capsys, "--backup", "b3")
    assert rc == 1, out
    assert "volumes of b3 still exist in shop-dev: data-files-0 (StatefulSet files)" in out
    assert "nothing was restored: add --replace to stop those workloads, replace their volumes from the backup and start them again" in out
    assert last_line(out) == DB_LINE
    nothing_changed(erepo, kube, before)
    assert not kube.created("Restore")


def idx(kube, pattern):
    for i, c in enumerate(kube.calls):
        if re.search(pattern, " ".join(c[0]) + " " + (c[2] or "")):
            return i
    return -1


def test_replace_stops_the_workload_replaces_the_volume_restores_and_starts_again_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    volumes_world(kube)
    kube.calls.clear()
    rc, out = srestore(erepo, capsys, "--backup", "b3", "--replace")
    assert rc == 0, out
    stop = idx(kube, r"^delete (statefulsets?|sts)\S*[ /]files\b")
    pvc = idx(kube, r"^delete (pvc|persistentvolumeclaims?)\S*[ /]data-files-0\b")
    restore_i = idx(kube, r"kind: Restore")
    assert -1 < stop < pvc < restore_i, (stop, pvc, restore_i)
    lines = [ln.strip() for ln in out.splitlines()]
    order = [lines.index(x) for x in ("stopped StatefulSet files", "replaced data-files-0", "restored b3 into shop-dev: 7 items", "started StatefulSet files")]
    assert order == sorted(order)
    assert last_line(out) == DB_LINE


def test_replace_never_touches_a_database_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    volumes_world(kube)
    kube.put("cluster", cnpg_cluster("shop-orders-db"))
    kube.put("pvc", {"metadata": {"name": "shop-orders-db-1", "namespace": NS, "labels": {"cnpg.io/cluster": "shop-orders-db"}}})
    kube.calls.clear()
    rc, out = srestore(erepo, capsys, "--backup", "b3", "--replace")
    assert rc == 0 and kube.created("Restore"), out
    for args, _, stdin in kube.calls:
        if args[0] in WRITES:
            assert "orders-db" not in " ".join(args) and "cnpg" not in " ".join(args).lower(), args


WRITES = ("create", "apply", "delete", "patch", "annotate", "replace", "scale")


def test_a_partially_failed_restore_reports_the_errors_and_exits_1_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    three(kube)
    kube.auto["velero.restore"] = {"phase": "PartiallyFailed", "errors": 3}
    rc, out = srestore(erepo, capsys, "--backup", "b3")
    name = kube.created("Restore")[0]["metadata"]["name"]
    assert rc == 1 and f"restore partially failed: 3 errors (kubectl -n velero describe restore {name})" in out


def test_a_failed_restore_reports_the_reason_and_exits_1_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    three(kube)
    kube.auto["velero.restore"] = {"phase": "Failed", "failureReason": "backup storage location unavailable"}
    rc, out = srestore(erepo, capsys, "--backup", "b3")
    assert rc == 1 and "restore failed: backup storage location unavailable" in out


def test_prod_restore_without_confirm_prints_the_action_and_changes_nothing_ac_117_14(erepo, kube, capsys, clock):  # AC-117.14
    kube.put("velero.backup", velero_backup("p1", env="prod", done="2026-10-27T03:00:40Z"))
    before = tree_state(erepo)
    rc, out = srestore(erepo, capsys, "--backup", "p1", env="prod")
    assert rc == 1 and "would restore p1 into shop-prod" in out and "nothing was changed: add --confirm prod to do it" in out
    assert last_line(out) == DB_LINE or "nothing was changed" in last_line(out)
    nothing_changed(erepo, kube, before)


def test_prod_restore_names_the_volumes_it_would_replace_ac_117_14(erepo, kube, capsys, clock):  # AC-117.14
    kube.put("velero.backup", velero_backup("p1", env="prod", done="2026-10-27T03:00:40Z"))
    kube.put("podvolumebackup", pod_volume_backup("p1", "files-0", "data", ns="shop-prod", workload="files"))
    kube.put("pod", {"metadata": {"name": "files-0", "namespace": "shop-prod", "ownerReferences": [{"kind": "StatefulSet", "name": "files"}]},
                     "spec": {"volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "data-files-0"}}]}})
    kube.put("pvc", {"metadata": {"name": "data-files-0", "namespace": "shop-prod"}})
    rc, out = srestore(erepo, capsys, "--backup", "p1", "--replace", env="prod")
    assert rc == 1 and "would restore p1 into shop-prod and replace the volumes data-files-0" in out
    assert kube.writes() == []


def test_prod_restore_runs_with_confirm_and_the_list_needs_none_ac_117_14(erepo, kube, capsys, clock):  # AC-117.14
    kube.put("velero.backup", velero_backup("p1", env="prod", done="2026-10-27T03:00:40Z"))
    kube.auto["velero.restore"] = {"phase": "Completed", "progress": {"itemsRestored": 4}}
    rc, out = srestore(erepo, capsys, env="prod")
    assert rc == 0 and "backups of shop-prod (newest first):" in out and kube.writes() == []
    rc, out = srestore(erepo, capsys, "--backup", "p1", "--confirm", "prod", env="prod")
    assert rc == 0 and "restored p1 into shop-prod: 4 items" in out
