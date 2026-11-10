"""Spec 167 acceptance tests: readiness, the premise check and the order (AC-167.3, AC-167.4, AC-167.5).

Contract: design.md "Readiness", "Premise check", "Order", "Steering". The verdicts are read from `cplat dispatch plan --json`
(`verdict`, `reason`, `detail`, `premise`), the writes from the fake `gh` log, the stale close from `start --once`.
The premise answer of the fake claude is the JSON `{"verdict": "holds"|"resolved", "evidence": <sha>, "why": ...}` (a pinned guess).
"""
import re

import runs

from dispatch_world import SLUG, git, world  # noqa: F401  (fixture)

CLAIM = "<!-- cplat-claim -->\nClaimed for branch `{b}` ({who})."


# ---------------- AC-167.3: the held reasons ----------------

def test_in_progress_without_a_dispatcher_claim_is_held_claimed_ac_167_3(world):  # AC-167.3
    world.issue(1, labels=["triaged", "in-progress"])
    c = world.cand(world.plan(), "#1")
    assert c["verdict"] == "held" and c["reason"] == "claimed"


def test_a_claim_for_another_branch_is_held_claimed_ac_167_3(world):  # AC-167.3
    world.issue(1, labels=["triaged", "in-progress"], comments=[CLAIM.format(b="feature/074-ci", who="cplat component ship")])
    c = world.cand(world.plan(), "#1")
    assert c["verdict"] == "held" and c["reason"] == "claimed" and "feature/074-ci" in c["detail"]


def test_an_open_run_record_serving_the_spec_holds_it_claimed_ac_167_3(world):  # AC-167.3
    world.policy(sources=["specs"])
    sid = world.spec(7, "price-alerts")
    runs.start("ship", repo=SLUG, spec=sid)                       # a manual session's open run record
    [c] = world.plan()["candidates"]
    assert c["verdict"] == "held" and c["reason"] == "claimed"


def test_blocked_by_an_open_issue_is_held_and_a_closed_one_is_not_ac_167_3(world):  # AC-167.3
    world.issue(9, labels=["bug"])                                 # open, not triaged: no candidate
    world.issue(10, labels=["bug"], state="CLOSED")
    world.issue(1, body="This is blocked by #9.")
    world.issue(2, body="Depends On #9 and more")
    world.issue(3, body="blocked by #10")
    doc = world.plan()
    for n in ("#1", "#2"):
        assert world.cand(doc, n)["verdict"] == "held" and world.cand(doc, n)["reason"] == "blocked"
    assert world.cand(doc, "#3")["verdict"] == "ready"


def test_an_issue_an_open_pr_closes_is_held_duplicate_ac_167_3(world):  # AC-167.3
    world.issue(1)
    world.issue(2)
    world.pr(40, "fix/by-hand", closes=[1], body="Closes #1")
    doc = world.plan()
    c = world.cand(doc, "#1")
    assert c["verdict"] == "held" and c["reason"] == "duplicate" and "40" in c["detail"]
    assert world.cand(doc, "#2")["verdict"] == "ready"


def test_a_spec_that_tracks_the_issue_runs_and_the_issue_is_held_duplicate_ac_167_3(world):  # AC-167.3
    world.policy(sources=["issues", "specs"], slots=2)
    world.issue(42, labels=["triaged", "tracked"])
    sid = world.spec(7, "price-alerts", tracks=(42,))
    doc = world.plan()
    [spec_c] = [c for c in doc["candidates"] if c["kind"] == "ship"]
    assert spec_c["verdict"] == "ready" and sid.startswith("007")
    assert not [c for c in doc["candidates"] if c["item"] == "#42" and c["verdict"] == "ready"]


def test_a_tracked_issue_without_an_approved_spec_is_held_needs_spec_ac_167_3(world):  # AC-167.3
    world.issue(1, labels=["triaged", "tracked", "enhancement"])
    c = world.cand(world.plan(), "#1")
    assert c["verdict"] == "held" and c["reason"] == "needs-spec"


