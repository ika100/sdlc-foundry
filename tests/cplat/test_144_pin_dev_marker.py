"""Spec 144 acceptance tests: the gitops-app's pin-dev.yml skips a build a system ship pins in its joint dev PR.

Seam: the `run` script of pin-dev.yml's pin step, run with bash in a gitops clone whose origin is a local bare repo, with fake
`uv` (pin.py changes the overlay, render.py --check passes) and `gh` (logs every call, `pr create` prints a URL) on PATH.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import core

WORKFLOW = core.PLATFORM_ROOT / "templates" / "gitops-app" / ".github" / "workflows" / "pin-dev.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"

FAKE_UV = f"""#!{sys.executable}
import sys
a = sys.argv[1:]
if a[:2] == ["run", "scripts/pin.py"]:
    open("applications/shop/overlays/dev/" + a[3] + ".txt", "w").write(a[4] + "\\n")
    print(a[3] + " in dev: old -> " + a[4])
sys.exit(0)
"""

FAKE_GH = f"""#!{sys.executable}
import json, os, sys
open(os.environ["GH_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["pr", "create"]:
    print("https://github.com/acme/shop-gitops/pull/21")
sys.exit(0)
"""


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def pin_script() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text())
    return next(s["run"] for s in wf["jobs"]["pin"]["steps"] if s.get("id") == "pin")


@pytest.fixture()
def gitops(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    g = tmp_path / "shop-gitops"
    g.mkdir()
    git(g, "init", "-q", "-b", "main")
    (g / "applications" / "shop" / "overlays" / "dev").mkdir(parents=True)
    (g / "applications" / "shop" / "overlays" / "dev" / "shop-api.txt").write_text("old\n")
    git(g, "add", "-A")
    git(g, "commit", "-qm", "init")
    git(g, "remote", "add", "origin", str(origin))
    git(g, "push", "-q", "origin", "main")
    b = tmp_path / "bin"
    b.mkdir()
    for name, body in (("uv", FAKE_UV), ("gh", FAKE_GH)):
        (b / name).write_text(body)
        (b / name).chmod((b / name).stat().st_mode | stat.S_IEXEC)
    return {"dir": g, "origin": origin, "bin": b, "log": tmp_path / "gh.log", "out": tmp_path / "out.txt"}


def marker(g, ref):
    head = git(g["dir"], "rev-parse", "HEAD")
    git(g["dir"], "push", "-q", "origin", f"{head}:refs/heads/{ref}")


def run_pin(g, service="shop-api", tag=f"sha-{SHA}"):
    g["log"].write_text("")
    g["out"].write_text("")
    env = {**os.environ, "PATH": f"{g['bin']}{os.pathsep}{os.environ['PATH']}", "GH_TOKEN": "t", "SERVICE": service,
           "TAG": tag, "GH_LOG": str(g["log"]), "GITHUB_OUTPUT": str(g["out"])}
    p = subprocess.run(["bash", "-c", pin_script()], cwd=g["dir"], env=env, capture_output=True, text=True)
    calls = [json.loads(ln) for ln in g["log"].read_text().splitlines() if ln.strip()]
    heads = git(g["dir"], "ls-remote", "--heads", "origin")
    return p, calls, heads


def test_a_build_with_a_system_ship_marker_gets_no_pin_pr_ac_144_1(gitops):  # AC-144.1
    marker(gitops, f"ship/012-shop/shop-api-{SHA[:7]}")
    p, calls, heads = run_pin(gitops)
    assert p.returncode == 0, p.stderr
    assert "pinned by the system ship" in p.stdout and "012-shop" not in p.stderr
    assert not any(c[:2] == ["pr", "create"] for c in calls)
    assert "refs/heads/pin/dev-" not in heads
    assert "pr=" not in gitops["out"].read_text()          # the ci and merge jobs do not run
    assert git(gitops["dir"], "status", "--porcelain") == ""


def test_a_build_without_a_marker_is_pinned_in_its_own_pr_as_today_ac_144_6(gitops):  # AC-144.6
    p, calls, heads = run_pin(gitops)
    assert p.returncode == 0, p.stderr
    assert any(c[:2] == ["pr", "create"] for c in calls)
    assert f"refs/heads/pin/dev-shop-api-{SHA[:7]}" in heads
    assert "pr=https://github.com/acme/shop-gitops/pull/21" in gitops["out"].read_text()


@pytest.mark.parametrize("ref", [f"ship/012-shop/shop-api-{OTHER[:7]}",     # another build of the same component
                                 f"ship/012-shop/shop-web-{SHA[:7]}",       # the same sha prefix of another component
                                 f"ship/012-shop/xshop-api-{SHA[:7]}"])     # a component whose name ends like it
def test_a_marker_of_another_build_does_not_stop_this_pin_ac_144_6(gitops, ref):  # AC-144.6
    marker(gitops, ref)
    p, calls, _ = run_pin(gitops)
    assert p.returncode == 0, p.stderr
    assert any(c[:2] == ["pr", "create"] for c in calls)


def test_the_marker_check_comes_before_the_pin_ac_144_1():  # AC-144.1
    script = pin_script()
    assert script.index("refs/heads/ship/") < script.index("scripts/pin.py dev")
    assert shutil.which("bash")
    assert "spec 144" in WORKFLOW.read_text()
    assert Path(WORKFLOW).name == "pin-dev.yml"
