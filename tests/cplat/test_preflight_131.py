"""Spec 131 acceptance tests: `preflight.py` (design.md "Run allowlist and preflight").

The run allowlist, the refused rules, the matcher, the five checks with their lines, and `CPLAT_RUN_ALLOWLIST` for
`cplat pr open`. The settings layers are replaced through `preflight.layers`; `gh` is a stub on PATH; git identity comes from
the environment of the test. The module does not exist yet, so it is imported inside the tests.
"""
import importlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from waiting import with_prelude
from units131_support import GH_STUB, SPEC_ID, git, make_repo, snapshot_settings

B = f"feature/{SPEC_ID}"


def pf():
    return importlib.import_module("preflight")


@pytest.fixture()
def world(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    git(repo, "config", "user.name", "Tester")
    git(repo, "config", "user.email", "tester@example.test")
    (repo / ".gitignore").write_text(".claude/settings.local.json\n")      # as a generated repo ignores it
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-qm", "ignore local settings")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(with_prelude(GH_STUB))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    log.write_text("")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.delenv("FAKE_GH_AUTH", raising=False)
    monkeypatch.delenv("FAKE_GH_PUSH", raising=False)
    user = tmp_path / "user.json"
    user.write_text("{}")
    w = type("W", (), {})()
    w.repo, w.user, w.mp, w.tmp = repo, user, monkeypatch, tmp_path

    def layers(r=None):
        base = Path(r or repo)
        return [("managed", tmp_path / "none.json"), ("user", user), ("project", base / ".claude" / "settings.json"),
                ("local", base / ".claude" / "settings.local.json")]
    w.layers = layers
    return w


def install(w):
    w.mp.setattr(pf(), "layers", w.layers)


# ---------------- AC-131.8: the run allowlist ----------------

def test_the_run_allowlist_of_a_ship_names_the_branch_commit_push_pr_and_land():  # AC-131.8
    assert pf().run_allowlist("/component:ship", [B]) == [
        f"Bash(git switch {B})", f"Bash(git switch -c {B})", "Bash(git add *)", "Bash(git commit -s *)",
        "Bash(git rm *)", f"Bash(git push -u origin {B})", f"Bash(git push origin {B})", "Bash(gh pr create *)",
        "Bash(cplat component ship land)", "Bash(cplat component ship land *)"]


def test_a_build_has_no_land_rules():  # AC-131.8
    rules = pf().run_allowlist("/component:build", [B])
    assert not any("ship land" in r for r in rules)
    assert "Bash(gh pr create *)" in rules and "Bash(git commit -s *)" in rules


def test_system_ship_covers_any_feature_branch_and_the_entry_land():  # AC-131.8
    rules = pf().run_allowlist("/system:ship", ["feature/*"])
    assert "Bash(git switch feature/*)" in rules and "Bash(git push origin feature/*)" in rules
    assert "Bash(cplat system ship entry land *)" in rules and "Bash(cplat component ship land)" in rules


def test_several_specs_get_a_rule_set_each():  # AC-131.8
    rules = pf().run_allowlist("/component:ship", [B, "feature/008-other"])
    assert "Bash(git push origin feature/008-other)" in rules and f"Bash(git push origin {B})" in rules


def test_the_env_carries_the_allowlist_as_json():  # AC-131.8
    rules = pf().run_allowlist("/component:ship", [B])
    assert json.loads(pf().env(rules)["CPLAT_RUN_ALLOWLIST"]) == rules


# ---------------- AC-131.10: the refused rules ----------------

REFUSED = [
    "git push --force origin feature/x", "git push -f origin feature/x", "git push origin feature/x --force-with-lease",
    "git push origin feature/x -f", "git push origin +feature/x", "git push origin main", "git push -u origin main",
    "git push origin HEAD:main", "git push origin feature/x:main", "git push origin feature/x:refs/heads/main",
    "gh pr merge 7 --squash", "gh api repos/acme/x/pulls/7/merge -X PUT", "cplat pr wait 7 --merge",
]
FINE = [
    f"git push -u origin {B}", f"git push origin {B}", "git push origin feature/x-fix", "git push origin feature/domain",
    "git push origin feature/main-page", "git commit -s -m 'fix: x'", "gh pr create --base main --head feature/x --title t --body-file .pr-body.md",
    "cplat component ship land", "git switch -c feature/x-force-field",
]


@pytest.mark.parametrize("command", REFUSED)
def test_every_refused_action_matches_a_refused_rule(command):  # AC-131.10
    rules = pf().refused_rules("main")
    assert any(pf().matches(r, command) for r in rules), command


@pytest.mark.parametrize("command", FINE)
def test_no_action_of_the_run_matches_a_refused_rule(command):  # AC-131.10
    rules = pf().refused_rules("main")
    assert not any(pf().matches(r, command) for r in rules), [r for r in rules if pf().matches(r, command)]


def test_the_refused_rules_follow_the_default_branch_and_the_allowlist_never_contains_one():  # AC-131.10
    rules = pf().refused_rules("trunk")
    assert any(pf().matches(r, "git push origin trunk") for r in rules)
    assert not any(pf().matches(r, "git push origin main") for r in rules)
    allow = pf().run_allowlist("/system:ship", ["feature/*"]) + pf().run_allowlist("/component:ship", [B])
    assert not set(allow) & set(pf().refused_rules("main"))
    for r in pf().refused_rules("main"):
        assert r.startswith("Bash(")


def test_the_default_branch_is_main_without_a_remote_head(world):  # AC-131.10
    assert pf().default_branch(world.repo) == "main"


# ---------------- the matcher ----------------

@pytest.mark.parametrize("rule, command, expected", [
    ("Bash", "anything at all", True),
    ("Bash(*)", "git status", True),
    ("Bash(git push:*)", "git push origin x", True),
    ("Bash(git push:*)", "git pull", False),
    ("Bash(git switch feature/x)", "git switch feature/x", True),
    ("Bash(git switch feature/x)", "git switch feature/x --detach", False),
    ("Bash(git add *)", "git add -A", True),
    ("Bash(git push * main)", "git push origin main", True),
    ("Bash(git push * -f*)", "git push origin feature/x-fix", False),
    ("Bash(git push * -f*)", "git push origin x -f", True),
    ("Read(/tmp/**)", "git push origin x", False),
    ("Edit", "git push origin x", False),
])
def test_the_rule_matcher(rule, command, expected):  # AC-131.10
    assert pf().matches(rule, command) is expected


# ---------------- AC-131.11: the five checks ----------------

def check(w, **kw):
    install(w)
    return pf().check(w.repo, kw.get("command", "/component:ship"), kw.get("specs", [SPEC_ID]), kw.get("targets"))


def test_a_clean_environment_passes(world):  # AC-131.11
    assert check(world) is None


def test_no_repo_allowlist(world):  # AC-131.11
    (world.repo / ".claude" / "settings.json").unlink()
    f = check(world)
    assert f.category == "no-repo-allowlist"
    assert f.line() == (f"preflight failed: no-repo-allowlist: {world.repo} has no committed allowlist (.claude/settings.json): "
                        "run /platform:update or cplat adopt")
    assert f.reason() == "preflight failed: no-repo-allowlist"


@pytest.mark.parametrize("layer, kind, rule", [
    ("user", "deny", "Bash(git push:*)"),
    ("project", "ask", "Bash(git commit:*)"),
    ("local", "deny", "Bash(gh pr create:*)"),
    ("user", "deny", "Bash"),
])
def test_a_deny_or_ask_rule_of_any_layer_blocks_the_run(world, layer, kind, rule):  # AC-131.11
    path = dict((n, p) for n, p in world.layers())[layer]
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.is_file() else {}
    data.setdefault("permissions", {}).setdefault(kind, []).append(rule)
    path.write_text(json.dumps(data))
    f = check(world)
    assert f.category == "blocked-by-settings"
    assert f.line().startswith("preflight failed: blocked-by-settings: ")
    assert f'{kind} rule "{rule}" in {layer} settings ({path})' in f.line()
    assert f.reason() == "preflight failed: blocked-by-settings"


def test_an_unrelated_deny_rule_does_not_block(world):  # AC-131.11
    world.user.write_text(json.dumps({"permissions": {"deny": ["Bash(rm -rf:*)", "Read(.env)"]}}))
    assert check(world) is None


def test_no_git_identity(world, monkeypatch):  # AC-131.11
    empty = world.tmp / "gitconfig"
    empty.write_text("")
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git(world.repo, "config", "--unset", "user.name")
    git(world.repo, "config", "--unset", "user.email")
    f = check(world)
    assert f.category == "git-identity"
    assert f.line() == ("preflight failed: git-identity: commit -s needs an author: "
                        "git config --global user.name '<name>' and user.email '<email>'")


def test_gh_is_not_logged_in(world, monkeypatch):  # AC-131.11
    monkeypatch.setenv("FAKE_GH_AUTH", "fail")
    f = check(world)
    assert f.category == "gh-auth"
    assert f.line() == "preflight failed: gh-auth: gh is not logged in for github.com: gh auth login --hostname github.com"


def test_the_account_cannot_push(world, monkeypatch):  # AC-131.11
    git(world.repo, "remote", "set-url", "origin", "https://github.com/acme/shop-api.git")
    monkeypatch.setenv("FAKE_GH_PUSH", "false")
    f = check(world)
    assert f.category == "no-push-access"
    assert f.line().startswith("preflight failed: no-push-access: ")
    assert "cannot push to acme/shop-api: ask for write access to it" in f.line()


def test_a_dropped_network_is_retried_and_never_read_as_no_push_access(world, monkeypatch):  # AC-131.11
    """A network drop during the check once escalated a repo as `cannot push` (system-ship benchmark, 2026-11-09)."""
    import core
    monkeypatch.setattr(core, "sleep", lambda s: None)
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 60)       # conftest turns retries off
    git(world.repo, "remote", "set-url", "origin", "https://github.com/acme/shop-api.git")
    monkeypatch.setenv("FAKE_GH_PUSH", "flaky")
    assert check(world) is None
    monkeypatch.setenv("FAKE_GH_PUSH", "offline")
    f = check(world)
    assert f.category == "no-push-access"
    assert "could not read the push access to acme/shop-api (dial tcp" in f.line()
    assert "ask for write access" not in f.line()


