"""Spec 167 acceptance tests: steering and seeing the dispatcher (AC-167.11).

Contract: design.md "Steering" (pause, pause --drain, resume, slots; the stop flag `cplat-dispatch-stop` in each running unit's git
dir), "Commands and output" (`status`, `wait`, `report`). The units are the fake headless of `dispatch_world` (`honor_stop` makes it
end at the flag the way `cplat headless` does at a checkpoint); one `start --once` is one cycle.
"""
import re

from dispatch_world import world  # noqa: F401  (fixture)


def _issues(world, n=3):
    for i in range(1, n + 1):
        world.issue(i, title=f"issue {i}", labels=["triaged", "bug"], created=f"2026-11-0{i}T08:00:00Z")


def _running(world, slots=2, n=3, **behave):
    world.policy(slots=slots)
    _issues(world, n)
    world.behave(mode="wait", **behave)
    r = world.run("start", "--once")
    assert r.rc == 0, r
    return r


def _flag(world, key):
    return world.unit_file(key)[1] / "cplat-dispatch-stop"


def test_pause_stops_starts_and_flags_running_units_for_their_next_checkpoint_ac_167_11(world):  # AC-167.11
    _running(world, honor_stop=True)
    r = world.run("pause")
    assert r.rc == 0 and r.out.strip(), r
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: paused" in r.out, r
    assert _flag(world, "issue-1").exists() and _flag(world, "issue-2").exists()
    assert sorted(c["unit"] for c in world.calls()) == ["issue-1.1", "issue-2.1"]    # nothing new started (one pass starts both, in any order)
    assert world.run("status", "--json").json()["paused"] == "pause"
    world.wait_ended("issue-1.1")                                                  # the units stopped at their checkpoint
    world.wait_ended("issue-2.1")
    assert world.run("start", "--once").rc == 0
    phases = {u["unit"]: u["phase"] for u in world.run("status", "--json").json()["slots"]["units"]}
    assert phases == {"issue-1.1": "paused", "issue-2.1": "paused"}
    assert world.calls_of("issue-3.1") == []


def test_resume_allows_starts_again_and_restarts_paused_units_first_with_their_claims_ac_167_11(world):  # AC-167.11
    _running(world, honor_stop=True)
    world.run("pause")
    world.run("start", "--once")
    world.wait_ended("issue-1.1")
    world.wait_ended("issue-2.1")
    world.run("start", "--once")
    r = world.run("resume")
    assert r.rc == 0, r
    assert not _flag(world, "issue-1").exists() and not _flag(world, "issue-2").exists()
    world.behave(mode="wait", honor_stop=False)
    for _ in range(3):
        assert world.run("start", "--once").rc == 0
    world.wait_until(lambda: len(world.calls()) >= 4)
    assert [(c["unit"], c["n"]) for c in world.calls()] == [("issue-1.1", 1), ("issue-2.1", 1), ("issue-1.1", 2), ("issue-2.1", 2)]
    assert world.calls_of("issue-3.1") == []                                         # the paused units came first
    assert [len([c for c in world.comments_of(n) if "<!-- cplat-claim -->" in c]) for n in (1, 2)] == [1, 1]
    assert world.run("status", "--json").json()["paused"] is None


def test_drain_lets_running_units_finish_and_starts_nothing_ac_167_11(world):  # AC-167.11
    world.behave("issue-1.1", then="escalate")                                       # the fake reads it once, at start
    _running(world, honor_stop=True)
    r = world.run("pause", "--drain")
    assert r.rc == 0, r
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: drain" in r.out, r
    assert not _flag(world, "issue-1").exists() and not _flag(world, "issue-2").exists()      # no stop flag: they finish
    assert world.run("status", "--json").json()["paused"] == "drain"
    world.release("issue-1.1")
    world.wait_ended("issue-1.1")
    r = world.run("start", "--once")
    assert re.search(r"^escalated issue-1\.1", r.out, re.M) and world.calls_of("issue-3.1") == []


def test_pause_and_drain_survive_a_restart_of_the_dispatcher_ac_167_11(world):  # AC-167.11
    world.policy(slots=2)
    _issues(world)
    world.run("pause")
    world.restart()
    assert world.run("start", "--once").out.count("no starts: paused") == 1 and world.calls() == []
    world.run("pause", "--drain")
    world.restart()
    assert world.run("status", "--json").json()["paused"] == "drain"
    assert world.run("resume").rc == 0 and world.run("status", "--json").json()["paused"] is None


def test_a_lower_slot_count_stops_no_unit_and_blocks_starts_until_running_is_below_it_ac_167_11(world):  # AC-167.11
    _running(world, slots=2)
    world.behave("issue-1.1", then="escalate")
    r = world.run("slots", "1")
    assert r.rc == 0, r
    status = world.run("status", "--json").json()
    assert status["slots"]["total"] == 1 and len(status["slots"]["units"]) == 2      # nothing was stopped
    pids = [c["pid"] for c in world.calls()]
    assert all(world.alive(p) for p in pids)
    world.restart()                                                                   # the new count is part of the state
    assert world.run("status", "--json").json()["slots"]["total"] == 1
    world.release("issue-1.1")
    world.wait_ended("issue-1.1")
    for _ in range(2):
        world.run("start", "--once")
    assert world.calls_of("issue-3.1") == [] and world.alive(pids[1])                 # one unit still runs: 1 >= 1
    world.behave("issue-2.1", then="escalate")
    world.release("issue-2.1")
    world.wait_ended("issue-2.1")
    def started():                                                                    # a pass starts it once 2.1 is reaped
        world.run("start", "--once")
        return world.calls_of("issue-3.1")
    assert world.wait_until(started)


