"""Spec 207 acceptance tests: AC-207.1, a folder whose trust dialog was never accepted (`preflight_trust`, design.md).

The trust record is Claude Code's config file, replaced through `preflight_trust.config_file`; plugins installed on the machine
through `preflight_trust.plugins_dir`. The module reads the record and never writes it.
"""
import json
import os

import pytest

from pf207_support import BASE_SETTINGS, Seams, commit_settings, fresh, mod, plugin_dir
from units131_support import git, make_repo

KEY = "component@sdlc-foundry"


@pytest.fixture()
def s(tmp_path, monkeypatch):
    return Seams(tmp_path, monkeypatch)


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path)


def pt():
    return mod("preflight_trust")


def pass_line(folder):
    return f"preflight: {folder} is not trusted; its permission rules are passed to the session"


def fail_tail(folder):
    return f"open claude in {folder} once and accept the trust dialog"


# ---------------- trusted ----------------

def test_a_trusted_folder_passes_with_no_line_ac_207_1(s, repo):  # AC-207.1
    s.install().trust(repo)
    commit_settings(repo, {**BASE_SETTINGS, "env": {"X_KEY": "1"}, "permissions": {"additionalDirectories": ["/tmp"]}})
    assert pt().trusted(repo) is True
    assert pt().check(repo, []) == (None, None)


def test_trust_is_inherited_from_a_parent_folder_ac_207_1(s, repo):  # AC-207.1
    s.install().trust(repo.parent)
    assert pt().trusted(repo) is True
    assert pt().check(repo, []) == (None, None)


def test_a_missing_or_unreadable_config_means_not_trusted_ac_207_1(s, repo):  # AC-207.1
    s.install()
    assert not s.config.exists() and pt().trusted(repo) is False
    s.config.write_text("{ not json")
    assert pt().trusted(repo) is False
    s.config.write_text(json.dumps({"projects": {str(repo.resolve()): {"hasTrustDialogAccepted": False}}}))
    assert pt().trusted(repo) is False


# ---------------- untrusted, everything reaches the run another way ----------------

def test_an_untrusted_folder_with_plain_rules_passes_and_says_so_ac_207_1(s, repo):  # AC-207.1
    s.install()
    assert pt().check(repo, []) == (None, pass_line(repo))


def test_installed_plugins_count_as_available_ac_207_1(s, repo):  # AC-207.1
    s.install()
    s.install_plugin(KEY)
    commit_settings(repo, enabledPlugins={KEY: True})
    assert pt().installed_plugins()[KEY]
    assert pt().check(repo, []) == (None, pass_line(repo))


def test_plugins_passed_with_plugin_dir_count_as_available_ac_207_1(s, repo, tmp_path):  # AC-207.1
    s.install()
    d = plugin_dir(tmp_path, "component")
    commit_settings(repo, enabledPlugins={KEY: True})
    assert pt().plugin_dir_names([str(d)]) == {"component": d}
    assert pt().check(repo, [str(d)]) == (None, pass_line(repo))


def test_a_disabled_plugin_and_an_uncommitted_edit_do_not_count_ac_207_1(s, repo):  # AC-207.1
    s.install()
    commit_settings(repo, enabledPlugins={KEY: False})
    (repo / ".claude" / "settings.json").write_text(json.dumps({**BASE_SETTINGS, "env": {"X_KEY": "1"}}))   # not committed
    assert pt().committed_settings(repo)["enabledPlugins"] == {KEY: False}
    assert pt().check(repo, []) == (None, pass_line(repo))


def test_committed_settings_are_empty_when_missing_or_invalid_ac_207_1(s, tmp_path):  # AC-207.1
    s.install()
    bare = make_repo(tmp_path, name="bare")
    (bare / ".claude" / "settings.json").write_text("{ nope")
    git(bare, "commit", "-qam", "break")
    assert pt().committed_settings(bare) == {}


