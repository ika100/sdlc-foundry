"""Module-level tests of dispatch_state (spec 167): steering survives a reload, unit files are read
back from a worktree's git dir, events and the loop lock."""
import datetime as dt
import subprocess

import pytest

import dispatch_state as ds
from core import PlatformError

SLUG = "acme/shop-api"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(ds, "now", lambda: dt.datetime(2026, 11, 10, 12, 0, 0))
    return tmp_path


def test_missing_or_broken_state_is_the_empty_state(home):
    assert ds.load(SLUG)["steering"]["pinned"] == []
    ds.state_file(SLUG).parent.mkdir(parents=True)
    ds.state_file(SLUG).write_text("{not json")
    assert ds.load(SLUG)["steering"]["paused"] is None


def test_steering_is_recorded_and_survives_a_reload(home):
    ds.pause(SLUG, drain=True)
    ds.set_slots(SLUG, 3)
    ds.pin(SLUG, "issue-1")
    ds.pin(SLUG, "issue-2")
    ds.pin(SLUG, "issue-1")
    ds.skip(SLUG, "issue-4", "waiting for infra")
    ds.hold(SLUG, "spec-007", "needs-decision", "spec-007.1")
    st = ds.load(SLUG)["steering"]
    assert st["paused"] == "drain" and st["slots"] == 3 and st["pinned"] == ["issue-1", "issue-2"]
    assert st["skipped"]["issue-4"]["reason"] == "waiting for infra" and st["holds"]["spec-007"]["unit"] == "spec-007.1"
    ds.unpin(SLUG, "issue-1")
    ds.resume(SLUG)
    ds.resume_item(SLUG, "issue-4")
    ds.resume_item(SLUG, "spec-007")
    st = ds.load(SLUG)["steering"]
    assert st["paused"] is None and st["pinned"] == ["issue-2"] and st["skipped"] == {} and st["holds"] == {}


def test_slots_are_limited(home):
    with pytest.raises(PlatformError):
        ds.set_slots(SLUG, 11)


@pytest.mark.parametrize("text,key", [("#123", "issue-123"), ("007", "spec-007"), ("spec-007", "spec-007"),
                                      ("167-a-dispatcher-runs", "spec-167"), ("spec-12", "spec-012")])
def test_parse_item(text, key):
    assert ds.parse_item(text) == key


@pytest.mark.parametrize("text", ["nonsense", "123"])
def test_parse_item_refuses_other_text_and_a_bare_number(text):
    with pytest.raises(ds.ItemRefused):
        ds.parse_item(text)


def test_events_unseen_and_seen_and_unit_seq(home):
    a = ds.events_add(SLUG, "escalated", "issue-1.1", "#1", "why")
    b = ds.events_add(SLUG, "done", "issue-2.1", "#2", pr="https://x/pull/2")
    assert [e["seq"] for e in ds.events_unseen(SLUG, ["escalated", "red"])] == [a]
    ds.mark_seen(SLUG, a)
    assert ds.events_unseen(SLUG, ["escalated"]) == [] and [e["seq"] for e in ds.events_unseen(SLUG)] == [b]
    assert [ds.next_unit(SLUG, "issue-1"), ds.next_unit(SLUG, "issue-1"), ds.next_unit(SLUG, "spec-9")] == \
        ["issue-1.1", "issue-1.2", "spec-9.1"]


def test_pruning_keeps_90_days_and_500_events(home):
    ds.update(SLUG, lambda st: st["ledger"].update({"2026-01-01": {"units": {}, "agent": 1}, "2026-11-09": {"units": {}, "agent": 2}}))
    ds.history_add(SLUG, {"unit": "a.1", "ended_at": "2026-01-01T10:00:00"})
    ds.history_add(SLUG, {"unit": "b.1", "ended_at": "2026-11-09T10:00:00"})
    ds.days_held(SLUG, "2026-11-10", "#5", "claimed")
    st = ds.load(SLUG)
    assert list(st["ledger"]) == ["2026-11-09"] and [h["unit"] for h in st["history"]] == ["b.1"]
    assert st["days"]["2026-11-10"]["held"] == {"#5": "claimed"}
    for i in range(510):
        ds.update(SLUG, lambda st, i=i: st["events"].append({"seq": i + 1, "kind": "done"}))
    assert len(ds.load(SLUG)["events"]) == 500


def test_unit_files_are_read_back_from_a_worktree(home):
    wt = ds.worktree_path(SLUG, "issue-1")
    wt.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    assert ds.read_unit(wt) is None
    ds.write_unit(wt, {"unit": "issue-1.1", "status": "running", "pid": 4242})
    assert ds.read_unit(wt)["unit"] == "issue-1.1"
    assert [u["unit"] for u in ds.all_units(SLUG)] == ["issue-1.1"]
    ds.set_stop(wt)
    assert ds.stop_path(wt).exists()
    ds.clear_stop(wt)
    assert not ds.stop_path(wt).exists()
    assert ds.read_unit(home / "nowhere") is None


def test_loop_lock_is_exclusive_and_names_the_holder(home):
    assert not ds.loop_alive(SLUG)
    with ds.loop_lock(SLUG):
        assert ds.loop_alive(SLUG)
        with pytest.raises(ds.Busy) as e:
            with ds.loop_lock(SLUG):
                pass
        assert "a dispatcher already runs for acme/shop-api (pid " in str(e.value)
    assert not ds.loop_alive(SLUG)


def test_paths(home):
    assert ds.base(SLUG).as_posix().endswith("sdlc-foundry/dispatch/acme__shop-api")
    assert ds.merge_lock_path(SLUG).as_posix().endswith("sdlc-foundry/locks/acme__shop-api.merge.lock")
    ds.write_json(ds.needs_path(SLUG), {"items": []})
    assert ds.needs_files() == [ds.needs_path(SLUG)]
