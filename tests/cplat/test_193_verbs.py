"""Spec 193 acceptance tests: the `cplat dispatch` verbs an option of `cplat next` runs: `build` (AC-193.1), `setup` (AC-193.2),
`budget` and `resume <item>` (AC-193.5), in the dispatcher world of spec 167 (fake `gh`, fake headless, a real clone).

The build loop is never really spawned here: a test that calls `build` holds the loop lock itself, so the verb adopts the loop."""
import contextlib
import re

import pytest

from dispatch_world import SLUG, git, world  # noqa: F401  (fixture)
from waiting import poll_pause

SETUP_FILE = """# The run queue's policy (docs/dispatch.md), written by /platform:next.
budget:
  tokens_per_day: {n}
sources: [issues, specs]
gates:
  approve_specs: human
"""


@contextlib.contextmanager
def loop_held():
    import dispatch_state
    with dispatch_state.loop_lock(SLUG):
        yield


def two_issues(world):
    for i in (1, 2, 3):
        world.issue(i, title=f"issue {i}", labels=["triaged", "bug"], created=f"2026-11-0{i}T08:00:00Z")


def status_of(world):
    return git(world.repo, "status", "--porcelain")


# ---------------- AC-193.1: build ----------------

@pytest.mark.parametrize("slots", [1, 2])
def test_build_sets_slots_records_the_build_and_prints_the_undo(world, slots):  # AC-193.1
    world.policy(slots=1)
    two_issues(world)
    before_file = (world.repo / ".platform" / "dispatch.yml").read_text()
    with loop_held():
        r = world.run("build", "--slots", str(slots))
    assert r.rc == 0, r
    assert f"slots: {slots}" in r.lines
    assert any(re.fullmatch(r"build started at \d\d:\d\d", ln) for ln in r.lines), r
    assert any(ln.startswith("running: the build loop runs already (pid ") for ln in r.lines)
    assert "Undo: cplat dispatch pause --drain" in r.lines
    st = world.state()
    assert st["steering"]["slots"] == slots and st["build"]["slots"] == slots and st["build"]["started_at"]
    assert (world.repo / ".platform" / "dispatch.yml").read_text() == before_file      # slots are not committed to the policy


@pytest.mark.parametrize("slots,started", [(2, 2), (1, 1)])
def test_the_build_starts_that_many_items_at_once(world, slots, started):  # AC-193.1
    world.policy(slots=1)
    two_issues(world)
    world.behave(mode="wait")
    with loop_held():
        assert world.run("build", "--slots", str(slots)).rc == 0
    assert world.run("start", "--once").rc == 0
    assert len(world.calls()) == started


def test_build_lifts_a_drain_and_a_new_build_replaces_the_record(world):  # AC-193.1
    world.policy(slots=1)
    world.run("pause", "--drain")
    with loop_held():
        assert world.run("build", "--slots", "2").rc == 0
        first = world.state()["build"]
        world.now = world.now.replace(hour=13)
        assert world.run("build", "--slots", "1").rc == 0
    st = world.state()
    assert st["steering"]["paused"] is None
    assert st["build"]["slots"] == 1 and st["build"]["started_at"] != first["started_at"]


@pytest.mark.parametrize("slots", ["0", "11", "x"])
def test_build_refuses_a_bad_slot_count(world, slots):  # AC-193.1
    world.policy()
    r = world.run("build", "--slots", slots)
    assert r.rc == 2, r
    assert not world.state().get("build")


def test_build_needs_a_policy_with_a_budget(world):  # AC-193.1
    assert world.run("build", "--slots", "2").rc == 2
    world.policy(budget=None)
    r = world.run("build", "--slots", "2")
    assert r.rc == 2 and "ERROR:" in r.err
    assert not world.state().get("build")


def test_start_detach_adopts_a_running_loop(world):  # AC-193.1
    world.policy()
    with loop_held():
        r = world.run("start", "--detach")
    assert r.rc == 0 and re.search(r"^running: the build loop runs already \(pid \d+\)$", r.out, re.M), r


