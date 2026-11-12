"""Discard a spec the explore handoff created before anything of it was committed (spec 188).

`spec` imports this module lazily; this module imports `spec` only inside functions.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import core
from core import PlatformError

REASON = "discarded: explore first"


def discard(root: Path, spec) -> str:
    """Remove a draft spec's folder and release the claims on its tracked issues; refuse a spec git already holds."""
    if spec.status != "draft":
        raise PlatformError(f"{spec.id} is '{spec.status}', only a draft can be discarded",
                            hint="a spec past draft is withdrawn with `cplat spec set-status <id> superseded --reason ...`")
    rel = spec.dir.relative_to(root)
    if core.run(["git", "ls-files", "--", str(rel)], cwd=root).stdout.strip():
        raise PlatformError(f"{spec.id} is committed; discarding would drop history",
                            hint=f"remove it with `git rm -r {rel}` in a commit of its own")
    tracks = list(spec.meta.get("tracks") or [])
    shutil.rmtree(spec.dir)
    if tracks:
        import claim
        claim.release(root, tracks, REASON)
    return spec.id
