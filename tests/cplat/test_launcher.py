"""plugins/shared/bin/cplat (STORY-042): commands run the platform script at the installed plugins' version, offline."""
import os
import shutil
import subprocess

import pytest

import core

ROOT = core.PLATFORM_ROOT
LAUNCHER = ROOT / "plugins" / "shared" / "bin" / "cplat"
pytestmark = pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")


def fetched(tmp_path):
    """The launcher fetched the platform (uv keeps its own package cache in the same XDG cache dir)."""
    return any((tmp_path / "cache").glob("sdlc-foundry*"))


def run(launcher, tmp_path, **env):
    full = {k: v for k, v in os.environ.items() if not k.startswith("CPLAT_")} | {"XDG_CACHE_HOME": str(tmp_path / "cache")} | env
    return subprocess.run([str(launcher), "spec", "--repo", str(tmp_path), "list"], capture_output=True, text=True, env=full)


def test_in_place_plugin_uses_its_own_repo(tmp_path):
    out = run(LAUNCHER, tmp_path)
    assert out.returncode == 0, out.stderr
    assert "no open specs" in out.stdout and not fetched(tmp_path)


def test_installed_plugin_uses_the_marketplace_checkout_without_network(tmp_path):
    plugins = tmp_path / "home" / ".claude" / "plugins"
    installed = plugins / "cache" / "my-mkt" / "shared" / "9.9.9" / "bin"
    installed.mkdir(parents=True)
    shutil.copy(LAUNCHER, installed / "cplat")
    (plugins / "marketplaces").mkdir()
    (plugins / "marketplaces" / "my-mkt").symlink_to(ROOT)
    out = run(installed / "cplat", tmp_path)
    assert out.returncode == 0, out.stderr
    assert "no open specs" in out.stdout and not fetched(tmp_path)


def test_an_explicit_platform_checkout_wins(tmp_path):
    lone = tmp_path / "lone" / "bin"
    lone.mkdir(parents=True)
    shutil.copy(LAUNCHER, lone / "cplat")  # no repo and no marketplace around it: would otherwise fetch main
    out = run(lone / "cplat", tmp_path, CPLAT_PLATFORM=str(ROOT))
    assert out.returncode == 0, out.stderr
    assert not fetched(tmp_path)


def test_the_shared_plugin_allows_the_launcher():
    settings = (ROOT / "plugins" / "shared" / "settings.json").read_text()
    assert '"Bash(cplat *)"' in settings and os.access(LAUNCHER, os.X_OK)


def test_the_launcher_tells_doctor_where_the_scripts_came_from(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CPLAT_")} | {"XDG_CACHE_HOME": str(tmp_path / "cache")}
    out = subprocess.run([str(LAUNCHER), "platform", "doctor", "--json"], capture_output=True, text=True, env=env)
    rows = {r["name"]: r for r in __import__("json").loads(out.stdout)}
    assert rows["platform scripts"]["status"] == "ok" and rows["platform scripts"]["detail"].startswith("in-place: ")


@pytest.mark.parametrize("source, status", [("", "warn"), ("main /c/sdlc-foundry", "warn"), ("marketplace /m", "ok"), ("ref v4.0.0 /r", "ok")])
def test_doctor_rates_the_platform_source(monkeypatch, source, status):
    import doctor
    monkeypatch.setenv("CPLAT_SOURCE", source)
    assert doctor.check_platform_source()[0]["status"] == status


def test_no_command_fetches_the_platform_itself():
    """Commands call `cplat`; the clone-and-fetch prefix that pinned every run to `main` must not come back."""
    stale = [str(p.relative_to(ROOT)) for p in (ROOT / "plugins").glob("*/commands/*.md")
             if "sdlc-foundry.git" in p.read_text() or "XDG_CACHE_HOME" in p.read_text()]
    assert stale == []


def test_the_platform_runs_its_own_specs():
    import spec
    specs = spec.all_specs(ROOT)
    assert len(specs) >= 42 and all(spec.check(s) == [] for s in specs)
    assert "STORY-0" not in (ROOT / "docs" / "backlog.md").read_text().split(spec.START)[1].split(spec.END)[0]
