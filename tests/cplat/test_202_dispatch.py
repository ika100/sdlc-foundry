"""Spec 202 acceptance tests: the dispatcher's `guard` policy (AC-202.5), an escalation by the loop guard (AC-202.6) and pause (AC-202.7).

Contract: design.md ".platform/dispatch.yml `guard`", "`cplat dispatch status`", "`cplat needs --json` / `cplat dispatch inbox`".
The units are the fake headless of `dispatch_world`; a unit "escalated by the guard" is the fake that ends the way `cplat headless` does
when the guard trips (cause `platform`, a `looping: ...` reason, stop reason `escalated`).
"""
import re

import pytest

import dispatch_world
from dispatch_world import world  # noqa: F401  (fixture)
from waiting import fake_prelude

LOOPING = ("looping: 10 model calls in 5 min without progress in phase land; "
           "last message: Still waiting for the land to finish.")


def _issues(world, n=3):
    for i in range(1, n + 1):
        world.issue(i, title=f"issue {i}", labels=["triaged", "bug"], created=f"2026-11-0{i}T08:00:00Z")


def _looping_headless(world):
    """The fake headless that can end with another cause than `decision` (`cause` in what `World.behave` sets)."""
    text = dispatch_world.FAKE_HEADLESS.replace('cause="decision"', 'cause=cfg.get("cause", "decision")')
    assert text != dispatch_world.FAKE_HEADLESS
    exe = world.bin / "fake-headless-guard"
    exe.write_text(text % {"py": dispatch_world.sys.executable, "pre": fake_prelude()})
    exe.chmod(0o755)
    world.mp.setenv("CPLAT_DISPATCH_HEADLESS", str(exe))


# ---------------- AC-202.5: the policy ----------------

def test_plan_shows_the_effective_guard_values_with_defaults_marked_ac_202_5(world):  # AC-202.5
    pol = world.plan()["policy"]
    assert pol["values"]["guard"] == {"loop_calls": 10, "loop_minutes": 5}
    assert "guard.loop_calls" in pol["defaulted"] and "guard.loop_minutes" in pol["defaulted"]
    text = world.run("plan").out
    assert "  guard.loop_calls: 10 (default)" in text and "  guard.loop_minutes: 5 (default)" in text


def test_plan_shows_the_values_of_the_file_without_the_default_mark_ac_202_5(world):  # AC-202.5
    world.policy(guard={"loop_calls": 20, "loop_minutes": 10})
    pol = world.plan()["policy"]
    assert pol["values"]["guard"] == {"loop_calls": 20, "loop_minutes": 10}
    assert "guard.loop_calls" not in pol["defaulted"] and "guard.loop_minutes" not in pol["defaulted"]
    text = world.run("plan").out
    assert "guard.loop_calls: 20" in text and "guard.loop_calls: 20 (default)" not in text


def test_one_given_key_leaves_the_other_at_its_default_ac_202_5(world):  # AC-202.5
    world.policy(guard={"loop_calls": 7})
    pol = world.plan()["policy"]
    assert pol["values"]["guard"] == {"loop_calls": 7, "loop_minutes": 5}
    assert pol["defaulted"].count("guard.loop_minutes") == 1 and "guard.loop_calls" not in pol["defaulted"]


@pytest.mark.parametrize("guard,flag", [({"loop_calls": 20, "loop_minutes": 10}, "20/10"), (None, "10/5")])
def test_the_units_headless_gets_the_effective_guard_ac_202_5(world, guard, flag):  # AC-202.5
    world.policy(slots=1, **({"guard": guard} if guard else {}))
    _issues(world, 1)
    world.behave(mode="now")
    assert world.run("start", "--once").rc == 0
    [call] = world.calls_of("issue-1.1")
    argv = call["argv"]
    assert argv[argv.index("--loop-guard") + 1] == flag
    assert argv.index("--loop-guard") < max(i for i, a in enumerate(argv) if "/component:fix" in a)    # before the prompt


@pytest.mark.parametrize("verb", [("plan",), ("status",), ("inbox",), ("report",), ("pause",), ("resume",), ("start", "--once"), ("wait", "--timeout", "1")])
@pytest.mark.parametrize("text,message", [
    ("guard:\n  loop_calls: 2\n", "guard.loop_calls: 2 is not allowed (allowed: an integer 3..100)"),
    ("guard:\n  loop_calls: 101\n", "guard.loop_calls: 101 is not allowed (allowed: an integer 3..100)"),
    ("guard:\n  loop_minutes: 0\n", "guard.loop_minutes: 0 is not allowed (allowed: an integer 1..60)"),
    ("guard:\n  loop_minutes: 61\n", "guard.loop_minutes: 61 is not allowed (allowed: an integer 1..60)"),
    ("guard:\n  loop_minutes: five\n", "guard.loop_minutes: five is not allowed (allowed: an integer 1..60)"),
    ("guard:\n  frobnicate: 1\n", "guard.frobnicate: unknown key (allowed: loop_calls, loop_minutes)"),
])
def test_a_bad_guard_is_refused_by_every_dispatch_command_ac_202_5(world, verb, text, message):  # AC-202.5
    world.policy_text("budget:\n  tokens_per_day: 100\n" + text)
    world.issue(1)
    before = world.fingerprint()
    r = world.run(*verb)
    assert r.rc == 1, r
    assert r.err.startswith("ERROR:") and f".platform/dispatch.yml: {message}" in r.err, r.err
    assert world.calls() == [] and world.gh_writes() == [] and world.fingerprint() == before