def test_a_dropped_network_is_never_read_as_not_logged_in(world, monkeypatch):  # AC-131.11
    """A network drop during `gh auth status` once escalated a build as `gh-auth` (eval gate, 2026-11-09)."""
    import core
    monkeypatch.setattr(core, "sleep", lambda s: None)
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 60)       # conftest turns retries off
    monkeypatch.setenv("FAKE_GH_AUTH", "flaky")
    assert check(world) is None
    monkeypatch.setenv("FAKE_GH_AUTH", "offline")
    f = check(world)
    assert f.category == "gh-auth"
    assert "could not reach github.com to check the gh login (error connecting to api.github.com)" in f.line()
    assert "gh auth login" not in f.line()


def test_the_first_failure_wins_in_the_documented_order(world, monkeypatch):  # AC-131.11
    monkeypatch.setenv("FAKE_GH_AUTH", "fail")
    monkeypatch.setenv("FAKE_GH_PUSH", "false")
    world.user.write_text(json.dumps({"permissions": {"deny": ["Bash(git push:*)"]}}))
    assert check(world).category == "blocked-by-settings"          # before gh-auth and no-push-access
    (world.repo / ".claude" / "settings.json").unlink()
    assert check(world).category == "no-repo-allowlist"             # before everything else


# ---------------- AC-131.9: nothing is written ----------------

