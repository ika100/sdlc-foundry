"""Spec 131 acceptance tests: `cplat headless` checks and grants permissions before anything runs (AC-131.8 to AC-131.12),
caps no unit run by default (AC-131.6) and continues an interrupted run (AC-131.4).

The fake `claude` and the `gh` stub are in units131_support.py; the settings layers are replaced through `preflight.layers`.
"""
import importlib
import json
import subprocess

import pytest

from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import BRANCH, SPEC_ID, World, git, snapshot_settings

ALLOW_HEAD = "run allowlist (this run's sessions only; no settings file is changed):"


def pf():
    return importlib.import_module("preflight")


@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=False)      # the plan unit is the first of 7 sessions


def grants(argv):
    """(allowed, disallowed) rules of a claude command line."""
    out = {}
    for flag in ("--allowedTools", "--disallowedTools"):
        if flag not in argv:
            out[flag] = None
            continue
        rules = []
        for a in argv[argv.index(flag) + 1:]:
            if a.startswith("--"):
                break
            rules.append(a)
        out[flag] = rules
    return out["--allowedTools"], out["--disallowedTools"]


# ---------------- AC-131.8: printed, then granted to every session ----------------

def test_the_dry_run_prints_the_allowlist_after_the_command(w, capsys):  # AC-131.8
    assert w.run("--dry-run") == 0
    out = capsys.readouterr().out
    assert ALLOW_HEAD in out and out.index("claude") < out.index(ALLOW_HEAD)
    assert f"  Bash(git switch {BRANCH})" in out and "  Bash(gh pr create *)" in out
    assert "refused: Bash(git push --force*)" in out


def test_the_allowlist_is_printed_before_the_first_session(w, capsys):  # AC-131.8
    w.run("--max-runs", "1")
    out = capsys.readouterr().out
    assert ALLOW_HEAD in out
    rules = pf().run_allowlist("/component:ship", [BRANCH])
    for r in rules:
        assert f"  {r}" in out


def test_every_session_gets_exactly_the_run_allowlist_and_the_refused_rules(w):  # AC-131.8 AC-131.10
    assert w.run() == 0
    rules = pf().run_allowlist("/component:ship", [BRANCH])
    refused = pf().refused_rules("main")
    assert len(w.sessions()) >= 6
    for s in w.sessions():
        allowed, disallowed = grants(s["argv"])
        assert allowed == rules and disallowed == refused
        assert s["argv"].index("--allowedTools") < s["argv"].index("--disallowedTools") < s["argv"].index("--session-id")
        assert json.loads(s["allowlist"]) == rules
        assert not set(allowed) & set(disallowed)
        assert "--permission-mode" in s["argv"] and "acceptEdits" in s["argv"]    # the repo's committed allowlist still applies


def test_the_legacy_loop_of_a_system_ship_gets_the_same_grants(w):  # AC-131.8
    rc = w.run("--max-runs", "1", prompt="/system:ship 7")
    assert rc in (0, 1)
    s, = w.sessions()
    allowed, disallowed = grants(s["argv"])
    assert "Bash(git switch feature/*)" in allowed and "Bash(cplat system ship entry land *)" in allowed
    assert disallowed == pf().refused_rules("main")
    assert json.loads(s["allowlist"]) == allowed


def test_a_prompt_that_is_not_a_covered_command_gets_no_grants(w):  # AC-131.8
    assert w.run(prompt="/component:fix the price is wrong") == 0
    s, = w.sessions()
    assert grants(s["argv"]) == (None, None) and s["allowlist"] is None


# ---------------- AC-131.9: no settings file is touched ----------------

@pytest.mark.parametrize("deny", [False, True])
def test_no_settings_file_changes_in_a_run_whatever_the_preflight_says(w, deny):  # AC-131.9
    (w.repo / ".claude" / "settings.local.json").write_text('{"permissions": {"allow": ["Bash(ls)"]}}\n')
    if deny:
        w.user_settings.write_text(json.dumps({"permissions": {"deny": ["Bash(git commit:*)"]}}))
    paths = [w.repo / ".claude" / "settings.json", w.repo / ".claude" / "settings.local.json", w.user_settings]
    before = snapshot_settings(*paths)
    files = sorted(p.name for p in (w.repo / ".claude").iterdir())
    assert w.run() == (1 if deny else 0)
    assert snapshot_settings(*paths) == before
    assert sorted(p.name for p in (w.repo / ".claude").iterdir()) == files


# ---------------- AC-131.11, AC-131.12: a failed preflight ----------------

