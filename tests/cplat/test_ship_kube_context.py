"""`cplat ship deploy` takes the kube context from configuration when none is passed (AC-091.11, AC-105.1).

Headless coordinators did not pass `--context`, so a ship benchmark against a real cluster skipped Argo, smoke and the digest
check. Order: `--context`, the product link, `CPLAT_KUBE_CONTEXT`, `kube_context:` in .platform-settings.yml, then the user
settings file. A context is never guessed from kubectl.
"""
from __future__ import annotations

import pytest

import settings
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import clock as run_clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship_checks import gh  # noqa: F401  (fixture)
from test_smoke_091_ship import BASE, PASS_ALL, in_order, lines_of, repo, world  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def no_user_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CPLAT_KUBE_CONTEXT", raising=False)


def test_nothing_configured_gives_no_context(tmp_path):
    """AC-091.11: no flag and no setting → no context (deploy then reports smoke as not run)."""
    assert settings.kube_context(tmp_path) == (None, None)


def test_the_environment_wins_over_the_files(tmp_path, monkeypatch):
    """AC-091.11: CPLAT_KUBE_CONTEXT, then the project file, then the user file."""
    (tmp_path / ".platform-settings.yml").write_text("kube_context: from-project\n")
    user = tmp_path / "xdg" / "sdlc-foundry"
    user.mkdir(parents=True)
    (user / "settings.yml").write_text("kube_context: from-user\n")
    assert settings.kube_context(tmp_path) == ("from-project", "project")
    (tmp_path / ".platform-settings.yml").unlink()
    assert settings.kube_context(tmp_path) == ("from-user", "user")
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "from-env")
    assert settings.kube_context(tmp_path) == ("from-env", "CPLAT_KUBE_CONTEXT")


def test_a_non_string_setting_is_refused(tmp_path):
    """AC-091.11: a malformed kube_context names the file."""
    (tmp_path / ".platform-settings.yml").write_text("kube_context: [a, b]\n")
    with pytest.raises(Exception) as e:
        settings.kube_context(tmp_path)
    assert ".platform-settings.yml" in str(e.value)


def test_deploy_without_a_flag_uses_the_configured_context(world, capsys, monkeypatch):
    """AC-091.11 / AC-105.1: with CPLAT_KUBE_CONTEXT set, deploy checks Argo and runs smoke as if --context was passed."""
    world.install()
    world.fake.script([PASS_ALL])
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "lan")
    import ship
    said: list[str] = []
    monkeypatch.setattr(ship, "say", said.append)
    assert world.deploy(context=None) == 0
    assert "kube context: lan (CPLAT_KUBE_CONTEXT)" in said
    in_order(lines_of(capsys), "Argo CD shop-api-dev: Synced/Healthy", f"smoke (dev) against {BASE}:", "Smoke (dev): 2/2 passed")
    assert world.record()["smoke"]["outcome"] == "passed"


def test_an_explicit_flag_wins_over_the_configured_context(world, capsys, monkeypatch):
    """AC-091.11: --context beats CPLAT_KUBE_CONTEXT."""
    world.install()
    world.fake.script([PASS_ALL])
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "elsewhere")
    assert world.deploy() == 0          # the harness passes --context lan
    assert not any("kube context: elsewhere" in line for line in lines_of(capsys))
