"""Spec 210 acceptance tests: the filler queue before the weekly reset (AC-210.9).

Contract: design.md "Filler" (`dispatch_filler`, `state.filler`, candidates `task:<name>` and `retro#<N>.<rank>`), "Units" (kinds `task` and
`draft`, the start line), "A retro draft is never self-approved", "`plan --json`" (`filler`, `held: filler only`, `slot <n> (filler)`).
The filler window is the last 24 hours before the `seven_day` reset of the fixture reading. The units are the fake headless
(`fix` and `draft`) or a real command in its own worktree (`task`); the retro issue is in the fake `gh`.
"""
import re

import pytest

import dispatch_world
from dispatch_world import world  # noqa: F401  (fixture)
from support_210 import H, fresh, issues
from waiting import fake_prelude

TASK = {"name": "bench", "command": "touch ran.marker"}


def _window(world, week=60.0, five=10.0, remaining=10 * H):
    fresh(world, five=five, week=week, week_remaining=remaining)


def _policy(world, slots=2, **plan):
    return world.policy(slots=slots, sources=["issues", "specs"], budget={"mode": "plan", "plan": plan} if plan else {"mode": "plan"})


def _retro(world, n=90, items=(("Alpha thing", "P1", "add the alpha thing"), ("Beta thing", "P2", "add the beta thing"),
                               ("Gamma thing", "P2", "add the gamma thing"), ("Delta thing", "P2", "add the delta thing"))):
    lines = [f"{i}. **{title}** ({prio})\n   `/component:spec {req}`\n" for i, (title, prio, req) in enumerate(items, 1)]
    body = "## Weekly retro\n\nThe week in short.\n\n## Proposed specs\n\n" + "\n".join(lines) + "\n## Other\n\nNothing.\n"
    world.issue(n, title="Weekly retro 2026-W45", labels=["retro"], body=body, created="2026-11-09T08:00:00Z")


def _drafts(world):
    return [c for c in world.calls() if any("/component:spec" in a for a in c["argv"])]


def _text_of(call):
    return next(a for a in call["argv"] if "/component:spec" in a)


def _cycles(world, n):
    for _ in range(n):
        assert world.run("start", "--once").rc == 0
        for unit in {c["unit"] for c in world.calls()}:
            world.wait_ended(unit)


def _markers(world):
    return list((world.dispatch_dir() / "worktrees").glob("*/ran.marker"))


# ---------------- outside the filler window ----------------

def test_a_filler_only_candidate_outside_the_filler_window_is_held_ac_210_9(world):  # AC-210.9
    _policy(world)
    world.issue(1, title="nice to have", labels=["triaged", "enhancement"])
    world.issue(2, title="a plain bug", labels=["triaged", "bug"], created="2026-11-02T08:00:00Z")
    world.spec(7, "later", priority="P2", plan="single")
    fresh(world, five=10, week=30, week_remaining=4 * 24 * H)
    doc = world.plan()
    assert doc["plan"]["filler"] is False
    held = world.cand(doc, "#1")
    assert held["verdict"] == "held" and held["reason"] == "filler only" and held["detail"] is None and held["slot"] is None
    [spec] = [c for c in doc["candidates"] if c["kind"] == "ship"]
    assert spec["verdict"] == "held" and spec["reason"] == "filler only"
    assert world.cand(doc, "#2")["verdict"] == "ready"
    text = world.run("plan").out
    assert re.search(r"#1\s+fix\s+held: filler only(\s|$)", text), text
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-2.1"]


def test_filler_tasks_wait_for_the_filler_window_ac_210_9(world):  # AC-210.9
    _policy(world, filler_tasks=[TASK])
    fresh(world, five=10, week=30, week_remaining=4 * 24 * H)
    assert world.plan()["plan"]["filler"] is False
    assert world.run("start", "--once").rc == 0
    assert world.calls() == [] and _markers(world) == []
    assert "task:bench" not in world.order(world.plan())


# ---------------- inside the filler window ----------------

