"""Spec 167 acceptance tests: running units (AC-167.6, AC-167.8, AC-167.9).

Contract: design.md "Units" (start, observe, escalate, restart, adopt), "Commands and output" (`start` action lines).
Seams: `$CPLAT_DISPATCH_HEADLESS` (the fake headless of `dispatch_world`: real detached processes that write the result file and
wait for `world.release`), the fake `gh` on PATH, `cplat.main(["dispatch", "start", "--once"])` as one cycle. A killed dispatcher
is `world.restart()` (every dispatcher module is imported afresh) plus a new `start --once`.
"""
import os
import re
import signal

import pytest

from dispatch_world import git, world  # noqa: F401  (fixture)
from waiting import wait_for


def _fix_issues(world, n=3, bugs=2):
    for i in range(1, n + 1):
        world.issue(i, title=f"issue {i}", labels=["triaged", "bug"] if i <= bugs else ["triaged"], created=f"2026-11-0{i}T08:00:00Z")


def _claims(world, n):
    return [c for c in world.comments_of(n) if "<!-- cplat-claim -->" in c]


def _until_started(world, unit, cycles=3):
    for _ in range(cycles):
        if world.calls_of(unit):
            return True
        assert world.run("start", "--once").rc == 0
    return bool(world.calls_of(unit))


def _kill(world, unit):
    pid = world.calls_of(unit)[-1]["pid"]
    os.kill(pid, signal.SIGKILL)
    world.wait_until(lambda: not world.alive(pid))
    return pid


# ---------------- AC-167.6: start units in slots ----------------

def test_two_slots_start_two_overlapping_fix_units_and_the_third_waits_for_a_free_slot_ac_167_6(world):  # AC-167.6
    world.policy(slots=2, budget={"tokens_per_day": 20_000_000, "per_unit": {"cost": 20}})
    _fix_issues(world)
    world.behave(mode="wait")
    world.behave("issue-1.1", then="escalate")
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert re.search(r"^started issue-1\.1 \(fix, single, slot 1\)", r.out, re.M) and re.search(r"^started issue-2\.1 \(fix, single, slot 2\)", r.out, re.M)
    calls = world.calls()
    assert [c["unit"] for c in calls] == ["issue-1.1", "issue-2.1"]
    for n, c in ((1, calls[0]), (2, calls[1])):
        wt = world.worktree(f"issue-{n}")
        assert c["cwd"] == str(wt) and f"/component:fix #{n}" in c["argv"]
        assert c["argv"][c["argv"].index("--repo") + 1] == str(wt)
        assert "--budget" in c["argv"] and any("cost=20" in a for a in c["argv"])
        assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == f"fix/issue-{n}"
        assert world.alive(c["pid"])                                               # both run at the same time
        [claim] = _claims(world, n)
        assert "cplat dispatch" in claim and f"fix/issue-{n}" in claim and "in-progress" in world.labels_of(n)
        unit, gitdir = world.unit_file(f"issue-{n}")
        assert unit["pid"] == c["pid"] and unit["unit"] == f"issue-{n}.1" and unit["branch"] == f"fix/issue-{n}"
        assert unit["kind"] == "fix" and unit["mode"] == "single" and os.path.isfile(unit["log"])
    assert world.calls_of("issue-3.1") == [] and _claims(world, 3) == [] and world.labels_of(3) == ["triaged"]
    assert world.run("start", "--once").rc == 0 and world.calls_of("issue-3.1") == []   # still both slots busy
    status = world.run("status", "--json").json()
    assert [u["unit"] for u in status["slots"]["units"]] == ["issue-1.1", "issue-2.1"]
    assert [q["item"] for q in status["queue"]] == ["#3"]
    world.release("issue-1.1")                                                      # the first unit ends (escalated)
    world.wait_ended("issue-1.1")
    assert _until_started(world, "issue-3.1")
    assert world.alive(calls[1]["pid"])


