"""Spec 207 acceptance tests: AC-207.2, the commands a coder subagent runs in its worktree are allowed and matched by no deny
or ask rule (`preflight_rules`, design.md "The coder command sample").

The settings layers are replaced through `preflight.layers`; the committed settings are those of the repo's HEAD.
"""
import json
from pathlib import Path

import pytest

from pf207_support import BASE_SETTINGS, Env, Seams, commit_settings, mod
from units131_support import SPEC_ID, git

RESET = "cplat component build reset 0123abc"
ADD = "git add src/x.py"
COMMIT = 'git commit -s -m "<subject>"'
GIT_RULES = ["Bash(git add *)", "Bash(git commit -s *)", "Bash(git rm *)"]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    e.seams = Seams(tmp_path, monkeypatch)      # installed by `check`: a missing module fails the test, not its fixture
    return e


def pr():
    return mod("preflight_rules")


def agents(*roles):
    pa = mod("preflight_agents")
    return [pa.Agent(role=r, type=f"svc:{r}", path=Path(f"/x/{r}.md"), layer="platform", bash=True, model=None) for r in (roles or ("coder",))]


def check(env, *, allow=None, deny=(), roles=("coder",)):
    env.seams.install()
    env.arm()
    return pr().check(env.repo, [SPEC_ID], agents(*roles), GIT_RULES if allow is None else allow, list(deny))


def set_plan(env, text):
    d = env.repo / "docs" / "specs" / SPEC_ID
    (d / "plan.md").write_text(text)
    git(env.repo, "add", "-A")
    git(env.repo, "commit", "-qm", "plan")


# ---------------- the sample ----------------

def test_the_sample_is_the_reset_the_git_commands_and_the_plans_devbox_scripts_ac_207_2(env):  # AC-207.2
    set_plan(env, "## t1\nRun `devbox run test-fast`, then `devbox run quality` and `devbox run test-fast` again.\n")
    assert pr().coder_commands(env.repo, [SPEC_ID]) == [RESET, ADD, COMMIT, "devbox run test-fast", "devbox run quality"]


def test_a_plan_naming_no_script_falls_back_to_devbox_run_test_ac_207_2(env):  # AC-207.2
    set_plan(env, "## t1\nNothing to run here.\n")
    assert pr().coder_commands(env.repo, [SPEC_ID]) == [RESET, ADD, COMMIT, "devbox run test"]
    assert pr().coder_commands(env.repo, []) == [RESET, ADD, COMMIT, "devbox run test"]


def test_the_sample_reads_the_committed_plan_ac_207_2(env):  # AC-207.2
    set_plan(env, "## t1\n`devbox run lint`\n")
    (env.repo / "docs" / "specs" / SPEC_ID / "plan.md").write_text("`devbox run elsewhere`\n")     # uncommitted
    assert "devbox run lint" in pr().coder_commands(env.repo, [SPEC_ID])
    assert "devbox run elsewhere" not in pr().coder_commands(env.repo, [SPEC_ID])


# ---------------- a pass ----------------

def test_the_commands_are_allowed_by_the_committed_rules_and_the_run_allowlist_ac_207_2(env):  # AC-207.2
    pf = mod("preflight")
    assert check(env, allow=pf.run_allowlist("/component:ship", [f"feature/{SPEC_ID}"])) is None
    assert check(env) is None


# ---------------- deny and ask rules ----------------

@pytest.mark.parametrize("layer", ["managed", "user", "project", "local"])
def test_a_deny_rule_of_any_layer_blocks_the_command_ac_207_2(env, layer):  # AC-207.2
    path = env.set_layer(layer, {"permissions": {"deny": ["Bash(git commit:*)"]}})
    assert check(env) == (f'coder runs "{COMMIT}", which deny rule "Bash(git commit:*)" in {layer} settings ({path}) matches: '
                          'remove or narrow "Bash(git commit:*)"')


def test_an_ask_rule_blocks_the_command_ac_207_2(env):  # AC-207.2
    path = env.set_layer("user", {"permissions": {"ask": ["Bash(git add:*)"]}})
    assert check(env) == (f'coder runs "{ADD}", which ask rule "Bash(git add:*)" in user settings ({path}) matches: '
                          'remove or narrow "Bash(git add:*)"')


def test_a_refused_rule_of_the_run_blocks_the_command_ac_207_2(env):  # AC-207.2
    detail = check(env, deny=["Bash(git add *)"])
    assert detail.startswith(f'coder runs "{ADD}", which deny rule "Bash(git add *)" in run settings (')
    assert detail.endswith(') matches: remove or narrow "Bash(git add *)"')


def test_the_run_allowlist_never_blocks_a_command_ac_207_2(env):  # AC-207.2
    pf = mod("preflight")
    assert check(env, allow=pf.run_allowlist("/component:ship", [f"feature/{SPEC_ID}"]), deny=pf.refused_rules("main")) is None


def test_a_deny_rule_for_the_devbox_script_of_the_plan_blocks_it_ac_207_2(env):  # AC-207.2
    set_plan(env, "`devbox run quality`\n")
    path = env.set_layer("user", {"permissions": {"deny": ["Bash(devbox run quality)"]}})
    assert check(env) == (f'coder runs "devbox run quality", which deny rule "Bash(devbox run quality)" in user settings ({path}) '
                          'matches: remove or narrow "Bash(devbox run quality)"')


# ---------------- the shell as a whole, an agent ----------------

