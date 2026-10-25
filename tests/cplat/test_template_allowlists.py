"""Every template's Claude Code allowlist covers the steps headless sessions take: each commit flag order the commands use, and
reading the plugins' own reference files (outside the repo). Found by the spec-099 benchmark: one missing order (`-q -m`) or
the missing plugin read stopped a whole headless build."""
from pathlib import Path

import pytest

import core

TEMPLATES = sorted(p for p in (core.PLATFORM_ROOT / "templates").glob("*/.claude/settings.json*"))
NEEDED = ["Bash(git commit -m *)", "Bash(git commit -q -m *)", "Bash(git commit -s -m *)", "Bash(git commit -q -s -m *)",
          "Bash(git commit -s -q -m *)", "Read(~/.claude/plugins/**)"]


@pytest.mark.parametrize("settings", TEMPLATES, ids=lambda p: p.parts[-3])
def test_the_allowlist_covers_headless_commits_and_plugin_reads(settings: Path):
    text = settings.read_text()
    assert [rule for rule in NEEDED if f'"{rule}"' not in text] == []


def test_every_shape_has_an_allowlist():
    assert len(TEMPLATES) == 6
