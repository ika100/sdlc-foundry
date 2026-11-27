"""Spec 205 acceptance tests: the red check of an amended spec judges only the tests of new or changed criteria (AC-205.8).

Seams: `quiet.main(["test-fast", "--red", "--spec", <spec>, "--", ...])` in a small git repo (shape service-python, `test-fast`
runs pytest through a fake `devbox` that runs a real pytest, as in `test_205_red_check.py`) whose spec 007 was built (`done`) and
then amended in a later commit; `cplat.main(["component", "build", "tests", <spec>, "--red"])` on the spec 172 `proj` repo; the
build and tester prompts by structure. Contract: design.md, "Decisions — AC-205.8" and sections 3, 6 and 7.
"""
import collections
import json
import os
import re
import stat
import subprocess
import sys

import pytest

import quiet
from test_205_build_red_check import FILES, ROOT, build_tests, build_text, pytest_repo
from test_205_red_check import FAKE_DEVBOX, PKG, USAGE
from waiting import with_prelude

SPEC_ID = "007-price-alerts"
SPEC_REL = f"docs/specs/{SPEC_ID}/spec.md"
DONE = "- 2026-10-05 done"

SPEC = """---
spec_id: 007-price-alerts
title: Price alerts
status: {status}
priority: P1
shape: service-python
---

# 007 — Price alerts

## Problem

Traders miss moves.

## Acceptance criteria

{criteria}

## Non-goals

- SMS

## Assumptions

- {assumption}

## Open questions

None.

## Changelog

{changelog}
"""

BUILT = """- **AC-007.1** Given a rule, when the price crosses it, then an email is sent.
- **AC-007.2** Given a rule, when a webhook is set, then it is called.
- ~~**AC-007.3**~~ withdrawn: SMS is out of scope.
- **AC-007.5** Given a rule, when it is deleted, then no email is sent."""

# AC-007.1 only re-wrapped (whitespace collapses, so it is unchanged), AC-007.2 changed, AC-007.4 new, AC-007.5 unchanged
AMENDED = """- **AC-007.1** Given a rule, when the price crosses it,
  then an email is sent.
- **AC-007.2** Given a rule, when a webhook is set, then it is called within 5 seconds.
- ~~**AC-007.3**~~ withdrawn: SMS is out of scope.
- **AC-007.4** Given a rule, when it fires twice, then one email is sent.
- **AC-007.5** Given a rule, when it is deleted, then no email is sent."""

LOG_BUILT = f"- 2026-10-01 created\n- 2026-10-02 approved\n- 2026-10-03 building\n{DONE}"
LOG_AMENDED = LOG_BUILT + "\n- 2026-10-10 amended: the webhook has a deadline, one email per rule\n- 2026-10-10 approved"

ALERTS = '''import pytest

import pkg


def test_email_is_sent():  # AC-007.1
    assert True


def test_webhook_is_called():
    """AC-007.2: the webhook is called in time."""
    assert pkg.webhook_called()


def test_one_email_ac_007_4():
    assert 1 == 2


def test_without_its_own_id():
    assert 1 == 2


def test_two_unchanged():  # AC-007.5, AC-007.1
    assert True


class TestEmails:
    """AC-007.1: by class."""

    def test_from_class(self):
        assert True


@pytest.mark.parametrize("n", [1, 2])
def test_parametrized(n):  # AC-007.1
    assert n
'''

FILE_LEVEL = "# AC-007.1\n\n\ndef test_inherits_the_file_id():\n    assert True\n"

NOT_JUDGED_1 = "passes (not judged: AC-007.1 unchanged)"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


class World:
    def __init__(self, root, d):
        self.root, self.d = root, d

    def put(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)

    def spec(self, criteria=BUILT, changelog=LOG_BUILT, status="done", assumption="Email only."):
        self.put(SPEC_REL, SPEC.format(status=status, criteria=criteria, changelog=changelog, assumption=assumption))

    def commit(self, msg):
        git(self.root, "add", "-A")
        git(self.root, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
            "commit", "-q", "--allow-empty", "-m", msg)
        return git(self.root, "rev-parse", "HEAD").strip()

    def calls(self):
        return [p for p in self.d.iterdir() if p.name.startswith("calls-")]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "devbox"
    fake.write_text(with_prelude(FAKE_DEVBOX))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    root = tmp_path / "myrepo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    d = tmp_path / "fake"
    d.mkdir()
    w = World(root, d)
    w.put(".copier-answers.yml", "_src_path: gh:ika100/sdlc-foundry/templates/service-python\nproject_name: myrepo\n")
    w.put("devbox.json", json.dumps({"shell": {"scripts": {"test-fast": "uv run pytest -q \"$@\"", "quality": "y"}}}))
    w.put("pkg/__init__.py", PKG)
    monkeypatch.chdir(root)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("FAKE_DIR", str(d))
    monkeypatch.setenv("FAKE_PY", sys.executable)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    return w


