"""PR bodies: agents write `.pr-body.md` in the repo root (Claude Code refuses edits under .git/ even with acceptEdits, so a
headless quick-task could not call `cplat pr open`). cplat moves the file into .git/ before it commits, so no commit has it."""
import subprocess

import core


def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_a_body_in_the_repo_root_moves_into_git_dir(tmp_path):
    r = repo(tmp_path)
    (r / ".pr-body.md").write_text("Summary\n\n{{CLOSES}}\n")
    staged = core.stage_pr_body(r, ".pr-body.md")
    assert staged == r / ".git" / "PR_BODY.md" and staged.read_text() == "Summary\n\n{{CLOSES}}\n"
    assert not (r / ".pr-body.md").exists()


def test_a_body_already_under_git_dir_is_used_as_it_is(tmp_path):
    r = repo(tmp_path)
    (r / ".git" / "PR_BODY.md").write_text("old place")
    assert core.stage_pr_body(r, ".git/PR_BODY.md") == r / ".git" / "PR_BODY.md"
    assert core.stage_pr_body(r, ".pr-body.md").read_text() == "old place"   # default name, older location still found


def test_a_missing_body_is_returned_unchanged_for_the_caller_to_refuse(tmp_path):
    r = repo(tmp_path)
    assert core.stage_pr_body(r, ".pr-body.md") == r / ".pr-body.md"


def test_no_command_tells_the_model_to_write_into_git_dir():
    import re
    write_into_git = re.compile(r"[Ww]rite (?:a short |the )?(?:PR )?body (?:with the Write tool )?(?:to|into) `\.git/")
    for f in (core.PLATFORM_ROOT / "plugins").glob("*/commands/*.md"):
        assert not write_into_git.search(f.read_text()), f


def worktree(tmp_path):
    """A linked worktree: its `.git` is a file pointing at the main checkout's .git/worktrees/<name> (#227)."""
    main = repo(tmp_path / "main")
    subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "feature/x", str(wt)], check=True)
    assert (wt / ".git").is_file()
    return wt


def test_in_a_worktree_the_body_moves_into_the_worktrees_git_dir(tmp_path):
    """#227: the body left the work tree only when .git was a directory, so `pr open` committed it in a worktree."""
    wt = worktree(tmp_path)
    (wt / ".pr-body.md").write_text("Summary\n")
    staged = core.stage_pr_body(wt, ".pr-body.md")
    assert staged == core.git_dir(wt) / "PR_BODY.md" and staged.read_text() == "Summary\n"
    assert not (wt / ".pr-body.md").exists()
    status = subprocess.run(["git", "-C", str(wt), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    assert status == ""


def test_in_a_worktree_a_git_path_points_into_its_git_dir(tmp_path):
    wt = worktree(tmp_path)
    assert core.git_path(wt, ".git/PR_BODY.md") == core.git_dir(wt) / "PR_BODY.md"
    assert core.git_path(wt, "docs/x.md") == wt / "docs" / "x.md"
    (core.git_dir(wt) / "PR_BODY.md").write_text("staged")
    assert core.stage_pr_body(wt, ".git/PR_BODY.md").read_text() == "staged"
