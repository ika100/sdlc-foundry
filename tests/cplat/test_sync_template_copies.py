"""scripts/sync-template-copies.py keeps templates/cluster-gitops copies equal to gitops-app (spec 125)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "sync-template-copies.py"
PAIRS = {"render.py": "system_render.py", "local-cluster.sh": "local-cluster.sh", "ports.sh": "ports.sh"}


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(root / "scripts" / "sync-template-copies.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _sandbox(tmp_path: Path) -> Path:
    """A throwaway repo root holding the script and copies of the two template script folders."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)
    src = root / "templates" / "gitops-app" / "scripts"
    dst = root / "templates" / "cluster-gitops" / "scripts"
    src.mkdir(parents=True)
    dst.mkdir(parents=True)
    for s, d in PAIRS.items():
        (src / s).write_bytes(f"# source {s}\n".encode())
        shutil.copy2(src / s, dst / d)
    return root


def test_check_passes_when_in_sync(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    res = _run(root, "--check")
    assert res.returncode == 0, res.stderr


def test_check_names_the_differing_copy_and_the_fix(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    dst = root / "templates" / "cluster-gitops" / "scripts" / "system_render.py"
    dst.write_bytes(b"# drifted\n")
    res = _run(root, "--check")
    assert res.returncode == 1
    assert "templates/cluster-gitops/scripts/system_render.py" in res.stderr
    assert "uv run scripts/sync-template-copies.py" in res.stderr
    assert "ports.sh" not in res.stderr
    assert dst.read_bytes() == b"# drifted\n"  # --check never rewrites


def test_check_fails_when_a_copy_is_missing(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    (root / "templates" / "cluster-gitops" / "scripts" / "ports.sh").unlink()
    res = _run(root, "--check")
    assert res.returncode == 1
    assert "ports.sh" in res.stderr


def test_rewrite_restores_byte_equality(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    src = root / "templates" / "gitops-app" / "scripts"
    dst = root / "templates" / "cluster-gitops" / "scripts"
    (dst / "local-cluster.sh").write_bytes(b"# drifted\n")
    (dst / "ports.sh").unlink()
    res = _run(root)
    assert res.returncode == 0, res.stderr
    for s, d in PAIRS.items():
        assert (dst / d).read_bytes() == (src / s).read_bytes()
    assert _run(root, "--check").returncode == 0


def test_rewrite_keeps_executable_bit_of_existing_copy(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    dst = root / "templates" / "cluster-gitops" / "scripts" / "local-cluster.sh"
    dst.chmod(0o755)
    dst.write_bytes(b"# drifted\n")
    assert _run(root).returncode == 0
    assert dst.stat().st_mode & 0o111


def test_real_repo_is_in_sync() -> None:
    res = _run(REPO, "--check")
    assert res.returncode == 0, res.stderr