@pytest.fixture()
def amended(world):
    """Spec 007 built (`done` committed), a later commit, then the amendment; returns (world, sha of the done commit)."""
    world.spec()
    world.put("tests/test_alerts.py", ALERTS)
    world.put("tests/test_file_level.py", FILE_LEVEL)
    done = world.commit("spec 007 done")
    world.put("pkg/extra.py", "x = 1\n")
    world.commit("unrelated change")
    world.spec(criteria=AMENDED, changelog=LOG_AMENDED, status="approved", assumption="Email and webhook.")
    world.commit("amend spec 007")
    return world, done


def red(capsys, spec_ref, *files):
    capsys.readouterr()
    rc = quiet.main(["test-fast", "--red", "--spec", spec_ref, "--", *files])
    out = capsys.readouterr()
    rows = collections.defaultdict(lambda: ("no line printed", ""))
    for ln in out.out.splitlines():
        node, sep, rest = ln.partition(": ")
        if sep and "::" in node:
            cls, _, why = rest.partition(" — ")
            rows[node.split("::", 1)[1] if node.startswith("tests/test_alerts.py::") else node] = (cls, why)
    return rc, rows, out.out.splitlines() or ["no output"], out.err


ALL = ("tests/test_alerts.py", "tests/test_file_level.py")


# ---------------- AC-205.8: the scope and the labels ----------------

def test_only_the_tests_of_new_or_changed_criteria_are_judged_ac_205_8(amended, capsys):  # AC-205.8
    world, done = amended
    rc, rows, lines, err = red(capsys, SPEC_ID, *ALL)
    assert lines[0] == (f"red check: judging the tests of AC-007.2, AC-007.4 (new or changed since {done[:7]}); "
                        "every other test must pass")
    assert rows["test_webhook_is_called"][0] == "missing behaviour"              # AC-007.2 changed (docstring id)
    assert rows["test_one_email_ac_007_4"][0] == "missing behaviour"             # AC-007.4 new (name slug)
    assert rows["test_without_its_own_id"][0] == "missing behaviour"             # the file's ids, AC-007.2 among them
    assert rows["test_email_is_sent"] == (NOT_JUDGED_1, "")                     # AC-007.1 only re-wrapped
    assert rows["TestEmails::test_from_class"] == (NOT_JUDGED_1, "")             # by its class
    assert rows["test_parametrized[1]"] == (NOT_JUDGED_1, "") and rows["test_parametrized[2]"] == (NOT_JUDGED_1, "")
    assert rows["test_two_unchanged"] == ("passes (not judged: AC-007.1, AC-007.5 unchanged)", "")
    assert rows["tests/test_file_level.py::test_inherits_the_file_id"] == (NOT_JUDGED_1, "")
    body = lines[1:-1]
    assert [ln.split(": ")[0] for ln in body] == sorted(ln.split(": ")[0] for ln in body)    # sorted by node id
    assert lines[-1].startswith("red check: 3 missing behaviour, 6 passes (not judged) (log: ")
    assert rc == 0, "\n".join(lines) + err


def test_the_spec_number_resolves_too_and_the_record_is_written_ac_205_8(amended, capsys):  # AC-205.8
    world, _ = amended
    rc, rows, lines, _ = red(capsys, "007", *ALL)
    assert rc == 0 and lines[0].startswith("red check: judging the tests of AC-007.2, AC-007.4 ")
    rec = json.loads((world.root / ".git" / "cplat-red-check.json").read_text())
    assert rec["exit"] == 0 and set(rec["files"]) == set(ALL)


@pytest.mark.parametrize("body, line", [
    ("    assert 1 == 2\n", "AssertionError"),                                  # failed assertion
    ("    {}['k']\n", "KeyError"),                                             # an error in test code
    ("    raise NotImplementedError('later')\n", "NotImplementedError"),       # missing behaviour of a built criterion
])
def test_an_unjudged_test_that_fails_is_a_regression_ac_205_8(amended, capsys, body, line):  # AC-205.8
    world, _ = amended
    world.put("tests/test_alerts.py", ALERTS.replace("def test_email_is_sent():  # AC-007.1\n    assert True\n",
                                                     "def test_email_is_sent():  # AC-007.1\n" + body))
    rc, rows, lines, _ = red(capsys, SPEC_ID, *ALL)
    cls, why = rows["test_email_is_sent"]
    assert cls == "regression" and why.startswith(line)
    assert rows["test_webhook_is_called"][0] == "missing behaviour"             # the judged tests are classed as before
    assert rows["TestEmails::test_from_class"] == (NOT_JUDGED_1, "")
    assert "1 regression" in lines[-1]
    assert rc == 1
    assert json.loads((world.root / ".git" / "cplat-red-check.json").read_text())["exit"] == 1     # the freeze gate stays shut


