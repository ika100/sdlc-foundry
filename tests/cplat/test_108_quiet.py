"""Spec 108 acceptance tests: `cplat quiet [--raw] <script>` (AC-108.1, AC-108.7, AC-108.10). The fake devbox of the spec 100 tests prints
$FAKE_OUT and exits with $FAKE_RC."""
import json
from pathlib import Path

import pytest

import quiet
from failsum_support import sample
from test_lean_briefs import repo  # noqa: F401  (fixture: fake devbox, scripts test-fast and quality, XDG_CACHE_HOME)


def logs(cache: Path, script: str) -> list[Path]:
    return sorted((cache / "sdlc-foundry" / "logs" / "myrepo").glob(f"*-{script}.log"))


def test_a_failing_command_prints_the_summary_with_the_log_path_and_passes_the_exit_code_ac_108_1(repo, capsys, monkeypatch):  # AC-108.1
    out, cache = repo
    out.write_text(sample("pytest-long.log"))
    monkeypatch.setenv("FAKE_RC", "1")
    assert quiet.main(["test-fast"]) == 1
    printed = capsys.readouterr().out
    (log,) = logs(cache, "test-fast")
    assert printed.startswith(f"FAILED (exit 1): devbox run test-fast (log: {log})\n")
    assert f"== check: test-fast | format: pytest | command: devbox run test-fast | exit: 1 | log: {log} | entries: 3" in printed
    assert "- tests/test_todos_api.py::test_delete_todo at tests/test_todos_api.py:31 | AssertionError | " in printed
    assert "test session starts" not in printed and "site-packages" not in printed, "the summary replaces the last 40 lines"


@pytest.mark.parametrize("rc", [2, 3, 127])
def test_the_exit_code_passes_through_unchanged_ac_108_1(repo, capsys, monkeypatch, rc):  # AC-108.1
    repo[0].write_text(sample("mypy.log"))
    monkeypatch.setenv("FAKE_RC", str(rc))
    assert quiet.main(["quality"]) == rc
    printed = capsys.readouterr().out
    assert f"FAILED (exit {rc}): devbox run quality (log: " in printed
    assert f"== check: quality | format: mypy | command: devbox run quality | exit: {rc} | " in printed


def test_an_unreadable_failure_still_prints_the_last_40_lines_ac_108_1(repo, capsys, monkeypatch):  # AC-108.1
    repo[0].write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    monkeypatch.setenv("FAKE_RC", "3")
    assert quiet.main(["quality"]) == 3
    printed = capsys.readouterr().out
    assert printed.startswith("FAILED (exit 3): devbox run quality (log: ")
    assert "format: unknown" in printed and "line 99" in printed and "line 60" in printed and "line 59" not in printed


def test_a_succeeding_command_prints_what_spec_100_printed_ac_108_1(repo, capsys):  # AC-108.1
    import failsum  # noqa: F401  (the summarizer exists; success output must not change)
    out, cache = repo
    out.write_text("....\nnoise\n\n5 passed in 0.1s\n\n")
    assert quiet.main(["test-fast"]) == 0
    printed = capsys.readouterr().out
    (log,) = logs(cache, "test-fast")
    assert printed == f"ok: devbox run test-fast (5 lines, log: {log})\n5 passed in 0.1s\n"
    assert not Path(str(log) + ".summary.json").exists()


def test_the_full_log_stays_on_the_machine_next_to_a_sidecar_with_the_printed_summary_ac_108_7(repo, capsys, monkeypatch):  # AC-108.7
    out, cache = repo
    raw = sample("pytest-long.log")
    out.write_text(raw)
    monkeypatch.setenv("FAKE_RC", "1")
    quiet.main(["test-fast"])
    printed = capsys.readouterr().out
    (log,) = logs(cache, "test-fast")
    assert log.read_text() == raw, "the whole log is kept"
    side = Path(str(log) + ".summary.json")
    data = json.loads(side.read_text())
    assert data["text"] == printed.rstrip("\n") and "test-fast|" in data["normalized"]
    import failsum
    assert failsum.sidecar(log) == side and failsum.read_sidecar(log) == data


def test_raw_reports_the_failure_as_before_and_says_summaries_are_off_ac_108_10(repo, capsys, monkeypatch):  # AC-108.10
    out, cache = repo
    out.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    monkeypatch.setenv("FAKE_RC", "3")
    assert quiet.main(["--raw", "quality"]) == 3
    (log,) = logs(cache, "quality")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"FAILED (exit 3): devbox run quality (log: {log})"
    assert lines[1] == "summaries: off (--raw)"
    assert lines[2:] == [f"line {i}" for i in range(60, 100)]
    assert not Path(str(log) + ".summary.json").exists()


def test_raw_is_not_passed_on_to_the_script_and_a_raw_success_is_unchanged_ac_108_10(repo, capsys):  # AC-108.10
    repo[0].write_text("5 passed in 0.1s\n")
    assert quiet.main(["--raw", "test-fast"]) == 0
    assert capsys.readouterr().out.startswith("ok: devbox run test-fast (1 lines, log: ")
    assert quiet.main(["--raw", "nope"]) == 2 and quiet.main(["--raw"]) == 2 and quiet.main(["test-fast", "--raw"]) == 2


def test_the_project_setting_turns_summaries_off_ac_108_10(repo, capsys, monkeypatch):  # AC-108.10
    out, cache = repo
    (Path.cwd() / ".platform-settings.yml").write_text("failure_summary: off\n")
    out.write_text(sample("pytest-long.log"))
    monkeypatch.setenv("FAKE_RC", "1")
    assert quiet.main(["test-fast"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == "summaries: off (.platform-settings.yml failure_summary: off)"
    assert lines[2:] == sample("pytest-long.log").splitlines()[-40:]
    (log,) = logs(cache, "test-fast")
    assert not Path(str(log) + ".summary.json").exists()


def test_raw_wins_over_the_setting_in_the_reason_ac_108_10(repo, capsys, monkeypatch):  # AC-108.10
    (Path.cwd() / ".platform-settings.yml").write_text("failure_summary: off\n")
    repo[0].write_text("boom\n")
    monkeypatch.setenv("FAKE_RC", "1")
    quiet.main(["--raw", "quality"])
    assert capsys.readouterr().out.splitlines()[1] == "summaries: off (--raw)"


def test_an_invalid_setting_stops_with_exit_2_before_the_script_runs_ac_108_10(repo, capsys, monkeypatch):  # AC-108.10
    out, cache = repo
    (Path.cwd() / ".platform-settings.yml").write_text("failure_summary: maybe\n")
    out.write_text("x\n")
    assert quiet.main(["test-fast"]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR: ") and "failure_summary must be on or off, got 'maybe'" in captured.err
    assert not (cache / "sdlc-foundry").exists(), "nothing was run"


def test_summaries_are_on_by_default_ac_108_10(repo, capsys, monkeypatch):  # AC-108.10
    repo[0].write_text(sample("mypy.log"))
    monkeypatch.setenv("FAKE_RC", "1")
    quiet.main(["quality"])
    printed = capsys.readouterr().out
    assert "summaries: off" not in printed and "== check: quality" in printed
