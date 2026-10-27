"""The secrets baseline is repo-owned: a skeleton update keeps the repo's own (its recorded false positives), and only adds
the template's when the repo has none. Found by the 099 benchmark: an update replaced todo-api's baseline."""
import subprocess

import update


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_a_missing_baseline_is_seeded_but_other_new_project_owned_files_are_dropped(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".secrets.baseline.json").write_text("{}")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_starter.py").write_text("")
    dropped = update.drop_new_project_owned_files(tmp_path, [".secrets.baseline.json", "tests/**"])
    assert dropped == ["tests/test_starter.py"] and (tmp_path / ".secrets.baseline.json").is_file()


def test_every_template_keeps_an_existing_baseline():
    for cfg in (update.PLATFORM_ROOT / "templates").glob("*/copier.yml"):
        assert ".secrets.baseline.json" in update.project_owned_patterns(cfg.parent.name), cfg


def test_missing_project_notes_are_seeded_because_claude_md_imports_them(tmp_path):   # #239
    git(tmp_path, "init", "-q")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "project-notes.md").write_text("")
    dropped = update.drop_new_project_owned_files(tmp_path, [".claude/project-notes.md"])
    assert dropped == [] and (tmp_path / ".claude" / "project-notes.md").is_file()


def test_every_template_keeps_existing_project_notes():
    for cfg in (update.PLATFORM_ROOT / "templates").glob("*/copier.yml"):
        assert ".claude/project-notes.md" in update.project_owned_patterns(cfg.parent.name), cfg
