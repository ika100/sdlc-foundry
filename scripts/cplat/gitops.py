"""Helpers for commands that edit a gitops-app repo: system.yaml (comment-preserving), render, branch/commit/PR."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ruamel.yaml import YAML

import core
import model
import pr_rules
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


def scratch_tree(path: Path) -> None:
    """Make a throwaway copy a clean one-commit git tree, so commands that require a clean tree run on it (console preview)."""
    ident = ["-c", "user.name=preview", "-c", "user.email=preview@localhost", "-c", "commit.gpgsign=false"]
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", "snapshot"]):
        subprocess.run(["git", *ident, *args], cwd=path, text=True, capture_output=True, check=False)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def discard_changes(repo: Path) -> None:
    """Undo the working-tree changes of a command under applications/ and bootstrap/ (every caller started clean)."""
    run(["git", "checkout", "-q", "--", "applications", "bootstrap"], cwd=repo, check=False)
    run(["git", "clean", "-fdq", "--", "applications", "bootstrap"], cwd=repo, check=False)


def open_pr(repo: Path, branch: str, title: str, body: str) -> str:
    """Create the branch, commit everything under applications/ and bootstrap/, push, and open a PR. Returns the URL.

    A local branch of that name left by a merged PR (its remote branch is gone) is replaced. When a step fails, the clone
    is restored before the error is raised: back on the starting branch, the change discarded, the new local branch deleted
    (spec 142, AC-142.5), so the next run starts clean; a pushed branch is named in the error."""
    title = pr_rules.fit(title)
    start = run(["git", "branch", "--show-current"], cwd=repo, check=False).stdout.strip() or "main"
    if run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo, check=False).returncode == 0:
        if run(["git", "ls-remote", "--exit-code", "--heads", "origin", branch], cwd=repo, check=False).returncode == 2:
            run(["git", "branch", "-q", "-D", branch], cwd=repo)          # stale: its PR was merged and the branch deleted
    created = pushed = False
    try:
        run(["git", "checkout", "-q", "-b", branch], cwd=repo)
        created = True
        run(["git", "add", "applications", "bootstrap"], cwd=repo, check=False)
        run(["git", *core.git_identity(repo), "commit", "-q", "-m", title], cwd=repo)
        run(["git", "push", "-q", "-u", "origin", branch], cwd=repo)
        pushed = True
        return run(["gh", "pr", "create", "--base", "main", "--title", title, "--body", body], cwd=repo).stdout.strip().splitlines()[-1]
    except PlatformError as e:
        if created:
            run(["git", "checkout", "-q", "-f", start], cwd=repo, check=False)
            run(["git", "branch", "-q", "-D", branch], cwd=repo, check=False)
        discard_changes(repo)
        where = f"; the branch {branch} was pushed to origin: delete it there or open its PR by hand" if pushed else ""
        raise PlatformError(f"{e}{where}", hint="the clone is back on " + start + " with nothing changed; run the command again") from e
