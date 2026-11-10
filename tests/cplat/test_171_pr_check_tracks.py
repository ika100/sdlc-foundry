"""Spec 171 acceptance tests: `cplat platform pr-check --body-file` in a linked worktree and with a body it cannot read (AC-171.9),
and `--tracks` given more than once (AC-171.10).

Seams: the platform-shaped repo of the spec 150 tests and a real linked worktree of it; `cplat.main` (so that a crash would reach
the automatic issue filing, which the tests replace by a recorder); `spec.main` with `claim.claim` replaced by a recorder.
"""
import os
import re
from pathlib import Path

import pytest

import claim
import cplat
import house_rules
import spec
from test_150_pr_check import commit, git, repo  # noqa: F401  (fixtures, helpers)

TITLE = "feat(cplat): a change"


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


@pytest.fixture()
def crashes(monkeypatch):
    """The places a crash of `cplat` would be filed as an issue or printed: both must stay unused."""
    seen = []
    monkeypatch.setattr(cplat, "_file_crash", lambda argv, exc: (seen.append((argv, exc)), [])[1])
    return seen


def worktree(repo, tmp_path):
    wt = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "feature/linked", str(wt))
    git(wt, "config", "user.name", "t")
    git(wt, "config", "user.email", "t@t")
    commit(wt, "scripts/a.py")
    commit(wt, "docs/changelog.d/171-a.added.md", "**A change (spec 171).** Text.\n")
    gd = git(wt, "rev-parse", "--git-dir")
    return wt, (Path(gd) if os.path.isabs(gd) else wt / gd)


# ---------------- AC-171.9 ----------------

def test_a_body_in_the_git_dir_of_a_linked_worktree_is_read_where_the_other_commands_read_it(repo, tmp_path, capsys):  # AC-171.9
    wt, gitdir = worktree(repo, tmp_path)
    assert (wt / ".git").is_file()                                 # a linked worktree: `.git` is a file, not a directory
    (gitdir / "PR_BODY.md").write_text("Closes #12\n")
    rc = house_rules.main(["--repo", str(wt), "--base", "main", "--title", TITLE, "--body-file", ".git/PR_BODY.md"])
    out = capsys.readouterr().out
    assert "Traceback" not in out
    assert rc == 1 and "ERROR: spec-required" in out               # the body was read: it closes an issue, the change has no spec
    (gitdir / "PR_BODY.md").write_text("A change without a closing reference.\n")
    assert house_rules.main(["--repo", str(wt), "--base", "main", "--title", TITLE, "--body-file", ".git/PR_BODY.md"]) == 0
    assert capsys.readouterr().out.startswith("OK: the house rules pass")


def run_cli(repo, body_file):
    return cplat.main(["platform", "pr-check", "--repo", str(repo), "--base", "main", "--title", TITLE, "--body-file", body_file])


def test_a_body_file_that_does_not_exist_is_one_error_line(repo, capsys, crashes):  # AC-171.9
    assert run_cli(repo, "no-such-body.md") == 1
    cap = capsys.readouterr()
    lines = [ln for ln in (cap.out + cap.err).splitlines() if ln.strip()]
    assert lines == ["ERROR: body file no-such-body.md: does not exist"]
    assert crashes == []


def test_a_body_file_that_is_a_directory_is_one_error_line(repo, capsys, crashes):  # AC-171.9
    (repo / "bodies").mkdir()
    assert run_cli(repo, "bodies") == 1
    cap = capsys.readouterr()
    lines = [ln for ln in (cap.out + cap.err).splitlines() if ln.strip()]
    assert lines == ["ERROR: body file bodies: is a directory"]
    assert crashes == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_a_body_file_that_cannot_be_read_is_one_error_line(repo, capsys, crashes):  # AC-171.9
    body = repo / "locked.md"
    body.write_text("x\n")
    body.chmod(0)
    try:
        assert run_cli(repo, "locked.md") == 1
    finally:
        body.chmod(0o600)
    cap = capsys.readouterr()
    lines = [ln for ln in (cap.out + cap.err).splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("ERROR: body file locked.md: ") and "ermission" in lines[0]
    assert "Traceback" not in cap.out + cap.err and crashes == []


def test_a_missing_body_file_in_a_linked_worktree_names_the_path_as_given(repo, tmp_path, capsys, crashes):  # AC-171.9
    wt, _ = worktree(repo, tmp_path)
    assert run_cli(wt, ".git/PR_BODY.md") == 1
    cap = capsys.readouterr()
    assert [ln for ln in (cap.out + cap.err).splitlines() if ln.strip()] == ["ERROR: body file .git/PR_BODY.md: does not exist"]
    assert crashes == []


# ---------------- AC-171.10 ----------------

@pytest.fixture()
def claims(monkeypatch):
    seen = []
    monkeypatch.setattr(claim, "claim", lambda repo, issues, branch, **kw: (seen.append((list(issues), branch)), [])[1])
    return seen


def new_spec(root, capsys, *flags):
    assert spec.main(["--repo", str(root), "new", "Settle", "small", "problems", *flags]) == 0
    path = root / capsys.readouterr().out.splitlines()[0]
    return spec.read(path.parent)


@pytest.mark.parametrize("flags, tracks", [
    (["--tracks", "613", "--tracks", "621"], [613, 621]),
    (["--tracks", "613", "621"], [613, 621]),
    (["--tracks", "613", "621", "--tracks", "622", "633"], [613, 621, 622, 633]),
    (["--tracks", "613", "--tracks", "613"], [613]),
    (["--tracks", "621", "613", "--tracks", "613", "622", "621"], [621, 613, 622]),
    (["--tracks", "613", "--tracks", "621", "--tracks", "622", "--tracks", "623", "--tracks", "624", "--tracks", "625",
      "--tracks", "626", "--tracks", "633"], [613, 621, 622, 623, 624, 625, 626, 633]),
    (["--tracks", "613"], [613]),
])
def test_every_tracked_issue_is_kept_once_in_the_order_given_and_claimed(tmp_path, capsys, claims, flags, tracks):  # AC-171.10
    created = new_spec(tmp_path, capsys, *flags)
    assert created.meta["tracks"] == tracks
    assert [i for issues, _ in claims for i in issues] == tracks
    assert {branch for _, branch in claims} == {f"feature/{created.id}"}


def test_no_tracks_flag_keeps_no_tracks_and_claims_nothing(tmp_path, capsys, claims):  # AC-171.10
    created = new_spec(tmp_path, capsys)
    assert not created.meta.get("tracks") and claims == []


def test_no_other_command_keeps_only_the_last_tracks_flag():  # AC-171.10
    """The `--tracks` flag of every `cplat` command extends: none of them may be a plain `nargs="*"` that keeps the last."""
    calls = [c for f in sorted(Path(spec.__file__).parent.glob("*.py"))
             for c in re.findall(r"add_argument\(\s*[\"']--tracks[\"'][^)]*\)", f.read_text())]
    assert calls, "at least `cplat spec new` takes --tracks"
    assert all("extend" in c for c in calls), calls
