"""Spec 117 acceptance tests, the renderer part: `backup` on database instances and environments, the rendered objects, restore
generations, the three operators (AC-117.1, .2, .3, .4, .5, .8, .9, .10, .13 render side, .15, .16, .17, .22, .26, .30 render side).

Contract: design.md "Contract: system.yaml", "Render errors", "rendered objects — database backups", "rendered objects — environment
backups" and "versions table and operators/". The renderer runs as a script in a hand-built checkout; nothing touches the network or a
cluster. Criteria that need a cluster are covered by the rendered contract here and by the text of tests/e2e/run.sh in
test_backup_117_cmds.py. Missing symbols are guarded with getattr so each test fails on its own."""
import json
import re
import subprocess
import sys

import pytest
import yaml

from backup_fixtures import (P, PLUGIN, S3, bdoc, bucket, ext_prod_bucket, objs, rerender, restored_state, state_path, switched_state,
                             write_state)
from resources_fixtures import APP, LABELS, comp, db, external_secret_path, fails, ok, platform_render_module, render5, sets, system, tree, y
from system_fixtures import render, write_system

DEV = {"to": "backups"}
CRON = "(minute hour day-of-month month day-of-week, in UTC)"


def L(name="orders-db") -> dict:
    return {"app.kubernetes.io/name": name, **LABELS}


def dd(env="dev", name="orders-db") -> str:
    return f"{APP}/addons/{env}/{name}"


def dfiles(g, env="dev", name="orders-db") -> list[str]:
    return sorted(k.rsplit("/", 1)[1] for k in g if k.startswith(dd(env, name) + "/"))


def endpoint(env="dev") -> str:
    return f"http://shop-backups-filer.shop-{env}.svc:8333"


def op_names(g) -> list[str]:
    return sorted(k for k in g if k.startswith("operators/"))


# ---------------- AC-117.1: database backup objects ----------------

def test_a_database_backup_renders_the_object_store_ac_117_1(tmp_path):  # AC-117.1
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    assert y(g, f"{dd()}/objectstore.yaml") == {
        "apiVersion": "barmancloud.cnpg.io/v1", "kind": "ObjectStore", "metadata": {"name": "shop-orders-db", "labels": L()},
        "spec": {"retentionPolicy": "30d",
                 "configuration": {"destinationPath": "s3://shop-backups/databases", "endpointURL": endpoint(),
                                   "s3Credentials": {"accessKeyId": {"name": "shop-backups-app", "key": "accessKeyId"},
                                                     "secretAccessKey": {"name": "shop-backups-app", "key": "secretAccessKey"},
                                                     "region": {"name": "shop-backups-app", "key": "region"}},
                                   "wal": {"compression": "gzip"}, "data": {"compression": "gzip"}}}}


def test_a_database_backup_renders_the_scheduled_backup_with_the_defaults_ac_117_1(tmp_path):  # AC-117.1
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    assert y(g, f"{dd()}/scheduledbackup.yaml") == {
        "apiVersion": "postgresql.cnpg.io/v1", "kind": "ScheduledBackup", "metadata": {"name": "shop-orders-db", "labels": L()},
        "spec": {"schedule": "0 0 3 * * *", "immediate": True, "backupOwnerReference": "none", "cluster": {"name": "shop-orders-db"},
                 "method": "plugin", "pluginConfiguration": {"name": PLUGIN}}}


def test_schedule_and_retention_are_used_ac_117_1(tmp_path):  # AC-117.1
    g = ok(tmp_path, bdoc(dbb={"dev": {"to": "backups", "schedule": "30 2 * * *", "retention": "8w"}}))
    assert y(g, f"{dd()}/scheduledbackup.yaml")["spec"]["schedule"] == "0 30 2 * * *"
    assert y(g, f"{dd()}/objectstore.yaml")["spec"]["retentionPolicy"] == "8w"


def test_the_cluster_archives_its_wal_through_the_plugin_ac_117_1(tmp_path):  # AC-117.1
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    spec = y(g, f"{dd()}/cluster.yaml")["spec"]
    assert spec["plugins"] == [{"name": PLUGIN, "isWALArchiver": True, "parameters": {"barmanObjectName": "shop-orders-db"}}]
    assert list(spec)[-1] == "plugins"


def test_the_kustomization_lists_the_backup_files_sorted_ac_117_1(tmp_path):  # AC-117.1
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    assert y(g, f"{dd()}/kustomization.yaml")["resources"] == ["cluster.yaml", "objectstore.yaml", "scheduledbackup.yaml"]
    assert dfiles(g) == ["cluster.yaml", "kustomization.yaml", "objectstore.yaml", "scheduledbackup.yaml"]


def test_the_backup_is_per_environment_ac_117_1(tmp_path):  # AC-117.1
    g = ok(tmp_path, bdoc(dbb={"prod": {"to": "backups", "retention": "4w"}}))
    assert y(g, f"{dd('prod')}/objectstore.yaml")["spec"]["retentionPolicy"] == "4w"
    assert endpoint("prod") == y(g, f"{dd('prod')}/objectstore.yaml")["spec"]["configuration"]["endpointURL"]
    for env in ("dev", "staging"):
        assert dfiles(g, env) == ["cluster.yaml", "kustomization.yaml"]


def test_an_external_target_uses_the_declared_s3_coordinates_ac_117_1(tmp_path):  # AC-117.1
    g = ok(tmp_path, bdoc(dbb={"prod": DEV}, bucket_kw=ext_prod_bucket()))
    c = y(g, f"{dd('prod')}/objectstore.yaml")["spec"]["configuration"]
    assert c["destinationPath"] == "s3://acme-backups/databases" and c["endpointURL"] == S3["endpoint"]
    assert c["s3Credentials"]["accessKeyId"] == {"name": "shop-backups-app", "key": "accessKeyId"}


def test_the_resource_level_s3_is_used_unless_the_instance_has_its_own_whole_mapping_ac_117_1(tmp_path):  # AC-117.1
    other = {"endpoint": "https://minio.example.com", "bucket": "other", "region": "r2", "forcePathStyle": True}
    res_level = bucket(external=True, remote={"s3": dict(S3)}, instances={"staging": {"remote": {"s3": other}}})
    g = ok(tmp_path, bdoc(dbb={"dev": DEV, "staging": DEV}, bucket_kw=res_level))
    assert y(g, f"{dd('dev')}/objectstore.yaml")["spec"]["configuration"]["destinationPath"] == "s3://acme-backups/databases"
    st = y(g, f"{dd('staging')}/objectstore.yaml")["spec"]["configuration"]
    assert st["destinationPath"] == "s3://other/databases" and st["endpointURL"] == "https://minio.example.com"


def test_the_renderer_api_carries_the_backup_with_defaults_ac_117_1(tmp_path):  # AC-117.1
    write_system(tmp_path, bdoc(dbb={"prod": DEV, "dev": {"to": "backups", "schedule": "5 4 * * 1", "retention": "2w"}}, envb={"prod": DEV}))
    r = platform_render_module("render_117_api")
    cfg = r.load_system(tmp_path / APP)["cfg"]
    assert cfg["backup"] == {"prod": {"to": "backups", "schedule": "0 3 * * *", "retention": "30d"}}
    envs = cfg["resources"]["orders-db"]["envs"]
    assert envs["prod"]["backup"] == {"to": "backups", "schedule": "0 3 * * *", "retention": "30d"}
    assert envs["dev"]["backup"] == {"to": "backups", "schedule": "5 4 * * 1", "retention": "2w"}
    assert envs["staging"]["backup"] is None
    assert cfg["resources"]["backups"]["envs"]["dev"]["s3"] is None


