"""Spec 211 (AC-211.8): the base `cplat spec test-diff` uses when none is given: the latest "acceptance tests for <spec id>" commit."""
from __future__ import annotations

import subprocess
from pathlib import Path


class NoBase(Exception):
    """No base can be found; `why` is the text after `ERROR: no base: `."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout.strip()


def resolve(root: Path) -> tuple[str, str]:
    """`(sha, spec_id)`: the spec is the judged one the branch `feature/<id>` names, else the only one."""
    import spec
    ids = [s.id for s in spec.judged_specs(root)]
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not ids:
        raise NoBase("no building spec")
    if branch.startswith("feature/") and branch.removeprefix("feature/") in ids:
        spec_id = branch.removeprefix("feature/")
    elif len(ids) == 1:
        spec_id = ids[0]
    else:
        raise NoBase(f"{len(ids)} building specs and the branch {branch} names none of them")
    sha = _git(root, "log", "-1", "--format=%H", "-F", "--grep", f"acceptance tests for {spec_id}", "HEAD")
    if not sha:
        raise NoBase(f'no commit "acceptance tests for {spec_id}" on {branch}')
    return sha, spec_id
