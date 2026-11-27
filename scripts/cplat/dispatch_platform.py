"""#1074: the platform checkout the dispatcher's units run cplat from, and how far it is behind origin/main.

  state(repo, fetch=False) -> dict | None   path, commit, behind, mode (detached|branch), branch, clean; None when the units do not run
                                            on a platform checkout (CPLAT_PLATFORM, else the repo itself when it declares `shape: platform`)
  advance(repo) -> list[str]                fetch, then move a clean, detached checkout to origin/main; a dirty or branch checkout is left alone
  note(repo) -> str                         one sentence for an escalation when the checkout is behind ("" otherwise)
  line(doc) -> str                          the `platform:` line of `cplat dispatch status`

Every git failure (no network, no origin) leaves the checkout as it is and shows as an unknown `behind`.
"""
from __future__ import annotations

import os
from pathlib import Path

import core


def _git(path: Path, *args: str) -> str | None:
    try:
        p = core.run(["git", *args], cwd=path, check=False)
    except core.PlatformError:
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _root(repo: Path | str) -> Path | None:
    env = os.environ.get("CPLAT_PLATFORM")
    if env:
        return Path(env)
    try:
        lines = (Path(repo) / ".platform-settings.yml").read_text().splitlines()
    except OSError:
        return None
    return Path(repo) if any(x.replace(" ", "") == "shape:platform" for x in lines) else None


def state(repo: Path | str, fetch: bool = False) -> dict | None:
    path = _root(repo)
    if path is None or _git(path, "rev-parse", "--git-dir") is None:
        return None
    if fetch:
        _git(path, "fetch", "-q", "origin", "main")
    branch = _git(path, "symbolic-ref", "--short", "-q", "HEAD")
    behind = _git(path, "rev-list", "--count", "HEAD..origin/main")
    return dict(path=str(path), commit=_git(path, "rev-parse", "--short", "HEAD") or "?",
                behind=int(behind) if behind is not None and behind.isdigit() else None,
                mode="branch" if branch else "detached", branch=branch, clean=not _git(path, "status", "--porcelain", "--untracked-files=no"))


def advance(repo: Path | str) -> list[str]:
    doc = state(repo, fetch=True)
    if not doc or not doc["behind"] or doc["mode"] != "detached" or not doc["clean"]:
        return []
    if _git(Path(doc["path"]), "checkout", "-q", "--detach", "origin/main") is None:
        return []
    return [f"platform checkout {doc['path']}: {doc['commit']} -> origin/main ({doc['behind']} commits)"]


def _left(doc: dict) -> str:
    if doc["mode"] == "branch":
        return f"on branch {doc['branch']}"
    return "" if doc["clean"] else "with local changes"


def note(repo: Path | str) -> str:
    doc = state(repo)
    if not doc or not doc["behind"]:
        return ""
    why = f", {_left(doc)} and not moved by the dispatcher" if _left(doc) else ""
    return (f"The platform checkout {doc['path']} is at {doc['commit']}, {doc['behind']} commits behind origin/main{why}: "
            "fixes merged since are not in this run.")


def line(doc: dict | None) -> str:
    if not doc:
        return ""
    behind = "behind origin/main unknown" if doc["behind"] is None else f"{doc['behind']} behind origin/main"
    left = f" ({_left(doc)}, not moved by the dispatcher)" if _left(doc) else ""
    return f"platform: {doc['commit']} at {doc['path']}, {behind}{left}"
