"""`localport`: the port a local k3d cluster's Gateway answers on (spec 199).

The one I/O the model asks for: `docker port k3d-<cluster>-serverlb 80/tcp`, asked at most once per cluster per `cplat`
invocation (the cache is cleared by `reset()` at the start of `cplat.main`). Every failure gives None, silently; the caller
falls back to the default port. Imports `settings`, never `model`.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import settings
from core import PlatformError

TIMEOUT_S = 5
_CACHE: dict[str, int | None] = {}
_REPO: Path | None = None


def reset() -> None:
    """Forget the cached ports and the repo named by `use_repo`."""
    global _REPO
    _CACHE.clear()
    _REPO = None


def use_repo(repo: Path | None) -> None:
    """Name the repo whose `.platform-settings.yml` `kube_context:` is read; None: the current directory."""
    global _REPO
    _REPO = repo


def cluster(system: str | None) -> str | None:
    """The local cluster name: LOCAL_CLUSTER, a `k3d-<name>` kube context, `<system>-local`, else None."""
    name = os.environ.get("LOCAL_CLUSTER", "").strip()
    if name:
        return name
    try:
        ctx = settings.kube_context(_REPO or Path.cwd())[0]
    except (PlatformError, OSError):
        ctx = None
    if ctx and ctx.startswith("k3d-") and ctx[4:]:
        return ctx[4:]
    return f"{system}-local" if system else None


def docker_port(cluster: str) -> int | None:
    """The host port of the cluster's load balancer port 80, or None when docker gives no usable answer."""
    try:
        done = subprocess.run(["docker", "port", f"k3d-{cluster}-serverlb", "80/tcp"], capture_output=True, text=True,
                              timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    for line in done.stdout.splitlines():
        if line.strip():
            text = line.rsplit(":", 1)[-1].strip()
            return int(text) if text.isascii() and text.isdigit() and 1 <= int(text) <= 65535 else None
    return None


def lookup(system: str | None) -> int | None:
    """The discovered port for the system's cluster (cached, None included), None when no cluster is known."""
    name = cluster(system)
    if name is None:
        return None
    if name not in _CACHE:
        _CACHE[name] = docker_port(name)
    return _CACHE[name]
