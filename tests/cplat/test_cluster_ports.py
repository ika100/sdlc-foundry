"""templates/gitops-app/scripts/ports.sh: busy-port detection used by `devbox run cluster-up`."""
import socket
import subprocess
from pathlib import Path

import pytest

PORTS = Path(__file__).resolve().parents[2] / "templates" / "gitops-app" / "scripts" / "ports.sh"


def sh(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'. "{PORTS}"; {snippet}'], capture_output=True, text=True)


def _free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@pytest.fixture()
def busy_port():
    """A listening port below the ephemeral range, with the next port free: the scripts pick port + 1, and an ephemeral
    port's neighbour can be taken by any outgoing connection between their two checks under parallel test load."""
    import random
    for port in random.sample(range(20000, 30000), 200):
        if not (_free(port) and _free(port + 1)):
            continue
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            s.close()
            continue
        s.listen(1)
        yield port
        s.close()
        return
    pytest.fail("no free port pair between 20000 and 30000")


def free_port_number() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_listening_port_is_reported_busy(busy_port):
    assert sh(f"port_in_use {busy_port}").returncode == 0


def test_a_free_port_is_not_busy():
    assert sh(f"port_in_use {free_port_number()}").returncode != 0


def test_free_port_skips_busy_ports(busy_port):
    out = sh(f"free_port {busy_port}").stdout.strip()
    assert out.isdigit() and int(out) > busy_port


def test_the_owner_of_a_busy_port_is_named(busy_port):
    out = sh(f"port_owner {busy_port}").stdout
    assert "pid" in out          # e.g. "Python (pid 1234)"; empty only when lsof is missing


def test_cluster_up_refuses_a_busy_port_before_creating_anything(tmp_path, busy_port):
    """AC-056.2 (an explicit LOCAL_HTTP_PORT still wins). Run the real script against a gitops-app skeleton with fake k3d/gh/kubectl: it must stop at the port check."""
    import shutil
    skeleton = tmp_path / "gitops"
    (skeleton / "applications" / "demo").mkdir(parents=True)
    (skeleton / "scripts").mkdir()
    for f in ("local-cluster.sh", "ports.sh"):
        shutil.copy(PORTS.parent / f, skeleton / "scripts" / f)
    (skeleton / ".copier-answers.yml").write_text("github_org: acme\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    for tool in ("k3d", "kubectl", "gh"):
        script = bin_dir / tool
        script.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n[ "{tool}" = k3d ] && [ "$1 $2" = "cluster list" ] && exit 1\nexit 0\n')
        script.chmod(0o755)
    import os
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOCAL_HTTP_PORT": str(busy_port), "GH_TOKEN": "x"}
    run = subprocess.run(["bash", str(skeleton / "scripts" / "local-cluster.sh"), "up"], capture_output=True, text=True, env=env, cwd=skeleton)
    assert run.returncode == 1
    assert f"host port {busy_port} is already in use" in run.stderr and "LOCAL_HTTP_PORT=" in run.stderr
    assert "k3d cluster create" not in log.read_text()          # nothing was created


def _skeleton(tmp_path):
    import shutil
    skeleton = tmp_path / "gitops"
    (skeleton / "applications" / "demo").mkdir(parents=True)
    (skeleton / "scripts").mkdir()
    for f in ("local-cluster.sh", "ports.sh"):
        shutil.copy(PORTS.parent / f, skeleton / "scripts" / f)
    (skeleton / ".copier-answers.yml").write_text("github_org: acme\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    for tool in ("k3d", "kubectl", "gh", "helm"):
        script = bin_dir / tool
        # `cluster create` is recorded, then fails, so the script stops right after choosing the port
        script.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n[ "{tool}" = k3d ] && [ "$1 $2" = "cluster list" ] && exit 1\n'
                          f'[ "{tool}" = k3d ] && [ "$1 $2" = "cluster create" ] && exit 1\nexit 0\n')
        script.chmod(0o755)
    return skeleton, bin_dir, log


def test_cluster_up_moves_to_a_free_port_when_the_default_is_taken(tmp_path, busy_port):
    """AC-056.2: no LOCAL_HTTP_PORT and the preferred port busy → the next free port, announced, and used for the cluster."""
    import os
    skeleton, bin_dir, log = _skeleton(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "LOCAL_HTTP_PORT"}
    env |= {"PATH": f"{bin_dir}:{os.environ['PATH']}", "LOCAL_HTTP_PORT_BASE": str(busy_port), "GH_TOKEN": "x", "WITH_ARGO": "0",
            "WITH_ESO": "0", "WITH_CNPG": "0"}
    run = subprocess.run(["bash", str(skeleton / "scripts" / "local-cluster.sh"), "up"], capture_output=True, text=True, env=env, cwd=skeleton)
    out = run.stdout + run.stderr
    m = __import__("re").search(r"port (\d+) is busy .*using (\d+)", out)
    assert m and int(m.group(1)) == busy_port and int(m.group(2)) > busy_port, out
    assert f"{m.group(2)}:80" in log.read_text()             # the cluster binds the chosen port
