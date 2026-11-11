"""Unit tests for specnumbers: folder parsing and the legacy STORY ids."""
import specnumbers


def test_numbered_groups_folders_and_ignores_other_names():
    assert specnumbers.numbered(["001-a", "001-b", "12-short", "1234-long", "README.md"]) == {
        1: {"001-a", "001-b"}, 1234: {"1234-long"}}


def test_next_number_counts_legacy_story_ids(tmp_path):
    (tmp_path / "docs" / "specs" / "003-a").mkdir(parents=True)
    (tmp_path / "docs" / "backlog.md").write_text("#### STORY-009 - old\n")
    assert specnumbers.next_number(tmp_path)[0] == 10


def test_clashes_without_a_base_ref_is_empty(tmp_path):
    (tmp_path / "docs" / "specs" / "003-a").mkdir(parents=True)
    assert specnumbers.clashes(tmp_path) == ([], None)
