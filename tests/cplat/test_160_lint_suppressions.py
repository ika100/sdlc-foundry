"""Spec 160 acceptance tests: a line-level lint suppression that names its rule is not a changed acceptance test.

Seams: `spec.suppression_only` / `spec.formatting_only` on file contents, and `spec.test_diff` on a real git repo with one
`building` spec and its acceptance test (`test_spec.make`).
"""
import subprocess
from pathlib import Path

import pytest

import spec

ROOT = Path(__file__).resolve().parents[2]

GO = """package server

// AC-007.1
func TestReport(t *testing.T) {
	resp := getReport(t, srv)
	if resp.StatusCode != 200 {
		t.Fatal(resp.StatusCode)
	}
}
"""

TS = """// AC-007.1
test("lists files", async () => {
  const res: any = await load();
  expect(res.files).toHaveLength(3);
});
"""

JAVA = """class ReportTest {
    // AC-007.1
    @Test
    void lists() {
        List raw = load();
        assertEquals(3, raw.size());
    }
}
"""


def ok(old, new, name):
    return spec.suppression_only(old, new, name)


# ---------------- AC-160.1: accepted, for every language ----------------

@pytest.mark.parametrize("name,old,new", [
    ("report_test.go", GO, GO.replace("resp := getReport(t, srv)", "resp := getReport(t, srv) //nolint:bodyclose // closed by getReport")),
    ("report_test.go", GO, GO.replace("resp := getReport(t, srv)", "resp := getReport(t, srv) //nolint:bodyclose,errcheck")),
    ("page.test.ts", TS, TS.replace("  const res", "  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double\n  const res")),
    ("ReportTest.java", JAVA, JAVA.replace("    @Test\n", "    @Test\n    @SuppressWarnings(\"rawtypes\")\n")),
    ("ReportTest.java", JAVA, JAVA.replace("    @Test\n", "    @Test\n    @SuppressWarnings({\"rawtypes\", \"unchecked\"})\n")),
])
def test_a_rule_named_line_suppression_is_accepted_ac_160_1(name, old, new):  # AC-160.1
    good, why = ok(old, new, name)
    assert good and why.startswith("lint suppression only: line ")


def test_python_suppressions_are_named_too_ac_160_1():  # AC-160.1
    old = "# AC-007.1\ndef test_x():\n    password = 'x'\n    assert check(password)\n"
    new = old.replace("password = 'x'", "password = 'x'  # noqa: S105").replace("check(password)", "check(password)  # type: ignore[arg-type]")
    good, why = ok(old, new, "test_x.py")
    assert good and "line 3 `# noqa: S105`" in why and "line 4 `# type: ignore[arg-type]`" in why


def test_an_existing_suppression_kept_and_one_added_is_accepted_ac_160_1():  # AC-160.1
    old = GO.replace("t.Fatal(resp.StatusCode)", "t.Fatal(resp.StatusCode) //nolint:errcheck")
    new = old.replace("resp := getReport(t, srv)", "resp := getReport(t, srv) //nolint:bodyclose")
    good, why = ok(old, new, "report_test.go")
    assert good and "bodyclose" in why and "errcheck" not in why


# ---------------- AC-160.2: refused ----------------

