"""Spec 184 acceptance tests: a land session may read why its check went red (AC-184.4).

Seams: `preflight.run_allowlist` / `refused_rules` / `matches` / `log_dir_rule` / `ci_log_dir` (design.md, Contract, "Land allowlist") and
the allowlist block and the command line of `cplat headless --dry-run` (the fake world of spec 131).
"""
import os
from pathlib import Path

import pytest

import preflight
from units131_support import BRANCH, World

LOGS = Path("/var/tmp/ci-logs/shop-api")
GH = ["Bash(gh run view * --log-failed)", "Bash(gh run view * --log-failed -R *)", "Bash(gh run view * -R * --log-failed)"]
LAND = ["/component:ship", "/system:ship"]
REFUSED_BEFORE = [
    "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push * --force*)", "Bash(git push * -f*)", "Bash(git push * +*)",
    "Bash(git push * main)", "Bash(git push * main:*main*)", "Bash(git push * main:refs*)", "Bash(git push * *:main)",
    "Bash(git push * *:refs/heads/main)", "Bash(gh pr merge*)", "Bash(gh api *merge*)", "Bash(cplat pr wait *--merge*)",
    "Bash(git rm -f*)", "Bash(git rm --force*)", "Bash(git rm -rf*)", "Bash(git rm -fr*)", "Bash(git rm * -f*)",
    "Bash(git rm * --force*)", "Bash(git rm * -rf*)", "Bash(git rm * -fr*)"]


def allowed(rules, cmd):
    return any(preflight.matches(r, cmd) for r in rules)


@pytest.mark.parametrize("command", LAND)
def test_a_land_run_gets_the_ci_log_folder_and_gh_run_view_log_failed_after_the_land_rules_ac_184_4(command):  # AC-184.4
    before = preflight.run_allowlist(command, [BRANCH])
    rules = preflight.run_allowlist(command, [BRANCH], [LOGS, Path("/var/tmp/ci-logs/other")])
    assert rules[:len(before)] == before
    assert rules[len(before):] == ["Read(//var/tmp/ci-logs/shop-api/**)", "Read(//var/tmp/ci-logs/other/**)", *GH]


def test_a_log_folder_under_the_home_is_written_with_a_tilde_ac_184_4():  # AC-184.4
    assert preflight.log_dir_rule(Path.home() / ".cache" / "sdlc-foundry" / "logs" / "shop-api") == \
        "Read(~/.cache/sdlc-foundry/logs/shop-api/**)"
    assert preflight.log_dir_rule(Path("/var/tmp/x")) == "Read(//var/tmp/x/**)"


def test_the_ci_log_folder_is_where_cplat_saves_the_failed_check_logs_ac_184_4(tmp_path, monkeypatch):  # AC-184.4
    import quiet
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    repo = tmp_path / "shop-api"
    repo.mkdir()
    want = preflight.ci_log_dir(repo)
    assert want == tmp_path / "cache" / "sdlc-foundry" / "logs" / "shop-api"
    assert not want.exists()                                                     # asking creates nothing
    assert quiet._log_path(repo, "test-fast").parent == want                      # the folder spec 108 writes in
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert preflight.ci_log_dir(repo) == Path.home() / ".cache" / "sdlc-foundry" / "logs" / "shop-api"


@pytest.mark.parametrize("command", LAND)
@pytest.mark.parametrize("cmd", ["gh run view 123 --log-failed", "gh run view 123 --log-failed -R acme/shop-api",
                                 "gh run view 123 -R acme/shop-api --log-failed", "gh run view 98765432101 --log-failed"])
def test_the_failed_log_of_a_run_may_be_read_with_or_without_the_repo_ac_184_4(command, cmd):  # AC-184.4
    assert allowed(preflight.run_allowlist(command, [BRANCH], [LOGS]), cmd)


@pytest.mark.parametrize("command", LAND)
@pytest.mark.parametrize("cmd", ["gh run rerun 123", "gh run rerun 123 --failed", "gh run cancel 123", "gh run delete 123",
                                 "gh run watch 123", "gh run view 123", "gh run view 123 --log", "gh run list",
                                 "gh run download 123", "gh api repos/acme/shop-api/actions/runs/123",
                                 "gh api repos/acme/shop-api/actions/runs/123/rerun", "gh run view 123 --web"])
def test_no_other_gh_run_or_gh_api_command_is_allowed_ac_184_4(command, cmd):  # AC-184.4
    assert not allowed(preflight.run_allowlist(command, [BRANCH], [LOGS]), cmd)


@pytest.mark.parametrize("command", LAND)
def test_the_only_gh_run_or_gh_api_rules_are_the_three_view_rules_ac_184_4(command):  # AC-184.4
    rules = preflight.run_allowlist(command, [BRANCH], [LOGS])
    assert [r for r in rules if r.startswith(("Bash(gh run", "Bash(gh api"))] == GH


def test_a_build_gets_none_of_them_ac_184_4():  # AC-184.4
    assert preflight.run_allowlist("/component:build", [BRANCH], [LOGS]) == preflight.run_allowlist("/component:build", [BRANCH])


def test_the_refused_rules_stay_as_before_and_match_none_of_the_new_rules_ac_184_4():  # AC-184.4
    assert preflight.refused_rules("main") == REFUSED_BEFORE
    for command in LAND:
        for rule in preflight.run_allowlist(command, [BRANCH], [LOGS]):
            sample = rule[5:-1].replace("*", "x")
            if rule.startswith("Bash("):
                assert not any(preflight.matches(r, sample) for r in preflight.refused_rules("main")), rule
    preflight._self_check()


# ---------------- cplat headless --dry-run ----------------

@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=True)


def saved_logs_rule(repo):
    """The Read rule of the folder `cplat quiet` saves its logs in, built from XDG_CACHE_HOME and `quiet._log_path` alone."""
    import quiet
    folder = quiet._log_path(repo, "test-fast").parent
    assert folder == Path(os.environ["XDG_CACHE_HOME"]) / "sdlc-foundry" / "logs" / repo.name
    try:
        return f"Read(~/{folder.relative_to(Path.home())}/**)"
    except ValueError:
        return f"Read(//{str(folder).lstrip('/')}/**)"


def block_of(out):
    return [ln[2:] for ln in out.splitlines() if ln.startswith("  ")]


def test_the_dry_run_of_a_ship_shows_the_log_folder_and_the_view_rules_ac_184_4(w, capsys):  # AC-184.4
    assert w.run("--dry-run") == 0
    out = capsys.readouterr().out
    folder = saved_logs_rule(w.repo)
    assert folder.endswith("/sdlc-foundry/logs/shop-api/**)")
    block = block_of(out)
    assert folder in block and all(r in block for r in GH)
    assert block.index(folder) > block.index("Bash(cplat component ship land *)")
    assert not [r for r in block if r.startswith(("Bash(gh run", "Bash(gh api")) and r not in GH]
    assert "refused: " + ", ".join(preflight.refused_rules("main")) in out.splitlines()
    assert w.run("--dry-run", prompt="/component:build 7") == 0                  # a build gets none of them
    build = block_of(capsys.readouterr().out)
    assert build and not any(r.startswith(("Read(//", "Bash(gh run")) for r in build)


def test_every_session_of_a_ship_is_granted_them_ac_184_4(w):  # AC-184.4
    assert w.run() == 0
    folder = saved_logs_rule(w.repo)
    for s in w.sessions():
        argv = s["argv"]
        granted = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
        assert folder in granted and all(r in granted for r in GH)
        assert folder in s["allowlist"]