def test_start_detach_spawns_the_loop_in_its_own_session(world):  # AC-193.1
    import dispatch
    world.mp.setattr(dispatch, "sleep", poll_pause)     # the real loop needs a moment to start: wait outside the sleep guard
    world.policy()
    r = world.run("start", "--detach")
    assert r.rc == 0, r
    m = re.search(r"^started: the build loop \(pid (\d+)\), log (\S+)$", r.out, re.M)
    assert m, r
    assert world.alive(int(m.group(1)))
    assert m.group(2).endswith("loop.log")


# ---------------- AC-193.2: setup ----------------

def hint(world, *tokens):
    import dispatch_budget
    days = [{"day": f"2026-11-{3 + i:02d}", "tokens": t} for i, t in enumerate(tokens)]
    world.mp.setattr(dispatch_budget, "history_hint", lambda slug, days_=7, **k: days, raising=False)


def test_setup_show_prints_the_exact_file_from_the_hint(world):  # AC-193.2
    hint(world, None, 20_300_000, 12_000_000)
    r = world.run("setup", "--show")
    assert r.rc == 0 and r.out.strip() == SETUP_FILE.format(n=21_000_000).strip()


def test_setup_show_without_usage_names_the_missing_number(world):  # AC-193.2  (A4)
    hint(world, None, 0, None)
    r = world.run("setup", "--show")
    assert r.rc == 0 and r.out.strip() == SETUP_FILE.format(n="<your number>").strip()
    doc = world.run("setup", "--show", "--json").json()
    assert doc["tokens_per_day"] is None and doc["file"] == SETUP_FILE.format(n="<your number>")


def test_setup_show_json(world):  # AC-193.2
    hint(world, 3_000_000, 4_000_001)
    doc = world.run("setup", "--show", "--json").json()
    assert doc["tokens_per_day"] == 5_000_000 and doc["file"] == SETUP_FILE.format(n=5_000_000)
    assert [h["tokens"] for h in doc["hint"]] == [3_000_000, 4_000_001]


def test_setup_show_writes_nothing(world):  # AC-193.2
    hint(world, 1_000_000)
    before = (world.fingerprint(), status_of(world))
    assert world.run("setup", "--show").rc == 0
    assert (world.fingerprint(), status_of(world)) == before and world.gh_writes() == []


def test_setup_refuses_when_the_file_exists_and_a_bad_number(world):  # AC-193.2
    world.policy()
    r = world.run("setup", "--tokens-per-day", "21000000")
    assert r.rc == 2 and "ERROR:" in r.err and world.gh_writes() == []
    assert "merged" not in r.out


def test_setup_refuses_a_number_below_one(world):  # AC-193.2
    r = world.run("setup", "--tokens-per-day", "0")
    assert r.rc == 2 and "ERROR:" in r.err and world.gh_writes() == []


def test_setup_commits_the_file_through_a_pull_request_that_merges_on_green_ci(world):  # AC-193.2
    r = world.run("setup", "--tokens-per-day", "21000000")
    assert r.rc == 0, r
    assert re.search(r"^merged: PR #\d+$", r.out, re.M), r
    git(world.repo, "fetch", "-q", "origin")
    pushed = git(world.repo, "show", "origin/chore/dispatch-setup:.platform/dispatch.yml")
    assert pushed.strip() == SETUP_FILE.format(n=21_000_000).strip()
    message = git(world.repo, "log", "-1", "--format=%B", "origin/chore/dispatch-setup")
    assert message.startswith("chore(dispatch): set up the run queue policy") and "Signed-off-by:" in message
    verbs = [tuple(a[:2]) for a in world.gh_writes()]
    assert ("pr", "create") in verbs and ("pr", "merge") in verbs and verbs.index(("pr", "create")) < verbs.index(("pr", "merge"))
    create = next(a for a in world.gh_writes() if tuple(a[:2]) == ("pr", "create"))
    assert "/platform:next" in " ".join(create)


