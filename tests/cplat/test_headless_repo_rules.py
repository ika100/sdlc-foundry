"""Spec 162 (#588): headless sessions get the repo's committed permission rules as `--settings`, so they apply in an untrusted clone."""
import json
import shlex
import subprocess

import pytest

import headless


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    r = tmp_path / "shop-api"
    (r / ".claude").mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(cplat *)", "Bash(devbox run *)"], "deny": ["Bash(rm -rf *)"], "ask": []},
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "devbox install"}]}]}}))
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return r


def settings_of(cmd):
    return json.loads(cmd[cmd.index("--settings") + 1])


def test_repo_rules_are_the_committed_permission_rules_only(repo):
    """AC-162.1"""
    assert headless.repo_rules(repo) == {"allow": ["Bash(cplat *)", "Bash(devbox run *)"], "deny": ["Bash(rm -rf *)"]}


def test_an_uncommitted_edit_grants_nothing(repo):
    """AC-162.2"""
    (repo / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(*)"]}}))
    assert "Bash(*)" not in headless.repo_rules(repo)["allow"]


@pytest.mark.parametrize("content", [None, "not json", '{"permissions": "x"}', '["a"]'])
def test_no_or_unreadable_settings_give_no_rules(tmp_path, content):
    """AC-162.3"""
    r = tmp_path / "r"
    (r / ".claude").mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    if content is not None:
        (r / ".claude" / "settings.json").write_text(content)
        git(r, "add", ".")
        git(r, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "x")
    assert headless.repo_rules(r) == {}


def test_claude_cmd_merges_repo_rules_with_the_plugin_read_rules():
    """AC-162.1"""
    cmd = headless.claude_cmd("/component:ship 1", "sonnet", ["/p"], rules={"allow": ["Bash(cplat *)"], "deny": ["Bash(x)"]})
    assert cmd.count("--settings") == 1
    assert settings_of(cmd) == {"permissions": {"allow": ["Bash(cplat *)", "Read(//p/**)"], "deny": ["Bash(x)"]}}


def test_claude_cmd_without_rules_or_plugins_passes_no_settings():
    """AC-162.3"""
    assert "--settings" not in headless.claude_cmd("/component:ship 1", "sonnet")


def test_headless_passes_the_repo_rules_to_the_session(repo, capsys):
    """AC-162.1"""
    assert headless.main(["/component:fix typo", "--repo", str(repo), "--dry-run"]) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("claude ")][0]
    assert settings_of(shlex.split(line)) == {"permissions": headless.repo_rules(repo)}