def test_only_triaged_issues_without_needs_decision_wontfix_or_excluded_labels_are_candidates_ac_167_3(world):  # AC-167.3
    world.policy(ready={"labels": ["bug"], "exclude_labels": ["blocked"]})
    world.issue(1, labels=["triaged", "bug"])
    world.issue(2, labels=["bug"])                                 # not triaged
    world.issue(3, labels=["triaged", "bug", "needs-decision"])
    world.issue(4, labels=["triaged", "bug", "wontfix"])
    world.issue(5, labels=["triaged", "bug", "blocked"])
    world.issue(6, labels=["triaged"])                             # lacks `bug`
    assert world.order(world.plan()) == ["#1"]


def test_a_held_candidate_gets_no_label_comment_or_claim_ac_167_3(world):  # AC-167.3
    world.policy(slots=5)
    world.issue(1, labels=["triaged", "in-progress"])
    world.issue(2, body="blocked by #1")
    world.issue(3, labels=["triaged", "tracked"])
    world.issue(4)
    world.pr(40, "fix/by-hand", closes=[4])
    world.issue(5)                                                  # the only ready one
    before = {n: (list(world.labels_of(n)), world.comments_of(n)) for n in (1, 2, 3, 4)}
    assert world.run("start", "--once").rc == 0
    assert {n: (world.labels_of(n), world.comments_of(n)) for n in (1, 2, 3, 4)} == before
    assert [c["unit"] for c in world.calls()] == ["issue-5.1"]
    assert not [a for a in world.gh_writes() if a[2:3] in (["1"], ["2"], ["3"], ["4"])]


# ---------------- AC-167.4: the premise check ----------------

def _stale_world(world, slots=1):
    world.policy(slots=slots)
    sha = world.commit("price.txt", "rounded\n", "fix: round the price (#1)")
    world.issue(1, title="stale thing", created="2026-11-01T08:00:00Z")
    world.issue(2, title="live thing", created="2026-11-02T08:00:00Z")
    world.answer("stale thing", verdict="resolved", evidence=sha, why="the price is rounded since this commit")
    return sha


def test_start_comments_labels_and_closes_a_stale_issue_and_starts_no_unit_for_it_ac_167_4(world):  # AC-167.4
    sha = _stale_world(world)
    r = world.run("start", "--once")
    assert r.rc == 0, r
    issue = world.issue_of(1)
    assert issue["state"] == "CLOSED" and "stale-premise" in issue["labels"] and "in-progress" not in issue["labels"]
    [note] = [c for c in world.comments_of(1) if "<!-- cplat-dispatch-stale -->" in c]
    assert sha[:7] in note and "cplat dispatch" in note
    assert not [c for c in world.calls() if c["unit"].startswith("issue-1.")]
    assert "closed #1 as stale" in r.out


def test_plan_only_shows_held_stale_and_closes_nothing_ac_167_4(world):  # AC-167.4
    sha = _stale_world(world)
    before = world.fingerprint()
    doc = world.plan()
    c = world.cand(doc, "#1")
    assert c["verdict"] == "held" and c["reason"] == "stale" and sha[:7] in (c["detail"] or "") and c["premise"] == "resolved"
    assert "held: stale" in world.run("plan").out
    assert world.fingerprint() == before and world.gh_writes() == []


def test_an_issue_reopened_after_a_stale_close_is_never_closed_as_stale_again_ac_167_4(world):  # AC-167.4
    _stale_world(world)
    world.run("start", "--once")
    assert world.issue_of(1)["state"] == "CLOSED"
    world.edit_gh(lambda d: d["issues"]["1"].update(state="OPEN"))
    asked = len([c for c in world.claude_calls() if "stale thing" in c["prompt"]])
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert world.issue_of(1)["state"] == "OPEN"
    assert len([c for c in world.comments_of(1) if "<!-- cplat-dispatch-stale -->" in c]) == 1
    assert len([c for c in world.claude_calls() if "stale thing" in c["prompt"]]) == asked


def test_evidence_that_is_no_commit_on_main_counts_as_the_premise_holding_ac_167_4(world):  # AC-167.4
    world.policy(slots=1)
    world.issue(1, title="stale thing")
    world.answer("stale thing", verdict="resolved", evidence="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", why="trust me")
    assert world.run("start", "--once").rc == 0
    assert world.issue_of(1)["state"] == "OPEN"
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_a_failed_premise_call_counts_as_the_premise_holding_ac_167_4(world):  # AC-167.4
    world.policy(slots=1)
    world.issue(1, title="stale thing")
    world.claude(fail=True)
    assert world.run("start", "--once").rc == 0
    assert world.issue_of(1)["state"] == "OPEN"
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_only_issues_about_to_take_a_slot_get_the_premise_check_ac_167_4(world):  # AC-167.4
    world.policy(slots=1)
    for n in (1, 2, 3):
        world.issue(n, created=f"2026-11-0{n}T08:00:00Z")
    doc = world.plan()
    assert [c["premise"] for c in doc["candidates"]] == ["holds", "unchecked", "unchecked"]
    assert len(world.claude_calls()) == 1
    assert "premise unchecked" in world.run("plan").out


