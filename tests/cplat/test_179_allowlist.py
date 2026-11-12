"""Spec 179 acceptance tests: a run session may `git rm` what the repo tracks (AC-179.3).

Seams: `preflight.run_allowlist` / `refused_rules` / `matches` (the supervisor's list and the matcher the platform and
`_self_check` use), a real `git rm` in a temp repo, and `spec.test_diff` for a removed frozen acceptance test.
"""
import subprocess

import pytest

import preflight
import spec
from test_160_lint_suppressions import built, g  # noqa: F401  (fixture, helper)

B = "feature/179-unattended-runs-ask-less"
COMMANDS = ["/component:build", "/component:ship", "/system:ship"]


def allowed(command, cmd):
    return any(preflight.matches(r, cmd) for r in preflight.run_allowlist(command, [B]))


def refused(cmd):
    return [r for r in preflight.refused_rules("main") if preflight.matches(r, cmd)]


@pytest.mark.parametrize("command", COMMANDS)
def test_the_run_allowlist_names_git_rm_right_after_the_commit_ac_179_3(command):  # AC-179.3
    rules = preflight.run_allowlist(command, [B])
    assert "Bash(git rm *)" in rules
    assert rules.index("Bash(git rm *)") == rules.index("Bash(git commit -s *)") + 1


@pytest.mark.parametrize("cmd", ["git rm src/a.py", "git rm -r src/old", "git rm src/my-file.py", "git rm a.py b.py",
                                 "git rm --cached a.py", "git rm -r --cached src"])
def test_a_plain_git_rm_is_allowed_and_matches_no_refused_rule_ac_179_3(cmd):  # AC-179.3
    assert all(allowed(c, cmd) for c in COMMANDS)
    assert refused(cmd) == []


@pytest.mark.parametrize("cmd", ["git rm -f a", "git rm -rf d", "git rm -r -f d", "git rm --force a", "git rm -fr d", "git rm a -f",
                                 "git rm d -rf", "git rm d -fr", "git rm a --force"])
def test_a_forced_git_rm_matches_a_refused_rule_ac_179_3(cmd):  # AC-179.3
    assert refused(cmd), cmd


def test_the_forced_forms_are_on_the_refused_list_and_not_in_the_allowlist_ac_179_3():  # AC-179.3
    rules = preflight.refused_rules("main")
    for r in ("Bash(git rm -f*)", "Bash(git rm --force*)", "Bash(git rm -rf*)", "Bash(git rm -fr*)", "Bash(git rm * -f*)",
              "Bash(git rm * --force*)", "Bash(git rm * -rf*)", "Bash(git rm * -fr*)"):
        assert r in rules, r
    allow = [r for c in COMMANDS for r in preflight.run_allowlist(c, [B])]
    assert not set(allow) & set(rules)
    # the push rules stay in front of the new ones
    assert rules.index("Bash(cplat pr wait *--merge*)") < rules.index("Bash(git rm -f*)")


def test_the_self_check_of_the_module_still_passes_ac_179_3():  # AC-179.3
    preflight._self_check()
    for command in COMMANDS:
        for rule in preflight.run_allowlist(command, [B]):
            sample = rule[5:-1].replace("*", "x")
            assert not refused(sample), (rule, sample)


def test_git_removes_a_tracked_file_and_a_tracked_directory_and_refuses_an_untracked_one_ac_179_3(tmp_path):  # AC-179.3
    root = tmp_path / "r"
    (root / "src" / "old").mkdir(parents=True)
    g("init", "-q", "-b", "main", cwd=root)
    (root / "src" / "a.py").write_text("x = 1\n")
    (root / "src" / "old" / "b.py").write_text("y = 1\n")
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base", cwd=root)
    (root / "untracked.py").write_text("z = 1\n")
    # the commands a session runs are the ones the allowlist grants
    for cmd in ("git rm src/a.py", "git rm -r src/old", "git rm untracked.py", "git rm ../outside.py"):
        assert allowed("/component:build", cmd), cmd
    assert subprocess.run(["git", "rm", "src/a.py"], cwd=root, capture_output=True).returncode == 0
    assert subprocess.run(["git", "rm", "-r", "src/old"], cwd=root, capture_output=True).returncode == 0
    assert not (root / "src" / "a.py").exists() and not (root / "src" / "old").exists()
    assert subprocess.run(["git", "rm", "untracked.py"], cwd=root, capture_output=True).returncode != 0   # git refuses
    assert (root / "untracked.py").exists()
    outside = tmp_path / "outside.py"
    outside.write_text("o = 1\n")
    assert subprocess.run(["git", "rm", str(outside)], cwd=root, capture_output=True).returncode != 0
    assert outside.exists()


def test_removing_a_frozen_acceptance_test_is_still_flagged_by_the_test_diff_ac_179_3(built):  # AC-179.3
    root, t = built
    g("rm", "-q", "tests/test_alerts.py", cwd=root)
    good, why = spec.test_diff(root, "HEAD", ["tests/test_alerts.py"])["tests/test_alerts.py"]
    assert not good and why == "new or deleted file"
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", "tests/test_alerts.py"]) == 1


def test_git_rm_is_a_rule_of_the_allowlist_in_the_build_prompt_ac_179_3():  # AC-179.3
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "plugins" / "component" / "commands" / "build.md").read_text()
    assert "git rm" in text
