"""A shared render builds with git auto-maintenance off and leaves the environment as it was."""
from __future__ import annotations

import os

from shared_render import SharedRenders


def _config(env) -> dict[str, str]:
    n = int(env.get("GIT_CONFIG_COUNT") or 0)
    return {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(n)}


def test_build_runs_with_auto_maintenance_off_and_env_is_restored(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "x")
    before = dict(os.environ)
    seen: dict[str, str] = {}

    def build(workdir):
        seen.update(_config(os.environ))
        return workdir

    SharedRenders(tmp_path / "r").copy("k", build, tmp_path / "dest")
    assert seen["maintenance.auto"] == "false"
    assert seen["gc.auto"] == "0"
    assert seen["user.name"] == "x"
    assert dict(os.environ) == before
