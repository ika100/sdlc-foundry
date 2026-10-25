"""Spec 100 step 3: compact agent briefs and quiet output (AC-100.10 to AC-100.12)."""
import json
import os
import re
import stat

import pytest

import core
import quiet

ROOT = core.PLATFORM_ROOT
PLUGINS = ROOT / "plugins"
HEADINGS = ("Criteria", "Task", "Contract", "Tests", "Commands")
CODERS = [PLUGINS / p / "agents" / "coder.md" for p in ("svc", "svc-go", "svc-java", "web")]
TESTERS = [PLUGINS / p / "agents" / "tester.md" for p in ("svc", "svc-go", "svc-java", "web")]
QUALITY = PLUGINS / "shared" / "agents" / "quality.md"
AGENTS = CODERS + TESTERS + [QUALITY]


def text(path):
    return path.read_text()


def cmd(name):
    return text(PLUGINS / "svc" / "commands" / f"{name}.md")


@pytest.mark.parametrize("name", ["build", "quick-task", "fix-bug"])
def test_ac_100_10_commands_use_the_brief_headings(name):
    """AC-100.10: briefs carry Criteria, Task, Contract, Tests and Commands."""
    t = cmd(name)
    for h in HEADINGS:
        assert f"`{h}`" in t, (name, h)
    assert "brief" in t.lower()


def test_ac_100_10_build_does_not_send_agents_to_the_spec_files():
    """AC-100.10: the coder prompt copies facts instead of pointing at the spec files."""
    t = cmd("build")
    sec = t[t.index("### 2.3 Coder prompt"):t.index("### 2.4")]
    assert "`Criteria`" in sec and "`Contract`" in sec
    assert "SPEC_DIR" not in sec
    assert re.search(r"(?i)copies?|verbatim", sec)


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_ac_100_10_agents_start_from_the_brief(path):
    """AC-100.10: coder, tester and quality read spec/plan/design only for a fact the brief lacks."""
    t = text(path)
    assert "start from the brief" in t.lower()
    assert "only when the brief lacks" in t.lower()


@pytest.mark.parametrize("path", TESTERS, ids=lambda p: p.parent.parent.name)
def test_ac_100_10_tester_acceptance_mode_has_no_unconditional_spec_read(path):
    """AC-100.10: acceptance mode no longer begins by reading spec.md."""
    assert "1. Read `spec.md`" not in text(path)


def test_ac_100_11_reviewer_still_reads_the_full_spec():
    """AC-100.11: the reviewer prompt and agent stay on the full spec."""
    t = cmd("build")
    sec = t[t.index("## Phase 4"):t.index("## Phase 5")]
    assert "`SPEC_DIR`" in sec and "**reviewer**" in sec
    rev = text(PLUGINS / "svc" / "agents" / "reviewer.md")
    assert "spec.md" in rev
    assert "start from the brief" not in rev.lower()


@pytest.mark.parametrize("name", ["build", "quick-task", "fix-bug"])
def test_ac_100_12_commands_use_quiet_gates(name):
    """AC-100.12: test and gate commands in briefs run through `cplat quiet`."""
    t = cmd(name)
    assert "cplat quiet test-fast" in t
    assert "devbox run test-fast" not in t


def test_ac_100_12_build_gates_are_quiet():
    t = cmd("build")
    for s in ("quality", "ci", "lint-fix"):
        assert f"cplat quiet {s}" in t, s


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_ac_100_12_agents_run_quiet_commands(path):
    """AC-100.12: agents use `cplat quiet` and read the log it names on failure."""
    t = text(path)
    assert "cplat quiet" in t
    assert "log" in t.lower()


@pytest.mark.parametrize("shape", ["service-python", "library-python"])
def test_ac_100_12_python_test_fast_is_quiet(shape):
    """AC-100.12: pytest -q --tb=line in the Python templates."""
    cmdline = re.search(r'"test-fast":\s*"([^"]*)"', text(ROOT / "templates" / shape / "devbox.json")).group(1)
    assert "-q" in cmdline.split() and "--tb=line" in cmdline


@pytest.fixture
def repo(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "devbox"
    fake.write_text("#!/bin/sh\ncat \"$FAKE_OUT\"\nexit ${FAKE_RC:-0}\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "myrepo"
    work.mkdir()
    (work / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "x", "quality": "y"}}}))
    monkeypatch.chdir(work)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    out = tmp_path / "out.txt"
    monkeypatch.setenv("FAKE_OUT", str(out))
    return out, tmp_path / "cache"


def test_ac_100_12_quiet_success_prints_one_line_and_the_summary(repo, capsys):
    out, cache = repo
    out.write_text("....\nnoise\n\n5 passed in 0.1s\n\n")
    assert quiet.main(["test-fast"]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("ok: devbox run test-fast (")
    assert "5 passed in 0.1s" in printed and "noise" not in printed
    logs = list((cache / "sdlc-foundry" / "logs" / "myrepo").glob("*-test-fast.log"))
    assert len(logs) == 1 and "noise" in logs[0].read_text()
    assert str(logs[0]) in printed


def test_ac_100_12_quiet_failure_prints_the_tail_and_passes_the_exit_code(repo, capsys, monkeypatch):
    out, cache = repo
    out.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    monkeypatch.setenv("FAKE_RC", "3")
    assert quiet.main(["quality"]) == 3
    printed = capsys.readouterr().out
    assert printed.startswith("FAILED (exit 3): devbox run quality (log: ")
    assert "line 99" in printed and "line 60" in printed and "line 59" not in printed
    assert list((cache / "sdlc-foundry" / "logs" / "myrepo").glob("*-quality.log"))


@pytest.mark.parametrize("argv", [["nope"], ["test-fast", "--extra"], []])
def test_ac_100_12_quiet_refuses_unknown_scripts_and_extra_arguments(repo, capsys, argv):
    assert quiet.main(argv) == 2
    assert not (repo[1] / "sdlc-foundry").exists()


def test_ac_100_12_quiet_is_registered():
    import cplat
    assert cplat.COMMANDS["quiet"] == "quiet"
    assert "cplat.py quiet" in cplat.__doc__
