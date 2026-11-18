"""Spec 207 acceptance tests: AC-207.8 at the level of `preflight.check` and `preflight.check_repo` (the order of the checks, the first
failure wins, a model call only after every other check passed, no file written), and the `RunContext` they take (design.md "Order").

`cplat headless` itself (the line, the exit code, the record) is in test_207_headless.py.
"""
import json
import os

import pytest

from pf207_support import Env, Seams, commit_settings, mod, override_all, state_of, write_agent
from units131_support import make_repo, snapshot_settings


@pytest.fixture()
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


@pytest.fixture()
def s(tmp_path, monkeypatch):
    return Seams(tmp_path, monkeypatch)


def pf():
    return mod("preflight")


def lines(capsys):
    return capsys.readouterr().out.splitlines()


# ---------------- the order ----------------

def test_the_checks_run_in_the_documented_order_and_the_first_failure_wins_ac_207_8(env, s, monkeypatch):  # AC-207.8
    s.install()
    monkeypatch.setenv("FAKE_GH_AUTH_FAILS", "99")                                    # the existing gh-auth check
    commit_settings(env.repo, env={"K": "1"})                                        # AC-207.1
    env.set_layer("user", {"permissions": {"deny": ["Bash(git add:*)"]},            # AC-207.2
                           "availableModels": ["fictional-9"]})                      # AC-207.5
    write_agent(env.repo, "coder", tools="Read")                                     # AC-207.3
    (env.repo / ".claude" / "worktrees").write_text("not a folder\n")               # AC-207.4
    s.script["*"] = {"ok": False, "error": "Invalid API key", "offline": False}     # AC-207.6

    f = env.check()
    assert f.category == "gh-auth"                                                   # the existing checks come first
    monkeypatch.delenv("FAKE_GH_AUTH_FAILS")
    f = env.check()
    assert f.category == "untrusted-folder" and "set env (K)" in f.detail
    s.trust(env.repo)
    f = env.check()
    assert f.category == "subagent-tools" and 'which deny rule "Bash(git add:*)"' in f.detail
    env.set_layer("user", {"availableModels": ["fictional-9"]})
    f = env.check()
    assert f.category == "subagent-tools" and "does not grant Bash" in f.detail
    write_agent(env.repo, "coder", tools="Read, Bash")
    f = env.check()
    assert f.category == "agent-worktree" and f.detail.startswith("cannot create an agent worktree at ")
    (env.repo / ".claude" / "worktrees").unlink()
    f = env.check()
    assert f.category == "model-unreachable" and "is not in availableModels of user settings" in f.detail
    assert s.calls == []                                                             # no model call so far
    env.set_layer("user", {})
    f = env.check()
    assert f.category == "model-unreachable" and "cannot be called (Invalid API key)" in f.detail
    assert s.calls, "the model call is made once every other check has passed"
    s.script["*"] = {}
    assert env.check() is None


def test_an_agent_model_the_settings_exclude_fails_though_the_coordinator_is_allowed_ac_207_5(env, s):  # AC-207.5
    s.install()
    s.trust(env.repo)
    path = env.set_layer("user", {"availableModels": ["sonnet"]})
    write_agent(env.repo, "reviewer", model="opus")
    f = env.check()                                                                   # the coordinator is sonnet
    assert f.category == "model-unreachable"
    assert f.detail == (f"opus (used by reviewer) is not in availableModels of user settings ({path}): "
                        "add opus to availableModels, or set a model the settings allow")
    assert s.calls == []


def test_a_failure_line_is_one_line_in_the_known_format_ac_207_8(env, s):  # AC-207.8
    s.install()
    write_agent(env.repo, "coder", tools="Read")
    f = env.check()
    assert f.line() == f"preflight failed: subagent-tools: {f.detail}" and "\n" not in f.line()
    assert f.reason() == "preflight failed: subagent-tools"


def test_the_agents_and_models_of_every_folder_are_checked_and_each_model_is_called_once_ac_207_8(env, s, tmp_path):  # AC-207.8
    s.install()
    s.trust(env.repo)
    clone = make_repo(tmp_path, name="shop-lib")
    override_all(env.repo, "haiku")
    override_all(clone, "haiku")
    assert env.check("/system:ship", targets=[(clone, "acme/shop-lib")]) is None
    assert sorted(s.calls) == ["haiku", "sonnet"]


def test_a_clone_of_a_system_ship_gets_the_trust_check_too_ac_207_8(env, s, tmp_path, capsys):  # AC-207.8
    s.install()
    s.trust(env.repo)
    clone = make_repo(tmp_path, name="shop-lib")
    commit_settings(clone, env={"K": "1"})
    f = env.check("/system:ship", targets=[(clone, "acme/shop-lib")])
    assert f.category == "untrusted-folder" and f.detail.startswith(f"{clone} is not trusted and its committed settings set env (K)")
    assert s.calls == []


def test_the_untrusted_line_is_printed_once_per_untrusted_folder_that_passes_ac_207_8(env, s, tmp_path, capsys):  # AC-207.8
    s.install()
    clone = make_repo(tmp_path, name="shop-lib")
    assert env.check("/system:ship", targets=[(clone, "acme/shop-lib")]) is None
    expected = [f"preflight: {p} is not trusted; its permission rules are passed to the session" for p in (env.repo, clone)]
    assert [ln for ln in lines(capsys) if "is not trusted" in ln] == expected


