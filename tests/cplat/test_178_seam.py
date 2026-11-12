"""Spec 178 acceptance tests: the seam test (AC-178.7, AC-178.8).

`cplat headless "/component:ship 007-price-alerts"` runs as a process on a temporary clone with a bare origin, a fake `claude` that follows
a script and calls the configured hooks, a fake `gh` backed by that origin and a fake `devbox`; no network (seam178_world.py). The
variants of AC-178.8 each assert the correct behaviour of one seam, so each fails when that seam is broken.
"""
import json
import time

import pytest

from seam178_world import SPEC_ID, Seam

UNITS = ["red-tests", "task:t1", "verification", "land"]        # the plan is committed on main: its unit is done before any session


@pytest.fixture()
def seam(tmp_path):
    return Seam(tmp_path)


def result_line(res) -> str:
    return next((ln for ln in res.stdout.splitlines() if ln.startswith("HEADLESS ")), "")


# ---------------- AC-178.7: from preflight to land ----------------

def test_a_ship_runs_from_preflight_to_land_and_the_units_commits_are_on_main(seam):  # AC-178.7
    began = time.monotonic()
    res = seam.headless()
    took = time.monotonic() - began
    assert res.returncode == 0, res.stdout + res.stderr
    assert result_line(res).startswith(f"HEADLESS shop-api: shipped {SPEC_ID}"), res.stdout
    [record] = [r for r in seam.records() if r.get("kind") == "headless"]
    assert record["outcome"] == "done" and record.get("stop_reason") == "done"
    assert [s["unit"] for s in seam.sessions()] == UNITS
    assert seam.origin("show", "main:a.py") == "X = 1"                           # the unit's work is on the origin's main
    assert "AC-007.1" in seam.origin("show", "main:tests/test_alerts.py")
    assert "verification.md" in seam.origin("ls-tree", "-r", "--name-only", "main")
    assert len(seam.events("merged")) == 1 and seam.origin("branch", "--list", f"feature/{SPEC_ID}") == ""      # merged, branch deleted
    assert took <= 120, f"the seam test took {took:.0f}s"


def test_every_session_calls_the_configured_hooks_and_none_is_blocked(seam):  # AC-178.7
    res = seam.headless()
    assert res.returncode == 0, res.stdout + res.stderr
    hooks = seam.lines("hooks.jsonl")
    for unit in UNITS:
        events = [h["event"] for h in hooks if h["unit"] == unit]
        assert events.count("SessionStart") >= 1 and events.count("Stop") >= 2, (unit, events)   # the two Stop hooks of hooks.json
    assert [h for h in hooks if h["rc"] != 0] == []
    assert seam.lines("blocked.jsonl") == []


def test_the_unit_runs_its_real_commands_and_the_pr_is_landed_through_the_land_command(seam):  # AC-178.7
    res = seam.headless()
    assert res.returncode == 0, res.stdout + res.stderr
    ran = [c["argv"][:3] for c in seam.lines("commands.jsonl")]
    for expected in (["component", "ship", "start"], ["spec", "task-done", SPEC_ID], ["spec", "trace", SPEC_ID], ["component", "ship", "pr"],
                     ["component", "ship", "land"], ["component", "ship", "deploy"]):
        assert expected in ran, (expected, ran)
    assert [c for c in seam.lines("commands.jsonl") if c["rc"] != 0] == []
    assert [e["head"] for e in seam.events("merged")] == [seam.events("merge-attempt")[0]["match"]]   # merged on the head its checks judged


# ---------------- AC-178.8: each seam, broken, fails a variant ----------------

def test_a_cplat_variable_of_the_outer_run_does_not_reach_the_test_command(seam):  # AC-178.8
    res = seam.headless()
    assert res.returncode == 0, res.stdout + res.stderr
    runs = seam.devbox_runs()
    scripts = {next(a for i, a in enumerate(r["args"][1:], 1) if a not in ("-e", "--env") and r["args"][i - 1] not in ("-e", "--env"))
               for r in runs}   # the script after `devbox run`, past spec 185's `-e KEY=VALUE` pairs
    assert scripts >= {"ci", "test-fast"}, runs
    leaked = sorted({name for r in runs for name in r["cplat"]})
    assert leaked == [], f"the test command of the unit sees {leaked} of the outer run"


def test_a_repo_allowlist_without_a_required_rule_stops_the_run_before_any_session(seam):  # AC-178.8
    seam.write_settings(["Bash(devbox run *)", "Read(~/.claude/plugins/**)"], commit=True)      # `Bash(cplat *)` is missing
    res = seam.headless()
    assert res.returncode == 1, res.stdout + res.stderr
    assert any(ln.startswith("preflight failed: no-repo-allowlist:") for ln in res.stdout.splitlines()), res.stdout
    assert seam.sessions() == []


def test_a_session_that_ended_after_a_local_commit_is_resumed_and_the_commit_is_pushed_before_checks_are_judged(seam):  # AC-178.8
    seam.behave({"land": ["commit-then-die"]})
    seam.gh(first_red=True)                                  # the head the PR was opened on is red: judging it would stop the land
    res = seam.headless()
    assert res.returncode == 0, res.stdout + res.stderr
    assert [s["n"] for s in seam.sessions() if s["unit"] == "land"] == [1, 2]
    assert seam.origin("show", "main:late.txt") == "a late change"
    [merged] = seam.events("merged")
    judged = {c["sha"] for c in seam.events("checks")}
    first = json.loads((seam.dir / "state.json").read_text())["first_head"]
    assert merged["head"] != first and first not in judged and judged == {merged["head"]}


def test_a_session_that_stops_while_its_land_waits_is_blocked_and_the_stops_are_not_counted_as_without_progress(seam):  # AC-178.8
    seam.behave({"land": ["stop-during-wait"]})
    seam.gh(hold_file=str(seam.dir / "release"), handshake=str(seam.dir / "wait.fifo"))
    res = seam.headless()
    assert res.returncode == 0, res.stdout + res.stderr
    [waits] = seam.lines("waits.jsonl")
    assert waits["marks"], "the wait marked itself in the checkout's git dir while it ran"
    stops = seam.lines("stops.jsonl")
    assert len(stops) == 2
    for stop in stops:
        assert any(a.get("decision") == "block" for a in stop["answers"]), stop
    archived = sorted((seam.repo / ".git").glob("cplat-ship-*.json"))
    states = [json.loads(p.read_text()) for p in archived]
    assert states and all(not s.get("escalated") for s in states)
    assert all((s.get("stop_gate") or {}).get("no_progress", 0) == 0 for s in states)
