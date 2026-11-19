"""Spec 210 t3: usagelimit.record writes limit.json; headless.run_cost reads the run's USD cost."""
import datetime as dt
import json
from pathlib import Path

import pytest

import headless
import runs
import runs_usage
import usagelimit

ENDED = dt.datetime(2026, 11, 10, 12, 0, 0)


@pytest.fixture
def limit_file(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return tmp_path / "sdlc-foundry" / "usage" / "limit.json"


def test_a_message_with_a_reset_time_records_that_reset(limit_file):
    reset = ENDED + dt.timedelta(hours=3)
    hit = usagelimit.detect(f"Claude AI usage limit reached|{int(reset.timestamp())}", 500, ENDED)
    usagelimit.record(hit, ENDED)
    doc = json.loads(limit_file.read_text())
    assert doc["until"] == int(reset.timestamp()) and doc["reset_known"] is True
    assert "usage limit reached" in doc["message"]


def test_a_message_without_a_reset_time_holds_sixty_minutes(limit_file):
    hit = usagelimit.detect("You hit your usage limit", 500, ENDED)
    usagelimit.record(hit, ENDED)
    doc = json.loads(limit_file.read_text())
    assert doc["until"] == doc["at"] + 3600 and doc["reset_known"] is False


def test_a_silent_session_records_nothing(limit_file, monkeypatch):
    monkeypatch.setattr(usagelimit, "QUICK_SECONDS", 60)
    hit = usagelimit.detect("", 5, ENDED)
    assert hit is not None and hit.message is None
    usagelimit.record(hit, ENDED)
    assert not limit_file.exists()


@pytest.mark.parametrize("section, expected", [
    ({"totals": {"cost_usd": 1.5, "cost_complete": True}}, 1.5),
    ({"totals": {"cost_usd": 1.5, "cost_complete": False}}, None),
    ({"totals": {"cost_usd": 1.5, "cost_complete": True}, "incomplete": True}, None),
    ({}, None),
])
def test_run_cost_is_the_complete_total_or_none(monkeypatch, section, expected):
    monkeypatch.setattr(runs, "active", lambda rid: {"id": rid})
    monkeypatch.setattr(runs_usage, "for_run", lambda *a, **k: section)
    assert headless.run_cost("r1") == expected
    assert headless.run_cost(None) is None