def test_inside_the_filler_window_a_filler_only_candidate_takes_a_free_slot_ac_210_9(world):  # AC-210.9
    _policy(world)
    world.issue(1, title="nice to have", labels=["triaged", "enhancement"])
    world.behave(mode="wait")
    _window(world)
    doc = world.plan()
    assert doc["plan"]["filler"] is True
    c = world.cand(doc, "#1")
    assert c["verdict"] == "ready" and c["filler"] is True and c["slot"] == 1
    text = world.run("plan").out
    assert "filler: true" in text.splitlines() and re.search(r"#1\s+fix\s+ready\s+single\s+slot 1 \(filler\)", text), text
    r = world.run("start", "--once")
    assert r.rc == 0 and re.search(r"^started issue-1\.1 \(fix, single, slot 1\) \(filler\)", r.out, re.M), r.out
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_regular_candidates_come_first_and_filler_waits_while_one_is_ready_ac_210_9(world):  # AC-210.9
    _policy(world, slots=2, filler_tasks=[TASK])
    world.issue(1, title="a plain bug", labels=["triaged", "bug"])
    world.issue(2, title="nice to have", labels=["triaged", "enhancement"], created="2026-11-02T08:00:00Z")
    world.behave(mode="wait")
    _window(world)
    r = world.run("start", "--once")
    assert r.rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"] and "(filler)" not in r.out
    assert _markers(world) == []
    assert world.plan()["plan"]["filler"] is True


def test_no_filler_starts_at_or_above_the_weekly_target_ac_210_9(world):  # AC-210.9
    _policy(world, filler_tasks=[TASK])
    world.issue(1, title="nice to have", labels=["triaged", "enhancement"])
    _window(world, week=93)
    doc = world.plan()
    assert doc["plan"]["filler"] is False and doc["plan"]["hold"] == "weekly target reached"
    assert world.run("start", "--once").rc == 0
    assert world.calls() == [] and _markers(world) == []


def test_no_filler_starts_while_the_five_hour_window_holds_ac_210_9(world):  # AC-210.9
    _policy(world, filler_tasks=[TASK])
    world.issue(1, title="nice to have", labels=["triaged", "enhancement"])
    _window(world, five=85)
    assert world.plan()["plan"]["filler"] is False
    assert world.run("start", "--once").rc == 0 and world.calls() == [] and _markers(world) == []


def test_there_is_no_filler_queue_in_mode_cost_ac_210_9(world):  # AC-210.9
    world.policy(slots=1, budget={"usd_per_day": 5})
    world.issue(1, title="nice to have", labels=["triaged", "enhancement"])
    world.behave(mode="wait")
    doc = world.plan()
    assert doc["plan"] is None and world.cand(doc, "#1")["verdict"] == "ready"
    r = world.run("start", "--once")
    assert "(filler)" not in r.out and [c["unit"] for c in world.calls()] == ["issue-1.1"]


# ---------------- filler tasks ----------------

def test_a_filler_task_runs_its_command_in_its_own_worktree_once_per_window_ac_210_9(world):  # AC-210.9
    _policy(world, filler_tasks=[TASK])
    _window(world)
    doc = world.plan()
    [c] = [c for c in doc["candidates"] if c["item"] == "task:bench"]
    assert c["kind"] == "task" and c["filler"] is True and c["verdict"] == "ready"
    r = world.run("start", "--once")
    assert r.rc == 0 and re.search(r"^started task-bench\.1 \(task, single, slot 1\) \(filler\): touch ran\.marker", r.out, re.M), r.out
    assert world.wait_until(lambda: len(_markers(world)) == 1, timeout=10)
    [marker] = _markers(world)
    assert marker.parent != world.repo and "bench" in marker.parent.name                          # its own worktree
    assert not (world.repo / "ran.marker").exists()
    assert "bench" in world.state()["filler"]["tasks"]
    for _ in range(4):                                                                          # it ran: not a second time in this window
        out = world.run("start", "--once").out
        assert "started task-bench" not in out and "restarted task-bench" not in out
    assert "task:bench" not in [c["item"] for c in world.plan()["candidates"]]
    assert len(_markers(world)) == 1 and world.calls() == []                                    # no agent session: it is no headless unit


