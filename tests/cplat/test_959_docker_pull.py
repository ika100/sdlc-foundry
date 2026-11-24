"""#959: a unit session pulls a test image (testcontainers) without a permission prompt, in every repo that builds images."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# every settings file that allows image builds: the platform repo and the templates of image-building shapes
SETTINGS = [p for p in [ROOT / ".claude" / "settings.json", *sorted(ROOT.glob("templates/*/.claude/settings.json*"))]
            if "Bash(docker build *)" in p.read_text()]


def _allow(path: Path) -> list[str]:
    text = re.sub(r"{%.*?%}|{{.*?}}", "", path.read_text(), flags=re.DOTALL)   # the Jinja parts hold no allow rules
    return json.loads(text)["permissions"]["allow"]


def test_every_image_building_repo_is_covered():
    assert len(SETTINGS) >= 8


@pytest.mark.parametrize("settings", SETTINGS, ids=[str(p.relative_to(ROOT)) for p in SETTINGS])
def test_docker_pull_is_allowed_and_nothing_broader(settings):
    allow = _allow(settings)
    assert "Bash(docker pull *)" in allow
    assert not [r for r in allow if r in ("Bash(docker *)", "Bash(docker*)")]
