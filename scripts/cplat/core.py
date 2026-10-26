"""Shared helpers for platform.py: process execution, errors, registry access, versions, reporting."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT / "scripts"))
import shapes as registry  # noqa: E402  (scripts/shapes.py: the shape registry loader and validators)

# The platform's own checkout is always the template source: commands run the script from a clone at the wanted ref.


class PlatformError(Exception):
    """A user-facing failure. `hint` says how to fix it."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def run(cmd: list[str], *, cwd: Path | str | None = None, check: bool = True, capture: bool = True,
        env: dict[str, str] | None = None, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command; raise PlatformError with the command's stderr when it fails and `check` is set."""
    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=full_env, text=True, capture_output=capture, timeout=timeout)
    except FileNotFoundError:
        raise PlatformError(f"`{cmd[0]}` is not installed or not on PATH", hint=install_hint(cmd[0])) from None
    except subprocess.TimeoutExpired:
        raise PlatformError(f"`{' '.join(cmd[:3])}` timed out after {timeout}s") from None
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        raise PlatformError(f"`{' '.join(cmd[:4])}` failed (exit {proc.returncode}): " + " | ".join(detail))
    return proc


def git_dir(repo: Path | str) -> Path | None:
    """The absolute git dir of this checkout (`git rev-parse --git-dir`): per-run state lives here, so a linked
    worktree never sees state another checkout wrote (ADR-051). For the main checkout it is the `.git` directory."""
    out = run(["git", "rev-parse", "--git-dir"], cwd=repo, check=False).stdout.strip()
    if not out:
        return None
    return (Path(out) if Path(out).is_absolute() else Path(repo) / out).resolve()


def install_hint(tool: str) -> str | None:
    return {
        "gh": "brew install gh && gh auth login",
        "git": "install git",
        "devbox": "curl -fsSL https://get.jetify.com/devbox/install.sh | bash",
        "docker": "install and start Docker Desktop",
        "uv": "brew install uv",
        "kubectl": "provided by `devbox shell` in a gitops repo",
    }.get(tool)


def find_copier() -> list[str]:
    """Command prefix that runs copier: PATH, ~/.local/bin (uv tool), or an ephemeral uv tool run."""
    found = shutil.which("copier")
    if found:
        return [found]
    local = Path.home() / ".local" / "bin" / "copier"
    if local.is_file():
        return [str(local)]
    if shutil.which("uv"):
        return ["uv", "tool", "run", "--from", "copier", "copier"]
    raise PlatformError("copier is not installed and uv is unavailable", hint="brew install uv && uv tool install copier")


def has_gh() -> bool:
    return shutil.which("gh") is not None


def gh_login() -> str | None:
    if not has_gh():
        return None
    p = run(["gh", "api", "user", "-q", ".login"], check=False)
    return p.stdout.strip() or None if p.returncode == 0 else None


# ---------- platform version / changelog ----------

_VERSION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\](?: — (\S+))?", re.M)


def platform_version(root: Path = PLATFORM_ROOT) -> str:
    """Latest released version from docs/CHANGELOG.md (the first `## [x.y.z]` heading)."""
    text = (root / "docs" / "CHANGELOG.md").read_text()
    m = _VERSION_RE.search(text)
    return m.group(1) if m else "0.0.0"


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def changelog_between(old: str | None, new: str, root: Path = PLATFORM_ROOT) -> str:
    """CHANGELOG sections with old < version <= new, as one text block (empty if unknown)."""
    text = (root / "docs" / "CHANGELOG.md").read_text()
    heads = list(_VERSION_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        v = m.group(1)
        if vtuple(v) <= vtuple(new) and (old is None or vtuple(v) > vtuple(old)):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            out.append(text[m.start():end].strip())
    return "\n\n".join(out)


def read_stamp(repo: Path) -> dict[str, str]:
    f = repo / ".platform-version"
    if not f.is_file():
        return {}
    data = {}
    for line in f.read_text().splitlines():
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def write_stamp(repo: Path, shape: str, ref: str) -> None:
    (repo / ".platform-version").write_text(
        "# Written by /component:new and /platform:update; read by /platform:doctor.\n"
        f"platform: {platform_version()}\nshape: {shape}\nref: {ref}\n"
    )


# ---------- reporting ----------

@dataclass
class Report:
    """What a command intends to do / did, rendered as text or JSON."""

    title: str
    will_do: list[str] = field(default_factory=list)       # outward-facing steps are prefixed with "[outward]"
    did: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    undo: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def text(self, dry_run: bool) -> str:
        lines = [f"## {self.title}" + ("  (dry run — nothing was changed)" if dry_run else "")]
        if dry_run:
            lines += ["", "What I will do:"] + [f"  {i}. {s}" for i, s in enumerate(self.will_do, 1)]
        else:
            lines += ["", "What happened:"] + [f"  ✓ {s}" for s in self.did]
        if self.next_steps:
            lines += ["", "Next:"] + [f"  - {s}" for s in self.next_steps]
        if self.undo and not dry_run:
            lines += ["", "To undo:"] + [f"  - {s}" for s in self.undo]
        return "\n".join(lines)

    def emit(self, dry_run: bool, as_json: bool) -> None:
        if as_json:
            print(json.dumps({"title": self.title, "dry_run": dry_run, "will_do": self.will_do, "did": self.did,
                              "next": self.next_steps, "undo": self.undo, **self.data}, indent=2))
        else:
            print(self.text(dry_run))


PR_BODY = ".pr-body.md"   # where agents write a PR body: Claude Code never lets edits into .git/, even under acceptEdits


def stage_pr_body(repo: Path, given: str | Path) -> Path:
    """The PR body the model wrote, moved out of the work tree into .git/PR_BODY.md (so no commit picks it up) and returned.
    A file already under .git/ is used as it is; `.git/PR_BODY.md` is still found when the default `.pr-body.md` is missing."""
    path = Path(given) if Path(given).is_absolute() else repo / given
    git_dir = repo / ".git"
    staged = git_dir / "PR_BODY.md"
    if not path.is_file() and Path(given).name == PR_BODY and staged.is_file():
        return staged
    if not path.is_file() or not git_dir.is_dir() or git_dir in path.resolve().parents:
        return path
    staged.write_text(path.read_text())
    path.unlink()
    return staged


def git_identity(repo: Path) -> list[str]:
    """`-c user.name=… -c user.email=…` fallbacks so commits never fail on a missing identity."""
    name = run(["git", "config", "user.name"], cwd=repo, check=False).stdout.strip() or "claude-bootstrap"
    email = run(["git", "config", "user.email"], cwd=repo, check=False).stdout.strip() or "claude-bootstrap@users.noreply.github.com"
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]
