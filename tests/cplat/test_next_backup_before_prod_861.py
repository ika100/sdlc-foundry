"""#861: after a release, `cplat next` recommended promoting to prod while the prod database had no backup; the person's next
sentence asked for the backup before prod, but the prod PR was already open. A prod promotion now recommends setting the missing
backup first and keeps the promotion as the second choice."""
import pytest

import needs
from backup_fixtures import bdoc
from resources_fixtures import APP
from support_193 import BuildWorld, labels
from system_fixtures import mod, write_system
from test_193_release import deployable

MISSING = [{"resource": "postgres", "to": "postgres-backups"}]
BACKUP_STEP = "/resource:backup postgres --env prod --to postgres-backups --schedule daily"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch)
    w.queue()
    return w


def promote_item(consequence):
    return {"id": "promote:web:1.2.0", "kind": "promote", "stage": "Prod", "since": "2026-11-13T10:00:00Z",
            "reason": "web 1.2.0 is verified in staging", "command": "/instance:promote web --to prod --version v1.2.0",
            "object": {"type": "component", "repo": "o/n", "issue": None, "spec": None, "run_id": None, "component": "web",
                       "version": "1.2.0", "pr": None, "url": None}, "cwd_repo": "o/n", "consequence": consequence, "way_back": None}


def test_a_prod_database_without_backup_recommends_the_backup_first_861(world, capsys):
    world.dispatch_item(promote_item({"env": "prod", "missing_backups": MISSING}))
    q = next(q for q in world.doc(capsys)["questions"] if q["header"] == "Prod")
    assert labels(q) == ["Set the backup first", "Promote to Prod", "Show details", "Not now"]
    first = q["options"][0]
    assert first["recommended"] is True and first["steps"] == [BACKUP_STEP]
    assert q["options"][1]["steps"] == ["/instance:promote web --to prod --version v1.2.0"], "the promotion stays a choice"
    assert "postgres has no backup" in q["question"]


def test_with_the_backup_set_the_promotion_is_recommended_as_before_861(world, capsys):
    world.dispatch_item(promote_item({"env": "prod", "missing_backups": []}))
    q = next(q for q in world.doc(capsys)["questions"] if q["header"] == "Prod")
    assert labels(q) == ["Promote to Prod", "Show details", "Not now"]


def model_of(tmp_path, doc):
    write_system(tmp_path, doc)
    return mod("model").load_dir(tmp_path / APP)


def test_missing_prod_backups_lists_prod_databases_without_backup_861(tmp_path):
    assert needs.missing_prod_backups(model_of(tmp_path / "a", bdoc())) == [{"resource": "orders-db", "to": "orders-db-backups"}]
    assert needs.missing_prod_backups(model_of(tmp_path / "b", bdoc(dbb={"dev": {"to": "backups"}}))) == [
        {"resource": "orders-db", "to": "backups"}], "the bucket another environment backs up to"
    assert needs.missing_prod_backups(model_of(tmp_path / "c", bdoc(dbb={"prod": {"to": "backups"}}))) == []
    assert needs.missing_prod_backups(model_of(tmp_path / "d", bdoc(db_kw={"instances": {"prod": {"external": True}}}))) == []


def test_the_needs_promote_item_carries_the_missing_backups_861():
    # a release in staging: prod takes release tags only (#901)
    rows = [{"component": "web", "cells": {"staging": {"state": "verified", "version": "v1.0.0", "release": "v1.0.0"}, "prod": None}}]
    [item] = needs._promotions(rows, {}, "manual", MISSING)
    assert item["consequence"]["missing_backups"] == MISSING and item["consequence"]["env"] == "prod"


def test_the_deploy_step_of_a_component_repo_carries_them_861(tmp_path, monkeypatch, capsys):
    import staging
    w = deployable(tmp_path, monkeypatch, "manual", staging_runs_head=True, commits_after_tag=False, prod_tag="v0.9.0")
    repo, apps, comp, m, me = staging._find(None, None, None)
    ri = type("RI", (), {"resource": "postgres", "environment": "prod", "type": "database", "external": False, "backup": None})
    m.resource_instances = [ri()]
    monkeypatch.setattr(staging, "_find", lambda *a: (repo, apps, comp, m, me), raising=False)
    q = w.doc(capsys)["questions"][0]
    assert q["header"] == "Prod" and q["options"][0]["steps"] == [BACKUP_STEP]
