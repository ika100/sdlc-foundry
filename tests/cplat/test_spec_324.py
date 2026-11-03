"""#324: `cplat spec test-diff --approve` records a user-approved acceptance-test change; later runs accept that content."""
import spec
from test_spec import PY_BEFORE, _committed_repo


def test_an_approved_change_passes_until_the_file_changes_again_324(tmp_path, capsys):
    """#324: the approval covers the exact content; the next change is flagged again."""
    _committed_repo(tmp_path)
    f = tmp_path / "tests" / "test_x.py"
    f.write_text(PY_BEFORE.replace("200.01", "1"))
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 1
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD", "--approve", "tests/test_x.py",
                      "--reason", "the fixture was wrong"]) == 0
    capsys.readouterr()
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 0
    assert "tests/test_x.py: approved by the user: the fixture was wrong" in capsys.readouterr().out
    f.write_text(PY_BEFORE.replace("200.01", "2"))
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 1
    assert "tests/test_x.py: changed" in capsys.readouterr().out


def test_an_approval_belongs_to_its_red_commit_324(tmp_path):
    """#324: an approval against another red commit does not count."""
    import subprocess
    _committed_repo(tmp_path)
    f = tmp_path / "tests" / "test_x.py"
    f.write_text(PY_BEFORE.replace("200.01", "1"))
    spec.approve_test_change(tmp_path, "HEAD", ["tests/test_x.py"], None)
    assert spec.test_diff(tmp_path, "HEAD", [])["tests/test_x.py"][0] is True
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    f.write_text(PY_BEFORE + "\n")
    g("add", "."); g("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "another red")
    f.write_text(PY_BEFORE.replace("200.01", "1"))
    assert spec.test_diff(tmp_path, "HEAD", [])["tests/test_x.py"][0] is False


def test_approve_needs_files_324(tmp_path, capsys):
    """#324: `--approve` without files approves nothing."""
    _committed_repo(tmp_path)
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD", "--approve"]) == 2
    assert "--approve needs" in capsys.readouterr().err


def test_an_approval_is_added_to_the_run_record_324(tmp_path, monkeypatch):
    """#324: the active run gets an `approved_test_diffs` entry (the shape spec 133's PR block reads)."""
    import runs
    _committed_repo(tmp_path)
    (tmp_path / "tests" / "test_x.py").write_text(PY_BEFORE.replace("200.01", "1"))
    added = []
    monkeypatch.setattr(runs, "current_run", lambda root: "r1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **kw: added.append((rid, name, item)))
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD", "--approve", "tests/test_x.py", "--task", "t3",
                      "--reason", "typo in the fixture"]) == 0
    assert added == [("r1", "approved_test_diffs", {"file": "tests/test_x.py", "task": "t3", "reason": "typo in the fixture"})]
