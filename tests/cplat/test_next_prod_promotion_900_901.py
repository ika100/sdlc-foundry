"""#900: before the first prod promotion no component runs in prod, so the model holds no prod instance of the database the
promoted component uses, and `cplat next` skipped the backup-first question of #861. #901: the prod item recommended promoting
a `sha-` build, although prod takes release tags only, and kept offering it after prod ran the release."""
import json

import needs
import releases
from resources_fixtures import APP, comp, db, system
from system_fixtures import mod, write_system

ENVS2 = ("dev", "staging")


def model_of(tmp_path, resources, comps=None):
    write_system(tmp_path, system(resources, comps or {"api": comp("api", ["postgres"], envs=ENVS2),
                                                        "web": comp("web", envs=ENVS2)}))
    return mod("model").load_dir(tmp_path / APP)


def prod_db(**prod):
    return {"postgres": db(instances={"prod": {"replicas": 3, "storage": "20Gi", **prod}})}


# ---------------- #900 ----------------

def test_the_database_a_promoted_component_uses_counts_before_prod_runs_it_900(tmp_path):
    m = model_of(tmp_path, prod_db())
    assert not [ri for ri in m.resource_instances if ri.environment == "prod"], "the journey 23 state: no prod instance yet"
    assert needs.missing_prod_backups(m) == []
    assert needs.missing_prod_backups(m, ["api"]) == [{"resource": "postgres", "to": "postgres-backups"}]
    assert needs.missing_prod_backups(m, ["web"]) == [], "a component that uses no database"


def test_a_declared_prod_backup_or_external_prod_database_is_not_missing_900(tmp_path):
    assert needs.missing_prod_backups(model_of(tmp_path / "a", prod_db(backup={"to": "pg-bak"})), ["api"]) == []
    assert needs.missing_prod_backups(model_of(tmp_path / "b", prod_db(external=True)), ["api"]) == []


def test_the_bucket_another_environment_backs_up_to_is_kept_900(tmp_path):
    res = {"postgres": db(instances={"dev": {"backup": {"to": "pg-bak"}}}), "pg-bak": {"type": "bucket"}}
    assert needs.missing_prod_backups(model_of(tmp_path, res), ["api"]) == [{"resource": "postgres", "to": "pg-bak"}]


# ---------------- #901 ----------------

ROW = {"component": "api", "cells": {"staging": {"state": "verified", "version": "sha-7358960", "tag": "sha-7358960",
                                                 "release": None}, "prod": None}}


def fake_gh(monkeypatch, tags=(), last=""):
    def gh(args):
        if args[0] == "api" and "/tags" in args[1]:
            return json.dumps([{"name": n, "commit": {"sha": sha}} for n, sha in tags])
        if args[:2] == ["release", "view"]:
            return last
        return "{}" if args[0] == "api" and "/compare/" in args[1] else "[]"
    monkeypatch.setattr(releases, "gh", gh)
    monkeypatch.setattr(needs, "_staging_smoke", lambda *a: {})
    monkeypatch.setattr(needs, "_commit_time", lambda *a: "2026-11-20T10:00:00Z")


def with_prod(version):
    return {**ROW, "cells": {**ROW["cells"], "prod": {"state": "verified", "version": version}}}


def test_without_a_release_tag_the_prod_item_recommends_the_release_901(monkeypatch):
    fake_gh(monkeypatch)
    [item] = needs._promotions([ROW], {"api": "acme/api"}, "manual", {"api": [{"resource": "postgres", "to": "x"}]})
    assert item["kind"] == "release" and item["command"] == "/component:release" and item["cwd_repo"] == "acme/api"
    assert "--version sha-" not in item["command"]


def test_with_a_release_tag_on_the_staged_build_the_promotion_names_it_901(monkeypatch):
    fake_gh(monkeypatch, tags=[("v0.1.0", "7358960" + "a" * 33), ("v0.0.9", "1" * 40)])
    missing = [{"resource": "postgres", "to": "postgres-backups"}]
    [item] = needs._promotions([ROW], {"api": "acme/api"}, "manual", {"api": missing})
    assert item["kind"] == "promote" and item["command"] == "/instance:promote api --to prod --version v0.1.0"
    assert item["consequence"]["missing_backups"] == missing and item["consequence"]["env"] == "prod"


def test_a_component_already_at_the_release_in_prod_gets_no_prod_item_901(monkeypatch):
    fake_gh(monkeypatch, tags=[("v0.1.0", "7358960" + "a" * 33)])
    assert needs._promotions([with_prod("v0.1.0")], {"api": "acme/api"}, "manual", []) == []
    assert needs._promotions([with_prod("0.1.0")], {"api": "acme/api"}, "manual", []) == []


def test_tag_of_matches_a_release_tag_by_commit_prefix_901(monkeypatch):
    fake_gh(monkeypatch, tags=[("latest", "7358960" + "b" * 33), ("v0.2.0", "7358960" + "b" * 33)])
    assert releases.tag_of("acme/api", "7358960") == "v0.2.0"
    assert releases.tag_of("acme/api", "deadbee") is None