@pytest.mark.parametrize("rule", ["Bash", "Bash(*)"])
def test_a_deny_rule_for_the_whole_shell_blocks_every_agent_ac_207_2(env, rule):  # AC-207.2
    path = env.set_layer("user", {"permissions": {"deny": [rule]}})
    assert check(env) == f'deny rule "{rule}" in user settings ({path}) denies the shell tool to every agent: remove "{rule}"'


@pytest.mark.parametrize("rule", ["Agent(svc:coder)", "Agent(coder)", "Task(svc:coder)", "Task(coder)", "Agent", "Task"])
def test_a_deny_rule_for_an_agent_the_run_starts_blocks_it_ac_207_2(env, rule):  # AC-207.2
    path = env.set_layer("project", {"permissions": {"deny": [rule]}})
    assert check(env) == f'deny rule "{rule}" in project settings ({path}) denies the coder agent this run starts: remove "{rule}"'


def test_a_deny_rule_for_an_agent_the_run_does_not_start_is_ignored_ac_207_2(env):  # AC-207.2
    env.set_layer("user", {"permissions": {"deny": ["Agent(svc:architect)", "Agent(other:coder)"]}})
    assert check(env) is None


def test_the_first_failure_wins_shell_then_agent_then_deny_then_missing_allow_ac_207_2(env):  # AC-207.2
    env.set_layer("managed", {"permissions": {"deny": ["Bash(git add:*)"]}})
    commit_settings(env.repo, {"permissions": {"allow": []}})
    assert "which deny rule" in check(env, allow=[])                        # deny/ask beat a missing allow
    env.set_layer("user", {"permissions": {"deny": ["Agent(coder)"]}})
    assert "denies the coder agent" in check(env, allow=[])                 # an agent deny beats a deny/ask on a command
    env.set_layer("user", {"permissions": {"deny": ["Agent(coder)", "Bash"]}})
    assert "denies the shell tool to every agent" in check(env, allow=[])   # the shell beats an agent


# ---------------- a missing allow rule ----------------

@pytest.mark.parametrize("have, command, pattern", [
    ([], RESET, "Bash(cplat component build reset *)"),
    (["Bash(cplat *)"], ADD, "Bash(git add *)"),
    (["Bash(cplat *)", "Bash(git add *)"], COMMIT, "Bash(git commit -s *)"),
    (["Bash(cplat *)", "Bash(git add *)", "Bash(git commit -s *)"], "devbox run test", "Bash(devbox run test)"),
])
def test_a_command_no_allow_rule_permits_names_the_rule_to_add_ac_207_2(env, have, command, pattern):  # AC-207.2
    commit_settings(env.repo, {"permissions": {"allow": have}})
    assert check(env, allow=[]) == (f'coder runs "{command}", which no allow rule permits: add "{pattern}" to permissions.allow '
                                    f"in {env.repo}/.claude/settings.json")


def test_the_run_allowlist_supplies_the_missing_allow_rules_ac_207_2(env):  # AC-207.2
    commit_settings(env.repo, {"permissions": {"allow": ["Bash(cplat *)", "Bash(devbox run *)"]}})
    assert check(env, allow=[]) is not None
    assert check(env, allow=GIT_RULES) is None


def test_a_script_the_plan_names_needs_its_own_allow_rule_ac_207_2(env):  # AC-207.2
    set_plan(env, "`devbox run quality`\n")
    commit_settings(env.repo, {"permissions": {"allow": ["Bash(cplat *)", "Bash(devbox run test)"]}})
    assert check(env) == ('coder runs "devbox run quality", which no allow rule permits: add "Bash(devbox run quality)" to '
                          f"permissions.allow in {env.repo}/.claude/settings.json")


def test_only_the_committed_allow_rules_count_not_the_working_file_ac_207_2(env):  # AC-207.2
    commit_settings(env.repo, {"permissions": {"allow": ["Bash(cplat *)"]}})
    (env.repo / ".claude" / "settings.json").write_text(json.dumps(BASE_SETTINGS))          # an edit nobody committed
    assert 'no allow rule permits: add "Bash(devbox run test)"' in check(env)


def test_local_allow_rules_count_only_in_a_trusted_folder_ac_207_2(env):  # AC-207.2
    seams = env.seams.install()
    commit_settings(env.repo, {"permissions": {"allow": ["Bash(cplat *)"]}})
    env.set_layer("local", {"permissions": {"allow": ["Bash(devbox run *)"]}})
    assert 'no allow rule permits: add "Bash(devbox run test)"' in check(env)
    seams.trust(env.repo)
    assert check(env) is None


def test_user_and_managed_allow_rules_count_ac_207_2(env):  # AC-207.2
    commit_settings(env.repo, {"permissions": {"allow": ["Bash(cplat *)"]}})
    env.set_layer("user", {"permissions": {"allow": ["Bash(devbox run *)"]}})
    assert check(env) is None
    env.set_layer("user", {})
    env.set_layer("managed", {"permissions": {"allow": ["Bash(devbox run test)"]}})
    assert check(env) is None


def test_the_check_writes_nothing_ac_207_2(env):  # AC-207.2
    env.set_layer("local", {"permissions": {"allow": ["Bash(ls)"]}})
    before = {p: p.read_bytes() for _, p in env.layers() if p.is_file()}
    check(env)
    assert {p: p.read_bytes() for _, p in env.layers() if p.is_file()} == before
    assert git(env.repo, "status", "--porcelain") == ""
