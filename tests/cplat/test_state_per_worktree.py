"""Run state is per worktree (ADR-051): a linked worktree never sees state another checkout wrote."""
import json
import os
import subprocess
from pathlib import Path

import pytest

import appship_merge
import appship_state
import budget
import replan
import runs
import ship

ROOT = Path(__file__).resolve().parents[2]
HOOKS = json.loads((ROOT / "plugins" / "shared" / "hooks" / "hooks.json").read_text())


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def trio(tmp_path):
    """(main checkout, worktree A, worktree B) of one repo."""
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    git(main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    a, b = tmp_path / "wt-a", tmp_path / "wt-b"
    git(main, "worktree", "add", "-q", "-b", "a", str(a))
    git(main, "worktree", "add", "-q", "-b", "b", str(b))
    return main, a, b


def test_ship_state_invisible_to_other_worktree(trio):
    """spec 066: ship state written in worktree A is invisible to worktree B (and to the main checkout)."""
    main, a, b = trio
    ship.save_state(a, {"phase": "ci", "spec": "x"})
    assert ship.load_state(a)["phase"] == "ci"
    assert ship.load_state(b) is None
    assert ship.load_state(main) is None
    assert ship.state_path(a) != ship.state_path(b)


def test_ship_gate_from_other_worktree_sees_no_run(trio, capsys, monkeypatch):
    """spec 066: `ship gate` run from B does not block on A's run."""
    main, a, b = trio
    ship.save_state(a, {"phase": "ci", "spec": "x"})
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert ship.main(["--repo", str(b), "gate"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_main_checkout_keeps_dot_git_path(trio):
    """spec 066: the main checkout still reads and writes <repo>/.git/cplat-ship.json."""
    main, a, b = trio
    ship.save_state(main, {"phase": "ci", "spec": "x"})
    assert (main / ".git" / "cplat-ship.json").is_file()
    assert ship.state_path(main).resolve() == (main / ".git" / "cplat-ship.json").resolve()
    assert ship.state_path(a).parent.parent.name == "worktrees"


def test_attach_point_and_pointer_per_worktree(trio):
    """spec 088: attach_point and the `cplat runs begin` pointer belong to one worktree."""
    main, a, b = trio
    ship.save_state(a, {"phase": "ci", "spec": "x", "run_id": "r-1"})
    assert runs.attach_point(a) == "r-1"
    assert runs.attach_point(b) is None
    assert runs.attach_point(main) is None
    assert runs._pointer(a) != runs._pointer(b)
    assert runs._pointer(main).resolve() == (main / ".git" / "cplat-run.json").resolve()


def test_recovery_snapshot_per_worktree(trio):
    """spec 102: the recovery snapshot of A is not read from B."""
    main, a, b = trio
    path = budget.snapshot(a, "build", "boom")
    assert path is not None and path.parent != main / ".git"
    assert budget.read_snapshot(a)["stage"] == "build"
    assert budget.read_snapshot(b) is None
    assert budget.read_snapshot(main) is None


def test_replan_pending_per_worktree(trio):
    """spec 087: pending replan conflicts of A are not seen from B."""
    main, a, b = trio
    replan.set_pending(a, "087", "t1", {"x": 1})
    assert replan.pending(a, "087") == {"t1": {"x": 1}}
    assert replan.pending(b, "087") == {}
    assert replan._pending_path(main).resolve() == (main / ".git" / "cplat-replan.json").resolve()


def test_product_ship_state_per_worktree_merge_lock_shared(trio):
    """spec 097: the product-ship state is per worktree; the gitops merge lock stays in the common dir."""
    main, a, b = trio
    appship_state.save_state(a, {"phase": "plan"})
    assert appship_state.load_state(a)["phase"] == "plan"
    assert appship_state.load_state(b) is None
    assert appship_state.state_path(a) != appship_state.state_path(b)
    assert appship_state.state_path(main).resolve() == (main / ".git" / "cplat-app-ship.json").resolve()
    assert appship_merge.lock_path(a).resolve() == appship_merge.lock_path(b).resolve()
    assert appship_merge.lock_path(a).resolve().parent == (main / ".git").resolve()


def hook_commands():
    found = {}
    for group in ("PreToolUse", "Stop"):
        for entry in HOOKS["hooks"][group]:
            for h in entry["hooks"]:
                c = h["command"]
                for key in ("budget gate", "component ship gate", "system ship gate"):
                    if key in c:
                        found[key] = c
    return found


def test_hooks_use_git_dir():
    """spec 066: the Stop, app-ship Stop and budget hooks look at --git-dir, not the common dir."""
    cmds = hook_commands()
    assert set(cmds) == {"budget gate", "component ship gate", "system ship gate"}
    for c in cmds.values():
        assert "rev-parse --git-dir" in c
        assert "--git-common-dir" not in c


@pytest.mark.parametrize("key,state", [("budget gate", "cplat-ship.json"), ("component ship gate", "cplat-ship.json"),
                                       ("system ship gate", "cplat-app-ship.json")])
def test_hook_exit_behaviour(trio, tmp_path, key, state):
    """spec 066: no state in this worktree -> exit 0 without calling cplat; own state -> cplat is called."""
    main, a, b = trio
    plugin = tmp_path / "plugin"
    (plugin / "bin").mkdir(parents=True)
    marker = tmp_path / "called"
    fake = plugin / "bin" / "cplat"
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> {marker}\nexit 0\n")
    fake.chmod(0o755)
    cmd = hook_commands()[key]
    env = {k: v for k, v in os.environ.items() if k != "CPLAT_RUN_PARENT"} | {"CLAUDE_PLUGIN_ROOT": str(plugin)}

    def fire(cwd):
        marker.unlink(missing_ok=True)
        p = subprocess.run(["sh", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True)
        return p.returncode, marker.exists()

    (Path(git(a, "rev-parse", "--absolute-git-dir")) / state).write_text("{}")
    assert fire(b) == (0, False)
    assert fire(main) == (0, False)
    assert fire(a) == (0, True)
