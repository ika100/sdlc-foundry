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