def test_a_higher_slot_count_fills_the_new_slots_in_the_next_cycle_ac_167_11(world):  # AC-167.11
    _running(world, slots=1)
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]
    assert world.run("slots", "3").rc == 0
    world.run("start", "--once")
    assert sorted(c["unit"] for c in world.calls()) == ["issue-1.1", "issue-2.1", "issue-3.1"]


def test_slots_outside_1_to_10_is_refused_ac_167_11(world):  # AC-167.11
    world.policy()
    for bad in ("0", "11", "x"):
        assert world.run("slots", bad).rc != 0
    assert world.run("slots", "10").rc == 0


def test_status_lists_slots_queue_held_pause_state_and_the_days_tokens_ac_167_11(world):  # AC-167.11
    world.policy(slots=2)
    _issues(world, 3)
    world.issue(4, body="blocked by #1")
    world.behave(mode="wait")
    world.run("start", "--once")
    doc = world.run("status", "--json").json()
    assert doc["schema"] == 1 and doc["paused"] is None and doc["slots"]["total"] == 2
    u1, u2 = doc["slots"]["units"]
    for u, n in ((u1, 1), (u2, 2)):
        assert u["unit"] == f"issue-{n}.1" and u["item"] == f"#{n}" and u["kind"] == "fix" and u["mode"] == "single"
        assert u["phase"] in ("starting", "running") and u["since"] and "tokens" in u and u["pid"] and u["log"]
    assert u1["slot"] == 1 and u2["slot"] == 2
    assert [q["item"] for q in doc["queue"]] == ["#3"]
    assert [(h["item"], h["reason"]) for h in doc["held"]] == [("#4", "blocked")]
    assert doc["tokens"]["limit"] == 20_000_000 and doc["tokens"]["used"] >= 0 and doc["tokens"]["day"] == "2026-11-10"
    text = world.run("status").out
    for needle in ("issue-1.1", "issue-2.1", "#3", "#4", "blocked", "20,000,000"):
        assert needle in text, (needle, text)


def test_wait_exits_0_when_nothing_runs_and_nothing_is_queued_ac_167_11(world):  # AC-167.11
    world.policy()
    r = world.run("wait", "--timeout", "1")
    assert r.rc == 0 and r.lines[0].startswith("IDLE:"), r


def test_wait_exits_2_with_timeout_and_the_running_units_ac_167_11(world):  # AC-167.11
    _running(world)
    r = world.run("wait", "--timeout", "1")
    assert r.rc == 2, r
    assert r.lines[0] == "TIMEOUT: 2 unit(s) running after 1s"
    assert re.match(r"^\s+issue-1\.1 #1 \S+ since \d\d:\d\d", r.lines[1]) and re.match(r"^\s+issue-2\.1 #2 ", r.lines[2])


def test_wait_exits_1_on_an_escalation_once_and_report_lists_it_ac_167_11(world):  # AC-167.11
    world.policy(slots=1)
    world.issue(1, title="issue 1")
    world.behave("issue-1.1", mode="now", then="escalate", reason="escalated: tests keep failing")
    world.run("start", "--once")
    world.wait_ended("issue-1.1")
    world.run("start", "--once")
    r = world.run("wait", "--timeout", "1")
    assert r.rc == 1 and r.lines[0].startswith("ESCALATED:") and "issue-1.1" in r.lines[0] and "#1" in r.lines[0], r
    assert "tests keep failing" in r.lines[0]
    again = world.run("wait", "--timeout", "1")
    assert again.rc == 0 and again.lines[0].startswith("IDLE:"), again              # an event is reported once
    rep = world.run("report", "--json").json()
    row = (rep["days"] if isinstance(rep, dict) else rep)[0]
    assert row["day"] == "2026-11-10" and row["delivered"] == []
    assert [(e["item"], e["unit"]) for e in row["escalated"]] == [("#1", "issue-1.1")] and "tests keep failing" in row["escalated"][0]["reason"]
    assert isinstance(row["tokens"], int)
    text = world.run("report").out
    assert re.search(r"^2026-11-10  delivered 0  escalated 1  held \d+  tokens [\d,]+", text, re.M), text
    assert "issue-1.1" in text


def test_report_since_limits_the_days_newest_first_ac_167_11(world):  # AC-167.11
    world.policy()
    world.write_state(history=[
        {"unit": "issue-7.1", "item": "#7", "kind": "fix", "outcome": "done", "pr": "https://github.com/acme/shop-api/pull/70", "tokens": 900,
         "reason": None, "started_at": "2026-11-08T09:00:00", "ended_at": "2026-11-08T10:00:00"},
        {"unit": "issue-8.1", "item": "#8", "kind": "fix", "outcome": "done", "pr": "https://github.com/acme/shop-api/pull/80", "tokens": 100,
         "reason": None, "started_at": "2026-11-10T09:00:00", "ended_at": "2026-11-10T10:00:00"}])
    rep = world.run("report", "--json").json()
    days = rep["days"] if isinstance(rep, dict) else rep
    assert [d["day"] for d in days][:2] == ["2026-11-10", "2026-11-08"]
    assert days[0]["delivered"][0]["pr"].endswith("/80") and days[0]["delivered"][0]["tokens"] == 100
    one = world.run("report", "--since", "1", "--json").json()
    assert [d["day"] for d in (one["days"] if isinstance(one, dict) else one)] == ["2026-11-10"]