def break_env(w, category):
    mp = w.mp
    if category == "no-repo-allowlist":
        (w.repo / ".claude" / "settings.json").unlink()
    elif category == "blocked-by-settings":
        w.user_settings.write_text(json.dumps({"permissions": {"ask": ["Bash(git push:*)"]}}))
    elif category == "git-identity":
        empty = w.tmp / "empty-gitconfig"
        empty.write_text("")
        for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            mp.delenv(var, raising=False)
        mp.setenv("GIT_CONFIG_GLOBAL", str(empty))
        mp.setenv("GIT_CONFIG_NOSYSTEM", "1")
    elif category == "gh-auth":
        mp.setenv("FAKE_GH_AUTH", "fail")
    elif category == "no-push-access":
        mp.setenv("FAKE_GH_PUSH", "false")


CATEGORIES = ["blocked-by-settings", "git-identity", "gh-auth", "no-push-access", "no-repo-allowlist"]


@pytest.mark.parametrize("category", CATEGORIES)
def test_a_failed_preflight_starts_no_session_and_says_why(w, store, capsys, category):  # AC-131.11
    break_env(w, category)
    assert w.run() == 1
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("preflight failed: ")]
    assert len(lines) == 1 and lines[0].startswith(f"preflight failed: {category}: ")
    assert f"HEADLESS shop-api: preflight failed: {category}" in out
    assert w.sessions() == []
    assert any(f"preflight failed: {category}" in ln for ln in w.summary())
    rec = stored(store)[-1]
    assert rec["outcome"] == "escalated" and rec["stop_reason"] == "preflight"
    assert rec["escalation"]["reason"] == f"preflight failed: {category}" and rec["escalation"]["cause"] == "environment"


def test_a_blocked_by_settings_line_names_the_rule_and_its_layer(w, capsys):  # AC-131.11
    break_env(w, "blocked-by-settings")
    w.run()
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("preflight failed: "))
    assert 'ask rule "Bash(git push:*)" in user settings' in line


def test_a_system_ship_is_checked_as_well(w, capsys):  # AC-131.11
    break_env(w, "gh-auth")
    assert w.run(prompt="/system:ship 7") == 1
    assert "preflight failed: gh-auth: " in capsys.readouterr().out
    assert w.sessions() == []


@pytest.mark.parametrize("category", CATEGORIES)
def test_a_failed_preflight_costs_nothing_and_creates_nothing(w, store, category):  # AC-131.12
    break_env(w, category)
    commits, status = git(w.repo, "rev-list", "--all", "--count"), git(w.repo, "status", "--porcelain")
    w.run()
    rec = stored(store)[-1]
    assert rec["budget"]["used"]["invocations"] == 0 and rec["budget"]["used"]["cost"] == 0
    assert git(w.repo, "branch", "--list", "feature/*") == ""
    assert git(w.repo, "rev-list", "--all", "--count") == commits
    assert not any(c.startswith("pr create") for c in w.gh_calls())
    assert not (w.repo / ".git" / "cplat-ship.json").exists() and not (w.repo / ".git" / "cplat-units.json").exists()
    assert git(w.repo, "status", "--porcelain") == status
    (ledger,) = w.ledgers()
    assert ledger["used"]["invocations"] == 0 and ledger["carried"]["invocations"] == 0


# ---------------- AC-131.6: no session cap unless asked ----------------

def test_a_run_with_more_units_than_six_is_not_stopped_by_the_session_count(w):  # AC-131.6
    assert w.run() == 0
    assert len(w.sessions()) == 7


def test_max_runs_given_caps_the_sessions_as_in_070(w, capsys):  # AC-131.6
    assert w.run("--max-runs", "3") == 1
    assert len(w.sessions()) == 3
    assert "stopped after 3 runs, ship run still unfinished" in capsys.readouterr().out


# ---------------- AC-131.4: the same command, started again ----------------

def test_the_same_command_again_continues_at_the_first_unit_without_a_checkpoint(w):  # AC-131.4
    assert w.run("--max-runs", "4") == 1
    assert w.units_run() == ["plan", "red-tests", "task:t1", "task:t2"]
    data = w.units_file()
    t3 = next(u for u in data["units"] if u["id"] == "task:t3")
    t3.update(status="running", sessions=1)                       # the supervisor was killed in the middle of this unit
    (w.repo / ".git" / "cplat-units.json").write_text(json.dumps(data))
    assert w.run() == 0
    assert w.units_run() == ["plan", "red-tests", "task:t1", "task:t2", "task:t3", "verification", "land"]


def test_the_budget_usage_continues_where_it_stopped(w):  # AC-131.4
    import budget
    assert w.run("--max-runs", "4") == 1
    assert w.run() == 0
    (ledger,) = w.ledgers()                                       # one ledger for the one piece of work (AC-102.6)
    assert budget.used_of(ledger, cost=False)["invocations"] == 4 + 3 and len(ledger["roots"]) == 2
