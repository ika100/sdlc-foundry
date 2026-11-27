"""Which checks are the cluster e2e, and is a range of base commits or a pull request's own change inside its scope
(spec 220, ADR-089): the merge lock keeps the green e2e of a head across a catch-up when the base moved only outside the
e2e scope, and lets a land outside the scope merge while another land waits on its checks.

  e2e_gate.workflows(repo)                          the names of the workflows that run `scripts/e2e-scope.py`
  e2e_gate.ran(checks, names)                       did the e2e of a head really run and pass
  e2e_gate.range_scope(repo, url, base, e2e_head)   the base commits since the e2e head, judged by the base's own script
  e2e_gate.change_scope(repo, url, base)            the pull request's own change, judged the same way

The scope is decided by the `scripts/e2e-scope.py` of the current base, run in a temporary detached worktree of
`origin/<base>`. Every failure (another checkout, a fetch, an unknown commit, no script, a script that fails) is an
undecidable `Scope(None, [], "<one line>")`; nothing here raises.
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

import dispatch_state
from core import run

SCRIPT = "scripts/e2e-scope.py"
TIMEOUT = 120                 # seconds for the scope script


@dataclass(frozen=True)
class Scope:
    run: bool | None            # None: undecidable
    reasons: list[str]          # trigger lines without "trigger: "
    error: str = ""             # why undecidable (one line)


@dataclass(frozen=True)
class Range:
    scope: Scope
    since: str                  # the judged base (full sha) or "" when unknown
    to: str                     # the current base (full sha) or ""
    commits: int                # commits in since..to (0 when unknown)


def _undecidable(why: str) -> Scope:
    lines = [ln for ln in str(why).strip().splitlines() if ln.strip()]
    return Scope(None, [], lines[-1].strip() if lines else "unknown error")


def workflows(repo: Path) -> frozenset[str]:
    """The `name:` (else the file stem) of each workflow of the checkout whose text runs the e2e scope script."""
    out: set[str] = set()
    try:
        files = sorted([*(Path(repo) / ".github" / "workflows").glob("*.yml"),
                        *(Path(repo) / ".github" / "workflows").glob("*.yaml")])
    except OSError:
        return frozenset()
    for f in files:
        try:
            text = f.read_text()
            if SCRIPT not in text:
                continue
            doc = yaml.safe_load(text)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        name = doc.get("name") if isinstance(doc, dict) else None
        out.add(name if isinstance(name, str) and name else f.stem)
    return frozenset(out)


def ran(cs: list[dict], names: frozenset[str]) -> bool:
    """Checks of those workflows exist, all passed, none was skipped."""
    mine = [c for c in cs if c.get("workflow") in names]
    return bool(mine) and all(c.get("bucket") == "pass" for c in mine)


def local(repo: Path, slug: str) -> bool:
    """The checkout is the pull request's repository."""
    return dispatch_state.slug_of(repo) == slug


def _git(repo: Path, *args: str) -> tuple[bool, str]:
    p = run(["git", "-C", str(repo), *args], check=False)
    return p.returncode == 0, (p.stdout.strip() if p.returncode == 0 else (p.stderr.strip() or "git failed"))


def _parse(url: str) -> tuple[str, int] | None:
    m = re.search(r"github\.com/([\w.-]+/[\w.-]+?)/pull/(\d+)", url)
    return (m.group(1), int(m.group(2))) if m else None


def _scope_in_worktree(repo: Path, to: str, frm: str, head: str) -> Scope:
    """Run the script of commit `to` as `--diff frm head` in a temporary detached worktree of `to`."""
    tmp = Path(tempfile.mkdtemp(prefix="cplat-e2e-scope-"))
    tree = tmp / "tree"
    try:
        ok, out = _git(repo, "worktree", "add", "-q", "--detach", str(tree), to)
        if not ok:
            return _undecidable(out)
        script = tree / SCRIPT
        if not script.is_file():
            return _undecidable(f"{SCRIPT} is missing at {to[:7]}")
        p = run([sys.executable, "-I", str(script), "--diff", frm, head], cwd=tree, check=False, timeout=TIMEOUT)
        lines = p.stdout.splitlines()
        err = [ln[len("ERROR: "):] for ln in (*lines, *p.stderr.splitlines()) if ln.startswith("ERROR: ")]
        verdict = [ln for ln in lines if ln.startswith("run=")]
        if p.returncode != 0 or not verdict or verdict[-1] not in ("run=true", "run=false"):
            return _undecidable(err[-1] if err else (p.stderr or f"{SCRIPT} exited {p.returncode} without a verdict"))
        reasons = [ln[len("trigger: "):] for ln in p.stderr.splitlines() if ln.startswith("trigger: ")]
        return Scope(verdict[-1] == "run=true", reasons)
    except Exception as e:  # noqa: BLE001  (undecidable, never a traceback)
        return _undecidable(str(e) or type(e).__name__)
    finally:
        try:
            _git(repo, "worktree", "remove", "--force", str(tree))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _fetch(repo: Path, url: str, base: str) -> tuple[int | None, str]:
    parsed = _parse(url)
    if parsed is None:
        return None, f"not a pull request URL: {url}"
    slug, number = parsed
    if not local(repo, slug):
        return None, f"{repo} is not a checkout of {slug}"
    for ref in (base, f"pull/{number}/head"):         # one at a time: FETCH_HEAD is then the pull request's head
        ok, out = _git(repo, "fetch", "-q", "origin", ref)
        if not ok:
            return None, out
    return number, ""


def range_scope(repo: Path, url: str, base: str, e2e_head: str) -> Range:
    """The scope of the base commits since `e2e_head` (the judged base is its merge base with origin/<base>)."""
    try:
        number, err = _fetch(repo, url, base)
        if number is None:
            return Range(_undecidable(err), "", "", 0)
        ok, since = _git(repo, "merge-base", e2e_head, f"origin/{base}")
        if not ok:
            return Range(_undecidable(since), "", "", 0)
        ok, to = _git(repo, "rev-parse", "--verify", f"origin/{base}^{{commit}}")
        if not ok:
            return Range(_undecidable(to), since, "", 0)
        ok, count = _git(repo, "rev-list", "--count", f"{since}..{to}")
        commits = int(count) if ok and count.isdigit() else 0
        return Range(_scope_in_worktree(repo, to, since, to), since, to, commits)
    except Exception as e:  # noqa: BLE001
        return Range(_undecidable(str(e) or type(e).__name__), "", "", 0)


def change_scope(repo: Path, url: str, base: str) -> Scope:
    """The scope of the pull request's own change: its head against the merge base with origin/<base>."""
    try:
        number, err = _fetch(repo, url, base)
        if number is None:
            return _undecidable(err)
        ok, head = _git(repo, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
        if not ok:
            return _undecidable(head)
        ok, since = _git(repo, "merge-base", head, f"origin/{base}")
        if not ok:
            return _undecidable(since)
        ok, to = _git(repo, "rev-parse", "--verify", f"origin/{base}^{{commit}}")
        if not ok:
            return _undecidable(to)
        return _scope_in_worktree(repo, to, since, head)
    except Exception as e:  # noqa: BLE001
        return _undecidable(str(e) or type(e).__name__)
