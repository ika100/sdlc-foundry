"""Spec 193 acceptance tests: `cplat dispatch answer` writes the person's answer into the spec (or the issue) and the item goes on
(AC-193.4), in the dispatcher world of spec 167 with a unit that ended escalated with cause `decision`."""
import re

from dispatch_world import git, world  # noqa: F401  (fixture)


def stopped_spec(world, reason="escalated: which currency?"):
    world.policy(sources=["specs", "issues"], slots=1)
    sid = world.spec(7, "price-alerts", tracks=(42,))
    world.issue(42, title="alerts", labels=["triaged"])
    world.behave("spec-007.1", mode="now", then="escalate", reason=reason)
    assert world.run("start", "--once").rc == 0
    world.wait_ended("spec-007.1")
    assert world.run("start", "--once").rc == 0
    return sid


def spec_in_worktree(world, sid):
    return world.worktree("spec-007") / "docs" / "specs" / sid / "spec.md"


def stopped_issue(world):
    world.policy(slots=1)
    world.issue(1, title="issue 1", labels=["triaged", "bug"])
    world.behave("issue-1.1", mode="now", then="escalate", reason="escalated: which format?")
    assert world.run("start", "--once").rc == 0
    world.wait_ended("issue-1.1")
    assert world.run("start", "--once").rc == 0


def test_the_answer_is_an_amendment_that_quotes_it_and_approves_when_only_the_asked_point_is_added(world):  # AC-193.4
    sid = stopped_spec(world)
    r = world.run("answer", "spec-7", "--answer", "EUR")
    assert r.rc == 0, r
    text = spec_in_worktree(world, sid).read_text()
    assert re.search(r'^- Decided by the user \(\d{4}-\d\d-\d\d, stop of spec-007\.1\): .*Answer: "EUR"$', text, re.M), text
    assert re.search(r'^- \d{4}-\d\d-\d\d answer to the stop of spec-007\.1 approved by the user: "EUR"$', text, re.M), text
    assert "status: approved" in text
    assert re.search(r"^answered: spec \d+; it goes on from \S+", r.out, re.M), r
    msg = git(world.worktree("spec-007"), "log", "-1", "--format=%B")
    assert msg.startswith(f"docs(spec): answer to the stop of {sid}") and "Signed-off-by:" in msg
    undo = [ln for ln in r.lines if ln.startswith("Undo: ")]
    assert len(undo) == 1 and f"git -C {world.worktree('spec-007')} revert --no-edit " in undo[0]


def test_the_item_goes_on_after_the_answer(world):  # AC-193.4
    stopped_spec(world)
    assert world.run("answer", "spec-7", "--answer", "EUR").rc == 0
    holds = world.state()["steering"]
    assert "spec-007" not in holds["holds"] and "spec-007" not in holds["skipped"]
    assert "needs-decision" not in world.labels_of(42)


def test_an_answer_that_changes_a_criterion_sends_the_spec_back_to_approval(world):  # AC-193.4
    sid = stopped_spec(world)
    path = spec_in_worktree(world, sid)
    path.write_text(path.read_text().replace("Given x1, when y, then z.", "Given x1, when y, then z in euro."))
    r = world.run("answer", "spec-7", "--answer", "Euro, and say so in AC-007.1")
    assert r.rc == 0, r
    assert re.search(r"^back to approval: spec \d+ \(PR #\d+\)$", r.out, re.M), r
    text = path.read_text()
    assert "status: draft" in text
    assert re.search(r'answer of the user changes criteria: "Euro, and say so in AC-007\.1"; back to approval', text)
    assert not re.search(r"answer to the stop of \S+ approved", text)
    assert ("pr", "create") in [tuple(a[:2]) for a in world.gh_writes()]


def test_an_answer_for_an_item_that_did_not_stop_is_refused(world):  # AC-193.4
    world.policy(sources=["specs"])
    world.spec(7, "price-alerts")
    r = world.run("answer", "spec-7", "--answer", "EUR")
    assert r.rc == 2 and "has no stop to answer" in r.err and r.err.startswith("ERROR: ")


def test_an_issue_item_gets_the_answer_as_a_comment_and_loses_the_label(world):  # AC-193.4
    stopped_issue(world)
    r = world.run("answer", "issue-1", "--answer", "ISO dates")
    assert r.rc == 0 and "answered: #1" in r.lines, r
    notes = [c for c in world.comments_of(1) if "<!-- cplat-dispatch-answer -->" in c]
    assert len(notes) == 1 and 'Answer of the person to the stop of issue-1.1: "ISO dates"' in notes[0]
    assert "needs-decision" not in world.labels_of(1)
    assert "issue-1" not in world.state()["steering"]["holds"]
