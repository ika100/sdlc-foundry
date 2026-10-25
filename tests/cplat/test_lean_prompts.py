"""Spec 100 step 4: rare branches of build, ship and quick-task live in reference files."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ROOT / "plugins" / "svc" / "commands"
REFS = ROOT / "plugins" / "svc" / "references"
POINTER = "${CLAUDE_PLUGIN_ROOT}/references/"

# command -> reference file -> key text that must now live in the reference file
MOVED = {
    "build": {
        "build-resume.md": ["wip(<task-id>): interrupted", "git restore --staged"],
        "build-worktree-fallback.md": ["Cannot create agent worktree", "worktree.baseRef"],
        "build-replan.md": ["**Re-plan mode.**", "replan-abort", "Your earlier attempt is a reference only"],
        "build-security-red.md": ["cplat deps patch", "Exit 4", "agents.security"],
    },
    "ship": {
        "ship-gitops.md": ["cplat ship gitops prepare", "cplat ship gitops pr"],
        "ship-land-red.md": ["RED, the security check", "fix_rounds"],
    },
    "quick-task": {
        "quick-task-on-main.md": ["Skipping PR creation"],
    },
}


def _origin(name: str) -> str:
    out = subprocess.run(
        ["git", "show", f"origin/main:plugins/svc/commands/{name}.md"],
        cwd=ROOT, capture_output=True, check=True,
    )
    return out.stdout.decode()


@pytest.mark.parametrize("name", sorted(MOVED))
def test_command_is_smaller_than_at_origin_main(name):  # AC-100.13
    now = (COMMANDS / f"{name}.md").read_bytes()
    assert len(now) < len(_origin(name).encode())


@pytest.mark.parametrize("name,ref,keys", [(n, r, k) for n, refs in MOVED.items() for r, k in refs.items()])
def test_moved_branch_lives_in_its_reference_file(name, ref, keys):  # AC-100.14
    text = (REFS / ref).read_text()
    for key in keys:
        assert key in text, f"{key!r} missing from {ref}"


@pytest.mark.parametrize("name,ref", [(n, r) for n, refs in MOVED.items() for r in refs])
def test_command_points_to_the_reference_file(name, ref):  # AC-100.14
    assert POINTER + ref in (COMMANDS / f"{name}.md").read_text()


@pytest.mark.parametrize("name,ref,keys", [(n, r, k) for n, refs in MOVED.items() for r, k in refs.items()])
def test_moved_text_is_gone_from_the_command(name, ref, keys):  # AC-100.13
    text = (COMMANDS / f"{name}.md").read_text()
    assert not all(key in text for key in keys)
