"""Spec 154 acceptance tests: the journey 6 findings (#557–#560).

Seams: release-check.py loaded by path with `core.subprocess.run` scripted; spec 143's wait world (a real origin) for the
newer pin; spec 117's restore fixtures; the gitops template's plan.py loaded by path."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

import core
import envwait
from backup_fixtures import argo_app, bdoc, clock, cnpg_backup, cnpg_cluster, kube, make_repo, objectstore  # noqa: F401
from test_143_envwait import World as WaitWorld, git, kustomization
from test_backup_117_restore import repo, restore, window  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
DOWN = "Post \"https://api.github.com/graphql\": dial tcp 140.82.121.5:443: connect: network is down"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- AC-154.1 ----------------

@pytest.fixture()
def gate(monkeypatch):
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 300)
    monkeypatch.setattr(core, "sleep", lambda s: None)
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/platform")
    return load(ROOT / "scripts" / "release-check.py", "release_check_154")


def test_the_gate_retries_a_dropped_network_ac_154_1(gate, monkeypatch, capsys):  # AC-154.1
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, "", DOWN)
        body = '{"check_runs": [{"name": "%s", "conclusion": "success"}]}' % gate.E2E_NAME
        return subprocess.CompletedProcess(cmd, 0, body, "")
    monkeypatch.setattr(core.subprocess, "run", fake)
    assert gate.cmd_gate("abc1234") == 0 and len(calls) == 2
    assert "OK: abc1234 has a green upgrade e2e" in capsys.readouterr().out


def test_an_unreadable_answer_is_not_called_red_ac_154_1(gate, monkeypatch, capsys):  # AC-154.1
    monkeypatch.setattr(core.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "HTTP 404: Not Found"))
    assert gate.cmd_gate("abc1234") == 1
    out = capsys.readouterr().out
    assert "cannot read the check runs of abc1234" in out and "run the gate again" in out and "no green upgrade e2e" not in out


# ---------------- AC-154.2 ----------------

def test_a_newer_pin_on_main_is_read_after_one_fetch_ac_154_2(tmp_path, monkeypatch, capsys):  # AC-154.2
    w = WaitWorld(tmp_path, monkeypatch, capsys)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(w.origin), str(other)], check=True)
    git(other, "config", "user.name", "t")
    git(other, "config", "user.email", "t@t")
    new_tag = "sha-" + "7" * 40
    (other / "applications/shop/overlays/dev/todo-api/kustomization.yaml").write_text(kustomization(new_tag))
    git(other, "commit", "-qam", "pin newer")
    git(other, "push", "-q", "origin", "main")
    newer = git(other, "rev-parse", "HEAD")
    pins = envwait.Pins(w.repo, w.head, "shop")
    target = envwait.Target("todo-api-dev", "sha-" + "4f2a91c" + "0" * 33, True, "todo-api", "dev")
    assert pins(target, newer) == new_tag and pins.refetched
    assert pins(target, newer) == new_tag            # cached, no second fetch


# ---------------- AC-154.3 ----------------

def test_a_restore_without_any_point_says_take_a_backup_ac_154_3(repo, kube, capsys):  # AC-154.3
    window(kube, first=None, latest=None)
    with pytest.raises(core.PlatformError) as e:
        import dbrestore
        dbrestore.main(["orders-db", "--env", "dev", "--to", "latest", "--repo-dir", str(repo)])
    assert "no backup of it has completed yet" in str(e.value)
    assert "/resource:backup orders-db --env dev" in e.value.hint


# ---------------- AC-154.4 ----------------

def _slice(n, why=None):
    r = {"id": "shop-web", "shape": "web-nextjs", "acs": ["AC-001.3"],
         "criteria": [f"Given x{i}, when y, then z (system AC-001.3)" for i in range(n)]}
    if why:
        r["criteria_why"] = why
    return r


def test_a_slice_above_twelve_criteria_is_refused_unless_it_says_why_ac_154_4():  # AC-154.4
    plan = load(ROOT / "templates" / "gitops-app" / "scripts" / "plan.py", "plan_154")
    assert plan.check_criteria([_slice(12)]) == []
    [err] = plan.check_criteria([_slice(14)])
    assert "14 criteria, more than 12" in err and "criteria_why" in err
    assert plan.check_criteria([_slice(14, why="one criterion per screen state the spec names")]) == []
    planner = (ROOT / "plugins/system/agents/planner.md").read_text()
    assert "above 12 `plan-check` refuses the slice unless it has `criteria_why:`" in planner
