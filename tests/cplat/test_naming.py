"""The project was renamed from claude-platform (marketplace ika100-claude) to sdlc-foundry in v3.0.0: keep the old names out of the tree."""
import fnmatch
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = re.compile(r"claude-platform|ika100-claude")
# historical records and the code/tests that deliberately mention the old names (legacy-install detection, rename notes)
ALLOWED_FILES = ("docs/CHANGELOG.md", "docs/changelog.d/*", "docs/adr/*", "docs/requirements/*", "scripts/cplat/doctor.py",
                 "tests/cplat/test_naming.py", "tests/cplat/test_update_doctor.py", "tests/cplat/test_rename_migration.py", "site/package-lock.json")


def tracked_text_files():
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    for name in filter(None, names):
        if any(fnmatch.fnmatch(name, pattern) for pattern in ALLOWED_FILES):
            continue
        try:
            yield name, (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue


def test_the_old_project_name_does_not_come_back():
    offenders = []
    for name, text in tracked_text_files():
        for number, line in enumerate(text.splitlines(), 1):
            if OLD.search(line) and not re.search(r"formerly|renamed|rename", line, re.I):
                offenders.append(f"{name}:{number}: {line.strip()[:100]}")
    assert not offenders, "old name 'claude-platform'/'ika100-claude' found (use sdlc-foundry):\n" + "\n".join(offenders[:20])
