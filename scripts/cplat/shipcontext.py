"""`shipcontext`: the kube context a `ship start --detach` hands to its headless run (spec 203).

The headless `ship deploy` takes its context from `CPLAT_KUBE_CONTEXT`; an interactive session often has none there, so the dev
smoke was "not run". `resolve` picks one context in a fixed order (the option, the run's recorded one, the calling session's
environment, the settings files, the local k3d cluster of a linked system); `contexts()` is the one I/O it needs for the check of
`--context` and for the local cluster, and the seam tests replace. Imports `settings`, never `model`.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import settings

TIMEOUT_S = 10
NONE_LINE = "context: none (dev is not checked; pass --context <kube-context>)"


def contexts() -> set[str] | None:
    """The context names of the kubeconfig; None when kubectl is missing or fails."""
    try:
        p = subprocess.run(["kubectl", "config", "get-contexts", "-o", "name"], capture_output=True, text=True,
                           timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return {ln.strip() for ln in p.stdout.splitlines() if ln.strip()}


def _systems(repo: Path) -> list[str]:
    import ship
    import smoke
    names: list[str] = []
    for slug in ship.gitops_apps(repo):
        try:
            dirs = smoke._app_dirs(slug, repo)[0] or []
        except Exception:  # noqa: BLE001  (a failed read is no source)
            continue
        names.extend(sorted(dirs))
    return names


def resolve(repo: Path, given: str | None, recorded: str | None) -> tuple[str | None, str | None]:
    """(name, source) of the first source that has a context; (None, None) when none has."""
    if given and given.strip():
        return given.strip(), "--context"
    if recorded and recorded.strip():
        return recorded.strip(), "recorded at the hand-off"
    for var in ("CPLAT_KUBE_CONTEXT", "KUBE_CONTEXT"):
        value = os.environ.get(var, "").strip()
        if value:
            return value, var
    name, source = settings.kube_context(repo)
    if name:
        return name, f"kube_context in the {source} settings"
    known = contexts() or set()
    if any(c.startswith("k3d-") and c.endswith("-local") for c in known):   # no gh call when no local cluster exists
        for system in _systems(repo):
            if f"k3d-{system}-local" in known:
                return f"k3d-{system}-local", f"local cluster of {system}"
    return None, None


def line(name: str | None, source: str | None) -> str:
    """The `context:` line of the hand-off output."""
    return f"context: {name} ({source})" if name else NONE_LINE
