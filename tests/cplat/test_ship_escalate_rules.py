"""Spec 088 (amendment 2026-10-26): `ship escalate` prints the rule; the stop gate and headless `no progress` name `environment` (AC-088.15, .17, .18)."""
import subprocess

import headless
import ship
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_headless import fake_claude, repo as hl_repo  # noqa: F401  (fixtures)
from test_runs import buffered_lines, clock, mem, store, stored  # noqa: F401  (fixtures, helpers)
from test_ship import git, repo  # noqa: F401  (fixtures)

ALLOWED = ("platform", "code", "decision", "environment")


def escalate(repo, *args):
    return ship.main(["--repo", str(repo), "escalate", *args])


def lines(capsys):
    return [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]


def test_escalate_without_cause_prints_the_rule_after_the_message(repo, store, capsys):
    """AC-088.15: the AC-088.3 output is followed by `classified as <cause> by rule <rule name>`."""
    ship.start(repo, "7", True)
    capsys.readouterr()
    assert escalate(repo, "waiting for approval to create the branch") == 0
    out = lines(capsys)
    assert out[0].startswith("ship 007-price-alerts: escalated (waiting for approval to create the branch)")
    assert out[1].startswith("cause missing: recorded as unknown; allowed causes: ")
    assert out[2] == "classified as environment by rule git-action-awaits-approval"
    assert len(out) == 3


def test_escalate_with_an_unknown_cause_value_prints_the_rule_too(repo, store, capsys):
    """AC-088.15: a cause value that is not allowed is treated like a missing one."""
    ship.start(repo, "7", True)
    capsys.readouterr()
    assert escalate(repo, "left for the user to review", "--cause", "bogus") == 0
    out = capsys.readouterr().out
    assert "bogus" in out and out.rstrip().endswith("classified as decision by rule left-for-review")


def test_escalate_without_a_match_prints_only_the_message(repo, store, capsys):
    """AC-088.15: no rule matches: no `classified as` line, the cause stays unknown and the source is none."""
    ship.start(repo, "7", True)
    capsys.readouterr()
    assert escalate(repo, "tests fail after commit 1a2b3c") == 0
    out = capsys.readouterr().out
    assert "classified as" not in out and "recorded as unknown" in out
    (r,) = stored(store)
    assert (r["escalation"]["cause"], r["escalation"]["cause_source"]) == ("unknown", "none")


def test_escalate_with_a_stated_cause_prints_no_rule_line_and_records_given(repo, store, capsys):
    """AC-088.17 AC-088.15: `working tree is dirty` with `--cause code`: no extra line, cause `code`, `cause_source` `given`."""
    ship.start(repo, "7", True)
    capsys.readouterr()
    assert escalate(repo, "working tree is dirty", "--cause", "code") == 0
    out = capsys.readouterr().out
    assert "classified as" not in out and "cause missing" not in out
    (r,) = stored(store)
    assert r["escalation"] == {"reason": "working tree is dirty", "cause": "code", "cause_source": "given"}


def test_a_classified_escalation_is_not_filed_and_keeps_exit_zero(repo, tr, store, capsys):
    """AC-088.17: a classified escalation never reaches the tracker and prints no filing line."""
    ship.start(repo, "7", True)
    capsys.readouterr()
    assert escalate(repo, "stopped: working tree is dirty") == 0
    out = capsys.readouterr().out
    assert "classified as environment by rule dirty-working-tree" in out and "issue:" not in out and tr.calls == []


def test_the_stop_gate_giving_up_records_decision_given(repo, store, monkeypatch):
    """AC-126.7: the stop gate escalating on no progress records the cause by the rule (here `decision`), `cause_source` `given`."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "A")
    ship.start(repo, "7", True)
    for _ in range(2):
        assert ship.gate(repo, {"session_id": "A"}, run_tests=False)["decision"] == "block"
    ship.gate(repo, {"session_id": "A"}, run_tests=False)
    assert ship.load_state(repo)["cause"] == "decision"
    (r,) = stored(store)
    assert r["outcome"] == "escalated" and "no progress" in r["escalation"]["reason"]
    assert (r["escalation"]["cause"], r["escalation"]["cause_source"]) == ("decision", "given") and "rule" not in r["escalation"]
    assert r["filed"] == []


def test_headless_no_progress_records_environment_given(hl_repo, tmp_path, monkeypatch, store, capsys):
    """AC-088.18: `cplat headless` stopping on `no progress` records the ship escalation and its own as `environment`, `given`."""
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=hl_repo, check=True)
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--max-runs", "6"]) == 1
    assert "no progress" in capsys.readouterr().out
    assert ship.load_state(hl_repo)["cause"] == "environment" and "no progress" in ship.load_state(hl_repo)["escalated"]
    recs = stored(store) + [r for r in buffered_lines() if r["run_id"] not in {x["run_id"] for x in stored(store)}]
    (s,) = [r for r in recs if r["kind"] == "ship"]
    (h,) = [r for r in recs if r["kind"] == "headless"]
    for r in (s, h):
        assert r["outcome"] == "escalated" and r["escalation"]["reason"].startswith("no progress")
        assert (r["escalation"]["cause"], r["escalation"]["cause_source"]) == ("environment", "given"), r["kind"]
