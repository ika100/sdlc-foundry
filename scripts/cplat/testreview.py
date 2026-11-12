"""cplat component build reviewed — the commit that freezes the acceptance tests after their one review (spec 179).

  cplat.py build reviewed <spec> [--repo DIR] [--findings N] [--unresolved '<test> | <AC id> | <what>']...
"""
from __future__ import annotations

import argparse
from pathlib import Path

import core
import spec as specmod
from core import PlatformError

REVIEWED_MSG = "reviewed acceptance tests for"
ACCEPTANCE_MSG = "acceptance tests for"


def _git(repo: Path, *args: str) -> tuple[int, str]:
    proc = core.run(["git", "-C", str(repo), *args], check=False)
    return proc.returncode, proc.stdout.strip()


def _range(repo: Path, head: str) -> str:
    for ref in ("main", "origin/main"):
        code, out = _git(repo, "merge-base", ref, head)
        if code == 0 and out:
            return f"{out}..{head}"
    return head


def _find(repo: Path, spec_id: str, msg: str, head: str) -> list[str]:
    code, out = _git(repo, "log", f"--grep={msg} {spec_id}", "--format=%H", _range(repo, head))
    return out.split() if code == 0 and out else []


def reviewed_commit(repo: Path, spec_id: str, head: str = "HEAD") -> str | None:
    shas = _find(repo, spec_id, REVIEWED_MSG, head)
    return shas[0] if shas else None


def unresolved(repo: Path, spec_id: str, head: str = "HEAD") -> list[dict]:
    sha = reviewed_commit(repo, spec_id, head)
    if not sha:
        return []
    _, body = _git(repo, "log", "-1", "--format=%b", sha)
    found = []
    for line in body.splitlines():
        if not line.startswith("unresolved:"):
            continue
        parts = [p.strip() for p in line[len("unresolved:"):].split("|", 2)]
        if len(parts) == 3:
            found.append({"test": parts[0], "criterion": parts[1], "what": parts[2]})
    return found


def _parse(value: str, active: list[str]) -> str:
    parts = [p.strip() for p in value.split("|", 2)]
    if len(parts) != 3 or not all(parts):
        raise PlatformError(f"--unresolved {value!r} needs three non-empty parts",
                            hint="use '<test> | <AC id> | <what>'")
    if parts[1] not in active:
        raise PlatformError(f"--unresolved names {parts[1]}, which is not an active criterion of the spec",
                            hint="use an AC id of the spec that is not withdrawn")
    return " | ".join(parts)


def commit(repo: Path, spec_ref: str, findings: int, unresolved: list[str]) -> str:
    sp = specmod.find(repo, spec_ref)
    code, out = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if out:
        raise PlatformError("tracked files have uncommitted changes", hint="commit the tests first")
    if not _find(repo, sp.id, ACCEPTANCE_MSG, "HEAD"):
        raise PlatformError(f"no commit '{ACCEPTANCE_MSG} {sp.id}' on this branch",
                            hint="run the red-tests step and commit the acceptance tests first")
    lines = [f"findings: {findings}"] + [f"unresolved: {_parse(v, sp.active_acs())}" for v in unresolved]
    subject = f"test({sp.number}): {REVIEWED_MSG} {sp.id}"
    proc = core.run(["git", "-C", str(repo), *core.git_identity(repo), "commit", "-s", "--allow-empty",
                     "-m", subject, "-m", "\n".join(lines)], check=False)
    if proc.returncode != 0:
        raise PlatformError(f"git commit failed: {(proc.stderr or proc.stdout).strip()}")
    return _git(repo, "rev-parse", "HEAD")[1]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat component build reviewed", description=__doc__)
    ap.add_argument("spec")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--findings", type=int, default=0)
    ap.add_argument("--unresolved", action="append", default=[])
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()
    sp = specmod.find(repo, ns.spec)
    if (sha := reviewed_commit(repo, sp.id)):
        print(f"already reviewed at {sha[:7]}")
        return 0
    sha = commit(repo, ns.spec, ns.findings, ns.unresolved)
    print(f"REVIEWED {sha[:7]}: {ns.findings} findings, {len(ns.unresolved)} unresolved")
    return 0
