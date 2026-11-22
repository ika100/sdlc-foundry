"""Spec 198 acceptance tests: `cplat platform release` holds `main` from its first check until the tag, an error or a stop
(AC-198.1, 198.4 to 198.7). Contract: design.md, "`platrelease.main`" and the table of lines.

The world is the spec 129 release world (a bare origin, a scripted `gh`); the hold is read from its file by the seams of
hold_world_198 (the release's slug in the world is acme/shop, as the pull request URL says)."""
import os

import pytest

import dispatch_state
import ship
from hold_world_198 import OTHER_PID, SLUG, busy_lock, clock, hold_path, read_hold, stopped_hold, write_hold  # noqa: F401
from platrelease_world import w  # noqa: F401  (w is a fixture)

SET = f"release hold set on {SLUG} for 5.5.0"
STOP_LINE = f"  release hold: merges into {SLUG} wait until 2026-11-16 12:20 (lift it now: cplat platform hold --clear)"


@pytest.fixture()
def rw(w, clock, monkeypatch):
    """The release world with the hold seams: the repo's slug is acme/shop, and the clock stands at 2026-11-16 10:20."""
    import platrelease
    for mod in {dispatch_state, platrelease.dispatch_state}:         # the module the release calls, whichever copy the worker holds
        monkeypatch.setattr(mod, "slug_of", lambda repo: SLUG)
    w.clock198 = clock
    return w


def spy_checks(rw, monkeypatch, record):
    """Record what the repo looked like when each release check ran."""
    real = rw.run_check

    def run_check(repo, cmd):
        record.append({"hold": read_hold(), "said": list(rw.said), "t": rw.clock198.t, "cmd": list(cmd)})
        return real(repo, cmd)
    import platrelease_state
    monkeypatch.setattr(platrelease_state, "run_check", run_check)


def spy_merges(rw, monkeypatch, record):
    real = rw.fake_pr_run

    def run(cmd, **kw):
        if cmd[:3] == ["gh", "pr", "merge"]:
            record.append(read_hold())
        return real(cmd, **kw)
    import pr as prmod
    monkeypatch.setattr(prmod, "run", run)


# ---------------- AC-198.1 ----------------

def test_the_release_sets_its_hold_before_its_first_check_ac_198_1(rw, monkeypatch):  # AC-198.1
    seen = []
    spy_checks(rw, monkeypatch, seen)
    r = rw.run()
    assert r.rc == 3 and "CONFIRM: merge" in r.out, r.text
    seen = [s for s in seen if "needs-major" not in s["cmd"]]       # needs-major finds the version: it runs before the hold
    assert seen, "the release ran no check"
    first = seen[0]
    assert first["hold"]["version"] == "5.5.0" and first["hold"]["pid"] == os.getpid() and first["hold"]["state"] == "running"
    assert first["hold"]["since"] == "2026-11-16T10:20:00"
    assert SET in first["said"] + r.out.splitlines()
    assert SET in first["said"]                                       # said before the first check, not after


def test_a_dry_run_sets_no_hold_ac_198_1(rw, monkeypatch):  # AC-198.1
    seen = []
    spy_checks(rw, monkeypatch, seen)
    r = rw.run("--dry-run")
    assert r.rc == 0, r.text
    assert seen and all(s["hold"] is None for s in seen)
    assert read_hold() is None and "release hold" not in r.text


def test_the_release_first_waits_for_a_merge_inside_the_lock_ac_198_1(rw, monkeypatch):  # AC-198.1
    seen = []
    spy_checks(rw, monkeypatch, seen)
    let_go = busy_lock(SLUG, "pr 10")
    rw.clock198.at(20, let_go)
    try:
        r = rw.run()
    finally:
        let_go()
    assert r.rc == 3, r.text
    waiting = "waiting for the merge of pr 10 to end before the release"
    assert waiting in r.text and r.text.index(waiting) < r.text.index(SET)
    seen = [s for s in seen if "needs-major" not in s["cmd"]]       # needs-major finds the version: it runs before the hold
    assert seen and seen[0]["t"] >= 20                                        # no check before that merge ended


# ---------------- AC-198.4 ----------------

def test_the_release_merges_its_own_pull_request_through_its_own_hold_ac_198_4(rw, monkeypatch):  # AC-198.4
    rw.in_state("pr-open")
    at_merge = []
    spy_merges(rw, monkeypatch, at_merge)
    r = rw.run("--confirm", "merge")
    assert len(rw.merges) == 1, r.text
    assert at_merge and at_merge[0]["pid"] == os.getpid() and at_merge[0]["state"] == "running"   # the hold was set during the merge
    assert "waiting for the release hold" not in r.text
    assert rw.clock198.t == 0 or rw.clock198.t < 5                    # no wait of 5 seconds or more for its own hold


# ---------------- AC-198.5 ----------------

def test_the_hold_is_cleared_right_after_the_tag_is_pushed_ac_198_5(rw, monkeypatch):  # AC-198.5
    rw.in_state("merged")
    at_release = []
    real = rw.gh

    def gh(args, *, cwd, check=True):
        if list(args)[:2] == ["release", "create"]:
            at_release.append(read_hold())
        return real(args, cwd=cwd, check=check)
    monkeypatch.setattr(ship, "gh", gh)
    r = rw.run("--confirm", "tag")
    assert "v5.5.0" in rw.origin_tags(), r.text
    assert read_hold() is None
    assert "release hold cleared" in r.text
    assert at_release == [None]                                       # the GitHub release needs no still main


