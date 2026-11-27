"""Issue #1075: a land resolves conflicting plugin versions itself (higher one, above main's when the branch changed it)."""
import subprocess
from pathlib import Path

import pytest

import land_resolve

MARKET = """{
  "plugins": [
    {
      "name": "svc",
      "version": "%s",
      "description": "%s"
    },
    {
      "name": "web",
      "version": "%s"
    }
  ]
}
"""
PLUGIN = '{\n  "name": "svc",\n  "version": "%s",\n  "description": "%s"\n}\n'


def run(cmd, cwd, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(repo, *a, check=True):
    return run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], repo, check)


def conflict(tmp_path, path, make, base, ours, theirs):
    git(tmp_path, "init", "-q", "-b", "main")
    f = tmp_path / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(make(*base))
    git(tmp_path, "add", "-A"); git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "switch", "-qc", "branch")
    f.write_text(make(*ours))
    git(tmp_path, "commit", "-qam", "ours")
    git(tmp_path, "switch", "-q", "main")
    f.write_text(make(*theirs))
    git(tmp_path, "commit", "-qam", "theirs")
    git(tmp_path, "switch", "-q", "branch")
    assert git(tmp_path, "merge", "--no-commit", "main", check=False).returncode == 1


def go(tmp_path, path):
    assert land_resolve.handles(path)
    ctx = land_resolve.Context(base="", ours="", theirs="main", changed=[], next_adr=lambda: 0)
    return land_resolve.resolve(tmp_path, path, ctx, run)


def test_handles_only_the_manifests():
    assert land_resolve.handles(".claude-plugin/marketplace.json")
    assert land_resolve.handles("plugins/svc/.claude-plugin/plugin.json")
    assert not land_resolve.handles("plugins/svc/plugin.json") and not land_resolve.handles("package.json")


@pytest.mark.parametrize("ours,theirs,want", [("1.1.0", "1.0.1", "1.1.0"), ("1.0.1", "1.0.2", "1.0.3")])
def test_plugin_json_version(tmp_path, ours, theirs, want):
    path = "plugins/svc/.claude-plugin/plugin.json"
    conflict(tmp_path, path, lambda v, d: PLUGIN % (v, d), ("1.0.0", "d"), (ours, "d"), (theirs, "d"))
    out = go(tmp_path, path)
    assert f'"version": "{want}"' in (tmp_path / path).read_text() and "<<<<" not in (tmp_path / path).read_text()
    assert out.written == [path]


def test_marketplace_versions_per_plugin_and_other_edits_merge(tmp_path):
    path = ".claude-plugin/marketplace.json"
    make = lambda s, d, w: MARKET % (s, d, w)
    git(tmp_path, "init", "-q", "-b", "main")
    conflict(tmp_path, path, make, ("1.0.0", "d", "0.1.0"), ("1.0.1", "d", "0.2.0"), ("1.0.1", "d", "0.1.1"))
    out = go(tmp_path, path)
    text = (tmp_path / path).read_text()
    assert '"version": "1.0.1"' in text and '"version": "0.2.0"' in text and "<<<<" not in text
    assert out.written == [path]


def test_a_conflict_in_the_text_stays_a_person_decision(tmp_path):
    path = "plugins/svc/.claude-plugin/plugin.json"
    conflict(tmp_path, path, lambda v, d: PLUGIN % (v, d), ("1.0.0", "d"), ("1.0.1", "ours"), ("1.0.2", "theirs"))
    with pytest.raises(land_resolve.Refused):
        go(tmp_path, path)