# ---------------- untrusted, something would be lost ----------------

def test_env_in_the_committed_settings_fails_ac_207_1(s, repo):  # AC-207.1
    # plan.md t1: "env keys sorted" and "check in this order" (env, then directories, then plugins)
    s.install()
    commit_settings(repo, env={"B_KEY": "2", "A_KEY": "1"})
    detail, line = pt().check(repo, [])
    assert line is None
    assert detail == (f"{repo} is not trusted and its committed settings set env (A_KEY, B_KEY), which Claude Code ignores "
                      f"without trust: {fail_tail(repo)}")


def test_additional_directories_fail_ac_207_1(s, repo):  # AC-207.1
    s.install()
    commit_settings(repo, permissions={**BASE_SETTINGS["permissions"], "additionalDirectories": ["/data"]})
    detail, line = pt().check(repo, [])
    assert line is None
    assert detail == (f"{repo} is not trusted and its committed settings set permissions.additionalDirectories, which Claude Code "
                      f"ignores without trust: {fail_tail(repo)}")


def test_a_plugin_that_is_neither_installed_nor_passed_fails_ac_207_1(s, repo, tmp_path):  # AC-207.1
    s.install()
    commit_settings(repo, enabledPlugins={KEY: True})
    other = plugin_dir(tmp_path, "somethingelse")
    detail, line = pt().check(repo, [str(other)])
    assert line is None
    assert detail == (f"{repo} is not trusted and plugin {KEY}, which its committed settings enable, is neither installed on "
                      f"this machine nor passed with --plugin-dir: {fail_tail(repo)}")


def test_env_is_reported_before_directories_and_plugins_ac_207_1(s, repo):  # AC-207.1
    # The order is the one of plan.md t1 ("check in this order": env, directories, plugins).
    s.install()
    commit_settings(repo, env={"K": "1"}, enabledPlugins={KEY: True},
                    permissions={**BASE_SETTINGS["permissions"], "additionalDirectories": ["/data"]})
    detail, _ = pt().check(repo, [])
    assert "set env (K)" in detail


# ---------------- the record is only read ----------------

@pytest.mark.parametrize("trusted", [True, False])
def test_the_config_file_is_never_written_ac_207_1(s, repo, trusted):  # AC-207.1
    s.install()
    s.account("uuid-1")
    if trusted:
        s.trust(repo)
    commit_settings(repo, env={"K": "1"})
    before = (s.config.read_bytes(), os.stat(s.config).st_mtime_ns)
    pt().trusted(repo)
    pt().check(repo, [])
    assert (s.config.read_bytes(), os.stat(s.config).st_mtime_ns) == before
    assert sorted(p.name for p in s.home.iterdir()) == [".claude.json"]


def test_a_missing_config_file_is_not_created_ac_207_1(s, repo):  # AC-207.1
    s.install()
    pt().check(repo, [])
    assert not s.config.exists()


# ---------------- where the files are ----------------

def test_the_default_locations_follow_claude_config_dir_ac_207_1(tmp_path, monkeypatch):  # AC-207.1
    m = fresh("preflight_trust")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert m.config_file() == tmp_path / "cfg" / ".claude.json"
    assert m.plugins_dir() == tmp_path / "cfg" / "plugins"
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert m.config_file() == tmp_path / "home" / ".claude.json"
    assert m.plugins_dir() == tmp_path / "home" / ".claude" / "plugins"


def test_installed_plugins_reads_the_flat_form_too_ac_207_1(s, tmp_path):  # AC-207.1
    s.install()
    where = tmp_path / "flat-install"
    where.mkdir()
    s.plugins.mkdir()
    (s.plugins / "installed_plugins.json").write_text(json.dumps({KEY: {"installPath": str(where)},
                                                                   "gone@x": {"installPath": str(tmp_path / "missing")}}))
    got = pt().installed_plugins()
    assert got[KEY] == [where] and "gone@x" not in got
