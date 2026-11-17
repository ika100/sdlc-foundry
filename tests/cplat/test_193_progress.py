"""Spec 193 acceptance tests: the build screen while items run (AC-193.3): event lines, `Building now`, no agent output, the choices."""
import time

import pytest

from support_193 import BuildWorld, by_label, labels, question


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch)
    w.queue()
    w.build(started="2026-11-14T09:00:00", slots=2)
    w.unit("spec-189", "running")
    w.unit("issue-713", "running")
    w.event("started", "#712", "2026-11-14T09:12:00", unit="issue-712.1")
    w.event("done", "#712", "2026-11-14T09:40:00", unit="issue-712.1", pr="https://github.com/o/n/pull/760")
    w.event("started", "spec-189", "2026-11-14T09:41:00", unit="spec-189.1")
    w.event("started", "#713", "2026-11-14T09:42:00", unit="issue-713.1")
    w.local_spec("189-progress", "The progress screen", 3)
    return w


def screen_of(world, capsys, *args):
    lock = world.loop_runs()
    with lock:
        return world.screen(capsys, *args)


def test_one_line_per_event_with_the_local_time(world, capsys, tmp_path):  # AC-193.3
    j = world.judgement(tmp_path, {"issue-712": {"you_get": "A label that stays"}, "spec-189": {"you_get": "A progress screen"},
                                   "issue-713": {"you_get": "A second fix"}})
    screen = screen_of(world, capsys, "--judgement", j)
    lines = screen.splitlines()
    for expected in ("  09:12 started #712 A label that stays", "  09:40 merged #712 (PR #760)", "  09:40 finished #712",
                     "  09:41 started spec 189 A progress screen", "  09:42 started #713 A second fix"):
        assert expected in lines
    assert lines.index("  09:12 started #712 A label that stays") < lines.index("  09:40 merged #712 (PR #760)") \
        < lines.index("  09:40 finished #712")


def test_head_line_and_running_items(world, capsys, tmp_path):  # AC-193.3
    j = world.judgement(tmp_path, {"spec-189": {"you_get": "A progress screen"}, "issue-713": {"you_get": "A second fix"}})
    screen = screen_of(world, capsys, "--judgement", j)
    assert "Building 3 items, two at a time." in screen
    block = screen.split("Building now:\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert len(block) == 2
    assert any(ln.startswith("  A progress screen (spec 189): ") for ln in block)
    assert any(ln.startswith("  A second fix (#713): ") for ln in block)


def test_the_screen_prints_no_agent_output(world, capsys):  # AC-193.3
    screen = screen_of(world, capsys)
    assert "Building now:" in screen and "09:12 started #712" in screen
    assert "AGENT-OUTPUT-SENTINEL" not in screen
    with world.loop_runs():
        doc = world.doc(capsys)
    assert "Building now:" in doc["screen"] and "AGENT-OUTPUT-SENTINEL" not in doc["screen"]


def test_other_event_words(world, capsys):  # AC-193.3
    world.event("escalated", "#714", "2026-11-14T09:50:00", unit="issue-714.1")
    world.event("stale", "#715", "2026-11-14T09:51:00")
    lines = screen_of(world, capsys).splitlines()
    assert any(ln.startswith("  09:50 stopped #714") for ln in lines)
    assert any(ln.startswith("  09:51 closed #715: already fixed on main") for ln in lines)


def test_only_the_newest_five_events_are_listed(world, capsys):  # AC-193.3
    for i in range(3):
        world.event("started", f"#8{i}", f"2026-11-14T09:5{i}:00", unit=f"issue-8{i}.1")
    screen = screen_of(world, capsys)
    event_lines = [ln for ln in screen.splitlines() if ln[:2] == "  " and ln[2:4].isdigit() and ln[4] == ":"]
    assert len(event_lines) == 5
    assert "  and 3 earlier" in screen and screen.index("  and 3 earlier") < screen.index(event_lines[0])
    assert "09:12 started #712" not in screen


def test_build_choices(world, capsys):  # AC-193.3
    with world.loop_runs():
        doc = world.doc(capsys)
    q = question(doc, "watch")
    assert q["header"] == "Building"
    assert labels(q) == ["Keep watching", "Leave it running", "Stop after the running items"]
    assert q["options"][0]["recommended"] is True
    keep = by_label(q, "Keep watching")
    seq = doc["build"]["last_seq"]
    assert keep["then"][:3] == ["cplat", "next", "--json"] and keep["then"][-4:] == ["--watch", "540", "--after", str(seq)]
    assert not by_label(q, "Leave it running")["steps"] and not by_label(q, "Leave it running")["then"]
    stop = by_label(q, "Stop after the running items")
    assert stop["steps"] == ["cplat dispatch pause --drain"] and any("cplat dispatch resume" in u for u in stop["undo"])


def test_build_document_has_events_and_running(world, capsys):  # AC-193.3
    with world.loop_runs():
        b = world.doc(capsys)["build"]
    assert b["loop"]["running"] is True and b["current"] == {"started_at": "2026-11-14T09:00:00", "slots": 2}
    assert [e["kind"] for e in b["events"]] == ["started", "done", "started", "started"]
    assert b["events"][1]["time"] == "09:40" and b["events"][1]["pr"].endswith("/pull/760")
    assert b["last_seq"] == b["events"][-1]["seq"]
    assert {r["key"] for r in b["running"]} == {"spec-189", "issue-713"}
    assert b["ended"] is False


def test_watch_returns_at_once_when_an_event_is_newer(world, capsys):  # AC-193.3
    seq = world.read_state()["events"][0]["seq"]
    started = time.monotonic()
    with world.loop_runs():
        rc, out = world.next(capsys, "--json", "--watch", "30", "--after", str(seq))
    assert rc == 0 and time.monotonic() - started < 10
    assert '"schema": 1' in out


def test_watching_changes_nothing(world, capsys):  # AC-193.3
    with world.loop_runs():
        before = world.snapshot()
        assert "Building now:" in world.screen(capsys)
        assert world.doc(capsys)["build"]["running"]
        assert world.snapshot() == before and world.writes() == []