# ---------------- AC-117.2 / AC-117.16: checks ----------------

W = "resources.orders-db.instances.prod.backup"
WE = "environments.prod.backup"


def backup_cases(w: str):
    return [
        (["x"], f"{w} must be a mapping with to, schedule and retention"),
        ({"to": "backups", "version": "1.18.2"}, f"{w}: unknown key 'version' (allowed: to, schedule, retention)"),
        ({"schedule": "0 3 * * *"}, f"{w}.to is required: the name of a bucket resource of the system"),
        ({"to": "orders-db"}, f"{w}.to: 'orders-db' is not a bucket resource of the system (buckets: backups)"),
        ({"to": "nope"}, f"{w}.to: 'nope' is not a bucket resource of the system (buckets: backups)"),
        ({"to": "backups", "schedule": "0 3 * *"}, f"{w}.schedule '0 3 * *' is not a five-field cron expression {CRON}"),
        ({"to": "backups", "retention": "30"}, f"{w}.retention '30' must be <n>d or <n>w with n of at least 1"),
    ]


@pytest.mark.parametrize("backup, needle", backup_cases(W))
def test_an_invalid_database_backup_fails_naming_resource_environment_and_key_ac_117_2(tmp_path, backup, needle):  # AC-117.2
    fails(tmp_path, bdoc(dbb={"prod": backup}), P + needle)


@pytest.mark.parametrize("backup, needle", backup_cases(WE))
def test_an_invalid_environment_backup_fails_the_same_way_naming_the_environment_ac_117_16(tmp_path, backup, needle):  # AC-117.16
    fails(tmp_path, bdoc(envb={"prod": backup}), P + needle)


def test_a_list_of_buckets_names_none_when_there_is_no_bucket_ac_117_2(tmp_path):  # AC-117.2
    doc = system({"orders-db": db(instances={"prod": {"backup": {"to": "x"}}})}, {"api": comp("api", ["orders-db"])})
    fails(tmp_path, doc, P + f"{W}.to: 'x' is not a bucket resource of the system (buckets: none)")


def test_the_bucket_must_have_an_instance_in_the_environment_ac_117_2(tmp_path):  # AC-117.2
    comps = {"api": comp("api", ["orders-db"]), "files": comp("files", ["backups"], envs=("dev",))}
    fails(tmp_path, bdoc(dbb={"prod": DEV}, comps=comps),
          P + f"{W}.to: the bucket backups has no resource instance in prod (a component that runs in prod must use it)")


def test_the_environment_bucket_must_have_an_instance_there_too_ac_117_16(tmp_path):  # AC-117.16
    comps = {"api": comp("api", ["orders-db"]), "files": comp("files", ["backups"], envs=("dev",))}
    fails(tmp_path, bdoc(envb={"prod": DEV}, comps=comps),
          P + f"{WE}.to: the bucket backups has no resource instance in prod (a component that runs in prod must use it)")


def test_an_external_target_needs_remote_s3_ac_117_2(tmp_path):  # AC-117.2
    fails(tmp_path, bdoc(dbb={"dev": DEV}, bucket_kw={"external": True}),
          P + "resources.orders-db.instances.dev.backup.to: the external bucket backups needs remote.s3 (endpoint, bucket, region, forcePathStyle) in dev: "
              "backups cannot read them from the secret store")


@pytest.mark.parametrize("bad", ["0 3 * *", "0 3 * * * *", "@daily", "", "60 3 * * *", "0 24 * * *", "0 3 0 * *", "0 3 32 * *", "0 3 * 0 *",
                                 "0 3 * 13 *", "0 3 * * 8", "*/0 * * * *", "a b c d e", "0 3 * * mon", "5-1/x * * * *", "1,,2 * * * *", "0 3 * jan *"])
def test_an_invalid_cron_expression_fails_ac_117_2(tmp_path, bad):  # AC-117.2
    fails(tmp_path, bdoc(dbb={"prod": {"to": "backups", "schedule": bad}}), P + f"{W}.schedule '{bad}' is not a five-field cron expression {CRON}")


@pytest.mark.parametrize("good", ["0 3 * * *", "*/15 * * * *", "0,30 2 * * 0", "0 3 * * 1-5", "0 3 1-31/2 * *", "59 23 31 12 7", "10-20/5 0 1 1 *"])
def test_a_valid_cron_expression_is_accepted_ac_117_2(tmp_path, good):  # AC-117.2
    g = ok(tmp_path, bdoc(dbb={"prod": {"to": "backups", "schedule": good}}))
    assert y(g, f"{dd('prod')}/scheduledbackup.yaml")["spec"]["schedule"] == "0 " + good


@pytest.mark.parametrize("bad", ["0d", "0w", "30", "d", "30m", "1y", "-1d", "30D", "1.5d", "w8", " 8w", ""])
def test_an_invalid_retention_fails_ac_117_2(tmp_path, bad):  # AC-117.2
    fails(tmp_path, bdoc(dbb={"prod": {"to": "backups", "retention": bad}}), P + f"{W}.retention '{bad}' must be <n>d or <n>w with n of at least 1")


@pytest.mark.parametrize("good", ["1d", "7d", "30d", "1w", "52w", "100d"])
def test_a_valid_retention_is_accepted_ac_117_2(tmp_path, good):  # AC-117.2
    g = ok(tmp_path, bdoc(dbb={"prod": {"to": "backups", "retention": good}}))
    assert y(g, f"{dd('prod')}/objectstore.yaml")["spec"]["retentionPolicy"] == good


def test_the_environment_is_checked_before_the_databases_ac_117_2(tmp_path):  # AC-117.2
    p = render5(tmp_path, bdoc(dbb={"dev": {"to": "nope"}}, envb={"dev": {"to": "nope"}}))
    assert p.returncode == 1 and tree(tmp_path) == {}
    assert f"environments.dev.backup.to: 'nope'" in p.stderr
    assert "resources.orders-db.instances.dev.backup.to" not in p.stderr.split("environments.dev.backup.to")[0]


def test_backup_is_not_a_key_of_the_resource_or_of_a_bucket_instance_ac_117_2(tmp_path):  # AC-117.2
    fails(tmp_path, bdoc(db_kw={"backup": DEV}), P + "resources.orders-db: unknown key 'backup'")
    fails(tmp_path / "b", bdoc(bucket_kw={"instances": {"dev": {"backup": DEV}}}), P + "resources.backups.instances.dev: unknown key 'backup'")