@pytest.mark.parametrize("plan,number,parallel", [("team", 7, "3"), ("single", 8, "1")])
def test_a_ship_unit_starts_headless_ship_with_parallel_3_in_team_mode_and_1_in_single_mode_ac_167_6(world, plan, number, parallel):  # AC-167.6
    world.policy(sources=["specs"], slots=2)
    sid = world.spec(number, "feature", plan=plan)
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert re.search(rf"^started spec-{number:03d}\.1 \(ship, {plan}, slot 1\)", r.out, re.M)
    [c] = world.calls()
    assert any(a.startswith("/component:ship") and (sid in a or f" {number:03d}" in a) for a in c["argv"]), c["argv"]
    assert c["argv"][c["argv"].index("--parallel") + 1] == parallel
    assert c["cwd"] == str(world.worktree(f"spec-{number:03d}"))
    assert git(c["cwd"], "rev-parse", "--abbrev-ref", "HEAD") == f"feature/{sid}"


def test_while_a_ship_unit_runs_a_second_ship_candidate_is_held_ship_busy_ac_167_6(world):  # AC-167.6
    world.policy(sources=["specs"], slots=3)
    world.spec(7, "price-alerts", plan="team")
    world.spec(8, "refunds", plan="single")
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert len(world.calls()) == 1 and "007" in " ".join(world.calls()[0]["argv"])
    doc = world.plan()
    [second] = [c for c in doc["candidates"] if "008" in c["item"]]
    assert second["verdict"] == "held" and second["reason"] == "ship-busy"
    assert world.run("start", "--once").rc == 0 and len(world.calls()) == 1


def test_a_draft_spec_never_starts_while_approval_is_human_ac_167_6(world):  # AC-167.6
    world.policy(sources=["specs"])
    sid = world.spec(9, "drafty", status="draft", plan=None)
    before = world.fingerprint()
    [c] = world.plan()["candidates"]
    assert c["verdict"] == "held" and c["reason"] == "needs-approval"
    assert world.run("start", "--once").rc == 0
    assert world.calls() == [] and world.gh_writes() == [] and world.fingerprint() == before
    assert "status: draft" in (world.repo / "docs" / "specs" / sid / "spec.md").read_text()


def test_with_self_approval_a_clean_draft_is_approved_by_cplat_dispatch_and_started_ac_167_6(world):  # AC-167.6
    world.policy(sources=["specs"], gates={"approve_specs": "self"})
    sid = world.spec(9, "drafty", status="draft", plan=None)
    [c] = world.plan()["candidates"]
    assert c["verdict"] == "ready" and c["approve"] == "self"
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert re.search(r"^approved \S*9\S* \(cplat dispatch\)", r.out, re.M)
    [call] = world.calls()
    spec_md = (world.dispatch_dir() / "worktrees" / "shop-api-spec-009" / "docs" / "specs" / sid / "spec.md").read_text()
    assert "status: approved" in spec_md and "approved by cplat dispatch" in spec_md
    assert "approve" in git(call["cwd"], "log", "-1", "--format=%s") and "Signed-off-by" in git(call["cwd"], "log", "-1", "--format=%B")
    assert "status: draft" in (world.repo / "docs" / "specs" / sid / "spec.md").read_text()       # main is untouched until the ship merges


def test_with_self_approval_a_draft_with_an_open_question_or_a_failing_check_stays_held_ac_167_6(world):  # AC-167.6
    world.policy(sources=["specs"], gates={"approve_specs": "self"}, slots=3)
    world.spec(9, "asks", status="draft", plan=None, questions="- Which mail provider?")
    broken = world.spec(10, "broken", status="draft", plan=None)
    p = world.repo / "docs" / "specs" / broken / "spec.md"
    p.write_text(re.sub(r"(?m)^- \*\*AC-.*\n", "", p.read_text()))
    git(world.repo, "commit", "-qam", "break")
    git(world.repo, "push", "-q", "origin", "main")
    git(world.repo, "fetch", "-q", "origin")
    doc = world.plan()
    assert [(c["verdict"], c["reason"]) for c in doc["candidates"]] == [("held", "needs-approval")] * 2
    assert world.run("start", "--once").rc == 0
    assert world.calls() == [] and world.gh_writes() == []


# ---------------- AC-167.8: escalation, restart, stuck ----------------

