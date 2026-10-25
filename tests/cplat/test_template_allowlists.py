"""Every template's Claude Code allowlist covers the steps headless sessions take: each commit flag order the commands use, and
reading the plugins' own reference files (outside the repo). Found by the 099/100 benchmarks: every missing flag order
(`-q -m`, then `-am`, `-a -s -m`) or the missing plugin read stopped a whole headless build."""
from pathlib import Path

import pytest

import core

TEMPLATES = sorted(p for p in (core.PLATFORM_ROOT / "templates").glob("*/.claude/settings.json*"))
NEEDED = ["Bash(git commit *)", "Read(~/.claude/plugins/**)"]   # any flag order: -am, -a -s -m, -q -m … all stopped a build


@pytest.mark.parametrize("settings", TEMPLATES, ids=lambda p: p.parts[-3])
def test_the_allowlist_covers_headless_commits_and_plugin_reads(settings: Path):
    text = settings.read_text()
    assert [rule for rule in NEEDED if f'"{rule}"' not in text] == []


def test_every_shape_has_an_allowlist():
    assert len(TEMPLATES) == 6
