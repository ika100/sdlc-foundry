"""Spec 178 acceptance tests: the one landing path (AC-178.2, AC-178.3, AC-178.4).

The world is the land world of spec 171 (a bare repository for GitHub, a `gh` executable on PATH that answers from it, a fake clock)
with the stricter fake GitHub of land178_world.py: it refuses a merge while a required check of the head is not green and logs, for
every merge call, the required checks that were pending when it came. Nothing here reaches GitHub or the network.
`AC-178.1` (the release stops) is in test_178_release.py.
"""
import subprocess
from dataclasses import dataclass

import pytest

import cplat
import land_merge
import ship
from land171_world import BRANCH, PR_URL, git
from land178_world import lock_is_held, make_world, state
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

SLUG = "acme/shop-api"
SPEC_ID = "007-price-alerts"
REASON = 'Required status check "test" is expected.'
BOTH = {"test": "pass", "lint": "pass"}
AFTER_UPDATE = [{"test": "pass"}, {"test": "pass", "lint": "pending"}, BOTH]     # the checks of a new head appear one by one
ENTRIES = ["ship", "pr"]
COMMANDS = ["ship", "pr", "dispatch", "spec", "release"]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import platrelease
    w = make_world(tmp_path, monkeypatch)
    w.configure(check_names=["test", platrelease.E2E_NAME])      # the release also needs its upgrade e2e to have passed
    return w


def land(world, entry, capsys, timeout=900):
    capsys.readouterr()
    if entry == "ship":
        argv = ["component", "ship", "--repo", str(world.repo), "land", "--timeout", str(timeout), "--interval", "1"]
    else:
        argv = ["pr", "wait", PR_URL, "--merge", "--repo", str(world.repo), "--timeout", str(timeout), "--interval", "1"]
    rc = cplat.main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def attempts(world):
    return world.events("merge-attempt")


def new_head_is_checked_before_it_merges(world, old):
    [merged] = world.events("merged")
    new = merged["head"]
    assert new != old
    order = [(c["kind"], c["sha"] if c["kind"] == "checks" else c["head"]) for c in world.calls() if c.get("kind") in ("checks", "merged")]
    assert ("checks", new) in order and order.index(("checks", new)) < order.index(("merged", new))
    return new


def script_checks(world, names, after, start=None):
    """The head the land starts with shows `names` green; every later head shows the answers `after`, one per poll."""
    start = start or world.pr_head()
    world.configure(required=list(names), orig_head=start, scripts={start: [{n: "pass" for n in names}]}, moved_script=after)
    return start


# ---------------- AC-178.2: no merge call before the new head's checks finished ----------------

def move_head_by_catch_up(world):
    world.other_commit({"other.txt": "main moved\n"})


def move_head_by_regeneration(world):
    world.feature_adds_spec(199)
    world.other_adds_spec(108)


def move_head_by_push_ahead(world):
    world.local_commit("a.txt")


MOVES = [("ship", move_head_by_catch_up), ("pr", move_head_by_catch_up),
         ("ship", move_head_by_regeneration), ("pr", move_head_by_regeneration),
         ("ship", move_head_by_push_ahead)]


