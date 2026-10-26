"""Helpers for commands that edit a gitops-app repo: system.yaml (comment-preserving), render, branch/commit/PR."""
from __future__ import annotations

import re
from pathlib import Path

from ruamel.yaml import YAML

import core
import model
from core import PlatformError, run

ENVS = list(model.ENVIRONMENTS)


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 120
    return y


def find_app(repo: Path, app: str | None = None) -> Path:
    base = repo / "applications"
    apps = sorted(p.parent for p in base.glob("*/system.yaml"))
    old = sorted({p.parent for f in ("app.yaml", "services.yaml") for p in base.glob(f"*/{f}")})
    if old and (not app or any(o.name == app for o in old) or not apps):
        raise model.NotMigrated()
    if not apps:
        raise PlatformError("no applications/*/system.yaml here", hint="run this inside a gitops-app repo (/system:new <manifest>)")
    if app:
        match = [a for a in apps if a.name == app]
        if not match:
            raise PlatformError(f"no application '{app}'", hint="available: " + ", ".join(a.name for a in apps))
        return match[0]
    if len(apps) > 1:
        raise PlatformError("several applications found", hint="pass --app <name>: " + ", ".join(a.name for a in apps))
    return apps[0]


def answers(repo: Path) -> dict:
    import yaml
    f = repo / ".copier-answers.yml"
    return yaml.safe_load(f.read_text()) if f.is_file() else {}


def load(app_dir: Path):
    y = _yaml()
    data = y.load((app_dir / "system.yaml").read_text())
    if data is None:
        from ruamel.yaml.comments import CommentedMap
        data = CommentedMap()
    return y, data


def components_of(data):
    """The `components` mapping of a loaded system.yaml (created when missing)."""
    if data.get("components") is None:
        from ruamel.yaml.comments import CommentedMap
        data["components"] = CommentedMap()
    return data["components"]


def save(app_dir: Path, y: YAML, data) -> None:
    import io
    buf = io.StringIO()
    y.dump(data, buf)
    (app_dir / "system.yaml").write_text(buf.getvalue())


def render(repo: Path) -> None:
    """Regenerate ApplicationSets/overlays with the repo's own scripts/render.py."""
    run(["uv", "run", "scripts/render.py"], cwd=repo)


def rendered_changes(repo: Path) -> list[str]:
    out = run(["git", "status", "--porcelain"], cwd=repo).stdout.splitlines()
    return [ln[3:] for ln in out]


def require_clean(repo: Path) -> None:
    if run(["git", "status", "--porcelain"], cwd=repo).stdout.strip():
        raise PlatformError("the working tree has uncommitted changes", hint="commit or stash first; each operation is one reviewable PR")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def open_pr(repo: Path, branch: str, title: str, body: str) -> str:
    """Create the branch, commit everything under applications/ and bootstrap/, push, and open a PR. Returns the URL."""
    run(["git", "checkout", "-q", "-b", branch], cwd=repo)
    run(["git", "add", "applications", "bootstrap"], cwd=repo, check=False)
    run(["git", *core.git_identity(repo), "commit", "-q", "-m", title], cwd=repo)
    run(["git", "push", "-q", "-u", "origin", branch], cwd=repo)
    return run(["gh", "pr", "create", "--base", "main", "--title", title, "--body", body], cwd=repo).stdout.strip().splitlines()[-1]
