"""Every template ignores Claude Code's agent worktrees: a `git add -A` in the main checkout once staged a parallel
batch's worktrees in a Go repo, and the run escalated (system-ship benchmark, 2026-11-09)."""
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


@pytest.mark.parametrize("template", sorted(p.name for p in TEMPLATES.iterdir() if (p / "copier.yml").exists()))
def test_the_template_ignores_agent_worktrees_and_local_settings(template):
    lines = (TEMPLATES / template / ".gitignore").read_text().splitlines()
    assert ".claude/worktrees/" in lines
    assert ".claude/settings.local.json" in lines