def test_an_unjudged_file_that_does_not_collect_is_a_regression_ac_205_8(amended, capsys):  # AC-205.8
    world, _ = amended
    world.put("tests/test_file_level.py", "# AC-007.1\nvalue = undefined_name\n\n\ndef test_inherits_the_file_id():\n    assert value\n")
    rc, rows, _, _ = red(capsys, SPEC_ID, *ALL)
    cls, why = rows["tests/test_file_level.py::test_inherits_the_file_id"]
    assert cls == "regression" and why.startswith("NameError")
    assert rc == 1


def test_a_judged_test_that_passes_goes_back_as_before_ac_205_8(amended, capsys):  # AC-205.8
    world, _ = amended
    world.put("tests/test_alerts.py", ALERTS.replace("def test_one_email_ac_007_4():\n    assert 1 == 2\n",
                                                     "def test_one_email_ac_007_4():\n    assert True\n"))
    rc, rows, lines, _ = red(capsys, SPEC_ID, *ALL)
    assert rows["test_one_email_ac_007_4"] == ("passes", "")
    assert re.search(r"\b1 passes(?! \(not judged\))", lines[-1])
    assert rc == 1


def test_a_changed_criterion_without_a_judged_test_exits_1_ac_205_8(amended, capsys):  # AC-205.8
    world, _ = amended
    rc, rows, lines, _ = red(capsys, SPEC_ID, "tests/test_file_level.py")
    assert rows["tests/test_file_level.py::test_inherits_the_file_id"] == (NOT_JUDGED_1, "")
    assert rc == 1


def test_an_amendment_that_changes_no_criterion_asks_every_test_to_pass_ac_205_8(world, capsys):  # AC-205.8
    world.spec()
    world.put("tests/test_file_level.py", FILE_LEVEL)
    done = world.commit("spec 007 done")
    world.spec(changelog=LOG_BUILT + "\n- 2026-10-10 amended: an assumption", status="approved", assumption="Email and webhook.")
    world.commit("amend spec 007")
    rc, rows, lines, _ = red(capsys, SPEC_ID, "tests/test_file_level.py")
    assert lines[0] == f"red check: no criterion is new or changed since {done[:7]}; every test must pass"
    assert rows["tests/test_file_level.py::test_inherits_the_file_id"] == (NOT_JUDGED_1, "")
    assert rc == 0


# ---------------- AC-205.8: a first build is checked as in AC-205.6 ----------------

@pytest.mark.parametrize("changelog, status", [
    (LOG_BUILT, "done"),                                                               # built, not amended
    ("- 2026-10-01 created\n- 2026-10-02 approved\n- 2026-10-03 building", "building"),  # never built
    ("- 2026-10-01 created\n- 2026-10-02 amended: x\n- 2026-10-03 building", "building"),  # amended before any build
])
def test_a_spec_built_for_the_first_time_judges_every_test_ac_205_8(world, capsys, changelog, status):  # AC-205.8
    world.spec(criteria=AMENDED, changelog=changelog, status=status)
    world.put("tests/test_alerts.py", ALERTS)
    world.commit("spec 007")
    rc, rows, lines, _ = red(capsys, SPEC_ID, "tests/test_alerts.py")
    assert not lines[0].startswith("red check: ")                                 # no scope line
    assert rows["test_email_is_sent"] == ("passes", "")                           # every test judged (AC-205.6)
    assert not any("not judged" in c or c == "regression" for c, _ in rows.values())
    assert rc == 1


# ---------------- AC-205.8: refused before anything runs ----------------

def test_no_commit_ending_with_the_done_line_is_exit_2_and_nothing_runs_ac_205_8(world, capsys):  # AC-205.8
    world.spec(criteria=AMENDED, changelog=LOG_AMENDED, status="approved")      # done and amended in one commit
    world.put("tests/test_alerts.py", ALERTS)
    world.commit("spec 007, history rewritten")
    rc, rows, lines, err = red(capsys, SPEC_ID, "tests/test_alerts.py")
    assert rc == 2 and rows == {}
    msg = err.strip()
    assert msg.startswith(f"red check: no commit of {SPEC_REL} ends its Changelog with ")
    assert "2026-10-05 done" in msg and msg.endswith("fetch the full history (git fetch --unshallow)")
    assert world.calls() == []


