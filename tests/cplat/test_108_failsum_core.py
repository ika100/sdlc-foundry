"""Spec 108 acceptance tests: AC-108.5 (several checks, limits), AC-108.6 (deterministic, no model), AC-108.7 (redaction, agent
instructions), AC-108.10 (the setting, the summaries-off rendering). Contract: design.md (limits, byte-exact render, API)."""
import re

import pytest

import core
from failsum_support import LOG, TITLE, excerpt_runs, headers, marker, render, sample, summarize

TOKEN = "ghp_" + "a1B2c3D4e5F6" * 3
ROOT = core.PLATFORM_ROOT


def concise(prefix: str, n: int, code: str = "F401") -> str:
    return "".join(f"src/{prefix}{i}.py:1:8: {code} [*] `os{i}` imported but unused\n" for i in range(n)) + f"Found {n} errors.\n"


def framed(prefix: str, n: int) -> str:
    out = ""
    for i in range(n):
        out += (f"F401 [*] `m{i}` imported but unused\n --> src/{prefix}{i}.py:3:8\n  |\n3 | import m{i}\n  |        ^^\n  |\n"
                f"help: Remove unused import: `m{i}`\n\n")
    return out + f"Found {n} errors.\n"


# ---------------- AC-108.5 ----------------

def test_every_failing_check_of_a_multi_check_run_has_its_own_header_ac_108_5():  # AC-108.5
    log = (marker("ci") + marker("lint") + sample("ruff-concise.log") + marker("typecheck") + "Success: no issues found in 8 source files\n"
           + marker("test") + sample("pytest-tbline.log"))
    out = render(log, "ci", root="/work/todo-api")
    names = [re.match(r"== check: (\S+) \|", h).group(1) for h in headers(out)]
    assert names == ["lint", "test"], "log order; the passing typecheck and the empty ci segment have no header"
    assert "format: ruff" in headers(out)[0] and "command: devbox run lint" in headers(out)[0]
    assert "format: pytest" in headers(out)[1] and "command: devbox run test" in headers(out)[1]
    assert out.splitlines()[0] == TITLE.format(script="ci", log=LOG)


def test_the_last_check_always_appears_even_when_no_parser_reads_it_ac_108_5():  # AC-108.5
    log = marker("ci") + marker("lint") + sample("ruff-concise.log") + marker("security") + "scan crashed: out of memory\n"
    out = render(log, "ci")
    assert [re.match(r"== check: (\S+) \|", h).group(1) for h in headers(out)] == ["lint", "security"]
    assert "format: unknown" in headers(out)[1] and "scan crashed: out of memory" in out


def test_more_than_20_entries_show_20_then_the_exact_rest_and_the_log_path_ac_108_5():  # AC-108.5
    out = render(marker("lint") + concise("m", 25), "lint")
    entries = [ln for ln in out.splitlines() if ln.startswith("- src/")]
    assert len(entries) == 20
    assert f"- ... 5 more entries not shown (log: {LOG})" in out.splitlines()
    assert "entries: 25" in headers(out)[0]


def test_exactly_20_entries_are_all_shown_ac_108_5():  # AC-108.5
    out = render(marker("lint") + concise("m", 20), "lint")
    assert len([ln for ln in out.splitlines() if ln.startswith("- src/")]) == 20 and "more entries" not in out


def test_a_summary_over_80_lines_shortens_excerpts_first_ac_108_5():  # AC-108.5
    log = "".join(marker(f"lint{c}") + framed(f"{c}_", 20) for c in "abc")
    out = render(log, "ci")
    lines = out.splitlines()
    assert len(lines) <= 80
    assert len(headers(out)) == 3 and all("entries: 20" in h for h in headers(out))
    assert len([ln for ln in lines if ln.startswith("- src/")]) == 60, "excerpts go first: all 60 entries survive"
    assert sum(excerpt_runs(out)) < 60 * 3, "the code frames were shortened"


def test_over_80_lines_with_no_excerpts_cuts_entries_but_never_a_check_or_its_count_ac_108_5():  # AC-108.5
    log = "".join(marker(f"lint{c}") + concise(f"{c}_", 20) for c in "abcde")
    out = render(log, "ci")
    lines = out.splitlines()
    assert len(lines) <= 80
    assert len(headers(out)) == 5
    seen = 0
    for i, h in enumerate(headers(out)):
        assert "entries: 20" in h
        start = lines.index(h)
        end = lines.index(headers(out)[i + 1]) if i + 1 < 5 else len(lines)
        block = lines[start + 1:end]
        shown = len([ln for ln in block if ln.startswith("- src/")])
        more = [int(m.group(1)) for ln in block if (m := re.match(r"- \.\.\. (\d+) more entries not shown \(log: ", ln))]
        assert more and shown + more[0] == 20 and shown >= 1
        seen += 1
    assert seen == 5 and out.splitlines()[0] == TITLE.format(script="ci", log=LOG)


# ---------------- AC-108.6 ----------------

def test_the_same_log_twice_gives_byte_identical_summaries_ac_108_6():  # AC-108.6
    text = marker("lint") + sample("ruff-concise.log") + marker("test") + sample("pytest-long.log") + marker("x") + "mystery\n"
    a, b = summarize(text, "ci"), summarize(text, "ci")
    assert a.render().encode() == b.render().encode() and a.normalized() == b.normalized()
    assert a.render().encode() == summarize(text, "ci").render().encode()