def test_an_escalated_unit_releases_its_claim_labels_needs_decision_and_frees_the_slot_ac_167_8(world):  # AC-167.8
    world.policy(slots=1)
    _fix_issues(world, 2, 2)
    world.behave("issue-1.1", mode="now", then="escalate", reason="escalated: tests keep failing")
    assert world.run("start", "--once").rc == 0
    world.wait_ended("issue-1.1")
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert re.search(r"^escalated issue-1\.1: .*tests keep failing", r.out, re.M)
    labels = world.labels_of(1)
    assert "needs-decision" in labels and "in-progress" not in labels
    [note] = [c for c in world.comments_of(1) if "<!-- cplat-dispatch-escalation -->" in c]
    assert "tests keep failing" in note and "needs-decision" in note
    assert any("<!-- cplat-release -->" in c for c in world.comments_of(1))
    assert _until_started(world, "issue-2.1")                                       # the slot is refilled
    needs = world.needs("--json")
    assert needs.rc == 0, needs
    [item] = [i for i in needs.json()["items"] if i["kind"] == "escalation"]
    assert item["object"]["issue"] == 1 and "tests keep failing" in item["reason"]
    assert item["command"] == "gh issue edit 1 --remove-label needs-decision"
    assert "#1" not in world.order(world.plan())                                   # held back by the label (not a candidate)
    world.edit_gh(lambda d: d["issues"]["1"]["labels"].remove("needs-decision"))
    assert world.cand(world.plan(), "#1")["verdict"] == "ready"                    # judged again once the user removes it


def test_a_unit_that_ended_without_finishing_is_started_once_more_then_escalated_as_stuck_ac_167_8(world):  # AC-167.8
    world.policy(slots=1)
    world.issue(1)
    world.behave("issue-1.1", then="die", die_after=0.1)
    assert world.run("start", "--once").rc == 0
    first = world.calls_of("issue-1.1")[0]["pid"]
    world.wait_until(lambda: not world.alive(first))
    r = world.run("start", "--once")
    assert r.rc == 0 and re.search(r"^restarted issue-1\.1 \(start 2\)", r.out, re.M), r
    second = world.calls_of("issue-1.1")
    assert [c["n"] for c in second] == [1, 2] and second[0]["cwd"] == second[1]["cwd"]
    assert _claims(world, 1) and len(_claims(world, 1)) == 1                       # no second claim
    world.wait_until(lambda: not world.alive(second[1]["pid"]))
    r = world.run("start", "--once")
    assert r.rc == 0
    unit, _ = world.unit_file("issue-1")
    assert re.search(r"^stuck issue-1\.1: " + re.escape(unit["log"]), r.out, re.M), r
    assert len(world.calls_of("issue-1.1")) == 2                                   # not a third time
    assert "needs-decision" in world.labels_of(1) and "in-progress" not in world.labels_of(1)
    [note] = [c for c in world.comments_of(1) if "<!-- cplat-dispatch-escalation -->" in c]
    assert "environment" in note or unit["log"] in note
    items = world.needs("--json").json()["items"]
    [stuck] = [i for i in items if i["kind"] == "stuck"]
    assert unit["log"] in stuck["reason"] and "environment" in stuck["reason"]
    assert stuck["command"] == "gh issue edit 1 --remove-label needs-decision" and stuck["object"]["issue"] == 1


# ---------------- AC-167.7: the unit's land phase ----------------

def test_a_finished_fix_unit_lands_merges_releases_its_claim_and_frees_the_slot_ac_167_7(world):  # AC-167.7
    world.policy(slots=1)
    _fix_issues(world, 2, 2)
    world.behave("issue-1.1", mode="now", then="done", tokens=4321)
    assert world.run("start", "--once").rc == 0
    world.wait_ended("issue-1.1")
    r = world.run("start", "--once")
    assert r.rc == 0 and re.search(r"^landing issue-1\.1: https://github.com/acme/shop-api/pull/\d+", r.out, re.M), r
    world.wait_until(lambda: any(e["ev"] == "merged" for e in world.events()))
    assert [e["green"] for e in world.events() if e["ev"] == "merged"] == [True]
    seen = []

    def finished():
        seen.append(world.run("start", "--once"))
        return re.search(r"^done issue-1\.1: ", seen[-1].out, re.M)

    wait_for(finished, what="the land phase to report done issue-1.1")
    r = seen[-1]
    assert re.search(r"^done issue-1\.1: .*pull/\d+", r.out, re.M), r
    assert "in-progress" not in world.labels_of(1)
    assert any("<!-- cplat-release -->" in c for c in world.comments_of(1))
    assert _until_started(world, "issue-2.1")
    rep = world.run("report", "--json").json()
    row = (rep["days"] if isinstance(rep, dict) else rep)[0]
    [done] = row["delivered"]
    assert done["item"] == "#1" and done["unit"] == "issue-1.1" and "pull/" in done["pr"] and done["tokens"] == 4321