@pytest.mark.parametrize("name,old,new,reason", [
    ("report_test.go", GO, GO.replace("resp := getReport(t, srv)", "resp := getReport(t, srv) //nolint:bodyclose").replace("!= 200", "!= 201"), ""),
    ("report_test.go", GO, GO.replace("resp := getReport(t, srv)", "resp := getReport(t, srv) //nolint"), "names no rule"),
    ("report_test.go", GO, GO.replace("package server", "package server //nolint"), "file-wide"),
    ("test_x.py", "# AC-007.1\ndef test_x():\n    assert f()\n", "# ruff: noqa\n# AC-007.1\ndef test_x():\n    assert f()\n", "file-wide"),
    ("test_x.py", "# AC-007.1\ndef test_x():\n    assert f()\n", "# AC-007.1\ndef test_x():\n    assert f()  # noqa\n", "names no rule"),
    ("test_x.py", "# AC-007.1\ndef test_x():\n    assert f()\n", "# AC-007.1\ndef test_x():\n    assert f()  # type: ignore\n", "names no rule"),
    ("page.test.ts", TS, "/* eslint-disable */\n" + TS, "file-wide"),
    ("page.test.ts", TS, TS.replace("  const res", "  // eslint-disable-next-line\n  const res"), "names no rule"),
    ("ReportTest.java", JAVA, JAVA.replace("class ReportTest", "@SuppressWarnings(\"all\")\nclass ReportTest"), ""),
])
def test_a_code_change_a_rule_less_or_file_wide_suppression_is_refused_ac_160_2(name, old, new, reason):  # AC-160.2
    good, why = ok(old, new, name)
    assert not good and reason in why


def test_a_removed_suppression_is_not_suppression_only_ac_160_2():  # AC-160.2
    old = GO.replace("resp := getReport(t, srv)", "resp := getReport(t, srv) //nolint:bodyclose")
    assert ok(old, GO, "report_test.go") == (False, "")


def g(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def built(tmp_path):
    from test_spec import make
    root = tmp_path / "r"
    root.mkdir()
    g("init", "-q", "-b", "main", cwd=root)
    make(root, status="building")
    t = root / "tests" / "test_alerts.py"
    t.parent.mkdir()
    t.write_text("# AC-007.1\ndef test_alert():\n    password = 'x'\n    assert send(password)\n")
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "test: acceptance tests for 007", cwd=root)
    return root, t


def test_test_diff_names_the_suppression_and_refuses_a_rule_less_one_ac_160_1_ac_160_2(built):  # AC-160.1, AC-160.2
    root, t = built
    t.write_text(t.read_text().replace("password = 'x'", "password = 'x'  # noqa: S105"))
    out = spec.test_diff(root, "HEAD", [])
    assert out == {"tests/test_alerts.py": (True, "lint suppression only: line 3 `# noqa: S105`")}
    t.write_text(t.read_text().replace("# noqa: S105", "# noqa"))
    good, why = spec.test_diff(root, "HEAD", [])["tests/test_alerts.py"]
    assert not good and "names no rule" in why


def test_a_comment_that_is_no_suppression_stays_formatting_in_python_ac_160_1(built):  # AC-160.1
    root, t = built
    t.write_text(t.read_text().replace("password = 'x'", "password = 'x'  # a plain comment"))
    assert spec.test_diff(root, "HEAD", [])["tests/test_alerts.py"] == (True, "")


# ---------------- AC-160.3 / AC-160.4: coder and reviewer ----------------

def test_every_coder_may_suppress_a_false_positive_by_rule_ac_160_3():  # AC-160.3
    for plugin in ("svc", "web", "svc-go", "svc-java"):
        text = (ROOT / "plugins" / plugin / "agents" / "coder.md").read_text()
        assert "suppressed on its own line with the linter's comment naming the rule" in text and "spec 160" in text, plugin
    build = (ROOT / "plugins" / "component" / "commands" / "build.md").read_text()
    assert "line suppression naming the rule, nothing else (spec 160); name the suppressed rules in the commit" in build


def test_the_reviewer_lists_each_suppression_in_verification_ac_160_4():  # AC-160.4
    build = (ROOT / "plugins" / "component" / "commands" / "build.md").read_text()
    assert "`SUPPRESSIONS`: the `lint suppression only` lines of the last test diff (Phase 3, step 4)" in build
    reviewer = (ROOT / "plugins" / "svc" / "agents" / "reviewer.md").read_text()
    assert "## Suppressions in acceptance tests" in reviewer
    fmt = (ROOT / "plugins" / "svc" / "skills" / "spec-format" / "references" / "verification.md").read_text()
    assert "## Suppressions in acceptance tests" in fmt and "| File | Line | Rule | False positive |" in fmt
