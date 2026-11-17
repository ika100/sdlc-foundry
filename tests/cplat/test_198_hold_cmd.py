"""Spec 198 acceptance tests: `cplat platform hold [--clear] [--json]` (AC-198.8) and the line of `cplat dispatch status`
(AC-198.9). Contract: design.md, "`cplat platform hold`" and "`cplat dispatch status`"."""
import json
import subprocess

import pytest

import cplat
import dispatch_policy
import dispatch_view as dv
from hold_world_198 import OTHER_PID, SLUG, clock, hold_path, read_hold, stopped_hold, write_hold  # noqa: F401

RUNNING = {"version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": OTHER_PID, "state": "running", "expires": None}
STOPPED = {"version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": OTHER_PID, "state": "stopped at confirm merge",
           "expires": "2026-11-16T12:20:00"}


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "shop"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "remote", "add", "origin", f"https://github.com/{SLUG}.git"], check=True)
    return r


@pytest.fixture()
def hold(repo, clock, capsys):
    def run(*argv):
        try:
            rc = cplat.main(["platform", "hold", "--repo", str(repo), *argv])
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
        out = capsys.readouterr().out
        return rc, out
    return run


# ---------------- AC-198.8 ----------------

def test_without_a_hold_it_says_so_ac_198_8(hold):  # AC-198.8
    assert hold() == (0, f"no release hold on {SLUG}\n")


def test_a_running_hold_is_printed_with_version_since_process_and_state_ac_198_8(hold, clock):  # AC-198.8
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    assert hold() == (0, f"release hold on {SLUG}: release 5.24.0 since 2026-11-16 10:20, process {OTHER_PID}, running\n")


def test_a_hold_at_a_stop_is_printed_with_its_expiry_ac_198_8(hold):  # AC-198.8
    stopped_hold(confirm="merge", pid=OTHER_PID)
    assert hold() == (0, f"release hold on {SLUG}: release 5.24.0 since 2026-11-16 10:20, process {OTHER_PID}, "
                         "stopped at confirm merge, expires 2026-11-16 12:20\n")


def test_json_prints_the_same_as_one_object_or_null_ac_198_8(hold, clock):  # AC-198.8
    rc, out = hold("--json")
    assert rc == 0 and json.loads(out) is None
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    assert json.loads(hold("--json")[1]) == RUNNING
    stopped_hold(confirm="merge", pid=OTHER_PID)
    assert json.loads(hold("--json")[1]) == STOPPED
    stopped_hold(confirm="tag", pid=OTHER_PID)
    assert json.loads(hold("--json")[1])["state"] == "stopped at confirm tag"


def test_a_hold_whose_process_is_gone_shows_as_none_and_is_not_removed_by_showing_it_ac_198_8(hold):  # AC-198.8
    write_hold(pid=OTHER_PID)                       # not alive
    assert hold() == (0, f"no release hold on {SLUG}\n")
    assert json.loads(hold("--json")[1]) is None
    assert read_hold() is not None


def test_clear_removes_the_hold_and_says_so_ac_198_8(hold, clock):  # AC-198.8
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    assert hold("--clear") == (0, f"release hold of {SLUG} cleared by hand\n")
    assert not hold_path().exists()
    assert hold("--clear") == (0, f"no release hold on {SLUG}\n")


def test_clear_removes_a_stale_hold_too_ac_198_8(hold):  # AC-198.8
    write_hold(pid=OTHER_PID)                       # not alive
    assert hold("--clear") == (0, f"release hold of {SLUG} cleared by hand\n")
    assert not hold_path().exists()


def test_clear_with_json_prints_the_removed_hold_ac_198_8(hold, clock):  # AC-198.8
    assert json.loads(hold("--clear", "--json")[1]) == {"cleared": None}
    stopped_hold(confirm="merge", pid=OTHER_PID)
    assert json.loads(hold("--clear", "--json")[1]) == {"cleared": STOPPED}
    assert not hold_path().exists()


def test_a_waiting_merge_continues_when_the_hold_is_cleared_by_hand_ac_198_8(hold, clock):  # AC-198.8
    import merge_lock
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    clock.at(10, lambda: hold("--clear"))
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        assert clock.t >= 10


def test_a_usage_error_exits_2_ac_198_8(hold):  # AC-198.8
    rc, _ = hold("--bogus")
    assert rc == 2


# ---------------- AC-198.9: cplat dispatch status ----------------

def _status(tmp_path):
    (tmp_path / ".platform").mkdir(exist_ok=True)
    (tmp_path / ".platform" / "dispatch.yml").write_text("slots: 3\n")
    policy = dispatch_policy.load(tmp_path)
    doc = dv.status_doc(tmp_path, SLUG, policy)
    return doc, dv.render_status(doc).splitlines()


def test_status_shows_a_running_release_hold_as_its_second_line_ac_198_9(tmp_path, clock):  # AC-198.9
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    doc, lines = _status(tmp_path)
    assert doc["release_hold"] == RUNNING
    assert lines[0].startswith("dispatcher:") and lines[1] == "release hold: 5.24.0 since 2026-11-16 10:20"


def test_status_shows_a_hold_at_a_stop_with_its_expiry_ac_198_9(tmp_path, clock):  # AC-198.9
    stopped_hold(confirm="merge", pid=OTHER_PID)
    doc, lines = _status(tmp_path)
    assert doc["release_hold"] == STOPPED
    assert lines[1] == "release hold: 5.24.0 since 2026-11-16 10:20, stopped at confirm merge, expires 2026-11-16 12:20"


def test_status_without_a_hold_has_no_line_and_a_null_object_ac_198_9(tmp_path, clock):  # AC-198.9
    doc, lines = _status(tmp_path)
    assert "release_hold" in doc and doc["release_hold"] is None
    assert not any(ln.startswith("release hold:") for ln in lines)
    json.dumps(doc)


def test_status_treats_a_hold_of_a_dead_process_as_none_ac_198_9(tmp_path, clock):  # AC-198.9
    write_hold(pid=OTHER_PID)                       # not alive
    doc, lines = _status(tmp_path)
    assert doc["release_hold"] is None and not any(ln.startswith("release hold:") for ln in lines)