# ---------------- AC-167.5: the order, prioritize, skip ----------------

def _numbers(world):
    return [re.search(r"\d{3}", c["item"]).group() for c in world.plan()["candidates"]]


def _five(world):
    world.issue(1, title="plain", labels=["triaged"], created="2026-11-01T08:00:00Z")
    world.issue(2, title="p1", labels=["triaged", "p1"], created="2026-11-02T08:00:00Z")
    world.issue(3, title="bug", labels=["triaged", "bug"], created="2026-11-03T08:00:00Z")
    world.issue(4, title="bug p1", labels=["triaged", "bug", "p1"], created="2026-11-04T08:00:00Z")
    world.issue(5, title="old bug", labels=["triaged", "bug"], created="2026-10-31T08:00:00Z")


def test_the_default_order_is_bug_p1_spec_order_oldest_each_rule_only_breaking_a_tie_ac_167_5(world):  # AC-167.5
    world.policy(slots=5)
    _five(world)
    assert world.order(world.plan()) == ["#4", "#5", "#3", "#2", "#1"]


def test_the_policy_priority_rules_apply_in_the_order_given_ac_167_5(world):  # AC-167.5
    world.policy(slots=5, priority=["label:p1", "oldest"])
    _five(world)
    assert world.order(world.plan()) == ["#2", "#4", "#5", "#1", "#3"]
    world.policy(slots=5, priority=["oldest"])
    assert world.order(world.plan()) == ["#5", "#1", "#2", "#3", "#4"]


def test_a_spec_matches_label_p1_through_its_priority_and_specs_go_by_number_ac_167_5(world):  # AC-167.5
    world.policy(sources=["specs"], slots=2)
    world.spec(7, "price-alerts", priority="P2")
    world.spec(8, "refunds", priority="P1")
    assert _numbers(world) == ["008", "007"]
    world.policy(sources=["specs"], slots=2, priority=["spec-order"])
    assert _numbers(world) == ["007", "008"]


def test_prioritize_puts_the_item_first_until_it_starts_and_survives_a_restart_ac_167_5(world):  # AC-167.5
    world.policy(slots=1)
    _five(world)
    r = world.run("prioritize", "#1")
    assert r.rc == 0, r
    assert world.order(world.plan())[0] == "#1"
    world.restart()
    assert world.order(world.plan())[0] == "#1"
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]
    assert "#1" not in str(world.state().get("steering", {}).get("pinned")) and "issue-1" not in str(world.state()["steering"]["pinned"])


def test_skip_holds_the_item_with_its_reason_until_resume_and_survives_a_restart_ac_167_5(world):  # AC-167.5
    world.policy(slots=2)
    _five(world)
    r = world.run("skip", "#4", "--reason", "waiting for infra")
    assert r.rc == 0, r
    c = world.cand(world.plan(), "#4")
    assert c["verdict"] == "held" and c["reason"] == "skipped" and c["detail"] == "waiting for infra"
    assert "held: skipped: waiting for infra" in world.run("plan").out
    world.restart()
    assert world.cand(world.plan(), "#4")["reason"] == "skipped"
    world.run("start", "--once")
    assert "issue-4.1" not in [c["unit"] for c in world.calls()]
    assert world.labels_of(4) == ["triaged", "bug", "p1"]
    r = world.run("resume", "#4")
    assert r.rc == 0, r
    assert world.cand(world.plan(), "#4")["verdict"] == "ready"


def test_skip_and_prioritize_write_nothing_to_github_ac_167_5(world):  # AC-167.5
    world.policy(slots=1)
    world.issue(1)
    assert world.run("prioritize", "#1").rc == 0
    assert world.run("skip", "#1", "--reason", "later").rc == 0
    assert world.gh_writes() == []
    assert git(world.repo, "worktree", "list").count("\n") == 0