@pytest.mark.parametrize("entry, move", MOVES, ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_no_merge_call_while_a_required_check_of_the_new_head_is_pending(world, capsys, entry, move):  # AC-178.2
    move(world)
    start = script_checks(world, ["test", "lint"], AFTER_UPDATE)
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    [attempt] = attempts(world)                        # one merge call, and no required check was pending when it came
    assert attempt["pending"] == []
    new_head_is_checked_before_it_merges(world, start)
    polls = [c for c in world.events("checks") if c["sha"] == attempt["head"]]
    assert polls and polls[-1]["names"] == ["lint", "test"]     # the poll before the merge saw both (approved 2026-11-10)


@pytest.mark.parametrize("entry, move", MOVES, ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_a_red_check_of_the_new_head_stops_the_land_as_a_red_check_does(world, capsys, entry, move):  # AC-178.2
    move(world)
    script_checks(world, ["test", "lint"], [{"test": "fail", "lint": "pending"}])
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == [] and attempts(world) == []
    assert "RED" in out, out + err


def test_a_check_that_was_green_on_the_old_head_and_never_shows_on_the_new_one_is_dropped_when_not_required(world, capsys, monkeypatch):  # AC-178.2
    monkeypatch.setattr(ship, "NO_CHECKS_GRACE", 5)
    move_head_by_catch_up(world)
    start = world.pr_head()
    world.configure(required=["test"], orig_head=start, scripts={start: [{"test": "pass", "docs": "pass"}]}, moved_script=[{"test": "pass"}])
    rc, out, err = land(world, "pr", capsys)
    assert rc == 0, out + err
    new = new_head_is_checked_before_it_merges(world, start)
    assert f"docs did not run on {new[:7]}: not expected" in out


def test_a_required_check_that_never_shows_on_the_new_head_is_never_dropped(world, capsys, monkeypatch):  # AC-178.2
    monkeypatch.setattr(ship, "NO_CHECKS_GRACE", 5)
    move_head_by_catch_up(world)
    script_checks(world, ["test", "lint"], [{"test": "pass"}])
    rc, out, err = land(world, "pr", capsys, timeout=15)
    assert rc == 1 and world.events("merged") == [] and attempts(world) == []
    assert "lint" in err and "pending" in err, out + err


# ---------------- AC-178.3: a refused merge is waited for, three of them end the land ----------------

@pytest.mark.parametrize("entry", ENTRIES)
def test_a_refused_merge_goes_back_to_waiting_and_merges_when_the_checks_are_green(world, capsys, monkeypatch, entry):  # AC-178.3
    world.configure(refuse_next=[REASON])
    seen = []
    world.hook(lambda a: a[:2] == ["pr", "checks"], lambda: seen.append((len(attempts(world)), lock_is_held(SLUG))), repeat=True)
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    assert len(attempts(world)) == 2 and len(world.events("merged")) == 1
    assert "ERROR" not in err
    assert "refusal 1/3" in out and REASON in out
    after = [held for n, held in seen if n >= 1]
    assert after, "the land judged the checks of the head again after the refusal"
    assert all(after), "the wait after a refusal is inside the merge lock"
    order = [c["kind"] for c in world.calls() if c.get("kind") in ("checks", "merge-attempt", "merged")]
    assert order.index("merge-attempt") < len(order) - 1 and "checks" in order[order.index("merge-attempt"):]


@pytest.mark.parametrize("entry", ENTRIES)
def test_the_third_refused_merge_of_one_land_exits_1_with_githubs_reason(world, capsys, entry):  # AC-178.3
    world.configure(refuse_next=[REASON, REASON, REASON, REASON])
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert len(attempts(world)) == 3
    assert f"ERROR: merge refused 3 times: {REASON}" in err.splitlines()


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_red_check_after_a_refusal_ends_the_land_as_red(world, capsys, entry):  # AC-178.3
    world.configure(refuse_next=[REASON])
    world.after_checks(lambda: world.configure(checks={**state(world)["checks"], "default": ["fail"]}), nth=1)
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == [] and len(attempts(world)) == 1
    assert "RED" in out and "merge refused" not in err


# ---------------- AC-178.4: five commands, one landing path, a stated mode ----------------

@dataclass
class Outcome:
    ok: bool
    text: str
    stopped: bool = False           # the release stopped because main moved
    landed: str = ""                # the dispatcher's record


def drive(world, command, monkeypatch, capsys):
    """Run one of the five commands that merge into main, in this world; the same call for the same scenario."""
    capsys.readouterr()
    if command in ENTRIES:
        rc = world.land(command)
        cap = capsys.readouterr()
        return Outcome(rc == 0, cap.out + cap.err)
    if command == "dispatch":
        import dispatch_units as du
        unit, updates = {"unit": "u1", "pr": PR_URL, "worktree": str(world.repo)}, {}
        monkeypatch.setattr(du.ds, "worktree_path", lambda slug, key: world.repo)
        monkeypatch.setattr(du.ds, "read_unit", lambda wt: unit)
        monkeypatch.setattr(du, "update_unit", lambda wt, fn: (fn(updates), updates)[1])
        rc = du.land(world.repo, SLUG, "u1")
        cap = capsys.readouterr()
        return Outcome(rc == 0, cap.out + cap.err + str(updates.get("landed_summary", "")), landed=str(updates.get("landed")))
    if command == "spec":
        import spec as specmod
        import spec_pr
        sp = specmod.find(world.repo, SPEC_ID)
        sp.meta["status"] = "approved"
        monkeypatch.setattr(spec_pr, "publish", lambda root, s: {"pr": 7})
        monkeypatch.setattr(spec_pr, "login", lambda root: "me")
        monkeypatch.setattr(spec_pr, "owner_of", lambda root: "me")
        monkeypatch.setattr(spec_pr, "gh", lambda args, *, cwd: (0, ""))
        try:
            ok, lines = spec_pr.land(world.repo, sp)
        except land_merge.PlatformError as e:
            return Outcome(False, str(e))
        return Outcome(ok, capsys.readouterr().out + "\n".join(lines))
    import platrelease
    opts = platrelease.Opts(version="5.5.0", confirm="merge", timeout=900, interval=1)
    try:
        merged, _sha = platrelease._ci_and_merge(world.repo, PR_URL, "5.5.0", opts)
    except getattr(land_merge, "BaseMoved", ()) as e:
        return Outcome(False, str(e), stopped=True)
    except land_merge.PlatformError as e:
        return Outcome(False, str(e))
    return Outcome(bool(merged), capsys.readouterr().out)


@pytest.fixture()
def modes(monkeypatch):
    """Every call of `wait_green` and `settle`, with the `mode=` it was given."""
    seen = []
    for name in ("wait_green", "settle"):
        real = getattr(land_merge, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            seen.append((_name, kwargs.get("mode")))
            return _real(*args, **kwargs)
        monkeypatch.setattr(land_merge, name, spy)
    return seen


def assert_stated_mode(seen, command, merged=True):
    want = "release" if command == "release" else "catch-up"
    assert not merged or any(name == "settle" for name, _ in seen), seen
    for name, mode in seen:
        assert mode is not None, f"{command} calls land_merge.{name} without stating its mode"
        assert mode.name == want and mode.catch_up == (command != "release"), (command, name, mode)


@pytest.mark.parametrize("command", COMMANDS)
def test_a_head_that_moved_before_the_merge_is_checked_first_by_every_command(world, capsys, monkeypatch, modes, command):  # AC-178.4
    old = world.pr_head()
    world.after_checks(world.push_pr_commit)
    out = drive(world, command, monkeypatch, capsys)
    assert out.ok, out.text
    new_head_is_checked_before_it_merges(world, old)
    assert all(a["match"] for a in attempts(world))
    assert_stated_mode(modes, command)


@pytest.mark.parametrize("command", COMMANDS)
def test_a_failed_local_step_after_an_accepted_merge_is_no_failed_land_for_every_command(world, capsys, monkeypatch, modes, command):  # AC-178.4
    (world.repo / "work.txt").write_text("an edit that is not committed\n")      # `git switch main` would overwrite it
    out = drive(world, command, monkeypatch, capsys)
    assert out.ok, out.text
    assert len(world.events("merged")) == 1
    assert git(world.repo, "branch", "--show-current") == BRANCH
    if command != "release":                                  # the release prints no cleanup lines on success
        assert "WARNING: switching to main failed: " in out.text
    assert_stated_mode(modes, command)


@pytest.mark.parametrize("command", COMMANDS)
def test_a_refused_merge_is_waited_for_by_every_command(world, capsys, monkeypatch, modes, command):  # AC-178.4
    world.configure(refuse_next=[REASON])
    out = drive(world, command, monkeypatch, capsys)
    assert out.ok, out.text
    assert len(attempts(world)) == 2 and len(world.events("merged")) == 1
    assert_stated_mode(modes, command)


@pytest.mark.parametrize("command", COMMANDS)
def test_three_refused_merges_end_every_command_the_same_way(world, capsys, monkeypatch, modes, command):  # AC-178.4
    world.configure(refuse_next=[REASON] * 4)
    out = drive(world, command, monkeypatch, capsys)
    assert not out.ok and world.events("merged") == [] and len(attempts(world)) == 3
    assert f"merge refused 3 times: {REASON}" in out.text
    if command == "dispatch":
        assert out.landed == "merge-failed"
    assert_stated_mode(modes, command, merged=False)


@pytest.mark.parametrize("command", [c for c in COMMANDS if c != "release"])
def test_a_branch_behind_main_is_caught_up_and_its_new_head_checked_by_four_commands(world, capsys, monkeypatch, modes, command):  # AC-178.4
    world.other_commit({"other.txt": "main moved\n"})
    old = world.pr_head()
    out = drive(world, command, monkeypatch, capsys)
    assert out.ok, out.text
    assert len(world.events("update-branch")) == 1
    new_head_is_checked_before_it_merges(world, old)
    assert_stated_mode(modes, command)


def test_a_branch_behind_main_stops_the_release_and_changes_nothing(world, capsys, monkeypatch, modes):  # AC-178.4
    world.other_commit({"other.txt": "main moved\n"})
    old, main = world.pr_head(), world.main_tip()
    out = drive(world, "release", monkeypatch, capsys)
    assert out.stopped, out.text
    assert world.events("update-branch") == [] and attempts(world) == [] and world.events("merged") == []
    assert world.pr_head() == old and world.main_tip() == main
    assert_stated_mode(modes, "release", merged=False)


def test_the_land_of_a_unit_records_a_refused_merge_for_the_dispatcher(world, capsys, monkeypatch):  # AC-178.3
    world.configure(refuse_next=[REASON] * 4)
    out = drive(world, "dispatch", monkeypatch, capsys)
    assert out.landed == "merge-failed" and f"merge refused 3 times: {REASON}" in out.text


def test_the_checkout_is_left_as_it_was_by_a_refused_land(world, capsys):  # AC-178.3
    world.configure(refuse_next=[REASON] * 4)
    land(world, "pr", capsys)
    assert git(world.repo, "branch", "--show-current") == BRANCH
    assert subprocess.run(["git", "status", "--porcelain"], cwd=world.repo, capture_output=True, text=True).stdout.strip() == ""
