"""Spec 207 acceptance tests: AC-207.3 (every agent that runs shell commands resolves to a definition that grants the shell tool)
and AC-207.5 (a model the managed or user settings exclude fails without a model call), in `preflight_agents` (design.md).
"""
import json
import subprocess
from pathlib import Path

import pytest

import core
import shapecmd
from pf207_support import Env, Seams, agent_text, commit_settings, mod, plugin_dir, write_agent
from units131_support import make_repo

CODER = ("coder", "svc:coder")


@pytest.fixture()
def s(tmp_path, monkeypatch):
    return Seams(tmp_path, monkeypatch)


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def pa():
    return mod("preflight_agents")


def agent(role="coder", layer="project", bash=True, model=None, path="/x/coder.md"):
    return pa().Agent(role=role, type=f"svc:{role}", path=Path(path), layer=layer, bash=bash, model=model)


# ---------------- AC-207.3: which agents a command starts ----------------

def test_a_build_starts_five_agents_and_a_ship_adds_the_deployment_agent_ac_207_3(s, repo):  # AC-207.3
    s.install()
    build = pa().roles(repo, "/component:build")
    assert [r for r, _ in build] == ["coder", "tester", "reviewer", "security", "quality"]
    assert dict(build)["reviewer"] == "svc:reviewer" and dict(build)["quality"] == "shared:quality"
    assert dict(build)["security"] == "shared:security"
    ship = pa().roles(repo, "/component:ship")
    assert [r for r, _ in ship][:5] == ["coder", "tester", "reviewer", "security", "quality"]
    assert "deployment" in dict(ship)                         # the service-go shape is deployable


def test_a_gitops_folder_starts_no_coder_ac_207_3(s, tmp_path, monkeypatch):  # AC-207.3
    s.install()
    ops = tmp_path / "gitops"
    ops.mkdir()
    route = {"shape": "gitops-app", "plugin": "app", "agents": {"coder": "app:coder"},
             "unsupported": "/component:* commands do not apply to a gitops-app repo"}
    monkeypatch.setattr(shapecmd, "route", lambda folder: route)
    assert pa().roles(ops, "/system:ship") == []


def test_a_folder_without_a_shape_uses_the_svc_and_shared_agents_ac_207_3(s, tmp_path, monkeypatch):  # AC-207.3
    s.install()
    bare = tmp_path / "bare"
    bare.mkdir()

    def no_shape(folder):
        raise core.PlatformError("cannot determine the repo's shape")
    monkeypatch.setattr(shapecmd, "route", no_shape)
    got = dict(pa().roles(bare, "/component:ship"))
    assert got == {"coder": "svc:coder", "tester": "svc:tester", "reviewer": "svc:reviewer",
                   "security": "shared:security", "quality": "shared:quality"}


# ---------------- AC-207.3: the winning definition ----------------

def test_a_repo_override_without_bash_wins_and_fails_ac_207_3(s, repo):  # AC-207.3
    s.install()
    f = write_agent(repo, "coder", tools="Read, Write, Edit")
    a = pa().resolve(repo, *CODER, [])
    assert (a.role, a.type, a.path, a.layer, a.bash) == ("coder", "svc:coder", f, "project", False)
    assert pa().check_definitions([agent("tester"), a, agent("reviewer", bash=False)]) == (
        f"coder resolves to {f} (project definition), which does not grant Bash: add Bash to its tools, or remove the override")


def test_definitions_that_grant_bash_pass_ac_207_3(s):  # AC-207.3
    s.install()
    assert pa().check_definitions([agent("coder"), agent("tester")]) is None
    assert pa().check_definitions([]) is None


def test_the_override_is_found_by_role_or_by_type_ac_207_3(s, repo):  # AC-207.3
    s.install()
    f = write_agent(repo, "whatever", name="svc:coder", tools="Read")
    a = pa().resolve(repo, *CODER, [])
    assert a.path == f and a.bash is False


@pytest.mark.parametrize("tools, extra, bash", [
    (None, "", True),                                   # no tools line: every tool
    ("Read, Bash", "", True),
    ("Read, Bash(git:*)", "", True),
    ("[Read, Bash]", "", True),
    ("Read, Write", "", False),
    ("Read, Bash", "disallowedTools: Bash", False),
])
def test_the_shell_grant_follows_tools_and_disallowed_tools_ac_207_3(s, repo, tools, extra, bash):  # AC-207.3
    s.install()
    write_agent(repo, "coder", tools=tools, extra=extra)
    assert pa().resolve(repo, *CODER, []).bash is bash


def test_the_definition_lookup_order_ac_207_3(s, repo, tmp_path):  # AC-207.3
    s.install()
    platform_def = core.PLATFORM_ROOT / "plugins" / "svc" / "agents" / "coder.md"
    a = pa().resolve(repo, *CODER, [])
    assert (a.layer, a.path) == ("platform", platform_def)
    installed = s.install_plugin("svc@market", agents={"coder": agent_text("coder")})
    a = pa().resolve(repo, *CODER, [])
    assert (a.layer, a.path) == ("installed", installed / "agents" / "coder.md")
    d = plugin_dir(tmp_path, "svc", agents={"coder": agent_text("coder", tools="Read")})
    a = pa().resolve(repo, *CODER, [str(d)])
    assert (a.layer, a.path, a.bash) == ("plugin-dir", d / "agents" / "coder.md", False)
    user = s.user_agents() / "coder.md"
    user.write_text(agent_text("coder"))
    a = pa().resolve(repo, *CODER, [str(d)])
    assert (a.layer, a.path) == ("user", user)
    proj = write_agent(repo, "coder")
    a = pa().resolve(repo, *CODER, [str(d)])
    assert (a.layer, a.path) == ("project", proj)


