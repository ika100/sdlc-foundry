"""Spec 196 acceptance tests: the dispatcher's documented default rules start with `label:p0` (AC-196.8, AC-196.9; they replace
AC-176.10 and AC-167.5). Driven through `cplat dispatch plan --json|prioritize|skip|resume` in the world of spec 167."""
import re
from pathlib import Path

from dispatch_world import world  # noqa: F401  (fixture)

DEFAULT = ["label:p0", "label:bug", "label:p1", "spec-order", "oldest"]


def _items(world):
    """#1 plain, #2 p1, #3 bug, #4 p0 (newest, no bug label), #5 old bug."""
    world.issue(1, title="plain", labels=["triaged"], created="2026-11-01T08:00:00Z")
    world.issue(2, title="p1", labels=["triaged", "p1"], created="2026-11-02T08:00:00Z")
    world.issue(3, title="bug", labels=["triaged", "bug"], created="2026-11-03T08:00:00Z")
    world.issue(4, title="p0", labels=["triaged", "p0"], created="2026-11-04T08:00:00Z")
    world.issue(5, title="old bug", labels=["triaged", "bug"], created="2026-10-31T08:00:00Z")


# ---------------- AC-196.8: the labels triage sets order the backlog ----------------

def test_the_documented_default_rules_name_label_p0_first_ac_196_8():  # AC-196.8
    docs = (Path(__file__).resolve().parents[2] / "docs" / "dispatch.md").read_text()
    assert "[label:p0, label:bug, label:p1, spec-order, oldest]" in docs


def test_the_p1_bug_comes_before_the_older_p2_bug_under_the_default_rules_ac_196_8(world):  # AC-196.8
    world.policy(slots=5)
    world.issue(1, title="older p2", labels=["triaged", "bug", "p2"], created="2026-11-01T08:00:00Z")
    world.issue(2, title="newer p1", labels=["triaged", "bug", "p1"], created="2026-11-02T08:00:00Z")
    assert world.order(world.plan()) == ["#2", "#1"]


def test_a_spec_at_p1_comes_before_an_older_numbered_spec_at_p2_ac_196_8(world):  # AC-196.8
    world.policy(sources=["specs"], slots=2)
    world.spec(7, "older", priority="P2")
    world.spec(8, "triaged", priority="P1")
    assert [re.search(r"\d{3}", c["item"]).group() for c in world.plan()["candidates"]] == ["008", "007"]


# ---------------- AC-196.9: label:p0 first, the other rules only break ties ----------------

def test_the_default_priority_rules_are_p0_bug_p1_spec_order_oldest_ac_196_9():  # AC-196.9
    import dispatch_policy
    assert dispatch_policy.DEFAULTS["priority"] == DEFAULT


def test_a_ready_p0_issue_comes_before_an_older_bug_and_the_p1_and_p2_items_ac_196_9(world):  # AC-196.9
    world.policy(slots=5)
    _items(world)
    assert world.order(world.plan()) == ["#4", "#5", "#3", "#2", "#1"]


def test_a_spec_at_p0_comes_before_an_older_bug_issue_ac_196_9(world):  # AC-196.9
    world.policy(sources=["issues", "specs"], slots=5)
    world.issue(1, title="old bug", labels=["triaged", "bug"], created="2026-10-01T08:00:00Z")
    world.issue(2, title="p1", labels=["triaged", "p1"], created="2026-10-02T08:00:00Z")
    world.spec(9, "urgent", priority="P0")
    world.spec(7, "normal", priority="P1")
    first, second = world.plan()["candidates"][:2]
    assert first["kind"] == "ship" and "009" in first["item"] and second["item"] == "#1"


def test_a_repo_that_sets_its_own_priority_rules_is_ordered_by_them_unchanged_ac_196_9(world):  # AC-196.9
    world.policy(slots=5, priority=["label:bug", "oldest"])
    _items(world)
    assert world.order(world.plan()) == ["#5", "#3", "#1", "#2", "#4"]


def test_prioritize_puts_the_item_first_until_it_starts_and_survives_a_restart_ac_196_9(world):  # AC-196.9
    world.policy(slots=1)
    _items(world)
    assert world.order(world.plan())[0] == "#4"
    assert world.run("prioritize", "#1").rc == 0
    assert world.order(world.plan())[0] == "#1"
    world.restart()
    assert world.order(world.plan())[0] == "#1"
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_skip_holds_the_item_with_its_reason_until_resume_and_survives_a_restart_ac_196_9(world):  # AC-196.9
    world.policy(slots=5)
    _items(world)
    assert world.order(world.plan())[0] == "#4"
    assert world.run("skip", "#4", "--reason", "waiting for infra").rc == 0
    c = world.cand(world.plan(), "#4")
    assert c["verdict"] == "held" and c["reason"] == "skipped" and c["detail"] == "waiting for infra"
    assert "held: skipped: waiting for infra" in world.run("plan").out
    world.restart()
    assert world.cand(world.plan(), "#4")["reason"] == "skipped"
    assert world.run("resume", "#4").rc == 0
    assert world.order(world.plan())[0] == "#4"
