"""A detached cplat command never runs on uv's temporary Python, which uv deletes when its `uv run` parent exits (#1122)."""
import sys

import pytest

import dispatch_units as du

EPHEMERAL = "/home/u/.cache/uv/builds-v0/.tmpAbC123/bin/python"


def test_stable_interpreter_is_used_as_is(monkeypatch):
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    assert du.cplat_cmd() == ["/usr/bin/python3", str(du.CPLAT)]


def test_ephemeral_interpreter_goes_through_uv_script(monkeypatch):
    monkeypatch.setattr(sys, "executable", EPHEMERAL)
    cmd = du.cplat_cmd()
    assert cmd == ["bash", str(du.UV_SCRIPT), str(du.CPLAT)]
    assert not any(du.ephemeral(a) for a in cmd)


def test_detach_refuses_an_ephemeral_path(tmp_path):
    with pytest.raises(OSError, match="temporary Python"):
        du._detach([EPHEMERAL, "cplat.py"], tmp_path, {}, tmp_path / "log")
