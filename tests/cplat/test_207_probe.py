"""Spec 207 acceptance tests: AC-207.4 (the agent worktree probe) and AC-207.6 (one minimal model call per distinct model,
cached for 60 minutes, not charged to the run), in `preflight_probe` (design.md).

The model call is replaced through `preflight_probe.model_call`; nothing here calls a real model or sleeps. A real git repo is
built in tmp_path for the probe.
"""
import datetime
import json
import os
import stat
import sys
from pathlib import Path

import pytest

import core
import runs
from pf207_support import ZERO, Seams, mod, state_of
from units131_support import git, make_repo
from waiting import with_prelude


@pytest.fixture()
def s(tmp_path, monkeypatch):
    return Seams(tmp_path, monkeypatch)


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path)


def pp():
    return mod("preflight_probe")


# ---------------- AC-207.4: the agent worktree probe ----------------

def test_the_agent_worktrees_go_under_the_repos_claude_folder_ac_207_4(repo):  # AC-207.4
    assert pp().worktree_location(repo) == repo / ".claude" / "worktrees"


def test_the_probe_passes_and_leaves_the_repo_exactly_as_it_was_ac_207_4(repo):  # AC-207.4
    before = state_of(repo)
    assert not (repo / ".claude" / "worktrees").exists()
    assert pp().check_worktree(repo, []) is None
    assert state_of(repo) == before
    assert not (repo / ".claude" / "worktrees").exists()           # it created the folder, so it removes it
    assert git(repo, "branch", "--list") == "* main"


def test_an_existing_worktrees_folder_stays_and_holds_nothing_of_the_probe_ac_207_4(repo):  # AC-207.4
    loc = repo / ".claude" / "worktrees"
    loc.mkdir()
    (loc / "agent-1").mkdir()
    before = state_of(repo)
    assert pp().check_worktree(repo, []) is None
    assert state_of(repo) == before
    assert [p.name for p in loc.iterdir()] == ["agent-1"]


def test_the_probe_with_uncommitted_work_leaves_it_alone_ac_207_4(repo):  # AC-207.4
    (repo / "wip.txt").write_text("not committed\n")
    (repo / ".claude" / "settings.json").write_text("{}\n")
    before = state_of(repo)
    assert pp().check_worktree(repo, []) is None
    assert state_of(repo) == before
    assert (repo / "wip.txt").read_text() == "not committed\n"


def test_a_worktree_that_cannot_be_created_fails_with_the_git_error_ac_207_4(repo):  # AC-207.4
    loc = repo / ".claude" / "worktrees"
    loc.write_text("a file where the folder should be\n")
    before = state_of(repo)
    detail = pp().check_worktree(repo, [])
    path = loc / f"cplat-preflight-{os.getpid()}"
    assert detail.startswith(f"cannot create an agent worktree at {path} (")
    assert detail.endswith(f"): run git worktree prune in {repo}, then run again")
    assert len(detail.splitlines()) == 1
    assert state_of(repo) == before
    assert loc.read_text() == "a file where the folder should be\n"


def test_a_location_that_resolves_outside_the_repo_fails_ac_207_4(repo, tmp_path):  # AC-207.4
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (repo / ".claude" / "worktrees").symlink_to(outside)
    before = state_of(repo)
    detail = pp().check_worktree(repo, [])
    real = outside.resolve() / f"cplat-preflight-{os.getpid()}"
    assert detail.startswith(f"agent worktrees go to {real}, outside the folders the session may work in ({repo}): ")
    assert detail.endswith(f"make {repo}/.claude/worktrees a plain folder inside the repo")
    assert state_of(repo) == before
    assert list(outside.iterdir()) == []                            # the probe removed what it made there
    assert (repo / ".claude" / "worktrees").is_symlink()


def test_a_folder_passed_with_add_dir_is_a_place_the_session_may_work_in_ac_207_4(repo, tmp_path):  # AC-207.4
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (repo / ".claude" / "worktrees").symlink_to(outside)
    assert pp().check_worktree(repo, [str(outside)]) is None
    assert list(outside.iterdir()) == []
    detail = pp().check_worktree(repo, [str(tmp_path / "unrelated")])
    assert f"({repo}, {tmp_path / 'unrelated'})" in detail


# ---------------- AC-207.6: one call per distinct model ----------------

MODELS = {"sonnet": ["coordinator", "coder", "tester"], "opus": ["reviewer"]}


def test_one_call_per_distinct_model_and_never_more_ac_207_6(s):  # AC-207.6
    s.install()
    assert pp().check_models(MODELS, None) is None
    assert s.calls == ["sonnet", "opus"]


def test_a_model_that_passed_within_60_minutes_is_not_called_again_ac_207_6(s):  # AC-207.6
    s.install()
    assert pp().check_models(MODELS, None) is None
    assert pp().check_models(MODELS, None) is None
    assert s.calls == ["sonnet", "opus"]
    assert (s.tmp / "cache" / "sdlc-foundry" / "preflight" / "models.json").is_file()