def test_a_filler_task_that_fails_is_escalated_and_labels_no_issue_ac_210_9(world):  # AC-210.9
    _policy(world, filler_tasks=[{"name": "broken", "command": "exit 3"}])
    world.issue(5, title="untouched", labels=["wontfix"])                      # not triaged: no candidate
    _window(world)
    assert world.run("start", "--once").rc == 0

    def escalated():
        world.run("start", "--once")
        return world.run("status", "--json").json()["escalated"]

    assert world.wait_until(escalated, timeout=10)
    [e] = escalated()
    assert e["unit"].startswith("task-broken") and e["kind"] == "task"
    assert world.labels_of(5) == ["wontfix"] and not [a for a in world.gh_writes() if a[:2] == ["issue", "edit"]]


# ---------------- spec drafts from the weekly retro ----------------

def test_a_draft_unit_runs_the_spec_command_for_the_first_unanswered_proposal_ac_210_9(world):  # AC-210.9
    _policy(world)
    _retro(world)
    world.behave(mode="wait")
    _window(world)
    doc = world.plan()
    c = world.cand(doc, "retro#90.1")
    assert c["kind"] == "draft" and c["filler"] is True and c["verdict"] == "ready"
    r = world.run("start", "--once")
    assert re.search(r"^started retro-90-1\.1 \(draft, single, slot 1\) \(filler\): /component:spec add the alpha thing #90", r.out, re.M), r.out
    [call] = world.calls()
    assert _text_of(call) == "/component:spec add the alpha thing #90" and call["argv"][call["argv"].index("--repo") + 1] == str(call["cwd"])
    assert world.issue_of(90)["state"] == "OPEN"


def test_at_most_3_drafts_start_in_one_weekly_window_and_the_issue_stays_open_ac_210_9(world):  # AC-210.9
    _policy(world, slots=3)
    _retro(world)
    world.behave(mode="now", then="done")
    _window(world)
    _cycles(world, 8)
    texts = [_text_of(c) for c in _drafts(world)]
    assert texts == ["/component:spec add the alpha thing #90", "/component:spec add the beta thing #90",
                     "/component:spec add the gamma thing #90"], texts
    assert set(world.state()["filler"]["drafted"]) == {"retro-90-1", "retro-90-2", "retro-90-3"}
    issue = world.issue_of(90)
    assert issue["state"] == "OPEN" and issue["labels"] == ["retro"]
    assert "retro#90.4" not in world.order(world.plan())


def test_a_draft_that_ended_without_a_pull_request_is_escalated_and_labels_no_issue_ac_210_9(world):  # AC-210.9
    _policy(world, slots=1)
    _retro(world)
    world.issue(5, title="a note", labels=["wontfix"])                          # not triaged: no candidate
    world.behave(mode="now", then="done")
    _window(world)
    _cycles(world, 3)
    doc = world.run("status", "--json").json()
    assert [e["unit"] for e in doc["escalated"] if e["unit"].startswith("retro-90-1")]
    assert world.labels_of(90) == ["retro"] and world.labels_of(5) == ["wontfix"]


