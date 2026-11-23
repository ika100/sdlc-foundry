"""Journey noise (journeys 25 and 26): Docker Hub pulls of the LGTM and SeaweedFS images broke off on a flaky network for 30+
minutes per cluster. `DOCKERHUB_MIRROR` lets a new local cluster pull docker.io images through a pull-through cache; unset, the
cluster is created exactly as before."""
import os
import subprocess

from test_cluster_ports import _skeleton
from waiting import with_prelude


def cluster_up(tmp_path, **extra):
    skeleton, bin_dir, log = _skeleton(tmp_path)
    k3d = bin_dir / "k3d"   # records the call and the registries file it is given, then fails the create so the script stops
    k3d.write_text(with_prelude(f'#!/bin/sh\necho "k3d $*" >> "{log}"\n[ "$1 $2" = "cluster list" ] && exit 1\n'
                                f'prev=""; for a in "$@"; do [ "$prev" = --registry-config ] && cat "$a" >> "{log}"; prev="$a"; done\n'
                                f'[ "$1 $2" = "cluster create" ] && exit 1\nexit 0\n'))
    env = {k: v for k, v in os.environ.items() if k not in ("DOCKERHUB_MIRROR", "LOCAL_HTTP_PORT")}
    env |= {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_TOKEN": "x", "WITH_ARGO": "0", "WITH_ESO": "0", "WITH_CNPG": "0", **extra}
    run = subprocess.run(["bash", str(skeleton / "scripts" / "local-cluster.sh"), "up"], capture_output=True, text=True, env=env, cwd=skeleton)
    return run.stdout + run.stderr, log.read_text()


def test_a_mirror_routes_docker_hub_pulls_through_the_cache(tmp_path):
    out, log = cluster_up(tmp_path, DOCKERHUB_MIRROR="http://host.k3d.internal:5050")
    assert "--registry-config" in log, log
    assert 'mirrors:\n  "docker.io":\n    endpoint:\n      - "http://host.k3d.internal:5050"\n' in log
    assert "Docker Hub images: through http://host.k3d.internal:5050" in out


def test_without_a_mirror_the_cluster_is_created_as_before(tmp_path):
    out, log = cluster_up(tmp_path)
    assert "k3d cluster create" in log and "--registry-config" not in log and "Docker Hub images" not in out