def test_a_red_pr_is_never_merged_and_the_unit_escalates_with_a_red_event_ac_167_7(world):  # AC-167.7
    world.policy(slots=1)
    world.issue(1)
    world.set_default_checks([[{"name": "ci", "bucket": "fail"}]])
    world.behave("issue-1.1", mode="now", then="done")
    assert world.run("start", "--once").rc == 0
    world.wait_ended("issue-1.1")
    assert re.search(r"^landing issue-1\.1", world.run("start", "--once").out, re.M)
    world.wait_until(lambda: world.unit_file("issue-1")[0].get("landed") == "red")
    r = world.run("start", "--once")
    assert r.rc == 0 and re.search(r"^escalated issue-1\.1", r.out, re.M), r
    assert not any(e["ev"] == "merged" for e in world.events()) and not any(a[:2] == ["pr", "merge"] for a in world.gh_calls())
    assert "needs-decision" in world.labels_of(1)
    w = world.run("wait", "--timeout", "1")
    assert w.rc == 1 and w.lines[0].startswith("RED:") and "issue-1.1" in w.lines[0]


# ---------------- AC-167.9: kill and restart ----------------

def test_after_a_kill_the_new_dispatcher_adopts_live_units_and_restarts_dead_ones_without_a_second_claim_ac_167_9(world):  # AC-167.9
    world.policy(slots=2)
    _fix_issues(world)
    world.behave(mode="wait")
    assert world.run("start", "--once").rc == 0
    live = world.calls_of("issue-1.1")[0]["pid"]
    _kill(world, "issue-2.1")
    world.restart()                                                                 # the killed dispatcher kept nothing in memory
    comments = {n: world.comments_of(n) for n in (1, 2, 3)}
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert re.search(rf"^adopted issue-1\.1 \(pid {live}\)", r.out, re.M)
    assert re.search(r"^restarted issue-2\.1 \(start 2\)", r.out, re.M)
    assert not re.search(r"^started ", r.out, re.M)
    assert [(c["unit"], c["n"]) for c in world.calls()] == [("issue-1.1", 1), ("issue-2.1", 1), ("issue-2.1", 2)]
    assert world.alive(live)
    assert {n: world.comments_of(n) for n in (1, 2, 3)} == comments
    assert [len(_claims(world, n)) for n in (1, 2, 3)] == [1, 1, 0]


def test_a_claim_of_the_dispatcher_without_a_worktree_is_resumed_without_a_second_claim_ac_167_9(world):  # AC-167.9
    world.policy(slots=1)
    world.issue(1, labels=["triaged", "in-progress"], comments=["<!-- cplat-claim -->\nClaimed for branch `fix/issue-1` (cplat dispatch)."])
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]
    assert len(_claims(world, 1)) == 1 and [a for a in world.gh_writes() if a[:2] == ["issue", "comment"]] == []
    assert os.path.isdir(world.worktree("issue-1"))


def test_a_second_start_while_the_units_still_run_starts_nothing_twice_ac_167_9(world):  # AC-167.9
    world.policy(slots=2)
    _fix_issues(world)
    world.behave(mode="wait")
    world.run("start", "--once")
    for _ in range(2):
        world.restart()
        r = world.run("start", "--once")
        assert r.rc == 0 and not re.search(r"^started ", r.out, re.M) and len(re.findall(r"^adopted ", r.out, re.M)) == 2, r
    assert sorted(c["unit"] for c in world.calls()) == ["issue-1.1", "issue-2.1"]
    assert [len(_claims(world, n)) for n in (1, 2)] == [1, 1]