def test_the_unknown_key_texts_name_backup_ac_117_2(tmp_path):  # AC-117.2
    fails(tmp_path, bdoc(db_kw={"instances": {"dev": {"bogus": 1}}}),
          P + "resources.orders-db.instances.dev: unknown key 'bogus' (allowed: external, remote, replicas, storage, resources, backup, version)")  # spec 121: version is an instance key
    doc = bdoc()
    doc["environments"]["dev"]["bogus"] = 1
    fails(tmp_path / "e", doc, P + "environments.dev: unknown key 'bogus' (allowed: host, url, policy, promote, observability, operators, backup, autonomy)")  # spec 124: autonomy


# ---------------- remote.s3 of a bucket ----------------

S3W = "resources.backups.remote"


@pytest.mark.parametrize("s3, needle", [
    ("x", f"{S3W}.s3 must be a mapping with endpoint, bucket, region and forcePathStyle"),
    ({**S3, "extra": 1}, f"{S3W}.s3: unknown key 'extra' (allowed: endpoint, bucket, region, forcePathStyle)"),
    ({"endpoint": S3["endpoint"]}, f"{S3W}.s3 needs endpoint, bucket, region and forcePathStyle"),
    ({**S3, "endpoint": "s3.example.com"}, f"{S3W}.s3.endpoint must be an http(s) URL"),
    ({**S3, "bucket": "No_Good"}, f"{S3W}.s3.bucket must be a valid S3 bucket name"),
    ({**S3, "region": ""}, f"{S3W}.s3.region must be a non-empty string"),
    ({**S3, "forcePathStyle": "yes"}, f"{S3W}.s3.forcePathStyle must be true or false"),
])
def test_an_invalid_remote_s3_fails_ac_117_2(tmp_path, s3, needle):  # AC-117.2
    fails(tmp_path, bdoc(bucket_kw={"external": True, "remote": {"s3": s3}}), P + needle)


def test_the_remote_of_a_bucket_lists_s3_as_allowed_and_a_database_does_not_ac_117_2(tmp_path):  # AC-117.2
    fails(tmp_path, bdoc(bucket_kw={"external": True, "remote": {"bogus": 1}}), P + f"{S3W}: unknown key 'bogus' (allowed: path, refreshInterval, s3)")
    fails(tmp_path / "i", bdoc(bucket_kw={"instances": {"prod": {"external": True, "remote": {"bogus": 1}}}}),
          P + "resources.backups.instances.prod.remote: unknown key 'bogus' (allowed: path, refreshInterval, s3)")
    fails(tmp_path / "d", bdoc(db_kw={"external": True, "remote": {"s3": dict(S3)}}), P + "resources.orders-db.remote: unknown key 's3' (allowed: path, refreshInterval)")


# ---------------- AC-117.3: retention in the object store ----------------

@pytest.mark.parametrize("retention", ["1d", "30d", "8w"])
def test_the_object_store_keeps_exactly_the_retention_window_ac_117_3(tmp_path, retention):  # AC-117.3
    g = ok(tmp_path, bdoc(dbb={"dev": {"to": "backups", "retention": retention}}))
    assert y(g, f"{dd()}/objectstore.yaml")["spec"]["retentionPolicy"] == retention


def test_an_environment_backup_keeps_its_backups_for_the_retention_as_a_ttl_ac_117_3(tmp_path):  # AC-117.3
    for retention, ttl in (("30d", "720h0m0s"), ("4w", "672h0m0s"), ("1d", "24h0m0s")):
        g = ok(tmp_path / retention, bdoc(envb={"dev": {"to": "backups", "retention": retention}}))
        assert y(g, f"{APP}/backup/dev/schedule.yaml")["spec"]["template"]["ttl"] == ttl


# ---------------- AC-117.4: off unless set ----------------

def test_a_database_without_backup_archives_nothing_in_any_environment_ac_117_4(tmp_path):  # AC-117.4
    g = ok(tmp_path, bdoc())
    for env in ("dev", "staging", "prod"):
        assert dfiles(g, env) == ["cluster.yaml", "kustomization.yaml"]
        assert "plugins" not in y(g, f"{dd(env)}/cluster.yaml")["spec"]
    assert not [k for k in g if "objectstore" in k or "scheduledbackup" in k or "/backup/" in k]
    assert "barman" not in "".join(g.values()).lower()


def test_backup_in_one_environment_leaves_the_others_untouched_ac_117_4(tmp_path):  # AC-117.4
    g = ok(tmp_path, bdoc(dbb={"prod": DEV}))
    for env in ("dev", "staging"):
        assert dfiles(g, env) == ["cluster.yaml", "kustomization.yaml"] and "plugins" not in y(g, f"{dd(env)}/cluster.yaml")["spec"]
    assert "plugins" in y(g, f"{dd('prod')}/cluster.yaml")["spec"]


def test_a_system_without_backup_has_no_backup_directory_set_or_operator_ac_117_4(tmp_path):  # AC-117.4
    g = ok(tmp_path, bdoc())
    assert not [k for k in g if "/backup/" in k]
    assert not any(f"{s}-backup-" in n for s in ("shop",) for n in sets(g))
    assert "preservedFields" not in g[f"{APP}/applicationset.yaml"]   # spec 128: the retry now comes from the bucket's Job
    assert op_names(g) == ["operators/apps/cloudnative-pg.yaml", "operators/apps/seaweedfs.yaml", "operators/root.yaml"]


# ---------------- AC-117.5: external databases ----------------

def test_an_external_database_with_backup_fails_ac_117_5(tmp_path):  # AC-117.5
    fails(tmp_path, bdoc(db_kw={"external": True, "instances": {"prod": {"backup": DEV}}}),
          P + "resources.orders-db.instances.prod: an external database is backed up by its provider (remove backup)")


def test_an_instance_that_is_external_with_backup_fails_ac_117_5(tmp_path):  # AC-117.5
    fails(tmp_path, bdoc(db_kw={"instances": {"staging": {"external": True, "backup": DEV}}}),
          P + "resources.orders-db.instances.staging: an external database is backed up by its provider (remove backup)")


def test_the_external_refusal_comes_before_the_unknown_key_check_ac_117_5(tmp_path):  # AC-117.5
    err = fails(tmp_path, bdoc(db_kw={"external": True, "instances": {"dev": {"backup": DEV, "bogus": 1}}}),
                P + "resources.orders-db.instances.dev: an external database is backed up by its provider (remove backup)")
    assert "bogus" not in err


def test_an_external_database_in_one_environment_may_sit_next_to_a_backed_up_one_ac_117_5(tmp_path):  # AC-117.5
    g = ok(tmp_path, bdoc(db_kw={"instances": {"prod": {"external": True}}}, dbb={"dev": DEV}))
    assert dfiles(g, "dev") == ["cluster.yaml", "kustomization.yaml", "objectstore.yaml", "scheduledbackup.yaml"]
    assert not [k for k in g if k.startswith(dd("prod"))]


# ---------------- restore generations (AC-117.8, .9, .10, .13) ----------------

def gen_ok(tmp_path, state, dbb=None):
    doc = bdoc(dbb={"dev": DEV} if dbb is None else dbb)
    write_system(tmp_path, doc)
    write_state(tmp_path, state)
    p = render(tmp_path)
    assert p.returncode == 0, p.stderr
    return tree(tmp_path)