def shift_cache(s, minutes):
    f = s.tmp / "cache" / "sdlc-foundry" / "preflight" / "models.json"
    data = json.loads(f.read_text())
    assert data and all(isinstance(v, str) for v in data.values())
    f.write_text(json.dumps({k: (datetime.datetime.fromisoformat(v) - datetime.timedelta(minutes=minutes)).isoformat()
                             for k, v in data.items()}))


def test_the_cache_holds_for_59_minutes_and_not_for_61_ac_207_6(s):  # AC-207.6
    s.install()
    pp().check_models({"sonnet": ["coordinator"]}, None)
    shift_cache(s, 59)
    pp().check_models({"sonnet": ["coordinator"]}, None)
    assert s.calls == ["sonnet"]
    shift_cache(s, 2)
    pp().check_models({"sonnet": ["coordinator"]}, None)
    assert s.calls == ["sonnet", "sonnet"]


@pytest.mark.parametrize("change", ["key", "base-url", "account"])
def test_other_credentials_get_a_new_call_and_no_secret_is_cached_ac_207_6(s, monkeypatch, change):  # AC-207.6
    s.install()
    s.account("uuid-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-one")
    pp().check_models({"sonnet": ["coordinator"]}, None)
    pp().check_models({"sonnet": ["coordinator"]}, None)
    assert s.calls == ["sonnet"]
    if change == "key":
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-two")
    elif change == "base-url":
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.test")
    else:
        s.account("uuid-2")
    pp().check_models({"sonnet": ["coordinator"]}, None)
    assert s.calls == ["sonnet", "sonnet"]
    text = (s.tmp / "cache" / "sdlc-foundry" / "preflight" / "models.json").read_text()
    assert "sk-secret" not in text and "uuid-" not in text


def test_the_check_never_writes_the_claude_config_ac_207_6(s):  # AC-207.6
    s.install()
    s.account("uuid-1")
    before = (s.config.read_bytes(), os.stat(s.config).st_mtime_ns)
    pp().check_models(MODELS, None)
    assert (s.config.read_bytes(), os.stat(s.config).st_mtime_ns) == before


# ---------------- AC-207.6: failures ----------------

def test_an_authentication_error_fails_naming_the_model_the_agents_and_the_error_ac_207_6(s):  # AC-207.6
    s.install()
    s.script["opus"] = {"ok": False, "error": "Invalid API key: please run /login", "offline": False}
    detail = pp().check_models({"sonnet": ["coordinator"], "opus": ["reviewer", "security"]}, None)
    assert detail == ("opus (used by reviewer, security) cannot be called (Invalid API key: please run /login): "
                      "run claude /login, or set a model the account may use")
    assert s.calls == ["sonnet", "opus"]                      # no retry of an error that is not the network


def test_a_failed_call_is_not_cached_ac_207_6(s):  # AC-207.6
    s.install()
    s.script["*"] = {"ok": False, "error": "no access to this model", "offline": False}
    assert pp().check_models({"opus": ["coordinator"]}, None) is not None
    assert pp().check_models({"opus": ["coordinator"]}, None) is not None
    assert s.calls == ["opus", "opus"]


def test_a_dropped_network_is_retried_and_then_named_ac_207_6(s, monkeypatch):  # AC-207.6
    s.install()
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 60)        # conftest turns retries off
    err = "dial tcp: lookup api.anthropic.com: no such host"
    s.script["*"] = {"ok": False, "error": err, "offline": True}
    detail = pp().check_models({"sonnet": ["coordinator"]}, None)
    assert detail == f"could not reach the model API ({err}): check the network, then run again"
    assert s.net_waits[:2] == [10, 20] and sum(s.net_waits) <= 60
    assert len(s.calls) == len(s.net_waits) + 1


def test_a_network_that_comes_back_passes_with_one_pass_recorded_ac_207_6(s, monkeypatch):  # AC-207.6
    s.install()
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 60)
    s.script["sonnet"] = [{"ok": False, "error": "connection reset", "offline": True}, {}]
    assert pp().check_models({"sonnet": ["coordinator"]}, None) is None
    assert s.calls == ["sonnet", "sonnet"] and s.net_waits == [10]
    pp().check_models({"sonnet": ["coordinator"]}, None)
    assert s.calls == ["sonnet", "sonnet"]


def test_without_retry_time_a_dropped_network_fails_at_once_ac_207_6(s):  # AC-207.6
    s.install()
    s.script["*"] = {"ok": False, "error": "dial tcp: no such host", "offline": True}
    assert pp().check_models({"sonnet": ["coordinator"]}, None).startswith("could not reach the model API (dial tcp: no such host)")
    assert s.calls == ["sonnet"] and s.net_waits == []


# ---------------- AC-207.6: tokens in the run's log, not in the budget ----------------

