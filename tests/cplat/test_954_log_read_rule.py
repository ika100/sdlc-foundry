"""#954: a session reads the log `cplat quiet` saved without a permission prompt, in every repo the platform makes."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import preflight
import quiet

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = [ROOT / ".claude" / "settings.json", *sorted(ROOT.glob("templates/*/.claude/settings.json*"))]


def _allow(path: Path) -> list[str]:
    text = re.sub(r"{%.*?%}|{{.*?}}", "", path.read_text(), flags=re.DOTALL)   # the Jinja parts hold no allow rules
    return json.loads(text)["permissions"]["allow"]


@pytest.mark.parametrize("settings", SETTINGS, ids=[str(p.relative_to(ROOT)) for p in SETTINGS])
def test_the_saved_log_of_a_quiet_run_is_readable(settings, monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log = quiet._log_path(tmp_path / "some-worktree", "test-fast")
    path = "~/" + log.relative_to(tmp_path).as_posix()
    assert any(preflight.read_matches(rule, path) for rule in _allow(settings))
