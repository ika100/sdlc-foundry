"""Spec 100: the coordinator model of a headless run (AC-100.1 to AC-100.6)."""
import re
import shlex
import subprocess

import pytest

import core
import headless
from core import PlatformError
from test_headless import repo  # noqa: F401  (fixture)


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """The user settings folder; the project file is written into `repo` by the tests."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path / "config" / "sdlc-foundry"


def user(cfg, text):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.yml").write_text(text)


def project(repo, text):
    (repo / ".platform-settings.yml").write_text(text)


def model_of(repo, capsys, *args, prompt="/svc:build 900"):
    assert headless.main([prompt, "--repo", str(repo), "--dry-run", *args]) == 0
    out = capsys.readouterr().out
    cmd = shlex.split([ln for ln in out.splitlines() if ln.startswith("claude ")][0])
    assert cmd.count("--model") == 1
    return cmd[cmd.index("--model") + 1], out


def test_the_default_coordinator_model_is_sonnet(repo, cfg, capsys):
    """AC-100.1: no flag, no setting: the claude command carries --model sonnet."""
    model, out = model_of(repo, capsys)
    assert model == "sonnet"
    assert "coordinator: sonnet (default)" in out


def test_the_model_flag_is_used_and_opus_is_accepted(repo, cfg, capsys):
    """AC-100.2: --model opus runs the coordinator on opus."""
    model, out = model_of(repo, capsys, "--model", "opus")
    assert model == "opus" and "coordinator: opus (flag)" in out


def test_project_beats_user_and_flag_beats_both(repo, cfg, capsys):
    """AC-100.3: project over user; flag over both."""
    user(cfg, "coordinator_model: haiku\n")
    assert model_of(repo, capsys)[0] == "haiku"
    project(repo, "coordinator_model: opus\n")
    model, out = model_of(repo, capsys)
    assert model == "opus" and "(project)" in out
    assert model_of(repo, capsys, "--model", "sonnet")[0] == "sonnet"


def test_a_per_workflow_map_applies_to_that_workflow_only(repo, cfg, capsys):
    """AC-100.4: build: opus applies to /svc:build; others use default of the map, the user setting or sonnet."""
    project(repo, "coordinator_model:\n  build: opus\n")
    assert model_of(repo, capsys, prompt="/svc:build 900")[0] == "opus"
    assert model_of(repo, capsys, prompt="/svc:quick-task x")[0] == "sonnet"
    user(cfg, "coordinator_model: haiku\n")
    assert model_of(repo, capsys, prompt="/svc:quick-task x")[0] == "haiku"
    project(repo, "coordinator_model:\n  default: opus\n  build: haiku\n")
    assert model_of(repo, capsys, prompt="/svc:quick-task x")[0] == "opus"
    assert model_of(repo, capsys, prompt="/svc:build 1")[0] == "haiku"


@pytest.mark.parametrize("where", ["flag", "project", "user", "project-map", "unused-workflow"])
def test_an_unknown_model_is_refused_before_anything_starts(repo, cfg, where, monkeypatch, capsys):
    """AC-100.5: any name but sonnet, opus, haiku (flag or any setting value) is refused, naming the three, before a run record or a session."""
    started = []
    monkeypatch.setattr(headless.runlog, "start", lambda *a, **k: started.append(a))
    monkeypatch.setattr(headless, "run_once", lambda *a, **k: started.append(a) or 0)
    args = []
    if where == "flag":
        args = ["--model", "gpt-5"]
    elif where == "project":
        project(repo, "coordinator_model: claude-4\n")
    elif where == "user":
        user(cfg, "coordinator_model: Opus\n")
    elif where == "project-map":
        project(repo, "coordinator_model:\n  build: turbo\n")
    else:
        project(repo, "coordinator_model:\n  ship: turbo\n")   # every value is checked, not only the one in use
    for extra in ([], ["--dry-run"]):
        with pytest.raises(PlatformError, match=r"sonnet, opus or haiku") as e:
            headless.main(["/svc:build 900", "--repo", str(repo), *extra, *args])
        assert re.search(r"unknown coordinator model '[^']+'", str(e.value))
    assert started == []


def test_the_model_is_recorded_in_the_run(repo, cfg, monkeypatch):
    """AC-100.1: the run record names the model and where it came from."""
    seen = {}
    monkeypatch.setattr(headless.runlog, "start", lambda *a, **k: "rid")
    monkeypatch.setattr(headless.runlog, "finish", lambda rid, outcome, fields=None, **k: seen.update(fields or {}))
    monkeypatch.setattr(headless, "run_once", lambda *a, **k: 0)
    monkeypatch.setattr(headless.runlog, "phase", lambda *a, **k: None, raising=False)
    headless.main(["/svc:build 900", "--repo", str(repo), "--model", "opus"])
    assert seen.get("coordinator_model") == "opus" and seen.get("coordinator_model_source") == "flag"


@pytest.mark.parametrize("agent", ["architect", "reviewer", "product-manager"])
def test_agents_keep_their_own_model(agent):
    """AC-100.6: the coordinator model does not touch the agents' frontmatter model: opus."""
    text = (core.PLATFORM_ROOT / "plugins" / "svc" / "agents" / f"{agent}.md").read_text()
    assert re.search(r"^model: opus$", text.split("---")[1], re.M)
    assert "--model" not in text