def test_the_tokens_of_each_call_are_recorded_under_preflight_ac_207_6(s, monkeypatch):  # AC-207.6
    s.install()
    seen = []
    monkeypatch.setattr(runs, "set_section", lambda rid, name, value: seen.append((rid, name, json.loads(json.dumps(value)))))
    usage = {"input_tokens": 11, "output_tokens": 3, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7, "cost_usd": 0.0123}
    s.script["opus"] = {"usage": usage}
    assert pp().check_models(MODELS, "run-1") is None
    rid, name, value = seen[-1]
    assert (rid, name) == ("run-1", "preflight")
    assert value["model_calls"] == [
        {"model": "sonnet", "cached": False, **ZERO},
        {"model": "opus", "cached": False, "input_tokens": 11, "output_tokens": 3, "cache_read_input_tokens": 5,
         "cache_creation_input_tokens": 7, "cost_usd": 0.0123}]
    pp().check_models(MODELS, "run-1")                             # cached: an entry with zero tokens
    assert [(c["model"], c["cached"], c["input_tokens"]) for c in seen[-1][2]["model_calls"]] == [("sonnet", True, 0), ("opus", True, 0)]


def test_the_failed_call_is_in_the_log_too_ac_207_6(s, monkeypatch):  # AC-207.6
    s.install()
    seen = []
    monkeypatch.setattr(runs, "set_section", lambda rid, name, value: seen.append((rid, name, value)))
    s.script["opus"] = {"ok": False, "error": "denied", "offline": False, "usage": {**ZERO, "input_tokens": 4}}
    assert pp().check_models(MODELS, "run-2") is not None
    models = [c["model"] for c in seen[-1][2]["model_calls"]]
    assert models == ["sonnet", "opus"]


# ---------------- AC-207.6: the real call (REAL_MODEL_CALL, design.md "Model check call") ----------------

FAKE_MODEL_CLAUDE = "#!" + sys.executable + """
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "env": sorted(os.environ)}) + "\\n")
mode = os.environ["FAKE_MODE"]
if mode == "pass":
    print(json.dumps({"type": "result", "is_error": False, "result": "ok", "usage": {"input_tokens": 3, "output_tokens": 1}}))
elif mode == "is-error":
    print(json.dumps({"type": "result", "is_error": True, "result": "Credit balance is too low\\n\\nAdd credit to go on\\n"}))
elif mode == "auth":
    sys.stderr.write("Error: authentication failed\\n\\nInvalid API key - Please run /login\\n\\n")
    sys.exit(1)
else:
    sys.stderr.write("request failed\\nPost https://api.anthropic.com/v1/messages: dial tcp: lookup api.anthropic.com: no such host\\n")
    sys.exit(1)
"""


@pytest.fixture()
def real(tmp_path, monkeypatch):
    exe = tmp_path / "fake-claude"
    exe.write_text(with_prelude(FAKE_MODEL_CLAUDE))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "model-calls.jsonl"
    monkeypatch.setenv("CPLAT_CLAUDE", str(exe))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setattr(core, "sleep", lambda seconds: None)
    monkeypatch.setenv("CPLAT_RUN_ID", "run-from-the-session")
    monkeypatch.setenv("CPLAT_UNIT", "unit-1")

    def call(mode, model="opus"):
        monkeypatch.setenv("FAKE_MODE", mode)
        return pp().REAL_MODEL_CALL(model), [json.loads(ln) for ln in log.read_text().splitlines()]
    return call


def test_the_real_call_is_a_minimal_claude_call_in_a_clean_folder_ac_207_6(real):  # AC-207.6
    result, (seen,) = real("pass")
    assert result.ok is True and result.error == "" and result.offline is False
    assert seen["argv"] == ["-p", "Reply with the single word ok.", "--model", "opus", "--output-format", "json", "--max-turns", "1"]
    cwd = Path(seen["cwd"])
    assert cwd.name.startswith("cplat-preflight-") and not cwd.exists()      # a fresh temporary folder, removed afterwards
    assert not cwd.resolve().is_relative_to(Path.cwd().resolve())
    assert not [k for k in seen["env"] if k.startswith("CPLAT_")]            # the run's variables never reach it


def test_the_real_call_reports_an_error_result_ac_207_6(real):  # AC-207.6
    result, _ = real("is-error")
    assert result.ok is False and result.offline is False
    assert result.error == "Add credit to go on"                             # the last non-empty line of the result


def test_the_real_call_reports_the_last_line_of_a_failure_ac_207_6(real):  # AC-207.6
    result, (seen,) = real("auth", model="sonnet")
    assert result.ok is False and result.offline is False
    assert result.error == "Invalid API key - Please run /login"
    assert seen["argv"][3] == "sonnet"


def test_the_real_call_recognises_a_dropped_network_ac_207_6(real):  # AC-207.6
    result, _ = real("network")
    assert result.ok is False and result.offline is True
    assert result.error.endswith("no such host")
