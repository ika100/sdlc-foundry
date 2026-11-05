"""#424: `resource restore --discard` waited for the database addon's Argo application to report Synced, but that
application never prunes (prune: false), so the removed cluster stayed OutOfSync and the discard timed out before deleting
it. A second discard then refused, because restore-state.yaml no longer listed the cluster."""
import argparse

import dbrestore
from core import Report

APP = {"status": {"resources": [
    {"kind": "Cluster", "name": "shop-postgres-g1", "status": "OutOfSync", "requiresPruning": True},
    {"kind": "ScheduledBackup", "name": "shop-postgres", "status": "Synced"}]}}


def test_only_a_resource_waiting_for_pruning_counts_as_synced_for_a_discard(monkeypatch):
    monkeypatch.setattr(dbrestore.backupstate, "get_json", lambda args, ctx: APP)
    assert dbrestore._only_prune_left("addon-postgres-prod", None)


def test_a_resource_that_really_differs_is_not_synced(monkeypatch):
    app = {"status": {"resources": [*APP["status"]["resources"], {"kind": "Secret", "name": "x", "status": "OutOfSync"}]}}
    monkeypatch.setattr(dbrestore.backupstate, "get_json", lambda args, ctx: app)
    assert not dbrestore._only_prune_left("addon-postgres-prod", None)
    monkeypatch.setattr(dbrestore.backupstate, "get_json", lambda args, ctx: {"status": {"resources": []}})
    assert not dbrestore._only_prune_left("addon-postgres-prod", None)


def _clusters(*names):
    return lambda args, ctx: [{"metadata": {"name": n}} for n in names]


def test_a_cluster_the_state_no_longer_lists_is_a_leftover(monkeypatch):
    monkeypatch.setattr(dbrestore.backupstate, "get_items", _clusters("shop-postgres", "shop-postgres-g1", "shop-postgres-g2", "shop-redis-g1"))
    state = {"next": 3, "clusters": [{"name": "shop-postgres-g2", "role": "active"}]}
    assert dbrestore.leftover_clusters("shop", "postgres", "shop-prod", state, None) == ["shop-postgres-g1"]


def test_without_leftovers_nothing_is_offered(monkeypatch):
    monkeypatch.setattr(dbrestore.backupstate, "get_items", _clusters("shop-postgres", "shop-postgres-g2"))
    state = {"next": 3, "clusters": [{"name": "shop-postgres", "role": "active"}, {"name": "shop-postgres-g2", "role": "restored"}]}
    assert dbrestore.leftover_clusters("shop", "postgres", "shop-prod", state, None) == []


def test_finishing_a_leftover_deletes_it_and_waits_for_its_volumes(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(dbrestore, "_write", lambda args, ctx, msg, **kw: calls.append(args))
    monkeypatch.setattr(dbrestore, "_wait_volumes_gone", lambda name, kns, ctx: calls.append(["volumes", name]))
    ns = argparse.Namespace(env="prod", confirm="prod", dry_run=False)
    assert dbrestore._finish_leftover(ns, "shop-postgres-g1", "shop-prod", None, Report(title="t")) == 0
    assert calls == [["delete", dbrestore.CLUSTER_KIND, "shop-postgres-g1", "-n", "shop-prod", "--ignore-not-found"],
                     ["volumes", "shop-postgres-g1"]]
    assert "unfinished discard" in capsys.readouterr().out


def test_finishing_a_leftover_in_prod_needs_confirm(monkeypatch):
    monkeypatch.setattr(dbrestore, "_write", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not delete")))
    ns = argparse.Namespace(env="prod", confirm=None, dry_run=False)
    try:
        dbrestore._finish_leftover(ns, "shop-postgres-g1", "shop-prod", None, Report(title="t"))
    except dbrestore.PlatformError as e:
        assert "--confirm prod" in str(e)
    else:
        raise AssertionError("no error")
