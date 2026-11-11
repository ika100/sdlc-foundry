"""refscan: an unreadable open-PR list (None) differs from no open PRs ({})."""
import stat
import subprocess

import refscan
import waiting


def fake_gh(tmp_path, monkeypatch, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    gh = bin_dir / "gh"
    gh.write_text(waiting.with_prelude("#!/bin/sh\n" + body + "\n"))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "feature/y", str(repo)], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "i"],
                   cwd=repo, check=True, capture_output=True)
    return repo


def test_no_open_prs_is_an_empty_dict(tmp_path, monkeypatch):
    repo = fake_gh(tmp_path, monkeypatch, "echo '[]'")
    assert refscan.open_pr_paths(repo) == {}


def test_open_prs_list_every_path_and_leave_out_the_current_branch(tmp_path, monkeypatch):
    rows = ('[{"number":1,"headRefName":"a","files":[{"path":"docs/specs/176-x/spec.md"},{"path":"x.py"}]},'
            '{"number":2,"headRefName":"feature/y","files":[{"path":"y"}]}]')
    repo = fake_gh(tmp_path, monkeypatch, f"echo '{rows}'")
    assert refscan.open_pr_paths(repo) == {"#1": ["docs/specs/176-x/spec.md", "x.py"]}


def test_unreadable_prs_are_none(tmp_path, monkeypatch):
    assert refscan.open_pr_paths(fake_gh(tmp_path, monkeypatch, "exit 1")) is None
    assert refscan.open_pr_paths(fake_gh(tmp_path / "b", monkeypatch, "echo 'not json'")) is None


def test_missing_gh_is_none(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PATH", "/nonexistent")
    assert refscan.open_pr_paths(repo) is None
