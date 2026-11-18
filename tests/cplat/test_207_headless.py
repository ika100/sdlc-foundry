"""Spec 207 acceptance tests: `cplat headless` stops on a failed check of this spec as AC-131.11 and AC-131.12 say, and a run that
passes them makes one model call per distinct model without charging it (AC-207.1 to AC-207.8, at the level of the command).

The fake world is the one of spec 131; the model call, the Claude config and the waits are the seams of `pf207_support.Seams`.
"""
import json
import subprocess

import pytest

from pf207_support import Seams, commit_settings, write_agent
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import World, git, snapshot_settings

USAGE = {"input_tokens": 9, "output_tokens": 2, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4, "cost_usd": 0.25}


@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")


@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=False)


@pytest.fixture()
def seams(w, tmp_path, monkeypatch):
    s = Seams(tmp_path, monkeypatch)
    s.script["*"] = {"usage": dict(USAGE)}
    return s


def go(w, seams, *args, prompt=None):
    seams.install()                              # imports the new modules: a missing one fails the test, not its fixture
    return w.run("--max-runs", "1", *args, prompt=prompt)


# ---------------- the breaks, one per check of this spec ----------------

def b_env(w, s):
    commit_settings(w.repo, env={"A_KEY": "1"})


def b_rules(w, s):
    w.user_settings.write_text(json.dumps({"permissions": {"deny": ["Bash(git add:*)"]}}))


def b_definition(w, s):
    write_agent(w.repo, "coder", tools="Read")


def b_worktree(w, s):
    (w.repo / ".claude" / "worktrees").write_text("not a folder\n")


def b_static_model(w, s):
    w.user_settings.write_text(json.dumps({"availableModels": ["fictional-9"]}))


def b_call(w, s):
    s.script["*"] = {"ok": False, "error": "Invalid API key", "offline": False, "usage": dict(USAGE)}


def b_gh(w, s):
    w.mp.setenv("FAKE_GH_AUTH", "fail")


BREAKS = [
    pytest.param(b_env, "untrusted-folder", "set env (A_KEY)", id="untrusted-folder"),
    pytest.param(b_rules, "subagent-tools", 'which deny rule "Bash(git add:*)"', id="subagent-rules"),
    pytest.param(b_definition, "subagent-tools", "does not grant Bash", id="subagent-definition"),
    pytest.param(b_worktree, "agent-worktree", "cannot create an agent worktree", id="agent-worktree"),
    pytest.param(b_static_model, "model-unreachable", "is not in availableModels of user settings", id="model-excluded"),
    pytest.param(b_call, "model-unreachable", "cannot be called (Invalid API key)", id="model-call"),
    pytest.param(b_gh, "gh-auth", "(3 tries over 45 s)", id="gh-login"),
]


# ---------------- AC-207.8: the outcome of a failed check ----------------

@pytest.mark.parametrize("brk, category, marker", BREAKS)
def test_a_failed_check_starts_no_session_and_says_why_ac_207_8(w, seams, store, capsys, brk, category, marker):  # AC-207.8
    brk(w, seams)
    assert go(w, seams) == 1
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("preflight failed: ")]
    assert len(lines) == 1 and lines[0].startswith(f"preflight failed: {category}: ") and marker in lines[0]
    assert f"HEADLESS shop-api: preflight failed: {category}" in out
    assert w.sessions() == []
    rec = stored(store)[-1]
    assert rec["outcome"] == "escalated" and rec["stop_reason"] == "preflight"
    assert rec["escalation"] == {"reason": f"preflight failed: {category}", "cause": "environment"}


@pytest.mark.parametrize("brk, category, marker", BREAKS)
def test_a_failed_check_costs_nothing_and_a_model_is_called_only_after_the_other_checks_ac_207_8(w, seams, store, brk, category, marker):  # AC-207.8
    brk(w, seams)
    assert go(w, seams) == 1
    rec = stored(store)[-1]
    assert rec["budget"]["used"]["invocations"] == 0 and rec["budget"]["used"]["cost"] == 0
    (ledger,) = w.ledgers()
    assert ledger["used"]["invocations"] == 0 and ledger["carried"]["invocations"] == 0
    assert bool(seams.calls) == (category == "model-unreachable" and marker.startswith("cannot be called"))