def test_an_installed_plugin_of_the_marketplace_the_repo_enables_is_preferred_ac_207_3(s, repo):  # AC-207.3
    s.install()
    s.install_plugin("svc@other", agents={"coder": agent_text("coder")})
    wanted = s.install_plugin("svc@market", agents={"coder": agent_text("coder")})
    commit_settings(repo, enabledPlugins={"svc@market": True})
    a = pa().resolve(repo, *CODER, [])
    assert (a.layer, a.path) == ("installed", wanted / "agents" / "coder.md")


# ---------------- AC-207.5: the model of each agent ----------------

@pytest.mark.parametrize("model, expected", [("opus", "opus"), ("claude-sonnet-4-5", "claude-sonnet-4-5"), ("inherit", None), (None, None)])
def test_the_model_of_an_agent_is_its_definitions_or_inherited_ac_207_5(s, repo, model, expected):  # AC-207.5
    s.install()
    write_agent(repo, "coder", model=model)
    assert pa().resolve(repo, *CODER, []).model == expected


def test_the_subagent_model_variable_replaces_every_model_ac_207_5(s, repo, monkeypatch):  # AC-207.5
    s.install()
    write_agent(repo, "coder", model="opus")
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "haiku")
    assert pa().resolve(repo, *CODER, []).model == "haiku"


def test_models_groups_the_roles_by_model_with_the_coordinator_first_ac_207_5():  # AC-207.5
    folder = Path("/x")
    got = pa().models({folder: [agent("coder"), agent("reviewer", model="opus"), agent("tester")]}, "sonnet")
    assert list(got.items()) == [("sonnet", ["coordinator", "coder", "tester"]), ("opus", ["reviewer"])]
    assert pa().models({folder: [agent("coder"), agent("reviewer", model="opus")]}, None) == {"opus": ["reviewer"]}


# ---------------- AC-207.5: models the settings exclude ----------------

MODELS = {"opus": ["coordinator", "reviewer"], "sonnet": ["coder"]}


def test_a_model_the_available_models_list_leaves_out_fails_without_a_call_ac_207_5(s, env):  # AC-207.5
    s.install()
    env.arm()
    path = env.set_layer("managed", {"availableModels": ["sonnet"]})
    assert pa().check_models(MODELS, env.repo) == (
        f"opus (used by coordinator, reviewer) is not in availableModels of managed settings ({path}): "
        "add opus to availableModels, or set a model the settings allow")
    assert s.calls == []


def test_a_denied_model_fails_without_a_call_ac_207_5(s, env):  # AC-207.5
    s.install()
    env.arm()
    path = env.set_layer("user", {"deniedModels": ["sonnet"]})
    assert pa().check_models(MODELS, env.repo) == (
        f"sonnet (used by coder) is in deniedModels of user settings ({path}): "
        "remove sonnet from deniedModels, or set a model the settings allow")
    assert s.calls == []


def test_the_managed_layer_is_checked_before_the_user_layer_ac_207_5(s, env):  # AC-207.5
    s.install()
    env.arm()
    env.set_layer("user", {"deniedModels": ["opus"]})
    managed = env.set_layer("managed", {"deniedModels": ["opus"]})
    assert f"deniedModels of managed settings ({managed})" in pa().check_models(MODELS, env.repo)


@pytest.mark.parametrize("layer, key, listed, model, excluded", [
    ("user", "availableModels", ["opus"], "claude-opus-4-5", False),     # an alias matches a full id by word
    ("user", "availableModels", ["claude-opus-4-5"], "opus", False),
    ("user", "availableModels", ["claude-opus-4-5"], "sonnet", True),
    ("user", "deniedModels", ["opus"], "claude-opus-4-5", True),
    ("user", "deniedModels", ["claude-opus-4-5"], "opus", True),
    ("user", "deniedModels", ["opus"], "claude-sonnet-4-5", False),
    ("managed", "availableModels", ["claude-sonnet-4-5"], "claude-sonnet-4-5", False),
    ("managed", "deniedModels", ["claude-sonnet-4-5"], "claude-sonnet-4-6", False),
])
def test_alias_and_full_id_matching_ac_207_5(s, env, layer, key, listed, model, excluded):  # AC-207.5
    s.install()
    env.arm()
    env.set_layer(layer, {key: listed})
    detail = pa().check_models({model: ["coder"]}, env.repo)
    assert (detail is not None) is excluded
    assert s.calls == []


def test_settings_without_model_lists_exclude_nothing_ac_207_5(s, env):  # AC-207.5
    s.install()
    env.arm()
    env.set_layer("user", {"permissions": {"allow": []}})
    assert pa().check_models(MODELS, env.repo) is None
    assert json.loads(env.user.read_text()) == {"permissions": {"allow": []}}
    assert subprocess.run(["git", "status", "--porcelain"], cwd=env.repo, capture_output=True, text=True).stdout == ""
