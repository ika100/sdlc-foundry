"""#927: an on-demand backup waits for a backup of the cluster still running (the schedule's first one) and reports it, uses one that
completed less than a minute ago, and names an overlapping backup when CloudNativePG fails its own with a generic error.
The kube fixture reads the cluster at 2026-10-27T06:00:00Z."""
import json
import re

from backup_fixtures import clock, cnpg_backup, kube, run_cplat  # noqa: F401  (fixtures)
from test_backup_117_restore import backup, repo, window  # noqa: F401  (repo is a fixture)

SCHEDULED = "shop-orders-db-20261027055950"


def finishes_after(kube, name, polls, **status):
    """Backup `name` reports `status` from its `polls`-th read on, as a running backup would."""
    seen = {"n": 0}

    def hook(args, stdin):
        if args[0] == "get" and name in args:
            seen["n"] += 1
            if seen["n"] >= polls:
                obj = next(b for b in kube.store["cnpg.backup"] if b["metadata"]["name"] == name)
                obj["status"].update(status)
    kube.hooks.append(hook)


def test_a_running_scheduled_backup_is_waited_for_and_is_the_result(repo, kube, capsys, clock):
    window(kube, backups=[cnpg_backup(SCHEDULED, phase="running", stopped=None, created="2026-10-27T05:59:50Z")])
    finishes_after(kube, SCHEDULED, 3, phase="completed", stoppedAt="2026-10-27T06:00:40Z")
    rc, out = backup(repo, capsys)
    assert rc == 0, out
    assert f"a backup is running (started by the schedule): waiting for Backup {SCHEDULED}" in out
    assert f"backup completed: orders-db/dev at 2026-10-27T06:00:40Z (Backup {SCHEDULED}, started by the schedule)" in out
    assert kube.created("Backup") == [], "no second backup overlaps the first"


def test_a_failed_running_backup_is_followed_by_a_new_one(repo, kube, capsys, clock):
    window(kube, backups=[cnpg_backup(SCHEDULED, phase="started", stopped=None, created="2026-10-27T05:59:50Z")])
    finishes_after(kube, SCHEDULED, 2, phase="failed", error="barman-cloud-backup exit status 1")
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T06:02:00Z"}
    rc, out = backup(repo, capsys)
    assert rc == 0, out
    assert f"Backup {SCHEDULED} failed (barman-cloud-backup exit status 1): taking a new backup" in out
    assert re.search(r"^backup completed: orders-db/dev at 2026-10-27T06:02:00Z \(Backup shop-orders-db-manual-\d{14}\)$", out, re.M), out
    assert len(kube.created("Backup")) == 1


def test_a_backup_completed_less_than_a_minute_ago_is_used(repo, kube, capsys, clock):
    window(kube, backups=[cnpg_backup(SCHEDULED, stopped="2026-10-27T05:59:30Z", created="2026-10-27T05:59:00Z")])
    rc, out, err = run_cplat("resource", "backup", "orders-db", "--env", "dev", "--repo-dir", repo, "--json", capsys=capsys)
    assert rc == 0, out + err
    assert f"a backup completed less than a minute ago (started by the schedule): using Backup {SCHEDULED}" in err
    d = json.loads(out)
    assert d["backup"] == SCHEDULED and d["at"] == "2026-10-27T05:59:30Z" and d["started_by"] == "started by the schedule"
    assert kube.created("Backup") == []


def test_old_or_stuck_backups_do_not_hold_up_a_new_one(repo, kube, capsys, clock):
    window(kube, backups=[cnpg_backup("shop-orders-db-20261027030000"),                      # completed hours ago
                          cnpg_backup("shop-orders-db-20261027040000", phase="pending", stopped=None, created="2026-10-27T04:00:00Z"),
                          cnpg_backup("other-db-20261027055950", cluster="other-db", phase="running", stopped=None,
                                      created="2026-10-27T05:59:50Z")])
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T06:01:00Z"}
    rc, out = backup(repo, capsys)
    assert rc == 0 and "waiting" not in out and len(kube.created("Backup")) == 1, out


def test_a_failure_names_the_backup_it_overlapped(repo, kube, capsys, clock):
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "failed", "error": "rpc error: code = Unknown desc = exit status 1",
                                "startedAt": "2026-10-27T05:59:55Z", "stoppedAt": "2026-10-27T05:59:58Z"}

    def schedule_starts_too(args, stdin):   # the schedule's first backup appears right after the command looked
        if args[0] == "create":
            kube.put("cnpg.backup", cnpg_backup(SCHEDULED, phase="running", stopped=None, created="2026-10-27T05:59:50Z"))
    kube.hooks.append(schedule_starts_too)
    rc, out = backup(repo, capsys)
    assert rc == 1, out
    assert ("backup failed: orders-db/dev: rpc error: code = Unknown desc = exit status 1 (it overlapped Backup "
            f"{SCHEDULED}, started by the schedule, and a cluster takes one backup at a time: run /resource:backup again)") in out