# ---------------- AC-202.6: a unit escalated by the guard ----------------

def _guard_escalated(world, tokens=777):
    _looping_headless(world)
    world.policy(slots=1)
    for n in (1, 2):
        world.issue(n, title=f"issue {n}", labels=["triaged", "bug"], created=f"2026-11-0{n}T08:00:00Z")
    world.behave("issue-1.1", mode="now", then="escalate", cause="platform", reason=LOOPING, tokens=tokens)
    assert world.run("start", "--once").rc == 0
    world.wait_ended("issue-1.1")
    r = world.run("start", "--once")
    assert r.rc == 0, r
    return r


def test_the_dispatcher_handles_a_guard_escalation_as_an_escalation_ac_202_6(world):  # AC-202.6
    r = _guard_escalated(world)
    assert re.search(r"^escalated issue-1\.1: .*looping: 10 model calls in 5 min", r.out, re.M), r.out
    labels = world.labels_of(1)
    assert "needs-decision" in labels and "in-progress" not in labels
    [note] = [c for c in world.comments_of(1) if "<!-- cplat-dispatch-escalation -->" in c]
    assert "looping: 10 model calls in 5 min without progress in phase land" in note
    assert any("<!-- cplat-release -->" in c for c in world.comments_of(1))
    for _ in range(3):
        if world.calls_of("issue-2.1"):
            break
        assert world.run("start", "--once").rc == 0
    assert world.calls_of("issue-2.1")                                              # the slot is refilled


def test_inbox_and_needs_list_the_escalation_with_cause_platform_ac_202_6(world):  # AC-202.6
    _guard_escalated(world)
    for run in (world.needs("--json"), world.run("inbox", "--json")):
        assert run.rc == 0, run
        [item] = [i for i in run.json()["items"] if i["kind"] == "escalation"]
        assert item["cause"] == "platform" and "looping: 10 model calls in 5 min" in item["reason"]
    text = world.run("inbox").out
    assert "looping: 10 model calls in 5 min" in text and "(cause platform)" in text


def test_status_shows_the_unit_as_escalated_looping_with_the_reason_ac_202_6(world):  # AC-202.6
    _guard_escalated(world)
    doc = world.run("status", "--json").json()
    [e] = doc["escalated"]
    assert e["unit"] == "issue-1.1" and e["item"] == "#1" and e["kind"] == "fix"
    assert e["label"] == "escalated: looping" and e["cause"] == "platform" and e["reason"].startswith("looping: 10 model calls in 5 min")
    assert all(u["unit"] != "issue-1.1" for u in doc["slots"]["units"])             # it holds no slot
    text = world.run("status").out
    assert "escalated today (1):" in text
    assert re.search(r"^\s+issue-1\.1\s+#1\s+escalated: looping\s+looping: 10 model calls", text, re.M), text


def test_a_unit_escalated_with_another_cause_is_labelled_by_its_cause_ac_202_6(world):  # AC-202.6
    _looping_headless(world)
    world.policy(slots=1)
    world.issue(1)
    world.behave("issue-1.1", mode="now", then="escalate", cause="environment", reason="wait cplat pr wait 7 still running after 120 min")
    world.run("start", "--once")
    world.wait_ended("issue-1.1")
    world.run("start", "--once")
    [e] = world.run("status", "--json").json()["escalated"]
    assert e["label"] == "escalated: environment" and e["cause"] == "environment"


def test_report_counts_the_guard_escalation_and_its_tokens_count_for_the_day_ac_202_6(world):  # AC-202.6
    _guard_escalated(world, tokens=777)
    row = world.run("report", "--json").json()["days"][0]
    assert [(e["item"], e["unit"]) for e in row["escalated"]] == [("#1", "issue-1.1")] and "looping:" in row["escalated"][0]["reason"]
    status = world.run("status", "--json").json()
    assert status["tokens"]["used"] >= 777 and status["tokens"]["unknown"] == []     # AC-167.10: up to the stop, they count


# ---------------- AC-202.7: pause ----------------

def test_pause_says_that_running_units_stop_at_their_next_stop_ac_202_7(world):  # AC-202.7
    world.policy(slots=1)
    _issues(world, 1)
    world.behave(mode="wait", honor_stop=True)
    world.run("start", "--once")
    r = world.run("pause")
    assert r.rc == 0 and r.out.strip() == "paused: nothing new starts; running units stop at their next stop", r


def test_a_paused_unit_shows_its_phase_and_last_checkpoint_in_status_ac_202_7(world):  # AC-202.7
    world.policy(slots=1)
    _issues(world, 1)
    world.behave(mode="wait", honor_stop=True)
    world.run("start", "--once")
    world.run("pause")
    world.run("start", "--once")                                                    # the cycle that flags the running units
    world.wait_ended("issue-1.1")
    world.run("start", "--once")
    doc = world.run("status", "--json").json()
    [u] = doc["slots"]["units"]
    assert u["phase"] == "paused"                                                   # AC-167.11's readers keep it
    assert set(u["paused_at"]) == {"phase", "checkpoint"}
    assert re.search(r"paused \(phase \S+, checkpoint \S+\)", world.run("status").out)