def test_the_summary_is_made_without_a_model_call_ac_108_6():  # AC-108.6
    sources = sorted((ROOT / "scripts" / "cplat" / "failsum").glob("*.py"))
    assert {p.name for p in sources} >= {"__init__.py", "core.py", "python.py"}
    text = "\n".join(p.read_text() for p in sources)
    for banned in ("anthropic", "import headless", "subprocess", "claude -p", "import requests", "urllib.request"):
        assert banned not in text, banned


# ---------------- AC-108.7 ----------------

def test_secrets_in_the_summary_are_redacted_but_the_log_path_is_not_ac_108_7():  # AC-108.7
    log = (f"/work/todo-api/src/todo_api/auth.py:9: RuntimeError: GH_TOKEN={TOKEN} rejected by /Users/eike/secret-dir/x\n"
           "FAILED tests/test_auth.py::test_login - RuntimeError: boom\n1 failed in 0.1s\n")
    out = render(log, "test-fast", root="/work/todo-api")
    assert TOKEN not in out and "<redacted>" in out
    path = str(LOG)
    assert path in out.splitlines()[0] and path in headers(out)[0]
    for ln in out.splitlines():
        assert "/Users/eike" not in ln.replace(path, ""), ln
    unknown = render(f"GH_TOKEN={TOKEN}\nplain failure\n", "security")
    assert TOKEN not in unknown and "plain failure" in unknown


AGENT_FILES = [
    "plugins/svc/agents/coder.md", "plugins/svc/agents/tester.md", "plugins/svc-go/agents/coder.md", "plugins/svc-go/agents/tester.md",
    "plugins/svc-java/agents/coder.md", "plugins/svc-java/agents/tester.md", "plugins/web/agents/coder.md", "plugins/web/agents/tester.md",
    "plugins/shared/agents/quality.md",
]
BRIEF_FILES = ["plugins/component/commands/build.md", "plugins/component/commands/fix.md",
               "plugins/component/references/ship-land-red.md"]


@pytest.mark.parametrize("path", AGENT_FILES)
def test_agent_instructions_say_to_open_the_log_only_when_the_summary_is_not_enough_ac_108_7(path):  # AC-108.7
    t = " ".join((ROOT / path).read_text().lower().split())
    assert "cplat quiet" in t and "log" in t
    assert "summary" in t and "not enough" in t
    assert "read that log, do not rerun" not in t


@pytest.mark.parametrize("path", BRIEF_FILES)
def test_the_briefs_hand_over_the_summary_and_the_log_path_ac_108_7(path):  # AC-108.7
    t = " ".join((ROOT / path).read_text().lower().split())
    assert "summary" in t and "not enough" in t and "log" in t


# ---------------- AC-108.10 ----------------

def test_summaries_are_on_without_a_setting_ac_108_10(tmp_path):  # AC-108.10
    import failsum
    import settings
    assert settings.failure_summary(tmp_path) == (True, "")
    assert failsum.enabled(tmp_path) == (True, "")
    (tmp_path / ".platform-settings.yml").write_text("shape: platform\n")
    assert settings.failure_summary(tmp_path) == (True, "")


@pytest.mark.parametrize("value", ["off", "false"])
def test_the_project_setting_turns_summaries_off_ac_108_10(tmp_path, value):  # AC-108.10
    import failsum
    import settings
    (tmp_path / ".platform-settings.yml").write_text(f"failure_summary: {value}\n")
    want = (False, ".platform-settings.yml failure_summary: off")
    assert settings.failure_summary(tmp_path) == want and failsum.enabled(tmp_path) == want


@pytest.mark.parametrize("value", ["on", "true"])
def test_the_project_setting_on_keeps_summaries_on_ac_108_10(tmp_path, value):  # AC-108.10
    import settings
    (tmp_path / ".platform-settings.yml").write_text(f"failure_summary: {value}\n")
    assert settings.failure_summary(tmp_path) == (True, "")


def test_an_invalid_setting_is_an_error_naming_the_value_ac_108_10(tmp_path):  # AC-108.10
    import settings
    (tmp_path / ".platform-settings.yml").write_text("failure_summary: maybe\n")
    with pytest.raises(core.PlatformError, match="failure_summary must be on or off, got 'maybe'"):
        settings.failure_summary(tmp_path)


def test_the_personal_settings_file_is_not_read_for_this_key_ac_108_10(tmp_path, monkeypatch):  # AC-108.10
    import settings
    home = tmp_path / "home"
    (home / ".config" / "sdlc-foundry").mkdir(parents=True)
    for f in (home / ".config" / "sdlc-foundry" / "settings.yml", home / ".platform-settings.yml"):
        f.write_text("failure_summary: off\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    repo = tmp_path / "repo"
    repo.mkdir()
    assert settings.failure_summary(repo) == (True, "")


def test_summaries_off_prints_the_title_the_reason_and_the_last_40_lines_ac_108_10():  # AC-108.10
    import failsum
    rows = [f"row {i}" for i in range(100)]
    for reason in ("--raw", ".platform-settings.yml failure_summary: off"):
        out = failsum.raw("FAILED (exit 1): devbox run test (log: /tmp/x.log)", "\n".join(rows) + "\n", reason).splitlines()
        assert out[0] == "FAILED (exit 1): devbox run test (log: /tmp/x.log)"
        assert out[1] == f"summaries: off ({reason})"
        assert out[2:] == rows[-40:]
