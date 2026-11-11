"""`devbox run cluster-ui`: k9s on the local cluster (templates/gitops-app)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

from waiting import with_prelude

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "gitops-app"


def skeleton(tmp_path, cluster_running: bool):
    root = tmp_path / "gitops"
    (root / "applications" / "demo").mkdir(parents=True)
    (root / "scripts").mkdir()
    for f in ("local-cluster.sh", "ports.sh"):
        shutil.copy(TEMPLATE / "scripts" / f, root / "scripts" / f)
    (root / ".copier-answers.yml").write_text("github_org: acme\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    (bin_dir / "kubectl").write_text(with_prelude(f'#!/bin/sh\necho "kubectl $*" >> "{log}"\nexit {0 if cluster_running else 1}\n'))
    (bin_dir / "k9s").write_text(with_prelude(f'#!/bin/sh\necho "k9s $*" >> "{log}"\n'))
    for t in bin_dir.iterdir():
        t.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return root, env, log


def run_ui(root, env, *args):
    return subprocess.run(["bash", str(root / "scripts" / "local-cluster.sh"), "ui", *args], capture_output=True, text=True, env=env, cwd=root)


def test_ui_opens_k9s_on_the_apps_dev_namespace(tmp_path):
    root, env, log = skeleton(tmp_path, cluster_running=True)
    run = run_ui(root, env)
    assert run.returncode == 0, run.stderr
    assert "k9s --context k3d-demo-local -n demo-dev" in log.read_text()


def test_ui_passes_extra_arguments_to_k9s(tmp_path):
    root, env, log = skeleton(tmp_path, cluster_running=True)
    run_ui(root, env, "--readonly")
    assert "k9s --context k3d-demo-local -n demo-dev --readonly" in log.read_text()


def test_ui_explains_what_to_do_when_the_cluster_is_not_running(tmp_path):
    root, env, log = skeleton(tmp_path, cluster_running=False)
    run = run_ui(root, env)
    assert run.returncode == 1
    assert "not running" in run.stderr and "devbox run cluster-up" in run.stderr
    assert "k9s" not in log.read_text()


def test_devbox_ships_k9s_and_the_recipe():
    devbox = json.loads((TEMPLATE / "devbox.json").read_text())
    assert "k9s@latest" in devbox["packages"]
    assert devbox["shell"]["scripts"]["cluster-ui"] == "bash scripts/local-cluster.sh ui"
