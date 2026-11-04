"""#416: a database whose scheduled backup silently stopped (ScheduledBackup missing or suspended, operator down) showed `ok`
with an ever older last success. It is now failing once no base backup completed within one schedule period plus 2 hours."""
import datetime as dt

import backupstate
import pytest
from backup_fixtures import cnpg_backup, kube  # noqa: F401  (kube: fixture)


@pytest.mark.parametrize("schedule, hours", [("0 3 * * *", 24), ("0 0 3 * * *", 24), ("0 */6 * * *", 6), ("15 * * * *", 1),
                                             ("0 3 * * 0", 168), ("0 3 1 * *", 744), (None, 24), ("bad", 24)])
def test_the_schedule_period(schedule, hours):
    assert backupstate.schedule_period(schedule) == dt.timedelta(hours=hours)


def _at(monkeypatch, when):
    monkeypatch.setattr(backupstate, "now", lambda: dt.datetime.fromisoformat(when.replace("Z", "+00:00")))


def test_a_daily_backup_is_overdue_after_26_hours(monkeypatch):
    _at(monkeypatch, "2026-10-28T05:00:00Z")
    assert backupstate.overdue("2026-10-27T03:00:00Z", None, "0 3 * * *") is None
    _at(monkeypatch, "2026-10-28T05:00:01Z")
    why = backupstate.overdue("2026-10-27T03:00:00Z", None, "0 3 * * *")
    assert why and "more than 26 h ago" in why and "ScheduledBackup" in why


def test_without_any_backup_the_cluster_age_counts(monkeypatch):
    _at(monkeypatch, "2026-10-27T20:00:00Z")
    assert backupstate.overdue(None, "2026-10-27T00:00:00Z", "0 3 * * *") is None          # a new database: not yet
    _at(monkeypatch, "2026-10-29T00:00:00Z")
    assert "no base backup has completed" in backupstate.overdue(None, "2026-10-27T00:00:00Z", "0 3 * * *")


def test_status_marks_an_overdue_backup_failing(kube, monkeypatch):  # noqa: F811
    kube.healthy_database(backups=[cnpg_backup("ok", stopped="2026-10-27T03:00:12Z")])
    _at(monkeypatch, "2026-10-29T12:00:00Z")
    row = backupstate.database_state("shop", "orders-db", "dev", None, backup=True, schedule="0 3 * * *")
    assert row["backup"]["state"] == "failing" and "more than 26 h ago" in row["backup"]["error"]
    _at(monkeypatch, "2026-10-27T12:00:00Z")
    row = backupstate.database_state("shop", "orders-db", "dev", None, backup=True, schedule="0 3 * * *")
    assert row["backup"]["state"] == "ok"
