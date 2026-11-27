"""Issue #1071: a changelog test holds before and after the release."""
import re

import changelogpins
from changelog_support import changelog_entry


def _repo(tmp_path, frag=None, released=""):
    (tmp_path / "docs" / "changelog.d").mkdir(parents=True)
    (tmp_path / "docs" / "changelog.d" / "README.md").write_text("fragments needle\n")
    if frag:
        (tmp_path / "docs" / "changelog.d" / "9-x.added.md").write_text(frag)
    (tmp_path / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n" + released)
    return tmp_path


def test_helper_finds_a_fragment_and_a_released_paragraph(tmp_path):
    root = _repo(tmp_path, "**Frag** needle one.\n", "## [1.0.0]\n\n**Rel** needle two.\n")
    assert len(changelog_entry("needle", root=root)) == 2          # README.md is no entry
    assert changelog_entry(re.compile("needle two"), root=root) == ["**Rel** needle two.\n"]
    assert changelog_entry("needle", fragment="8-*.md", root=root) == ["**Rel** needle two.\n"]


def test_helper_finds_the_entry_after_the_fragment_moved(tmp_path):
    root = _repo(tmp_path, released="**Moved** needle.\n")
    assert changelog_entry("needle", root=root) == ["**Moved** needle.\n"]


def _scan(tmp_path, body):
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_x.py").write_text(body)
    return changelogpins.scan(tmp_path)


def test_check_refuses_a_test_that_globs_only_the_fragments(tmp_path):
    body = "def test_a():\n    folder = ROOT / 'docs' / 'changelog.d'\n    assert list(folder.glob('9-*.md'))\n"
    assert [(f, ln) for f, ln, _ in _scan(tmp_path, body)] == [("tests/test_x.py", 3)]
    assert _scan(tmp_path, "def test_a():\n    assert list((ROOT / 'docs/changelog.d').glob('*.md'))\n")


def test_check_accepts_a_test_that_reads_the_released_file_or_uses_the_helper(tmp_path):
    reads = "def test_a():\n    list((ROOT / 'docs' / 'changelog.d').glob('*.md'))\n    (ROOT / 'docs' / 'CHANGELOG.md').read_text()\n"
    helper = "def test_a():\n    changelog_entry('x')\n"
    assert _scan(tmp_path, reads) == [] and _scan(tmp_path, helper) == []