@pytest.mark.parametrize("brk, category, marker", BREAKS)
def test_a_failed_check_changes_no_settings_file_and_no_trust_record_ac_207_8(w, seams, brk, category, marker):  # AC-207.8
    seams.account("uuid-1")
    (w.repo / ".claude" / "settings.local.json").write_text('{"permissions": {"allow": ["Bash(ls)"]}}\n')
    brk(w, seams)
    paths = [w.repo / ".claude" / "settings.json", w.repo / ".claude" / "settings.local.json", w.user_settings, seams.config]
    before, status = snapshot_settings(*paths), git(w.repo, "status", "--porcelain")
    heads = git(w.repo, "rev-list", "--all", "--count")
    assert go(w, seams) == 1
    assert snapshot_settings(*paths) == before
    assert git(w.repo, "status", "--porcelain") == status and git(w.repo, "rev-list", "--all", "--count") == heads
    assert git(w.repo, "branch", "--list", "feature/*") == "" and git(w.repo, "worktree", "list").count("\n") == 0


def test_the_dispatch_result_carries_the_cause_environment_ac_207_8(w, seams, tmp_path, monkeypatch):  # AC-207.8
    result = tmp_path / "result.json"
    monkeypatch.setenv("CPLAT_DISPATCH_RESULT", str(result))
    b_definition(w, seams)
    assert go(w, seams) == 1
    data = json.loads(result.read_text())
    assert data["cause"] == "environment" and data["result"] == "preflight failed: subagent-tools"
    assert data["stop_reason"] == "preflight" and data["outcome"] == "escalated"


def test_a_system_ship_is_checked_for_trust_as_well_ac_207_8(w, seams, capsys):  # AC-207.8
    b_env(w, seams)
    assert go(w, seams, prompt="/system:ship 7") == 1
    assert "preflight failed: untrusted-folder: " in capsys.readouterr().out
    assert w.sessions() == []


# ---------------- AC-207.1, AC-207.6: a passing run ----------------

def test_an_untrusted_folder_that_passes_says_so_once_and_a_trusted_one_does_not_ac_207_1(w, seams, capsys):  # AC-207.1
    assert go(w, seams) == 1
    out = capsys.readouterr().out.splitlines()
    line = f"preflight: {w.repo} is not trusted; its permission rules are passed to the session"
    assert out.count(line) == 1
    assert len(w.sessions()) == 1


def test_a_trusted_folder_prints_no_untrusted_line_ac_207_1(w, seams, capsys):  # AC-207.1
    seams.install()
    seams.trust(w.repo)
    assert w.run("--max-runs", "1") == 1
    out = capsys.readouterr().out
    assert "is not trusted" not in out and "preflight failed" not in out
    assert len(w.sessions()) == 1


def test_one_call_per_distinct_model_is_not_a_session_and_not_charged_ac_207_6(w, seams, store):  # AC-207.6
    assert go(w, seams) == 1
    assert seams.calls and len(seams.calls) == len(set(seams.calls))
    rec = stored(store)[-1]
    assert rec["budget"]["used"]["invocations"] == 1                     # the one session; the model calls are no invocations
    assert rec["budget"]["used"]["cost"] < USAGE["cost_usd"]
    calls = rec["preflight"]["model_calls"]
    assert [c["model"] for c in calls] == seams.calls
    for c in calls:
        assert c == {"model": c["model"], "cached": False, "input_tokens": 9, "output_tokens": 2,
                     "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4, "cost_usd": 0.25}


def test_a_model_that_passed_a_minute_ago_is_not_called_again_by_the_next_run_ac_207_6(w, seams, store):  # AC-207.6
    assert go(w, seams) == 1
    first = list(seams.calls)
    assert first
    assert w.run("--max-runs", "1") in (0, 1)
    assert seams.calls == first
    calls = stored(store)[-1]["preflight"]["model_calls"]
    assert all(c["cached"] and c["input_tokens"] == 0 for c in calls)


def test_a_clean_run_changes_no_settings_file_ac_207_8(w, seams):  # AC-207.8
    seams.account("uuid-1")
    paths = [w.repo / ".claude" / "settings.json", w.user_settings, seams.config]
    before = snapshot_settings(*paths)
    assert go(w, seams) == 1
    assert snapshot_settings(*paths) == before
    assert subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=w.repo, capture_output=True, text=True).stdout.count("worktree ") == 1