def test_a_restored_generation_is_rendered_next_to_the_active_cluster_ac_117_8(tmp_path):  # AC-117.8
    g = gen_ok(tmp_path, restored_state())
    assert dfiles(g) == ["cluster-g1.yaml", "cluster.yaml", "kustomization.yaml", "objectstore.yaml", "restore-state.yaml", "scheduledbackup.yaml"]
    c = y(g, f"{dd()}/cluster-g1.yaml")
    assert c["metadata"]["name"] == "shop-orders-db-g1" and c["kind"] == "Cluster"
    spec = c["spec"]
    assert spec["bootstrap"] == {"recovery": {"source": "origin", "database": "shop", "owner": "shop", "secret": {"name": "shop-orders-db-app"},
                                              "recoveryTarget": {"targetTime": "2026-10-27T09:59:00Z"}}}
    assert spec["externalClusters"] == [{"name": "origin", "plugin": {"name": PLUGIN, "parameters": {"barmanObjectName": "shop-orders-db",
                                                                                                  "serverName": "shop-orders-db"}}}]
    assert list(spec) == ["instances", "imageName", "storage", "enableSuperuserAccess", "bootstrap", "externalClusters", "resources"]


def test_a_restored_generation_has_the_sizing_of_the_active_cluster_and_no_plugin_ac_117_8(tmp_path):  # AC-117.8
    g = gen_ok(tmp_path, restored_state())
    base, gen = y(g, f"{dd()}/cluster.yaml")["spec"], y(g, f"{dd()}/cluster-g1.yaml")["spec"]
    for k in ("instances", "imageName", "storage", "enableSuperuserAccess", "resources"):
        assert gen[k] == base[k], k
    assert "plugins" not in gen and "plugins" in base


def test_the_scheduled_backup_stays_on_the_active_cluster_while_a_restore_is_pending_ac_117_8(tmp_path):  # AC-117.8
    g = gen_ok(tmp_path, restored_state())
    assert y(g, f"{dd()}/scheduledbackup.yaml")["spec"]["cluster"] == {"name": "shop-orders-db"}


def test_a_restore_to_latest_has_no_recovery_target_ac_117_8(tmp_path):  # AC-117.8
    state = restored_state()
    state["clusters"][1]["from"]["to"] = "latest"
    g = gen_ok(tmp_path, state)
    assert y(g, f"{dd()}/cluster-g1.yaml")["spec"]["bootstrap"]["recovery"].get("recoveryTarget") is None
    assert "recoveryTarget" not in g[f"{dd()}/cluster-g1.yaml"]


def test_the_kustomization_lists_every_cluster_but_not_the_state_ac_117_8(tmp_path):  # AC-117.8
    g = gen_ok(tmp_path, restored_state())
    assert y(g, f"{dd()}/kustomization.yaml")["resources"] == ["cluster-g1.yaml", "cluster.yaml", "objectstore.yaml", "scheduledbackup.yaml"]


def test_the_render_keeps_the_state_file_byte_for_byte_ac_117_8(tmp_path):  # AC-117.8
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    p = write_state(tmp_path, restored_state())
    before = p.read_bytes()
    assert render(tmp_path).returncode == 0 and p.read_bytes() == before
    assert render(tmp_path, "--check").returncode == 0


def test_a_switched_generation_is_active_and_backed_up_ac_117_9(tmp_path):  # AC-117.9
    g = gen_ok(tmp_path, switched_state())
    new, old = y(g, f"{dd()}/cluster-g1.yaml")["spec"], y(g, f"{dd()}/cluster.yaml")["spec"]
    assert new["plugins"] == [{"name": PLUGIN, "isWALArchiver": True, "parameters": {"barmanObjectName": "shop-orders-db"}}]
    assert list(new)[-1] == "plugins" and "bootstrap" in new
    assert old["plugins"] == new["plugins"], "the previous instance keeps archiving until it is discarded"
    assert y(g, f"{dd()}/scheduledbackup.yaml")["spec"]["cluster"] == {"name": "shop-orders-db-g1"}


def test_the_connection_secret_name_does_not_change_with_a_generation_ac_117_9(tmp_path):  # AC-117.9
    g = gen_ok(tmp_path, switched_state())
    assert y(g, f"{dd()}/cluster-g1.yaml")["spec"]["bootstrap"]["recovery"]["secret"] == {"name": "shop-orders-db-app"}
    secrets = [v for k, v in g.items() if "externalsecret" in k and "orders-db" in k]
    assert not secrets, "the secret is the cluster's; a generation renders no other secret"


def test_a_switched_generation_keeps_schedule_and_retention_ac_117_13(tmp_path):  # AC-117.13
    write_system(tmp_path, bdoc(dbb={"dev": {"to": "backups", "schedule": "30 2 * * *", "retention": "8w"}}))
    write_state(tmp_path, switched_state())
    assert render(tmp_path).returncode == 0
    g = tree(tmp_path)
    assert y(g, f"{dd()}/scheduledbackup.yaml")["spec"]["schedule"] == "0 30 2 * * *"
    assert y(g, f"{dd()}/objectstore.yaml")["spec"]["retentionPolicy"] == "8w"
    assert y(g, f"{dd()}/objectstore.yaml")["metadata"]["name"] == "shop-orders-db", "one object store: restore points of the old instance stay restorable"


def test_a_discarded_generation_disappears_and_the_active_cluster_stays_ac_117_10(tmp_path):  # AC-117.10
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    write_state(tmp_path, restored_state())
    assert render(tmp_path).returncode == 0 and (objs(tmp_path) / "cluster-g1.yaml").is_file()
    write_state(tmp_path, {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "active"}]})
    assert render(tmp_path).returncode == 0
    g = tree(tmp_path)
    assert not (objs(tmp_path) / "cluster-g1.yaml").exists()
    assert y(g, f"{dd()}/kustomization.yaml")["resources"] == ["cluster.yaml", "objectstore.yaml", "scheduledbackup.yaml"]
    assert y(g, f"{dd()}/scheduledbackup.yaml")["spec"]["cluster"] == {"name": "shop-orders-db"}


def test_a_discarded_previous_cluster_disappears_and_the_new_one_stays_ac_117_10(tmp_path):  # AC-117.10
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    write_state(tmp_path, switched_state())
    assert render(tmp_path).returncode == 0 and (objs(tmp_path) / "cluster.yaml").is_file()
    write_state(tmp_path, {"next": 2, "clusters": [{"name": "shop-orders-db-g1", "role": "active", "from": {"server": "shop-orders-db", "to": "2026-10-27T09:59:00Z"}}]})
    assert render(tmp_path).returncode == 0
    g = tree(tmp_path)
    assert not (objs(tmp_path) / "cluster.yaml").exists() and (objs(tmp_path) / "cluster-g1.yaml").is_file()
    assert y(g, f"{dd()}/kustomization.yaml")["resources"] == ["cluster-g1.yaml", "objectstore.yaml", "scheduledbackup.yaml"]


