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


def run(launcher, tmp_path, cwd=None, **env):
    full = {k: v for k, v in os.environ.items() if not k.startswith("CPLAT_")} | {"XDG_CACHE_HOME": str(tmp_path / "cache")} | env
    return subprocess.run([str(launcher), "spec", "--repo", str(tmp_path), "list"], capture_output=True, text=True, env=full,
                          cwd=cwd or tmp_path)


def lone_launcher(tmp_path):
    """A launcher with no repo and no marketplace around it: it would otherwise fetch main."""
    lone = tmp_path / "lone" / "bin"
    lone.mkdir(parents=True)
    shutil.copy(LAUNCHER, lone / "cplat")
    return lone / "cplat"


def fake_platform_checkout(tmp_path, shape="platform"):
    """A git checkout whose cplat.py prints where it ran and the CPLAT_SOURCE it got."""
    repo = tmp_path / "checkout"
    (repo / "scripts" / "cplat").mkdir(parents=True)
    (repo / "scripts" / "cplat" / "cplat.py").write_text("import os, sys\nprint('CHECKOUT', os.environ['CPLAT_SOURCE'])\n")
    (repo / ".platform-settings.yml").write_text(f"# project settings\nshape: {shape}\n")
    (repo / "docs").mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


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
    out = run(lone_launcher(tmp_path), tmp_path, CPLAT_PLATFORM=str(ROOT))
    assert out.returncode == 0, out.stderr
    assert not fetched(tmp_path)


def test_inside_the_platform_repo_the_launcher_runs_the_checkout_320(tmp_path):
    """#320: in a checkout of the platform repo (`shape: platform`), fixes merged there apply without a release."""
    repo = fake_platform_checkout(tmp_path)
    out = run(lone_launcher(tmp_path), tmp_path, cwd=repo / "docs")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"CHECKOUT checkout {repo.resolve()}" and not fetched(tmp_path)


def test_explicit_platform_and_ref_beat_the_checkout_320(tmp_path):
    """#320: CPLAT_PLATFORM still wins inside the platform repo."""
    repo = fake_platform_checkout(tmp_path)
    out = run(lone_launcher(tmp_path), tmp_path, cwd=repo, CPLAT_PLATFORM=str(ROOT))
    assert out.returncode == 0, out.stderr
    assert "CHECKOUT" not in out.stdout and "no open specs" in out.stdout


def test_a_repo_of_another_shape_does_not_run_its_scripts_320(tmp_path):
    """#320: only a repo that declares `shape: platform` is the platform checkout."""
    repo = fake_platform_checkout(tmp_path, shape="service-python")
    out = run(LAUNCHER, tmp_path, cwd=repo)
    assert out.returncode == 0, out.stderr
    assert "CHECKOUT" not in out.stdout and "no open specs" in out.stdout


def test_the_shared_plugin_allows_the_launcher():
    settings = (ROOT / "plugins" / "shared" / "settings.json").read_text()
    assert '"Bash(cplat *)"' in settings and os.access(LAUNCHER, os.X_OK)


def test_the_launcher_tells_doctor_where_the_scripts_came_from(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CPLAT_")} | {"XDG_CACHE_HOME": str(tmp_path / "cache")}
    out = subprocess.run([str(LAUNCHER), "platform", "doctor", "--json"], capture_output=True, text=True, env=env, cwd=tmp_path)
    rows = {r["name"]: r for r in __import__("json").loads(out.stdout)}
    assert rows["platform scripts"]["status"] == "ok" and rows["platform scripts"]["detail"].startswith("in-place: ")


@pytest.mark.parametrize("source, status", [("", "warn"), ("main /c/sdlc-foundry", "warn"), ("marketplace /m", "ok"), ("ref v4.0.0 /r", "ok"),
                                            ("checkout /Users/me/sdlc-foundry", "ok")])
def test_doctor_rates_the_platform_source(monkeypatch, source, status):
    import doctor
    monkeypatch.setenv("CPLAT_SOURCE", source)
    assert doctor.check_platform_source()[0]["status"] == status


def test_doctor_rates_the_checkout_as_ok_320(monkeypatch):
    """#320: the platform repo running its own checkout is the intended setup, not a warning."""
    import doctor
    monkeypatch.setenv("CPLAT_SOURCE", "checkout /Users/me/sdlc-foundry")
    row = doctor.check_platform_source()[0]
    assert row["status"] == "ok" and row["detail"].startswith("checkout: /Users/me/sdlc-foundry")


def test_doctor_warns_when_the_session_is_not_at_the_repo_root_319(tmp_path):
    """#319: project settings (worktree.baseRef) are read from the directory the session starts in."""
    import doctor
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".copier-answers.yml").write_text("_src_path: x\n")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text('{"worktree": {"baseRef": "head"}}')
    assert doctor.check_session(repo) == []
    rows = doctor.check_session(repo / "src")
    assert [r["name"] for r in rows] == ["session directory"] and rows[0]["status"] == "warn"
    assert str(repo.resolve()) in rows[0]["fix"]
    (repo / ".claude" / "settings.json").write_text("{}")
    rows = doctor.check_session(repo)
    assert [r["name"] for r in rows] == ["worktree base"] and "baseRef" in rows[0]["fix"]
    assert doctor.check_session(tmp_path) == []   # not in a git repo: nothing to say


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


def test_output_to_a_pipe_arrives_line_by_line_335(tmp_path):
    """#335: a first line reaches a pipe before the command ends, not only at exit."""
    assert "export PYTHONUNBUFFERED=1" in LAUNCHER.read_text()
    probe = tmp_path / "probe.py"
    probe.write_text(f"import sys, time\nsys.path.insert(0, {str(ROOT / 'scripts' / 'cplat')!r})\nimport cplat\n"
                     "cplat._resolve = lambda argv: ('probe_mod', [], 'probe')\n"
                     "sys.modules['probe_mod'] = type(sys)('probe_mod')\n"
                     "sys.modules['probe_mod'].main = lambda rest: (print('first'), time.sleep(30), 0)[2]\n"
                     "sys.exit(cplat.main([]))\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    p = subprocess.Popen(["uv", "run", "--quiet", "--with", "pyyaml", "--with", "ruamel.yaml", "python", str(probe)],
                         stdout=subprocess.PIPE, text=True, env=env)
    try:
        assert p.stdout.readline().strip() == "first"
    finally:
        p.kill()
