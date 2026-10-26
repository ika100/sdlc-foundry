"""Spec 100 (AC-100.17): `cplat runs benchmark --plugins DIR` and `cplat headless --plugin-dir`. Git, gh and the headless driver are replaced."""
import json
import shlex
import subprocess

import pytest

import runs
from core import PlatformError
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_usage_bench import benchmark_records, world  # noqa: F401  (fixtures)
from usage_support import projects  # noqa: F401


def make_plugins(root, names=("svc", "shared", "gitops")):
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@invalid"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    for n in names:
        d = root / "plugins" / n / ".claude-plugin"
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(json.dumps({"name": n, "version": "1.0.0"}))
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], cwd=root, check=True)
    return root / "plugins"


@pytest.fixture()
def plugins_world(world, monkeypatch, tmp_path):  # noqa: F811
    """The benchmark clone enables svc and shared; git -C <worktree> calls are real."""
    import runs_bench
    fake = runs_bench.run

    def run(cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        if "-C" in cmd:
            p = subprocess.run(cmd, capture_output=True, text=True)
            return p.returncode, p.stdout, p.stderr
        out = fake(cmd, cwd)
        if cwd and cmd[:2] == ["git", "fetch"]:
            (cwd / ".claude").mkdir(exist_ok=True)
            (cwd / ".claude" / "settings.json").write_text(json.dumps(
                {"enabledPlugins": {"svc@sdlc-foundry": True, "shared@sdlc-foundry": True, "gitops@sdlc-foundry": False}}))
        return out
    monkeypatch.setattr(runs_bench, "run", run)
    wt = tmp_path / "wt"
    wt.mkdir()
    world.plugins = make_plugins(wt)
    return world


def test_plugins_are_passed_per_enabled_plugin_and_recorded(plugins_world, store, capsys):
    """AC-100.17: --plugins DIR passes --plugin-dir for each enabled plugin only; the record has {dir, commit, dirty} and the coordinator model."""
    w = plugins_world
    assert runs.main(["benchmark", "quick-task", "--plugins", str(w.plugins)]) == 0
    argv = w.headless_calls[0]
    dirs = [argv[i + 1] for i, a in enumerate(argv) if a == "--plugin-dir"]
    assert dirs == [str(w.plugins / "svc"), str(w.plugins / "shared")]
    (r,) = benchmark_records(store)
    head = subprocess.run(["git", "-C", str(w.plugins), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert r["benchmark"]["plugins"] == {"dir": str(w.plugins), "commit": head, "dirty": False}
    assert r["benchmark"]["coordinator_model"] == "sonnet"
    assert f"plugins local {head[:7]}, coordinator sonnet" in capsys.readouterr().out


def test_a_dirty_worktree_is_recorded(plugins_world, store, capsys):
    """AC-100.17: uncommitted changes in the plugins folder set dirty and show as +dirty."""
    w = plugins_world
    (w.plugins / "svc" / "new.md").write_text("x")
    runs.main(["benchmark", "quick-task", "--plugins", str(w.plugins)])
    (r,) = benchmark_records(store)
    assert r["benchmark"]["plugins"]["dirty"] is True
    assert "+dirty, coordinator" in capsys.readouterr().out


def test_without_plugins_the_record_says_installed(world, store, capsys):
    """AC-100.17: no --plugins: plugins is null, no --plugin-dir, the model is still recorded."""
    assert runs.main(["benchmark", "quick-task"]) == 0
    (r,) = benchmark_records(store)
    assert r["benchmark"]["plugins"] is None and r["benchmark"]["coordinator_model"] == "sonnet"
    assert "--plugin-dir" not in world.headless_calls[0]
    assert "plugins installed, coordinator sonnet" in capsys.readouterr().out


def test_an_enabled_plugin_missing_in_dir_is_refused_before_the_run(plugins_world, store):
    """AC-100.17: an enabled plugin without a manifest in DIR is refused, no record, no session."""
    w = plugins_world
    (w.plugins / "shared" / ".claude-plugin" / "plugin.json").unlink()
    with pytest.raises(PlatformError, match="shared"):
        runs.main(["benchmark", "quick-task", "--plugins", str(w.plugins)])
    assert benchmark_records(store) == [] and w.headless_calls == []


def test_headless_adds_plugin_dir_and_a_read_rule_per_path(repo, tmp_path, capsys, monkeypatch):
    """AC-100.17: --plugin-dir PATH (repeatable) adds --plugin-dir <abs> and one --settings JSON with a Read rule per path."""
    import headless
    a, b = tmp_path / "a", tmp_path / "b"
    for p in (a, b):
        (p / ".claude-plugin").mkdir(parents=True)
        (p / ".claude-plugin" / "plugin.json").write_text('{"name": "x"}')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    assert headless.main(["/svc:build 1", "--repo", str(repo), "--dry-run", "--plugin-dir", str(a), "--plugin-dir", str(b)]) == 0
    cmd = shlex.split([ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("claude ")][0])
    assert [cmd[i + 1] for i, c in enumerate(cmd) if c == "--plugin-dir"] == [str(a), str(b)]
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert settings["permissions"] == {"allow": [f"Read(/{a}/**)", f"Read(/{b}/**)"]}   # spec 111 adds disableClaudeAiConnectors


def test_headless_refuses_a_plugin_dir_without_manifest(repo, tmp_path, monkeypatch):
    """AC-100.17: a --plugin-dir without .claude-plugin/plugin.json is refused before anything starts."""
    import headless
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    with pytest.raises(PlatformError, match="plugin.json"):
        headless.main(["/svc:build 1", "--repo", str(repo), "--dry-run", "--plugin-dir", str(tmp_path)])


from test_headless import repo  # noqa: E402,F401  (fixture)


def test_the_benchmark_passes_an_explicit_coordinator_model(world, store):
    """`cplat runs benchmark <wf> --model opus` runs the coordinator on that model and records it (baseline comparisons)."""
    assert runs.main(["benchmark", "quick-task", "--model", "opus"]) == 0
    argv = world.headless_calls[-1]
    assert argv[argv.index("--model") + 1] == "opus"
    (r,) = benchmark_records(store)
    assert r["benchmark"]["coordinator_model"] == "opus"


def test_the_sessions_run_the_checkouts_cplat_too(plugins_world, store):
    """With --plugins the session's `cplat` must be that checkout's (b2: the installed 4.5.0 cplat had no `pr open`); the
    launcher prefers CPLAT_PLATFORM, so the benchmark sets it for the run and restores it afterwards."""
    import os
    w = plugins_world
    before = os.environ.get("CPLAT_PLATFORM")
    assert runs.main(["benchmark", "quick-task", "--plugins", str(w.plugins)]) == 0
    assert w.env["CPLAT_PLATFORM"] == str(w.plugins.resolve().parent)
    assert os.environ.get("CPLAT_PLATFORM") == before