@pytest.mark.parametrize("label, state, reason", [
    ("two active", {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "active"}, {"name": "shop-orders-db-g1", "role": "active", "from": {"server": "s", "to": "latest"}}]},
     "exactly one cluster must be active"),
    ("no active", {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "previous", "until": "2026-10-27T11:02:13Z"}]}, "exactly one cluster must be active"),
    ("restored and previous", {"next": 3, "clusters": [{"name": "shop-orders-db", "role": "previous", "until": "2026-10-27T11:02:13Z"},
                                                       {"name": "shop-orders-db-g1", "role": "active", "from": {"server": "s", "to": "latest"}},
                                                       {"name": "shop-orders-db-g2", "role": "restored", "from": {"server": "s", "to": "latest"}}]}, None),
    ("generation without from", {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "active"}, {"name": "shop-orders-db-g1", "role": "restored"}]}, None),
    ("next not above generations", {"next": 1, "clusters": [{"name": "shop-orders-db", "role": "active"},
                                                            {"name": "shop-orders-db-g1", "role": "restored", "from": {"server": "s", "to": "latest"}}]}, None),
    ("to without Z", {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "active"},
                                              {"name": "shop-orders-db-g1", "role": "restored", "from": {"server": "s", "to": "2026-10-27T09:59:00+02:00"}}]}, None),
    ("previous without until", {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "previous"},
                                                        {"name": "shop-orders-db-g1", "role": "active", "from": {"server": "s", "to": "latest"}}]}, None),
])
def test_an_invalid_state_file_fails_and_writes_no_cluster_ac_117_8(tmp_path, label, state, reason):  # AC-117.8
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    write_state(tmp_path, state)
    p = render(tmp_path)
    prefix = "applications/shop/addons/dev/orders-db/restore-state.yaml is not valid ("
    assert p.returncode == 1 and prefix in p.stderr, p.stderr
    assert "); take it from git history" in p.stderr
    if reason:
        assert prefix + reason + "); take it from git history" in p.stderr
    assert not (objs(tmp_path) / "cluster.yaml").exists()


def test_a_state_file_that_does_not_parse_fails_ac_117_8(tmp_path):  # AC-117.8
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    state_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    state_path(tmp_path).write_text("clusters: [unclosed\n")
    p = render(tmp_path)
    assert p.returncode == 1 and "restore-state.yaml is not valid (" in p.stderr


# ---------------- AC-117.22: backup removed ----------------

def test_removing_database_backup_removes_its_objects_and_the_plugin_but_keeps_the_clusters_ac_117_22(tmp_path):  # AC-117.22
    write_system(tmp_path, bdoc(dbb={"dev": DEV}))
    write_state(tmp_path, switched_state())
    assert render(tmp_path).returncode == 0 and (objs(tmp_path) / "objectstore.yaml").is_file()
    write_system(tmp_path, bdoc())
    assert render(tmp_path).returncode == 0
    g = tree(tmp_path)
    assert dfiles(g) == ["cluster-g1.yaml", "cluster.yaml", "kustomization.yaml", "restore-state.yaml"]
    for c in ("cluster.yaml", "cluster-g1.yaml"):
        assert "plugins" not in y(g, f"{dd()}/{c}")["spec"]
    assert y(g, f"{dd()}/kustomization.yaml")["resources"] == ["cluster-g1.yaml", "cluster.yaml"]


def test_removing_database_backup_without_state_leaves_the_plain_directory_ac_117_22(tmp_path):  # AC-117.22
    ok(tmp_path, bdoc(dbb={"dev": DEV}))
    g = ok(tmp_path, bdoc())
    assert dfiles(g) == ["cluster.yaml", "kustomization.yaml"] and "plugins" not in y(g, f"{dd()}/cluster.yaml")["spec"]
    assert not (tmp_path / "operators" / "apps" / "plugin-barman-cloud.yaml").exists()
    assert not (tmp_path / "operators" / "apps" / "cert-manager.yaml").exists()


def test_removing_environment_backup_removes_the_directory_and_the_application_set_ac_117_22(tmp_path):  # AC-117.22
    g = ok(tmp_path, bdoc(envb={"dev": DEV, "prod": DEV}))
    assert "shop-backup-dev" in sets(g) and "shop-backup-prod" in sets(g)
    g = ok(tmp_path, bdoc(envb={"prod": DEV}))
    assert not [k for k in g if k.startswith(f"{APP}/backup/dev/")] and [k for k in g if k.startswith(f"{APP}/backup/prod/")]
    assert "shop-backup-dev" not in sets(g) and "shop-backup-prod" in sets(g)
    assert "preservedFields" not in sets(g)["shop-dev"]["spec"] and "preservedFields" in sets(g)["shop-prod"]["spec"]
    g = ok(tmp_path, bdoc())
    assert not [k for k in g if "/backup/" in k] and not (tmp_path / APP / "backup").exists()
    assert not any(n.startswith("shop-backup-") for n in sets(g))


def test_velero_leaves_the_cluster_with_the_last_environment_backup_ac_117_22(tmp_path):  # AC-117.22
    g = ok(tmp_path, bdoc(envb={"dev": DEV}))
    assert "operators/apps/velero.yaml" in g
    g = ok(tmp_path, bdoc())
    assert "operators/apps/velero.yaml" not in g and not (tmp_path / "operators" / "apps" / "velero.yaml").exists()


def test_removing_a_backup_deletes_nothing_in_the_bucket_ac_117_22(tmp_path):  # AC-117.22
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}, envb={"dev": DEV}))
    bucket_files = {k: v for k, v in g.items() if k.startswith(dd("dev", "backups"))}
    g2 = ok(tmp_path, bdoc())
    assert {k: v for k, v in g2.items() if k.startswith(dd("dev", "backups"))}.keys() == bucket_files.keys(), "the bucket itself stays rendered"


# ---------------- AC-117.15 / AC-117.17: environment backup objects ----------------

BDIR = f"{APP}/backup/dev"
BLABELS = {"app.kubernetes.io/name": "backup", "app.kubernetes.io/part-of": "shop", "app.kubernetes.io/managed-by": "gitops-app"}
ENV_FILES = ["externalsecret.yaml", "kustomization.yaml", "resource-policy.yaml", "role.yaml", "rolebinding.yaml", "schedule.yaml", "secretstore.yaml",
             "serviceaccount.yaml", "storage-location.yaml"]


def bf(g, name, env="dev"):
    return y(g, f"{APP}/backup/{env}/{name}")


def test_an_environment_backup_renders_its_directory_ac_117_15(tmp_path):  # AC-117.15
    g = ok(tmp_path, bdoc(envb={"dev": DEV}))
    assert sorted(k.rsplit("/", 1)[1] for k in g if k.startswith(BDIR + "/")) == ENV_FILES
    assert bf(g, "kustomization.yaml")["resources"] == [f for f in ENV_FILES if f != "kustomization.yaml"]
    assert "namespace" not in bf(g, "kustomization.yaml")
    assert not [k for k in g if k.startswith(f"{APP}/backup/staging") or k.startswith(f"{APP}/backup/prod")]


