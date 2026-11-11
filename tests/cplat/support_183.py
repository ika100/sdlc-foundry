"""Spec 183: builders shared by the acceptance tests (not a test module): git worlds with a bare origin, fake `gh`."""
import json
import os
import stat
import subprocess
from pathlib import Path

SPEC_TEXT = """---
spec_id: {name}
title: {title}
status: draft
priority: P1
---

# {num} - {title}

## Problem

Something.

## Acceptance criteria

- **AC-{num}.1** Given a thing, when it runs, then it works.

## Non-goals

- None

## Open questions

None.

## Changelog

- 2026-11-01 created
"""


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, check=True, capture_output=True)


def add_spec(repo, name, text=None):
    num = name.split("-", 1)[0]
    d = Path(repo) / "docs" / "specs" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(text or SPEC_TEXT.format(name=name, num=num, title=name.split("-", 1)[1].replace("-", " ")))
    return d


def commit_all(repo, msg="c"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


def world(tmp_path, main_specs=("175-base",), branches=None):
    """origin with main (the given spec folders) and pushed branches {name: [spec folders it adds]}; a clone on feature/y."""
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    git(repo, "remote", "add", "origin", str(origin))
    (repo / "README.md").write_text("x\n")
    for s in main_specs:
        add_spec(repo, s)
    commit_all(repo, "init")
    git(repo, "push", "-q", "origin", "main")
    for branch, specs in (branches or {}).items():
        git(repo, "switch", "-qc", branch)
        for s in specs:
            add_spec(repo, s)
        commit_all(repo, branch)
        git(repo, "push", "-q", "origin", branch)
        git(repo, "switch", "-q", "main")
    git(repo, "switch", "-qc", "feature/y")
    git(repo, "fetch", "-q", "origin")
    return repo


def fake_gh(tmp_path, monkeypatch, prs=None, fail=False):
    """A `gh` on PATH: `pr list` prints `prs` ({number: [paths]}) as the JSON gh gives, or exits 1 when `fail`."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    doc = [{"number": n, "headRefName": f"pr/{n}", "files": [{"path": p} for p in paths]} for n, paths in (prs or {}).items()]
    script = bin_dir / "gh"
    body = "#!/bin/sh\nexit 1\n" if fail else f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(doc)}\nEOF\n"
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