def _drafting_headless(world):
    """The fake headless as `/component:spec` ends: the unit's worktree gets a `feature/...` branch, the retro issue is claimed
    for it (what `cplat spec new --tracks 90` does) and a pull request is opened for the branch."""
    old = 'end("done", "pull request opened", "done")'
    new = '''if "/component:spec" in text:
    branch = "feature/spec-" + unit
    subprocess.run(["git", "checkout", "-q", "-b", branch], capture_output=True, text=True)
    subprocess.run(["gh", "issue", "edit", "90", "--add-label", "in-progress"], capture_output=True, text=True)
    subprocess.run(["gh", "issue", "comment", "90", "--body", "<!-- cplat-claim -->\\nClaimed for branch `" + branch + "`."],
                   capture_output=True, text=True)
    subprocess.run(["gh", "pr", "create", "--head", branch, "--title", "spec: alpha thing", "--body", "Tracks #90"],
                   capture_output=True, text=True)
end("done", "pull request opened", "done")'''
    text = dispatch_world.FAKE_HEADLESS.replace(old, new)
    assert text != dispatch_world.FAKE_HEADLESS
    exe = world.bin / "fake-headless-draft"
    exe.write_text(text % {"py": dispatch_world.sys.executable, "pre": fake_prelude()})
    exe.chmod(0o755)
    world.mp.setenv("CPLAT_DISPATCH_HEADLESS", str(exe))


def test_a_draft_with_an_open_pull_request_ends_done_and_the_pr_is_left_alone_ac_210_9(world):  # AC-210.9
    _drafting_headless(world)
    world.policy(slots=1, sources=["issues", "specs"], gates={"approve_specs": "self"}, budget={"mode": "plan"})
    _retro(world)
    world.behave(mode="wait")
    world.behave("retro-90-1.1", mode="now", then="done")
    _window(world)
    assert world.run("start", "--once").rc == 0
    world.wait_ended("retro-90-1.1")

    def finished():
        world.run("start", "--once")
        return [h for h in world.state().get("history", []) if h["unit"] == "retro-90-1.1"]

    assert world.wait_until(finished, timeout=15)
    [entry] = finished()
    assert entry["outcome"] == "done" and "/pull/" in str(entry["pr"]), entry
    [pr] = [p for p in world._gh()["prs"].values() if p["headRefName"] == "feature/spec-retro-90-1.1"]
    assert pr["state"] == "OPEN"                                                              # neither merged nor closed
    assert not [a for a in world.gh_calls() if a[:2] in (["pr", "merge"], ["pr", "review"], ["pr", "ready"], ["pr", "close"])]
    issue = world.issue_of(90)
    assert issue["state"] == "OPEN" and "in-progress" not in issue["labels"]                  # the claim is released, the issue stays open
    comments = world.comments_of(90)
    assert any(c.startswith("<!-- cplat-claim -->") for c in comments)
    assert any(c.startswith("<!-- cplat-release -->") and "retro draft retro-90-1.1 ended (cplat dispatch)" in c for c in comments), comments
    assert "retro-90-1" in world.state()["filler"]["drafted"]


def test_a_proposal_answered_by_an_open_pull_request_is_skipped_ac_210_9(world):  # AC-210.9
    _policy(world)
    _retro(world)
    world.pr(201, "feature/030-alpha")
    world.edit_gh(lambda d: d["prs"]["201"].__setitem__("title", "feat: Add the ALPHA thing for shop"))
    world.behave(mode="wait")
    _window(world)
    assert "retro#90.1" not in world.order(world.plan())
    assert world.run("start", "--once").rc == 0
    [call] = world.calls()
    assert _text_of(call) == "/component:spec add the beta thing #90"


def test_a_proposal_answered_by_a_spec_on_main_that_tracks_the_issue_is_skipped_ac_210_9(world):  # AC-210.9
    _policy(world)
    _retro(world, items=(("Price alerts", "P1", "add price alerts"), ("Beta thing", "P2", "add the beta thing")))
    world.spec(30, "price-alerts", status="done", plan=None, tracks=(90,))        # the title of the fixture spec is "Price alerts"
    world.behave(mode="wait")
    _window(world)
    assert "retro#90.1" not in world.order(world.plan())
    assert world.run("start", "--once").rc == 0
    [call] = world.calls()
    assert _text_of(call) == "/component:spec add the beta thing #90"


def test_no_draft_starts_with_filler_drafts_off_ac_210_9(world):  # AC-210.9
    _policy(world, filler_drafts=False)
    _retro(world)
    _window(world)
    assert not [i for i in world.order(world.plan()) if i.startswith("retro#")]
    assert world.run("start", "--once").rc == 0 and world.calls() == []