def test_the_schedule_backs_up_the_namespace_with_its_volumes_ac_117_15(tmp_path):  # AC-117.15
    g = ok(tmp_path, bdoc(envb={"dev": {"to": "backups", "schedule": "15 1 * * *", "retention": "4w"}}))
    s = bf(g, "schedule.yaml")
    assert (s["apiVersion"], s["kind"]) == ("velero.io/v1", "Schedule")
    assert s["metadata"] == {"name": "shop-dev", "namespace": "velero", "labels": BLABELS}
    spec = s["spec"]
    assert spec["schedule"] == "15 1 * * *" and spec["useOwnerReferencesInBackup"] is False
    t = spec["template"]
    assert t["includedNamespaces"] == ["shop-dev"] and t["storageLocation"] == "shop-dev" and t["ttl"] == "672h0m0s"
    assert t["defaultVolumesToFsBackup"] is True and t["snapshotVolumes"] is False
    assert t["resourcePolicy"] == {"kind": "configmap", "name": "shop-dev-backup-policy"}


def test_the_schedule_defaults_are_03_00_utc_and_30_days_ac_117_15(tmp_path):  # AC-117.15
    s = bf(ok(tmp_path, bdoc(envb={"dev": DEV})), "schedule.yaml")["spec"]
    assert s["schedule"] == "0 3 * * *" and s["template"]["ttl"] == "720h0m0s"


def test_the_policy_skips_empty_dir_volumes_ac_117_15(tmp_path):  # AC-117.15
    cm = bf(ok(tmp_path, bdoc(envb={"dev": DEV})), "resource-policy.yaml")
    assert (cm["kind"], cm["metadata"]["name"], cm["metadata"]["namespace"]) == ("ConfigMap", "shop-dev-backup-policy", "velero")
    assert yaml.safe_load(cm["data"]["policy.yaml"]) == {"version": "v1", "volumePolicies": [{"conditions": {"volumeTypes": ["emptyDir"]}, "action": {"type": "skip"}}]}


def test_the_storage_location_of_an_in_cluster_bucket_ac_117_15(tmp_path):  # AC-117.15
    bsl = bf(ok(tmp_path, bdoc(envb={"dev": DEV})), "storage-location.yaml")
    assert (bsl["apiVersion"], bsl["kind"]) == ("velero.io/v1", "BackupStorageLocation")
    assert bsl["metadata"]["name"] == "shop-dev" and bsl["metadata"]["namespace"] == "velero"
    assert bsl["spec"] == {"provider": "aws", "objectStorage": {"bucket": "shop-backups", "prefix": "environments/shop-dev"},
                           "credential": {"name": "shop-dev-backup", "key": "cloud"},
                           "config": {"region": "us-east-1", "s3ForcePathStyle": "true", "s3Url": endpoint()}, "accessMode": "ReadWrite"}


def test_the_storage_location_of_an_external_bucket_ac_117_15(tmp_path):  # AC-117.15
    bsl = bf(ok(tmp_path, bdoc(envb={"prod": DEV}, bucket_kw=ext_prod_bucket())), "storage-location.yaml", "prod")
    assert bsl["spec"]["objectStorage"] == {"bucket": "acme-backups", "prefix": "environments/shop-prod"}
    assert bsl["spec"]["config"] == {"region": "eu-central-1", "s3ForcePathStyle": "false", "s3Url": S3["endpoint"]}


def test_the_credentials_come_from_the_buckets_secret_through_a_store_in_velero_ac_117_15(tmp_path):  # AC-117.15
    g = ok(tmp_path, bdoc(envb={"dev": DEV}))
    assert bf(g, "serviceaccount.yaml")["metadata"] == {"name": "shop-dev-backup", "namespace": "velero", "labels": BLABELS}
    role = bf(g, "role.yaml")
    assert role["metadata"]["name"] == "shop-backup-credentials" and role["metadata"]["namespace"] == "shop-dev"
    assert {"apiGroups": [""], "resources": ["secrets"], "resourceNames": ["shop-backups-app"], "verbs": ["get"]} in role["rules"]
    assert any(r["resources"] == ["selfsubjectrulesreviews"] and r["verbs"] == ["create"] and r["apiGroups"] == ["authorization.k8s.io"] for r in role["rules"])
    rb = bf(g, "rolebinding.yaml")
    assert rb["roleRef"]["name"] == "shop-backup-credentials" and rb["roleRef"]["kind"] == "Role"
    assert rb["subjects"] == [{"kind": "ServiceAccount", "name": "shop-dev-backup", "namespace": "velero"}]
    store = bf(g, "secretstore.yaml")
    assert (store["apiVersion"], store["kind"]) == ("external-secrets.io/v1", "SecretStore")
    assert store["metadata"]["name"] == "shop-dev-backup" and store["metadata"]["namespace"] == "velero"
    assert store["spec"]["provider"]["kubernetes"] == {"remoteNamespace": "shop-dev", "server": {"caProvider": {"type": "ConfigMap", "name": "kube-root-ca.crt", "key": "ca.crt"}},
                                                       "auth": {"serviceAccount": {"name": "shop-dev-backup"}}}
    es = bf(g, "externalsecret.yaml")
    assert es["metadata"]["name"] == "shop-dev-backup" and es["metadata"]["namespace"] == "velero"
    spec = es["spec"]
    assert spec["refreshInterval"] == "1h" and spec["secretStoreRef"] == {"name": "shop-dev-backup", "kind": "SecretStore"}
    assert spec["target"]["name"] == "shop-dev-backup" and spec["target"]["creationPolicy"] == "Owner"
    assert spec["target"]["template"]["engineVersion"] == "v2"
    assert spec["target"]["template"]["data"] == {"cloud": "[default]\naws_access_key_id={{ .accessKeyId }}\naws_secret_access_key={{ .secretAccessKey }}\n"}
    assert {d["secretKey"]: d["remoteRef"]["key"] for d in spec["data"]} == {"accessKeyId": "shop-backups-app", "secretAccessKey": "shop-backups-app"}


def test_the_backup_application_set_syncs_the_directory_into_velero_ac_117_15(tmp_path):  # AC-117.15
    s = sets(ok(tmp_path, bdoc(envb={"dev": DEV})))
    b, ref = s["shop-backup-dev"], s["shop-dev"]
    assert b["metadata"] == {"name": "shop-backup-dev", "namespace": "argocd"}
    assert b["spec"]["generators"] == [{"list": {"elements": [{"name": "environment"}]}}]
    t = b["spec"]["template"]
    assert t["metadata"]["name"] == "shop-backup-dev" and t["spec"]["project"] == "default"
    src, ref_src = t["spec"]["source"], ref["spec"]["template"]["spec"]["source"]
    assert src == {"repoURL": ref_src["repoURL"], "targetRevision": "main", "path": "applications/shop/backup/dev"}
    assert t["spec"]["destination"] == {"server": ref["spec"]["template"]["spec"]["destination"]["server"], "namespace": "velero"}
    assert t["spec"]["syncPolicy"] == {"automated": {"prune": True, "selfHeal": True},
                                      "retry": {"limit": 10, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "10m"}}}


def test_component_and_addon_sets_preserve_the_skip_reconcile_annotation_ac_117_15(tmp_path):  # AC-117.15
    s = sets(ok(tmp_path, bdoc(envb={"dev": DEV})))
    for n in ("shop-dev", "shop-addons-dev"):
        assert s[n]["spec"]["preservedFields"] == {"annotations": ["argocd.argoproj.io/skip-reconcile"]}, n
        assert list(s[n]["spec"]).index("preservedFields") > list(s[n]["spec"]).index("template")
    for n in ("shop-staging", "shop-prod"):
        assert "preservedFields" not in s[n]["spec"], n


