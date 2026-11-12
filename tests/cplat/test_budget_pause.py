"""Pause minutes leave the budget ledger (AC-184.3): `add_pause`, `used_of`, `_fold_previous`, `on_finish`."""
import datetime

import pytest

import budget
import runs


def _iso(minutes_ago: float, now: datetime.datetime) -> str:
    return budget._iso(now - datetime.timedelta(minutes=minutes_ago))


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    now = datetime.datetime(2026, 11, 11, 12, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(runs, "utcnow", lambda: now)
    path = tmp_path / "ledger.json"
    data = {"roots": ["r1"], "limits": {"minutes": 100}, "carried": {"minutes": 5, "invocations": 0, "reruns": 0, "cost": 0},
            "used": {"invocations": 0, "reruns": 0},
            "current": {"run_id": "r1", "started_at": _iso(30, now)}}
    budget._write(path, data)
    monkeypatch.setattr(budget, "find", lambda run_id: (path, budget._read(path)))
    return path, now


def test_add_pause_is_added_to_the_current_root_and_leaves_used_minutes(ledger):
    path, _ = ledger
    budget.add_pause("r1", 10)
    budget.add_pause("r1", 2.5)
    data = budget._read(path)
    assert data["current"]["paused_minutes"] == 12.5
    assert budget.used_of(data, cost=False)["minutes"] == 22.5   # 5 carried + 30 live - 12.5 paused


def test_a_pause_longer_than_the_live_time_never_goes_below_carried(ledger):
    path, _ = ledger
    budget.add_pause("r1", 99)
    assert budget.used_of(budget._read(path), cost=False)["minutes"] == 5


def test_add_pause_without_a_ledger_or_current_is_a_no_op(ledger, monkeypatch):
    path, _ = ledger
    monkeypatch.setattr(budget, "find", lambda run_id: None)
    budget.add_pause("r1", 5)
    data = budget._read(path)
    data["current"] = None
    budget._write(path, data)
    monkeypatch.setattr(budget, "find", lambda run_id: (path, budget._read(path)))
    budget.add_pause("r1", 5)
    assert budget._read(path)["current"] is None


def test_a_continued_ledger_carries_minutes_without_the_pause(ledger):
    path, now = ledger
    budget.add_pause("r1", 10)
    data = budget._read(path)
    budget._fold_previous(data, budget._iso(now))
    assert data["carried"]["minutes"] == 25.0   # 5 + (30 - 10)
    assert data["current"] is None


def test_on_finish_carries_minutes_without_the_pause(ledger, monkeypatch):
    path, _ = ledger
    budget.add_pause("r1", 10)
    monkeypatch.setattr(runs, "active", lambda rid: {"kind": "ship"})
    monkeypatch.setattr(runs, "set_section", lambda *a, **k: None)
    monkeypatch.setattr(budget, "root_of", lambda rid: "r1")
    budget.on_finish("r1", None, "done")
    assert budget._read(path)["carried"]["minutes"] == 25.0