def test_the_retro_issue_is_not_read_outside_the_filler_window_ac_210_9(world):  # AC-210.9
    _policy(world)
    _retro(world)
    fresh(world, five=10, week=30, week_remaining=4 * 24 * H)
    assert world.run("start", "--once").rc == 0 and world.calls() == []
    assert not [a for a in world.gh_calls() if a[:2] == ["issue", "list"] and "retro" in a]


def test_a_retro_issue_without_a_proposals_section_offers_no_draft_ac_210_9(world):  # AC-210.9
    _policy(world)
    _window(world)
    world.issue(90, title="Weekly retro 2026-W45", labels=["retro"], body="## Weekly retro\n\nNothing to propose.\n", created="2026-11-09T08:00:00Z")
    r = world.run("start", "--once")
    assert r.rc == 0 and world.calls() == []
    assert any(a[:2] == ["issue", "list"] and "retro" in a for a in world.gh_calls())          # it was read, in the window


# ---------------- the order and the approval ----------------

def test_filler_starts_in_the_order_filler_only_then_tasks_then_drafts_ac_210_9(world):  # AC-210.9
    _policy(world, slots=3, filler_tasks=[TASK])
    world.issue(1, title="nice to have", labels=["triaged", "enhancement"])
    _retro(world)
    world.behave(mode="wait")
    _window(world)
    r = world.run("start", "--once")
    assert r.rc == 0, r
    starts = [ln.split()[1] for ln in r.out.splitlines() if ln.startswith("started ")]
    assert [s.split(".")[0] for s in starts] == ["issue-1", "task-bench", "retro-90-1"], r.out
    assert all("(filler)" in ln for ln in r.out.splitlines() if ln.startswith("started "))


def test_a_retro_draft_is_never_approved_even_with_self_approval_ac_210_9(world):  # AC-210.9
    world.policy(slots=2, sources=["issues", "specs"], gates={"approve_specs": "self"}, budget={"mode": "plan"})
    _retro(world, 90)
    sid = world.spec(9, "alpha-thing", status="draft", plan=None, tracks=(90,))
    world.behave(mode="wait")
    fresh(world, five=10, week=30)
    [c] = [c for c in world.plan()["candidates"] if c["kind"] == "ship"]
    assert c["verdict"] == "held" and c["reason"] == "needs-approval", c
    r = world.run("start", "--once")
    assert r.rc == 0 and "approved" not in r.out and world.calls() == []
    assert "status: draft" in (world.repo / "docs" / "specs" / sid / "spec.md").read_text()


@pytest.mark.parametrize("hours_left", [10, 100])
def test_a_retro_draft_stays_unapproved_in_and_out_of_the_filler_window_ac_210_9(world, hours_left):  # AC-210.9
    world.policy(slots=2, sources=["issues", "specs"], gates={"approve_specs": "self"},
                 budget={"mode": "plan", "plan": {"filler_drafts": False}})          # no new draft unit: only the approval is under test
    _retro(world, 90)
    sid = world.spec(9, "alpha-thing", status="draft", plan=None, tracks=(90,))
    fresh(world, five=10, week=30, week_remaining=hours_left * H)
    assert world.run("start", "--once").rc == 0
    assert world.calls() == [] and not [a for a in world.gh_calls() if a[:2] == ["pr", "merge"]]
    assert "status: draft" in (world.repo / "docs" / "specs" / sid / "spec.md").read_text()


def test_regular_work_is_not_marked_as_filler_in_the_window_ac_210_9(world):  # AC-210.9
    _policy(world, slots=3)
    issues(world, 3)
    world.behave(mode="wait")
    _window(world)
    doc = world.plan()
    assert doc["plan"]["filler"] is True and all(c["filler"] is False for c in doc["candidates"])
    r = world.run("start", "--once")
    assert len(world.calls()) == 3 and "(filler)" not in r.out