def test_the_addon_application_set_retries_when_a_database_has_backup_ac_117_15(tmp_path):  # AC-117.15
    s = sets(ok(tmp_path, bdoc(dbb={"dev": DEV})))
    assert s["shop-addons-dev"]["spec"]["template"]["spec"]["syncPolicy"]["retry"] == {"limit": 10, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "10m"}}
    assert s["shop-addons-staging"]["spec"]["template"]["spec"]["syncPolicy"]["retry"] == s["shop-addons-dev"]["spec"]["template"]["spec"]["syncPolicy"]["retry"]   # spec 128: the bucket's PreSync Job may fail once


def test_an_environment_without_backup_gets_nothing_ac_117_15(tmp_path):  # AC-117.15
    g = ok(tmp_path, bdoc(envb={"prod": DEV}))
    for env in ("dev", "staging"):
        assert not [k for k in g if k.startswith(f"{APP}/backup/{env}")] and f"shop-backup-{env}" not in sets(g)


def test_backup_is_an_allowed_environment_key_ac_117_15(tmp_path):  # AC-117.15
    ok(tmp_path, bdoc(envb={"dev": {"to": "backups", "schedule": "0 1 * * *", "retention": "1w"}}))


def test_the_schedule_leaves_out_databases_caches_and_the_target_ac_117_17(tmp_path):  # AC-117.17
    t = bf(ok(tmp_path, bdoc(envb={"dev": DEV})), "schedule.yaml")["spec"]["template"]
    assert t["excludedResources"] == ["clusters.postgresql.cnpg.io", "backups.postgresql.cnpg.io", "scheduledbackups.postgresql.cnpg.io",
                                      "objectstores.barmancloud.cnpg.io"]
    exprs = t["labelSelector"]["matchExpressions"]
    assert {"key": "cnpg.io/cluster", "operator": "DoesNotExist"} in exprs
    assert {"key": "app.kubernetes.io/name", "operator": "NotIn", "values": ["backups"]} in exprs
    assert {"key": "app.kubernetes.io/instance", "operator": "NotIn", "values": ["shop-backups"]} in exprs
    assert len(exprs) == 3


def test_the_target_buckets_secret_carries_the_target_labels_only_where_it_is_the_target_ac_117_17(tmp_path):  # AC-117.17
    g = ok(tmp_path, bdoc(envb={"dev": DEV}))
    plan = lambda env: json.loads(y(g, f"{dd(env, 'backups')}/credentials-configmap.yaml")["data"]["plan.json"])   # spec 128: the Job writes the Secret
    assert plan("dev")["secrets"][0]["name"] == "shop-backups-app" and plan("dev")["secrets"][0]["labels"] == L("backups")
    assert plan("staging")["secrets"][0]["labels"] == {}


def test_an_external_targets_secret_is_labelled_and_merged_ac_117_17(tmp_path):  # AC-117.17
    g = ok(tmp_path, bdoc(envb={"prod": DEV}, bucket_kw=ext_prod_bucket()))
    tpl = y(g, external_secret_path("prod", "api", "backups"))["spec"]["target"]["template"]
    assert tpl["engineVersion"] == "v2" and tpl["mergePolicy"] == "Merge" and tpl["metadata"]["labels"] == L("backups")


def test_other_objects_and_the_broker_are_not_excluded_ac_117_17(tmp_path):  # AC-117.17
    t = bf(ok(tmp_path, bdoc(envb={"dev": DEV})), "schedule.yaml")["spec"]["template"]
    assert "includedResources" not in t and "excludedNamespaces" not in t
    text = yaml.safe_dump(t)
    assert "broker" not in text and "persistentvolumeclaims" not in text and "pods" not in text


# ---------------- AC-117.26 / AC-117.30: versions and operators ----------------

PINS = {
    "plugin-barman-cloud": {"repo_url": "https://cloudnative-pg.github.io/charts", "chart": "plugin-barman-cloud", "chart_version": "0.8.1",
                            "operator_version": "0.15.1", "namespace": "cnpg-system", "release": "barman-cloud", "crd": "objectstores.barmancloud.cnpg.io"},
    "cert-manager": {"repo_url": "https://charts.jetstack.io", "chart": "cert-manager", "chart_version": "v1.21.3", "operator_version": "1.21.3",
                     "namespace": "cert-manager", "release": "cert-manager", "crd": "certificates.cert-manager.io"},
    "velero": {"repo_url": "https://vmware-tanzu.github.io/helm-charts", "chart": "velero", "chart_version": "12.2.1", "operator_version": "1.18.2",
               "namespace": "velero", "release": "velero", "crd": "schedules.velero.io"},
}
RETRY = {"limit": 10, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "10m"}}
AWS_IMAGE = "velero/velero-plugin-for-aws:v1.14.4@sha256:c85a7fa803569e3128c33e4f5766f84ab156c8d171c9f1dd2715581d45ce98fa"  # spec 121: the designed digest
VELERO_VALUES = {"initContainers": [{"name": "velero-plugin-for-aws", "image": AWS_IMAGE, "volumeMounts": [{"mountPath": "/target", "name": "plugins"}]}],
                 "deployNodeAgent": True, "snapshotsEnabled": False, "credentials": {"useSecret": False},
                 "configuration": {"backupStorageLocation": [], "volumeSnapshotLocation": [], "uploaderType": "kopia"}}


