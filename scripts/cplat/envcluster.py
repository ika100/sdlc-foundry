"""Which kube context an environment's command uses (spec 201, AC-201.9).

A system whose environments run on several clusters (`environments.<env>.cluster`) must never act on the current kube context:
`env_context` returns the context of the environment's cluster, from `kube_contexts` in the settings files, or raises before
anything is done. For a system on one cluster it returns None and the caller keeps today's choice of context.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import settings
from core import PlatformError

if TYPE_CHECKING:
    import model

PROBE_TIMEOUT = 20


def cluster_of(m: model.Model, env: str) -> str | None:
    e = m.environment(env)
    return getattr(e, "cluster", None) if e is not None else None


def spread(m: model.Model) -> bool:
    """True when the environments run on more than one distinct cluster."""
    return len({c for e in m.environments if (c := getattr(e, "cluster", None))}) > 1


def _probe(ctx: str) -> str | None:
    """None when the context answers, else the first line of kubectl's error."""
    cmd = ["kubectl", "--context", ctx, "-n", "argocd", "get", "applications", "-o", "name"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"no answer within {PROBE_TIMEOUT} s"
    except OSError as e:
        return str(e)
    if r.returncode == 0:
        return None
    lines = (r.stderr or r.stdout or "").strip().splitlines()
    return lines[0].strip() if lines else f"kubectl exited {r.returncode}"


def cluster_context(repo: Path, cluster: str, explicit: str | None, what: str) -> str:
    """The reachable kube context of `cluster`: `explicit`, else `kube_contexts` of the settings files; PlatformError otherwise."""
    known = settings.kube_contexts_with_source(repo)
    if explicit:
        ctx, source = explicit, "--context"
    elif cluster in known:
        ctx, source = known[cluster]
    else:
        ctx = source = ""
    hint = (f"pass --context <ctx>, or add kube_contexts: {{{cluster}: <ctx>}} to {settings.user_file()} "
            "(a context name only; the credentials stay in your kubeconfig)")
    if not ctx:
        raise PlatformError(f"{what} runs on cluster {cluster}, and no kube context is known for it", hint=hint)
    err = _probe(ctx)
    if err is not None:
        raise PlatformError(
            f"{what} runs on cluster {cluster}, whose kube context {ctx} ({source}) does not answer: {err}", hint=hint)
    return ctx


def env_context(repo: Path, m: model.Model, env: str, explicit: str | None) -> str | None:
    """`explicit`; None for a system on one cluster (today's choice stays); else the context of the environment's cluster."""
    if explicit:
        return explicit
    if not spread(m):
        return None
    what = f"environment {env} of {m.system}"
    cluster = cluster_of(m, env)
    if cluster is None:
        raise PlatformError(f"{what} runs on no known cluster",
                            hint="set environments.<env>.cluster for every environment in system.yaml")
    return cluster_context(repo, cluster, None, what)
