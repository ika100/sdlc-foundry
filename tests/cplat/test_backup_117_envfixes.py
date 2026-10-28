"""Spec 117 review fixes in `cplat system restore`: only a completed or partially failed backup can be restored (AC-117.21), and the
workloads are waited for with their rollout (AC-117.20)."""
import re

import pytest

from backup_fixtures import bdoc, clock, kube, make_repo, tree_state, velero_backup  # noqa: F401  (fixtures)
from test_backup_117_restore import (DB_LINE, DEV, NS, WRITES, last_line, nothing_changed, srestore, three,  # noqa: F401
                                     volumes_world)


@pytest.fixture()
def erepo(tmp_path):
    return make_repo(tmp_path, bdoc(envb={"dev": DEV, "prod": DEV}))


def bad(kube):
    kube.put("velero.backup", velero_backup("f1", phase="Failed", done="2026-10-27T04:00:40Z", reason="BSL unavailable"),
             velero_backup("p1", phase="InProgress", done=None))
    return kube


@pytest.mark.parametrize("name, state", [("f1", "failed"), ("p1", "in progress")])
@pytest.mark.parametrize("replace", [False, True])
def test_a_failed_or_running_backup_is_refused_before_any_write_ac_117_21(erepo, kube, capsys, clock, name, state, replace):  # AC-117.21
    volumes_world(kube)
    bad(kube)
    before = tree_state(erepo)
    kube.calls.clear()
    rc, out = srestore(erepo, capsys, "--backup", name, *(["--replace"] if replace else []))
    assert rc == 1, out
    assert (f"backup {name} is {state}: only a completed or partially failed backup can be restored (available: b3, b2, b1)") in out
    assert last_line(out) == DB_LINE
    nothing_changed(erepo, kube, before)
    assert not kube.created("Restore")


def test_the_available_list_of_an_unknown_name_has_only_restorable_backups_ac_117_21(erepo, kube, capsys):  # AC-117.21
    three(kube)
    bad(kube)
    rc, out = srestore(erepo, capsys, "--backup", "nope")
    assert rc == 1 and "no backup nope in dev; available: b3, b2, b1" in out
    assert "f1" not in out and "p1" not in out


def test_the_restore_waits_for_the_rollout_after_the_restore_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    volumes_world(kube)
    kube.calls.clear()
    rc, out = srestore(erepo, capsys, "--backup", "b3", "--replace")
    assert rc == 0, out
    roll = [i for i, c in enumerate(kube.calls) if c[0][:2] == ["rollout", "status"]]
    restore_i = next(i for i, c in enumerate(kube.calls) if c[2] and re.search(r"kind: Restore", c[2]))
    assert len(roll) == 1 and roll[0] > restore_i
    assert "statefulset/files" in kube.calls[roll[0]][0] and "-n" in kube.calls[roll[0]][0] and NS in kube.calls[roll[0]][0]
    assert out.index("started StatefulSet files") > out.index("restored b3 into shop-dev")


def test_a_rollout_that_times_out_fails_the_restore_ac_117_20(erepo, kube, capsys, clock):  # AC-117.20
    volumes_world(kube)
    kube.hooks.append(lambda args, stdin: (1, "", "error: timed out waiting for the rollout to finish") if args[:2] == ["rollout", "status"] else None)
    rc, out = srestore(erepo, capsys, "--backup", "b3", "--replace")
    assert rc == 1, out
    assert "restore failed: StatefulSet files did not become ready after 30 minutes" in out
    assert "started StatefulSet files" not in out and last_line(out) == DB_LINE