def app_doc(g, name):
    p = PINS[name]
    server = sets(g)["shop-dev"]["spec"]["template"]["spec"]["destination"]["server"]
    helm = {"releaseName": p["release"]}
    sync = {"automated": {"prune": True, "selfHeal": True}, "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]}
    meta = {"name": f"operator-{name}", "namespace": "argocd", "labels": {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/component": "operator"},
            "annotations": {"argocd.argoproj.io/compare-options": "ServerSideDiff=true"}}
    if name == "cert-manager":
        helm["valuesObject"] = {"crds": {"enabled": True}}
    if name == "velero":
        helm["valuesObject"] = VELERO_VALUES
        meta["finalizers"] = ["resources-finalizer.argocd.argoproj.io"]
    if name == "plugin-barman-cloud":
        sync["retry"] = RETRY
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": meta,
            "spec": {"project": "default", "source": {"repoURL": p["repo_url"], "chart": p["chart"], "targetRevision": p["chart_version"], "helm": helm},
                     "destination": {"server": server, "namespace": p["namespace"]}, "syncPolicy": sync}}


@pytest.mark.parametrize("name", list(PINS))
def test_the_versions_table_pins_each_operator_exactly_ac_117_26(name):  # AC-117.26
    ops = getattr(platform_render_module("render_117_pins"), "OPERATORS", {})
    assert name in ops, f"OPERATORS has {name}"
    for k, v in PINS[name].items():
        assert ops[name][k] == v, k
    assert re.fullmatch(r"v?\d+\.\d+\.\d+", ops[name]["chart_version"]) and re.fullmatch(r"\d+\.\d+\.\d+", ops[name]["operator_version"])


def test_the_operators_keep_the_design_order_and_the_aws_plugin_is_pinned_ac_117_26():  # AC-117.26
    r = platform_render_module("render_117_order")
    assert list(r.OPERATORS) == ["cloudnative-pg", "seaweedfs", "external-secrets", "kyverno", "plugin-barman-cloud", "cert-manager", "velero", "nack", "keda", "metrics-server"]  # spec 120: keda and metrics-server follow nack; spec 117: spec 125 added external-secrets and kyverno first; spec 119: nack is appended last
    assert getattr(r, "VELERO_AWS_PLUGIN_IMAGE", None) == AWS_IMAGE
    assert re.fullmatch(r"velero/velero-plugin-for-aws:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", r.VELERO_AWS_PLUGIN_IMAGE)  # spec 121: digested


def test_database_backup_installs_the_plugin_and_cert_manager_but_not_velero_ac_117_26(tmp_path):  # AC-117.26
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    assert op_names(g) == ["operators/apps/cert-manager.yaml", "operators/apps/cloudnative-pg.yaml", "operators/apps/plugin-barman-cloud.yaml",
                           "operators/apps/seaweedfs.yaml", "operators/root.yaml"]
    assert y(g, "operators/apps/plugin-barman-cloud.yaml") == app_doc(g, "plugin-barman-cloud")
    assert y(g, "operators/apps/cert-manager.yaml") == app_doc(g, "cert-manager")


def test_environment_backup_installs_velero_only_ac_117_26(tmp_path):  # AC-117.26
    g = ok(tmp_path, bdoc(envb={"dev": DEV}))
    assert op_names(g) == ["operators/apps/cloudnative-pg.yaml", "operators/apps/seaweedfs.yaml", "operators/apps/velero.yaml", "operators/root.yaml"]
    assert y(g, "operators/apps/velero.yaml") == app_doc(g, "velero")


def test_both_kinds_install_all_three_once_ac_117_26(tmp_path):  # AC-117.26
    g = ok(tmp_path, bdoc(dbb={"prod": DEV}, envb={"dev": DEV, "staging": DEV}))
    assert [k for k in op_names(g) if k.rsplit("/", 1)[1] in ("velero.yaml", "cert-manager.yaml", "plugin-barman-cloud.yaml")] == [
        "operators/apps/cert-manager.yaml", "operators/apps/plugin-barman-cloud.yaml", "operators/apps/velero.yaml"]


def test_two_systems_in_one_cluster_share_one_velero_ac_117_15(tmp_path):  # AC-117.15
    write_system(tmp_path, bdoc(envb={"dev": DEV}))
    other = bdoc(envb={"staging": DEV})
    other["system"] = "blog"
    write_system(tmp_path, other, name="blog")
    assert render(tmp_path).returncode == 0
    assert (tmp_path / "applications/shop/backup/dev").is_dir() and (tmp_path / "applications/blog/backup/staging").is_dir()
    assert sorted(p.name for p in (tmp_path / "operators/apps").glob("velero*")) == ["velero.yaml"]


def test_nothing_that_needs_an_operator_installs_none_ac_117_26(tmp_path):  # AC-117.26
    for label, doc in (("none", bdoc()), ("db-only-elsewhere", bdoc(db_kw={"instances": {"prod": {"external": True}}}))):
        g = ok(tmp_path / label, doc)
        assert not [k for k in g if k.rsplit("/", 1)[-1] in ("velero.yaml", "cert-manager.yaml", "plugin-barman-cloud.yaml")], label


def test_existing_operator_documents_are_unchanged_by_backups_ac_117_26(tmp_path):  # AC-117.26
    a, b = ok(tmp_path / "a", bdoc()), ok(tmp_path / "b", bdoc(dbb={"dev": DEV}, envb={"dev": DEV}))
    for f in ("operators/apps/cloudnative-pg.yaml", "operators/apps/seaweedfs.yaml", "operators/root.yaml"):
        assert a[f] == b[f], f


@pytest.mark.parametrize("where, key", [("backup", "version"), ("backup", "velero"), ("backup", "chart_version"), ("backup", "latest")])
def test_a_version_key_inside_backup_fails_as_an_unknown_key_ac_117_26(tmp_path, where, key):  # AC-117.26
    fails(tmp_path, bdoc(envb={"dev": {"to": "backups", key: "1.0.0"}}), P + f"environments.dev.backup: unknown key '{key}' (allowed: to, schedule, retention)")


@pytest.mark.parametrize("key", ["velero", "barman", "cert-manager", "veleroVersion"])
def test_a_version_key_on_an_environment_fails_as_an_unknown_key_ac_117_26(tmp_path, key):  # AC-117.26
    doc = bdoc(envb={"dev": DEV})
    doc["environments"]["dev"][key] = "1.18.2"
    fails(tmp_path, doc, P + f"environments.dev: unknown key '{key}'")


def test_no_pin_allows_a_range_or_latest_ac_117_26(tmp_path):  # AC-117.26
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}, envb={"dev": DEV}))
    for n in ("plugin-barman-cloud", "cert-manager", "velero"):
        rev = y(g, f"operators/apps/{n}.yaml")["spec"]["source"]["targetRevision"]
        assert re.fullmatch(r"v?\d+\.\d+\.\d+", rev), rev
    assert "latest" not in "".join(g[k] for k in g if k.startswith("operators/")).lower()


def test_owner_managed_environments_get_no_operator_but_the_backups_render_ac_117_30(tmp_path):  # AC-117.30
    doc = bdoc(dbb={"dev": DEV}, envb={"dev": DEV})
    doc["environments"]["dev"]["operators"] = "owner"
    g = ok(tmp_path, doc)
    assert not [k for k in g if k.rsplit("/", 1)[-1] in ("velero.yaml", "cert-manager.yaml", "plugin-barman-cloud.yaml")]
    assert f"{dd()}/objectstore.yaml" in g and f"{dd()}/scheduledbackup.yaml" in g and f"{BDIR}/schedule.yaml" in g and "shop-backup-dev" in sets(g)


def test_an_operator_is_still_installed_for_another_environment_that_needs_it_ac_117_30(tmp_path):  # AC-117.30
    doc = bdoc(dbb={"dev": DEV, "prod": DEV}, envb={"dev": DEV, "prod": DEV})
    doc["environments"]["dev"]["operators"] = "owner"
    g = ok(tmp_path, doc)
    for n in ("velero", "cert-manager", "plugin-barman-cloud"):
        assert f"operators/apps/{n}.yaml" in g, n
    doc["environments"]["prod"]["operators"] = "owner"
    g = ok(tmp_path / "all", doc)
    assert not [k for k in g if k.rsplit("/", 1)[-1] in ("velero.yaml", "cert-manager.yaml", "plugin-barman-cloud.yaml")]


def test_check_mode_covers_the_new_files_ac_117_22(tmp_path):  # AC-117.22
    ok(tmp_path, bdoc(dbb={"dev": DEV}, envb={"dev": DEV}))
    assert render(tmp_path, "--check").returncode == 0
    f = tmp_path / APP / "backup/dev/schedule.yaml"
    f.write_text(f.read_text() + "# hand edit\n")
    assert render(tmp_path, "--check").returncode == 1
