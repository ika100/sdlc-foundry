"""Spec 197 acceptance test: the web release agent's documented next-development-version step works as written (AC-197.5).

The test extracts the command line from step 3 of plugins/web/agents/release.md and runs it, unchanged, in a scratch git repo on a
`release/vX.Y.Z` branch whose new CHANGELOG.md is not committed yet, with the pnpm version the web template pins. `devbox run --`
is a shim that runs the rest of the line; `pnpm` is a shim to `npx pnpm@<pinned>`. Skipped where that pnpm cannot be fetched."""
import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "plugins" / "web" / "agents" / "release.md"
DEVBOX = ROOT / "templates" / "web-nextjs" / "devbox.json.jinja"
NEXT_DEV = "0.3.1-dev.0"


def documented_step() -> list[str]:
    """The single `devbox run -- ...` line of step 3's code block, as an argv (`pnpm version` or the `pnpm pkg set` fallback)."""
    text = PROMPT.read_text()
    step = re.split(r"^### 3\..*$", text, flags=re.M)[1].split("\n### ", 1)[0]
    block = re.search(r"```bash\n(.*?)```", step, re.S).group(1)
    (line,) = [ln for ln in block.splitlines() if ln.startswith("devbox run --")]
    return shlex.split(line.replace("<NEXT_DEV>", NEXT_DEV))


def pinned_pnpm() -> str:
    return re.search(r'"pnpm@([^"]+)"', DEVBOX.read_text()).group(1)


def shim(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    """A bin dir with `devbox` (runs `devbox run -- <cmd>`) and `pnpm` (the pinned version through npx), or a skip."""
    version = pinned_pnpm()
    bin_dir = tmp_path_factory.mktemp("bin197")
    shim(bin_dir / "devbox", '[ "$1" = run ] && shift; [ "$1" = -- ] && shift; exec "$@"\n')
    shim(bin_dir / "pnpm", f'exec npx --yes pnpm@{version} "$@"\n')
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    try:
        probe = subprocess.run(["pnpm", "--version"], env=env, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"pnpm {version} cannot be fetched here (npx: {type(e).__name__})")
    if probe.returncode != 0 or probe.stdout.strip() != version:
        pytest.skip(f"pnpm {version} cannot be fetched here (npx exit {probe.returncode}: {probe.stderr.strip()[:120]})")
    return env


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def release_branch(tmp_path, tracked_changelog):
    repo = tmp_path / "web"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "package.json").write_text(json.dumps({"name": "web", "version": "0.3.0", "private": True}, indent=2) + "\n")
    if tracked_changelog:
        (repo / "CHANGELOG.md").write_text("## [0.2.0]\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "checkout", "-qb", "release/v0.3.0")
    (repo / "CHANGELOG.md").write_text("## [0.3.0] - 2026-11-13\n\n### Features\n- x (abc1234)\n" + ("\n## [0.2.0]\n" if tracked_changelog else ""))
    return repo


@pytest.mark.parametrize("tracked_changelog", [False, True], ids=["untracked-changelog", "modified-changelog"])
def test_the_documented_version_step_runs_on_a_dirty_release_branch_ac_197_5(tools, tmp_path, tracked_changelog):  # AC-197.5
    repo = release_branch(tmp_path, tracked_changelog)
    commits, tags = git(repo, "rev-list", "--count", "HEAD"), git(repo, "tag")
    done = subprocess.run(documented_step(), cwd=repo, env=tools, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads((repo / "package.json").read_text())["version"] == NEXT_DEV
    assert git(repo, "tag") == tags == ""
    assert git(repo, "rev-list", "--count", "HEAD") == commits
    assert (repo / "CHANGELOG.md").is_file()