def test_a_trusted_folder_prints_no_untrusted_line_ac_207_8(env, s, capsys):  # AC-207.8
    s.install()
    s.trust(env.repo)
    assert env.check() is None
    assert not [ln for ln in lines(capsys) if "is not trusted" in ln]


def test_the_worktree_probe_runs_for_a_build_and_a_ship_only_ac_207_8(env, s):  # AC-207.8
    s.install()
    (env.repo / ".claude" / "worktrees").write_text("not a folder\n")
    assert env.check("/component:build").category == "agent-worktree"
    assert env.check("/component:ship").category == "agent-worktree"
    assert env.check("/system:ship") is None                                          # no probe for a system ship's own folder
    assert (env.repo / ".claude" / "worktrees").read_text() == "not a folder\n"


# ---------------- nothing is written ----------------

@pytest.mark.parametrize("fail", [False, True])
def test_a_check_writes_no_settings_file_and_no_trust_record_ac_207_8(env, s, fail):  # AC-207.8
    s.install()
    s.account("uuid-1")
    s.trust(env.repo.parent / "unrelated")
    env.set_layer("local", {"permissions": {"allow": ["Bash(ls)"]}})
    if fail:
        write_agent(env.repo, "coder", tools="Read")
    paths = [p for _, p in env.layers()] + [s.config]
    mtimes = {p: os.stat(p).st_mtime_ns for p in paths if p.is_file()}
    before, state = snapshot_settings(*paths), state_of(env.repo)
    tree = sorted(str(p.relative_to(env.repo)) for p in env.repo.rglob("*") if ".git" not in p.relative_to(env.repo).parts)
    f = env.check()
    assert (f is not None) == fail
    assert snapshot_settings(*paths) == before and {p: os.stat(p).st_mtime_ns for p in mtimes} == mtimes
    assert state_of(env.repo) == state
    assert sorted(str(p.relative_to(env.repo)) for p in env.repo.rglob("*") if ".git" not in p.relative_to(env.repo).parts) == tree


# ---------------- check_repo (a system ship's clone) ----------------

def headless_session(env, monkeypatch):
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    monkeypatch.setenv("CPLAT_RUN_ALLOWLIST", json.dumps(pf().run_allowlist("/system:ship", ["feature/*"])))
    env.arm()


def test_check_repo_under_a_headless_session_runs_the_trust_and_subagent_checks_ac_207_8(env, s, monkeypatch, capsys):  # AC-207.8
    s.install()
    headless_session(env, monkeypatch)
    clone = env.repo
    (clone / ".claude" / "worktrees").write_text("not a folder\n")                  # a clone gets no worktree probe
    assert pf().check_repo(clone, "acme/shop-api") is None
    assert [ln for ln in lines(capsys) if "is not trusted" in ln] == [
        f"preflight: {clone} is not trusted; its permission rules are passed to the session"]
    assert s.calls == []                                                              # and no model call

    commit_settings(clone, env={"K": "1"})
    f = pf().check_repo(clone, "acme/shop-api")
    assert f.category == "untrusted-folder" and f.detail.startswith(f"{clone} is not trusted and its committed settings set env (K)")
    s.trust(clone)
    assert pf().check_repo(clone, "acme/shop-api") is None

    write_agent(clone, "coder", tools="Read")
    assert pf().check_repo(clone, "acme/shop-api").category == "subagent-tools"
    write_agent(clone, "coder", tools="Bash")
    env.set_layer("user", {"permissions": {"deny": ["Agent(svc:coder)", "Agent(coder)"]}})
    assert "denies the coder agent" in pf().check_repo(clone, "acme/shop-api").detail
    assert s.calls == []


def test_check_repo_wants_the_devbox_allow_rule_of_the_coders_ac_207_8(env, s, monkeypatch):  # AC-207.8
    s.install()
    headless_session(env, monkeypatch)
    commit_settings(env.repo, {"permissions": {"allow": ["Bash(cplat *)", "Read(~/.claude/plugins/**)"]}})
    f = pf().check_repo(env.repo, "acme/shop-api")
    assert f.category == "subagent-tools" and 'which no allow rule permits: add "Bash(devbox run test)"' in f.detail


def test_check_repo_takes_an_explicit_run_context_and_an_attended_one_adds_nothing_ac_207_8(env, s, monkeypatch):  # AC-207.8
    s.install()
    env.arm()
    commit_settings(env.repo, env={"K": "1"})
    assert pf().check_repo(env.repo, "acme/shop-api") is None                        # not headless, no context: the old checks only
    f = pf().check_repo(env.repo, "acme/shop-api", run=env.ctx("/system:ship", model=None))
    assert f.category == "untrusted-folder"


# ---------------- the context ----------------

def test_the_run_context_of_a_headless_session_comes_from_its_environment_ac_207_8(env, monkeypatch, tmp_path):  # AC-207.8
    rules = pf().run_allowlist("/system:ship", ["feature/*"])
    monkeypatch.setenv("CPLAT_RUN_ALLOWLIST", json.dumps(rules))
    monkeypatch.setenv("CPLAT_PLUGIN_DIRS", os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")]))
    ctx = pf().RunContext.from_env(env.repo)
    assert ctx.allow == rules and ctx.deny == pf().refused_rules("main")
    assert ctx.plugin_dirs == [str(tmp_path / "a"), str(tmp_path / "b")] and ctx.add_dirs == [] and ctx.model is None