def tree(repo):
    return sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if ".git" not in p.relative_to(repo).parts)


@pytest.mark.parametrize("fail", [False, True])
def test_a_check_changes_no_settings_file_and_creates_nothing(world, monkeypatch, fail):  # AC-131.9
    (world.repo / ".claude" / "settings.local.json").write_text('{"permissions": {"allow": ["Bash(ls)"]}}\n')
    if fail:
        world.user.write_text(json.dumps({"permissions": {"ask": ["Bash(git push:*)"]}}))
    paths = [p for _, p in world.layers()]
    before, files = snapshot_settings(*paths), tree(world.repo)
    f = check(world)
    assert (f is not None) == fail
    assert snapshot_settings(*paths) == before
    assert tree(world.repo) == files
    assert subprocess.run(["git", "status", "--porcelain"], cwd=world.repo, capture_output=True, text=True).stdout == ""


# ---------------- cplat pr open honours the per-run grant ----------------

def test_pr_open_accepts_the_rules_of_cplat_run_allowlist(world, monkeypatch):  # AC-131.8
    import pr_open
    world.repo.joinpath(".claude", "settings.json").write_text("{}")
    assert not pr_open.pr_allowed(world.repo)
    monkeypatch.setenv("CPLAT_RUN_ALLOWLIST", json.dumps(["Bash(gh pr create *)", "Bash(git push origin feature/x)"]))
    assert pr_open.pr_allowed(world.repo)
    monkeypatch.setenv("CPLAT_RUN_ALLOWLIST", "not json")
    assert not pr_open.pr_allowed(world.repo)                          # an invalid value is ignored


def test_a_deny_rule_in_the_files_still_beats_the_run_grant(world, monkeypatch):  # AC-131.10
    import pr_open
    world.repo.joinpath(".claude", "settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(gh pr create:*)"]}}))
    monkeypatch.setenv("CPLAT_RUN_ALLOWLIST", json.dumps(["Bash(gh pr create *)", "Bash(git push origin feature/x)"]))
    assert not pr_open.pr_allowed(world.repo)
