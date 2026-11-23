"""#941: a repository's commands never see cplat's own Python environment: `core.repo_env()` drops VIRTUAL_ENV and that
environment's bin from PATH when they are cplat's (sys.prefix), and keeps a VIRTUAL_ENV of anything else."""
import os
import sys

import core


def test_cplat_own_venv_and_its_bin_are_dropped(monkeypatch):
    own_bin = os.path.join(sys.prefix, "bin")
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    monkeypatch.setenv("VIRTUAL_ENV_PROMPT", "cplat")
    monkeypatch.setenv("PATH", os.pathsep.join([own_bin, "/usr/local/bin", "/usr/bin"]))
    env = core.repo_env()
    assert "VIRTUAL_ENV" not in env and "VIRTUAL_ENV_PROMPT" not in env
    assert env["PATH"].split(os.pathsep) == ["/usr/local/bin", "/usr/bin"]


def test_another_virtualenv_is_left_alone(monkeypatch, tmp_path):
    other = tmp_path / "venv"
    monkeypatch.setenv("VIRTUAL_ENV", str(other))
    monkeypatch.setenv("PATH", os.pathsep.join([str(other / "bin"), "/usr/bin"]))
    env = core.repo_env()
    assert env["VIRTUAL_ENV"] == str(other) and env["PATH"].startswith(str(other / "bin"))


def test_extra_still_wins(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    monkeypatch.setenv("CPLAT_RUN", "x")
    env = core.repo_env({"VIRTUAL_ENV": "/set/on/purpose", "CPLAT_REPEAT_RUN": "1"})
    assert env["VIRTUAL_ENV"] == "/set/on/purpose" and env["CPLAT_REPEAT_RUN"] == "1" and "CPLAT_RUN" not in env
