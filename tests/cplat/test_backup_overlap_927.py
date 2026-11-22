"""#927: the prod ScheduledBackup took its first backup as soon as it was created; `resource backup` (on demand), started seconds
later, failed with a generic error, because CloudNativePG takes one backup of a cluster at a time. The on-demand backup now waits
for a running one first, and a failure while another one runs names that cause."""
import backupstate
import dbbackup
from backup_fixtures import clock, cnpg_backup, kube  # noqa: F401  (fixtures)
from test_backup_117_restore import backup, repo, window  # noqa: F401  (repo is a fixture)

RUNNING = dict(phase="running", stopped=None, created="2026-10-27T05:59:30Z")   # the kube fixture's clock reads 06:00


def first_backup_finishes_after(kube, clock, seconds):
    t0 = clock.now

    def finish(args, stdin):
        if clock.now - t0 >= seconds:
            for b in kube.store["cnpg.backup"]:
                if b["metadata"]["name"] == "shop-orders-db-first":
                    b["status"] = {"phase": "completed", "stoppedAt": "2026-10-27T06:01:00Z"}

    kube.hooks.append(finish)


def test_an_on_demand_backup_waits_for_the_running_scheduled_one_927(repo, kube, capsys, clock):
    window(kube, backups=[cnpg_backup("shop-orders-db-first", **RUNNING)])
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T06:02:00Z"}
    first_backup_finishes_after(kube, clock, 40)
    t0 = clock.now
    rc, out = backup(repo, capsys)
    assert rc == 0, out
    assert "a backup of orders-db/dev is running (shop-orders-db-first" in out
    [made] = kube.created("Backup")
    assert made["metadata"]["name"].startswith("shop-orders-db-manual-")
    created_at = next(i for i, c in enumerate(kube.calls) if c[0][0] == "create")
    assert clock.now - t0 >= 40 and created_at > 0, "ours is created only after the running one finished"


def test_the_wait_is_capped_so_a_stuck_backup_never_blocks_927(repo, kube, capsys, clock):
    window(kube, backups=[cnpg_backup("shop-orders-db-first", **RUNNING)])
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T06:12:00Z"}
    t0 = clock.now
    rc, out = backup(repo, capsys)
    assert rc == 0, out
    assert dbbackup.OVERLAP_S <= clock.now - t0 < dbbackup.OVERLAP_S + 2 * dbbackup.POLL_S
    assert len(kube.created("Backup")) == 1


def test_old_or_finished_backups_do_not_make_it_wait_927(repo, kube, capsys, clock):
    window(kube, backups=[cnpg_backup("old-stuck", phase="running", stopped=None, created="2026-10-26T01:00:00Z"),
                          cnpg_backup("other-cluster", cluster="shop-else-db", **RUNNING),
                          cnpg_backup("done", phase="completed", created="2026-10-27T05:59:00Z")])
    kube.auto["cnpg.backup"] = {"phase": "completed", "stoppedAt": "2026-10-27T06:00:10Z"}
    rc, out = backup(repo, capsys)
    assert rc == 0, out
    assert "is running" not in out


def test_a_failure_during_another_backup_names_it_927(repo, kube, capsys, clock, monkeypatch):
    window(kube)
    kube.auto["cnpg.backup"] = {"phase": "failed", "error": "rpc error: code = Unknown desc = exit status 1"}

    def schedule_starts_after_ours(args, stdin):   # the schedule's backup appears after our check, as in the journey
        if args[0] == "create":
            kube.put("cnpg.backup", cnpg_backup("shop-orders-db-first", **RUNNING))

    kube.hooks.append(schedule_starts_after_ours)
    rc, out = backup(repo, capsys)
    assert rc == 1
    assert "another backup of this cluster was running at the same time: shop-orders-db-first" in out
    assert backupstate.PLUGIN  # the created Backup is the plugin one, unchanged (AC-117.31)
