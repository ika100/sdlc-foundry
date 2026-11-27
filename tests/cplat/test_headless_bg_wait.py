"""#1040: `claude -p` waits for its own background subagents (the run timeout bounds it)."""
import headless
from test_headless import fake_claude, repo  # noqa: F401  (fixture)


def test_the_run_waits_for_background_subagents_without_a_ceiling(tmp_path, monkeypatch, repo):
    fake_claude(tmp_path, monkeypatch, 'echo "$CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS" > ceiling.txt')
    monkeypatch.setenv("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "600000")   # a person's own value does not cut a unit short
    headless.run_once([str(tmp_path / "claude")], repo, tmp_path / "log.txt", 1)
    assert (repo / "ceiling.txt").read_text().strip() == "0"