def test_an_unknown_spec_is_exit_2_and_nothing_runs_ac_205_8(amended, capsys):  # AC-205.8
    world, _ = amended
    rc, rows, _, err = red(capsys, "999", "tests/test_alerts.py")
    assert rc == 2 and rows == {} and err.startswith("red check: ") and "999" in err
    assert world.calls() == []


@pytest.mark.parametrize("argv", [
    ["test-fast", "--spec", SPEC_ID, "--", "tests/test_alerts.py"],               # without --red
    ["test-fast", "--red", "--spec", "--", "tests/test_alerts.py"],               # without a value
    ["test-fast", "--red", "--spec", SPEC_ID],                                     # without --
    ["test-fast", "--red", "--spec", SPEC_ID, "--"],                               # without a test
    ["test-fast", "--spec", SPEC_ID, "--red", "--", "tests/test_alerts.py"],      # before --red
    ["test-fast", "--repeat", "2", "--spec", SPEC_ID, "--", "tests/test_alerts.py"],
])
def test_other_forms_of_the_spec_flag_get_the_usage_line_ac_205_8(amended, capsys, argv):  # AC-205.8
    world, _ = amended
    capsys.readouterr()
    assert quiet.main(argv) == 2
    assert capsys.readouterr().err.strip() == USAGE
    assert world.calls() == []


# ---------------- AC-205.8: `build tests --red` adds --spec for an amended spec only ----------------

def amend_changelog(root, extra):
    p = root / "docs" / "specs" / SPEC_ID / "spec.md"
    p.write_text(p.read_text().rstrip("\n") + "\n" + extra + "\n")


def test_build_tests_adds_the_spec_for_an_amended_spec_ac_205_8(tmp_path, capsys):  # AC-205.8
    root = pytest_repo(tmp_path)
    amend_changelog(root, "- 2026-10-02 done\n- 2026-10-03 amended: x\n- 2026-10-03 approved")
    rc, out, err = build_tests(capsys, root, "--red")
    assert rc == 0, err
    assert out == " ".join(["cplat", "quiet", "test-fast", "--red", "--spec", SPEC_ID, "--", *FILES]) + "\n"
    rc, out, err = build_tests(capsys, root, "--red", "--json")
    doc = json.loads(out)
    assert doc.get("amended") is True and doc["args"] == FILES and doc["files"] == FILES
    assert doc["command"] == " ".join(["cplat", "quiet", "test-fast", "--red", "--spec", SPEC_ID, "--", *FILES])


@pytest.mark.parametrize("extra", ["", "- 2026-10-02 done", "- 2026-10-02 amended: x\n- 2026-10-03 done"])
def test_build_tests_keeps_the_line_for_a_first_build_ac_205_8(tmp_path, capsys, extra):  # AC-205.8
    root = pytest_repo(tmp_path)
    if extra:
        amend_changelog(root, extra)
    rc, out, err = build_tests(capsys, root, "--red", "--json")
    assert rc == 0, err
    doc = json.loads(out)
    assert doc.get("amended") is False
    assert doc["command"] == " ".join(["cplat", "quiet", "test-fast", "--red", "--", *FILES])


# ---------------- AC-205.8: the build and tester prompts, by structure ----------------

def _paragraph(text, needle):
    """The bullet or numbered step of a prompt that contains `needle`."""
    for block in text.split("\n"):
        if needle in block:
            return block
    return ""


def test_phase_1_escalates_a_regression_with_cause_code_ac_205_8():  # AC-205.8
    bullet = _paragraph(build_text(), "cplat component build tests <id> --red")  # interface: the red-check command line
    assert "`regression`" in bullet                                   # the label the red check prints
    assert "--cause code" in bullet.split("`regression`", 1)[1]       # the escalation flag the build runs
    assert "--wrong-failure" in build_text()


def test_the_tester_leaves_unjudged_passes_alone_ac_205_8():  # AC-205.8
    text = (ROOT / "plugins" / "svc" / "agents" / "tester.md").read_text()
    step = _paragraph(text, "--red")
    assert "not judged" in step and "`regression`" in step     # the labels the red check prints



def test_node_ids_relative_to_a_nested_pytest_ini_are_traced_too_ac_205_8(amended, capsys):  # AC-205.8
    world, _ = amended                                  # tests/cplat/pytest.ini in the platform repo: node ids lose `tests/`
    world.put("tests/pytest.ini", "[pytest]\n")
    capsys.readouterr()
    rc = quiet.main(["test-fast", "--red", "--spec", SPEC_ID, "--", *ALL])
    out = capsys.readouterr().out.splitlines()
    assert "test_alerts.py::test_email_is_sent: " + NOT_JUDGED_1 in out
    assert "test_alerts.py::test_one_email_ac_007_4: missing behaviour — AssertionError: assert 1 == 2" in out
    assert rc == 0