def test_the_hold_is_cleared_when_the_release_ends_in_an_error_ac_198_5(rw):  # AC-198.5
    rw.results["rows"] = (1, "ERROR: docs/CHANGELOG.md: [5.5.0] does not list - operator x 1 → 2\nFAILED: 1 problem(s)")
    r = rw.run()
    assert r.rc == 1
    assert read_hold() is None
    assert "release hold cleared" in r.text


def test_the_hold_is_cleared_when_the_release_is_interrupted_ac_198_5(rw, monkeypatch):  # AC-198.5
    import platrelease_state

    def interrupted(repo, cmd):
        if "rows" in cmd:
            raise KeyboardInterrupt
        return rw.run_check(repo, cmd)
    monkeypatch.setattr(platrelease_state, "run_check", interrupted)
    try:
        r = rw.run()
        text = r.text
    except KeyboardInterrupt:
        text = rw.capsys.readouterr().out + "\n".join(rw.said)
    assert read_hold() is None
    assert "release hold cleared" in text


# ---------------- AC-198.6 ----------------

def test_the_merge_stop_keeps_the_hold_for_two_hours_and_names_the_expiry_ac_198_6(rw):  # AC-198.6
    r = rw.run()
    assert r.rc == 3 and "CONFIRM: merge" in r.out, r.text
    assert read_hold()["state"] == "stopped" and read_hold()["confirm"] == "merge" and read_hold()["expires"] == "2026-11-16T12:20:00"
    lines = r.out.splitlines()
    assert STOP_LINE in lines
    assert lines[lines.index(STOP_LINE) + 1] == "  continue: cplat platform release --confirm merge"
    assert "release hold cleared" not in r.text


def test_the_tag_stop_keeps_the_hold_for_two_hours_and_names_the_expiry_ac_198_6(rw):  # AC-198.6
    rw.in_state("merged")
    r = rw.run()
    assert r.rc == 3 and "CONFIRM: tag" in r.out, r.text
    assert read_hold()["state"] == "stopped" and read_hold()["confirm"] == "tag" and read_hold()["expires"] == "2026-11-16T12:20:00"
    lines = r.out.splitlines()
    assert STOP_LINE in lines
    assert lines[lines.index(STOP_LINE) + 1].startswith("  continue: cplat platform release")


@pytest.mark.parametrize("argv", [["--confirm", "merge"], []], ids=["with-confirm", "without-confirm"])
def test_a_later_run_takes_the_stopped_hold_over_ties_it_to_itself_and_lifts_the_expiry_ac_198_6(rw, monkeypatch, argv):  # AC-198.6
    rw.in_state("pr-open")
    stopped_hold(confirm="merge", version="5.5.0", pid=OTHER_PID, since="2026-11-16T09:00:00", expires="2026-11-16T11:00:00")
    at_merge = []
    spy_merges(rw, monkeypatch, at_merge)
    r = rw.run(*argv)
    assert f"release hold set on {SLUG} for 5.5.0 (taken over from the stop at confirm merge)" in r.text
    if argv:
        assert at_merge[0]["pid"] == os.getpid() and at_merge[0]["state"] == "running"
        assert at_merge[0]["expires"] is None and at_merge[0]["since"] == "2026-11-16T09:00:00"


def test_a_run_over_an_expired_stop_sets_a_new_hold_ac_198_6(rw):  # AC-198.6
    stopped_hold(expires="2026-11-16T10:00:00", version="5.4.9", pid=OTHER_PID)
    r = rw.run()
    assert r.rc == 3, r.text
    assert f"release hold of {SLUG} expired" in r.text and SET in r.text
    assert read_hold()["version"] == "5.5.0"


# ---------------- AC-198.7 ----------------

def test_a_second_release_while_the_first_runs_stops_with_an_error_and_changes_nothing_ac_198_7(rw):  # AC-198.7
    rw.clock198.live.add(OTHER_PID)
    before = write_hold(version="5.4.9", pid=OTHER_PID)
    snap = rw.snapshot()
    r = rw.run()
    assert r.rc == 1, r.text
    assert "5.4.9" in r.err and str(OTHER_PID) in r.err and "one release at a time" in r.err
    assert read_hold() == before and rw.snapshot() == snap
    assert [c for _, c in rw.check_calls if "needs-major" not in c] == []     # needs-major is version detection, before the hold


def test_a_release_over_a_hold_whose_process_was_killed_drops_it_and_goes_on_ac_198_7(rw):  # AC-198.7
    write_hold(version="5.4.9", pid=OTHER_PID)                        # not alive: the release was killed
    r = rw.run()
    assert r.rc == 3, r.text
    assert f"release hold of {SLUG} dropped: process {OTHER_PID} is gone" in r.text
    assert SET in r.text and read_hold()["version"] == "5.5.0" and read_hold()["pid"] == os.getpid()
    assert hold_path().exists()


@pytest.mark.parametrize("argv", [(), ("--confirm", "merge")], ids=["at-the-check", "at-the-merge"])
def test_red_ci_on_the_release_pr_keeps_the_hold_as_a_stop_855(rw, argv):  # #855
    """A red check (a flake to rerun) is a stop the release resumes from: main stays held until the stop's expiry, so no other
    merge moves main and the resumed release needs no restart."""
    from platrelease_world import E2E, chk
    rw.in_state("pr-open")
    rw.check_seq = [[chk("quality", "fail", 42), chk(E2E, "pass", 43)]]
    r = rw.run(*argv)
    assert r.rc == 1 and f"CI is red on {rw.pr_url}: not merged" in r.err, r.text
    hold = read_hold()
    assert hold["state"] == "stopped" and hold["confirm"] == "ci" and hold["expires"] == "2026-11-16T12:20:00"
    assert STOP_LINE.strip() in r.err and "release hold cleared" not in r.text
    assert rw.merges == []