def test_setup_does_not_merge_a_red_pull_request(world):  # AC-193.2
    world.set_default_checks([[{"name": "ci", "bucket": "fail"}]])
    r = world.run("setup", "--tokens-per-day", "21000000")
    assert r.rc == 1, r
    assert ("pr", "merge") not in [tuple(a[:2]) for a in world.gh_writes()]
    assert ("pr", "create") in [tuple(a[:2]) for a in world.gh_writes()]       # the pull request stays open


# ---------------- AC-193.5: budget and resume ----------------

def test_budget_prints_the_limit_of_the_day(world):  # AC-193.5
    world.policy()
    r = world.run("budget")
    assert r.rc == 0 and re.fullmatch(r"budget for 2026-11-10: 20,?000,?000 tokens", r.out.strip()), r


def test_raising_the_budget_is_local_state_with_an_undo_and_changes_no_file(world):  # AC-193.5
    world.policy()
    text = (world.repo / ".platform" / "dispatch.yml").read_text()
    before = status_of(world)
    r = world.run("budget", "--today", "25000000")
    assert r.rc == 0, r
    assert re.search(r"^budget for 2026-11-10: 25,?000,?000 tokens \(the policy says 20,?000,?000; back to it at midnight\)$", r.out, re.M)
    assert "Undo: cplat dispatch budget --reset-today" in r.lines
    assert world.state()["steering"]["budget_today"]["tokens"] == 25_000_000
    assert world.state()["steering"]["budget_today"]["day"] == "2026-11-10"
    assert (world.repo / ".platform" / "dispatch.yml").read_text() == text and status_of(world) == before
    assert "raised for today" in world.run("budget").out
    back = world.run("budget", "--reset-today")
    assert back.rc == 0 and re.search(r"^budget for 2026-11-10: back to 20,?000,?000$", back.out, re.M), back
    assert not world.state()["steering"].get("budget_today")


@pytest.mark.parametrize("value", ["20000000", "100", "many"])
def test_a_raise_must_be_above_the_limit_of_today(world, value):  # AC-193.5
    world.policy()
    r = world.run("budget", "--today", value)
    assert r.rc == 2 and "ERROR:" in r.err
    assert not world.state().get("steering", {}).get("budget_today")


def test_a_raise_needs_a_budget_in_the_policy(world):  # AC-193.5
    world.policy(budget=None)
    assert world.run("budget", "--today", "25000000").rc == 2


def test_a_raise_of_an_earlier_day_is_ignored(world):  # AC-193.5
    world.policy()
    world.write_state(steering={"paused": None, "slots": None, "pinned": [], "skipped": {}, "holds": {},
                                "budget_today": {"day": "2026-11-09", "tokens": 30_000_000, "at": "2026-11-09T10:00:00"}})
    r = world.run("budget")
    assert re.fullmatch(r"budget for 2026-11-10: 20,?000,?000 tokens", r.out.strip()), r


def test_a_raised_budget_lets_the_dispatcher_start_again(world):  # AC-193.5
    world.policy(slots=1)
    world.issue(1, title="issue 1", labels=["triaged", "bug"])
    world.behave(mode="wait")
    world.write_state(ledger={"2026-11-10": {"units": {"old.1": 20_000_000}, "agent": 0}})
    r = world.run("start", "--once")
    assert r.rc == 0 and world.calls() == [], r
    assert world.run("budget", "--today", "25000000").rc == 0
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_resume_of_an_item_lifts_its_needs_decision_label(world):  # AC-193.5  (A7)
    world.policy()
    world.issue(1, title="issue 1", labels=["triaged", "bug", "needs-decision"])
    r = world.run("resume", "issue-1")
    assert r.rc == 0 and "label removed: #1" in r.lines, r
    assert "needs-decision" not in world.labels_of(1)
