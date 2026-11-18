"""Spec 205 acceptance tests: an edit to a frozen acceptance test that changes no assertion is not a changed test (AC-205.1 to AC-205.4).

Seams: `testdiff_neutral.judge(old, new, name)` on file contents; `spec.test_diff` and `spec.main` (`cplat spec test-diff`) on the
spec 160 `built` repo (one `building` spec and its acceptance test). Contract: design.md section 1. The module
`testdiff_neutral` does not exist yet, so it is imported inside the tests.
"""
import importlib

import pytest

import spec
from test_160_lint_suppressions import built, g  # noqa: F401  (fixture, helper)

FILE = "tests/test_alerts.py"
PASS = "no assertion changed: "


def judge(old, new, name):
    return importlib.import_module("testdiff_neutral").judge(old, new, name)


PY = """# AC-007.1
def test_alert():
    password = 'x'
    assert send(password)
"""

PY_DOC = '''"""Alerts."""
# AC-007.1


class TestAlerts:
    """A group."""

    def test_alert(self):
        """Sends one mail."""
        assert send("x")
'''

TS = """// AC-007.1
import { render } from './render';

test("lists files", async () => {
  const res = await load("http://a");
  expect(res.files).toHaveLength(3);
});
"""

GO = """package server

import "testing"

// AC-007.1
func TestReport(t *testing.T) {
	resp := getReport(t, "http://a")
	if resp.StatusCode != 200 {
		t.Fatal(resp.StatusCode)
	}
}
"""

JAVA = """import org.junit.jupiter.api.Test;

class ReportTest {
    // AC-007.1
    @Test
    void lists() {
        var raw = load("http://a");
        assertEquals(3, raw.size());
    }
}
"""


# ---------------- AC-205.1: comments, every language ----------------

@pytest.mark.parametrize("name,old,new", [
    ("test_alerts.py", PY, PY.replace("    password = 'x'\n", "    # a user\n    password = 'x'\n")),
    ("test_alerts.py", PY + "    # trailing\n", PY),
    ("test_alerts.py", PY.replace("def test_alert", "# one\ndef test_alert"), PY.replace("def test_alert", "# two, changed\ndef test_alert")),
    ("page.test.ts", TS, TS.replace('  expect', '  // the count\n  expect')),
    ("page.test.ts", TS, TS.replace('test("lists', '/* block\n   comment */\ntest("lists')),
    ("page.test.tsx", TS, TS.replace("// AC-007.1", "// AC-007.1 the list")),
    ("page.test.js", TS, TS.replace("expect(res.files)", "expect(res.files) // check")),
    ("report_test.go", GO, GO.replace("\tresp :=", "\t// fetch\n\tresp :=")),
    ("report_test.go", GO, GO.replace("// AC-007.1", "/* AC-007.1\n   note */")),
    ("ReportTest.java", JAVA, JAVA.replace("        var raw", "        // load it\n        var raw")),
    ("ReportTest.java", JAVA, JAVA.replace("class ReportTest", "/** The report. */\nclass ReportTest")),
])
def test_a_comment_only_edit_passes_in_every_language_ac_205_1(name, old, new):  # AC-205.1
    assert judge(old, new, name) == PASS + "comments"


@pytest.mark.parametrize("name,old,new", [
    ("test_alerts.py", "# AC-007.1\ndef test_a():\n    assert load('http://a')\n", "# AC-007.1\ndef test_a():\n    assert load('http://b')\n"),
    ("test_alerts.py", "# AC-007.1\ndef test_a():\n    assert load('a#b')\n", "# AC-007.1\ndef test_a():\n    assert load('a#c')\n"),
    ("page.test.ts", TS, TS.replace("http://a", "http://b")),
    ("page.test.ts", "// AC-007.1\nit('x', () => { expect(`//a`).toBe(1); });\n", "// AC-007.1\nit('x', () => { expect(`//b`).toBe(1); });\n"),
    ("page.test.ts", "// AC-007.1\nit('x', () => { expect(s.match(/\\/\\/a/)).toBe(1); });\n",
     "// AC-007.1\nit('x', () => { expect(s.match(/\\/\\/b/)).toBe(1); });\n"),
    ("report_test.go", GO, GO.replace("http://a", "http://b")),
    ("report_test.go", GO.replace('"http://a"', "`http://a`"), GO.replace('"http://a"', "`http://b`")),
    ("ReportTest.java", JAVA, JAVA.replace("http://a", "http://b")),
    ("ReportTest.java", JAVA.replace('"http://a"', '"""\n  http://a"""'), JAVA.replace('"http://a"', '"""\n  http://b"""')),
])
def test_a_comment_marker_inside_a_string_is_no_comment_ac_205_1(name, old, new):  # AC-205.1
    assert judge(old, new, name) is None


def test_the_check_prints_the_line_and_exits_0_without_a_record_ac_205_1(built, capsys):  # AC-205.1
    root, t = built
    t.write_text(t.read_text().replace("    password", "    # the secret\n    password").replace("# AC-007.1", "# AC-007.1 (alerts)"))
    assert spec.test_diff(root, "HEAD", [FILE])[FILE] == (True, PASS + "comments")
    capsys.readouterr()
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", FILE]) == 0
    assert capsys.readouterr().out.splitlines() == [f"{FILE}: {PASS}comments"]
    assert spec._approvals(root, "HEAD") == {}                         # no --tighten, no --approve


def test_a_changed_string_in_a_commented_file_is_still_refused_by_the_check_ac_205_1(built, capsys):  # AC-205.1
    root, t = built
    t.write_text("# AC-007.1\ndef test_alert():\n    # now\n    password = 'y'\n    assert send(password)\n")
    good, why = spec.test_diff(root, "HEAD", [FILE])[FILE]
    assert not good and not why.startswith(PASS)
    importlib.import_module("testdiff_neutral")
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", FILE]) == 1


# ---------------- AC-205.2: Python docstrings and imports ----------------

def test_a_changed_added_or_removed_docstring_passes_ac_205_2():  # AC-205.2
    assert judge(PY_DOC, PY_DOC.replace("Sends one mail.", "Sends two mails."), "test_alerts.py") == PASS + "docstrings"
    assert judge(PY_DOC, PY_DOC.replace('        """Sends one mail."""\n', ""), "test_alerts.py") == PASS + "docstrings"
    assert judge(PY_DOC, PY_DOC.replace('    """A group."""\n\n', ""), "test_alerts.py") == PASS + "docstrings"
    assert judge(PY_DOC, PY_DOC.replace('"""Alerts."""\n', ""), "test_alerts.py") == PASS + "docstrings"
    assert judge(PY, PY.replace("    password", '    """Now documented."""\n    password'), "test_alerts.py") == PASS + "docstrings"


def test_added_removed_and_local_imports_pass_ac_205_2():  # AC-205.2
    assert judge(PY, "import json\n" + PY, "test_alerts.py") == PASS + "imports"
    assert judge("from app import x\n" + PY, PY, "test_alerts.py") == PASS + "imports"
    assert judge(PY, PY.replace("    password", "    from app import mail\n    password"), "test_alerts.py") == PASS + "imports"
    assert judge("import a\nimport b\n" + PY, "import b\nimport c\n" + PY, "test_alerts.py") == PASS + "imports"


def test_a_pure_reorder_of_imports_is_no_difference_ac_205_2():  # AC-205.2
    assert judge("import a\nimport b\n" + PY, "import b\nimport a\n" + PY, "test_alerts.py") is None    # formatting_only's line, as before


def test_the_kinds_found_are_named_in_a_fixed_order_ac_205_2():  # AC-205.2
    with_import = PY_DOC.replace('"""Alerts."""\n', '"""Alerts."""\nimport json\n')
    new = with_import.replace("Sends one mail.", "Sends none.").replace("# AC-007.1", "# AC-007.1 (alerts)")
    assert judge(PY_DOC, new, "test_alerts.py") == PASS + "comments, docstrings, imports"
    assert judge(PY_DOC, with_import, "test_alerts.py") == PASS + "imports"
    assert judge(PY_DOC, PY_DOC.replace("Sends one mail.", "x").replace("# AC-007.1", "# AC-007.1 y"), "test_alerts.py") == PASS + "comments, docstrings"


@pytest.mark.parametrize("old,new", [
    ("# AC-007.1\ndef test_a():\n    x = 'a'\n    assert f(x)\n", "# AC-007.1\ndef test_a():\n    x = 'b'\n    assert f(x)\n"),
    ("# AC-007.1\ndef test_a():\n    f()\n    'note'\n    assert g()\n", "# AC-007.1\ndef test_a():\n    f()\n    'other'\n    assert g()\n"),
    ("# AC-007.1\ndef test_a():\n    assert importlib.import_module('a')\n", "# AC-007.1\ndef test_a():\n    assert importlib.import_module('b')\n"),
    ("# AC-007.1\ndef test_a():\n    assert __import__('a')\n", "# AC-007.1\ndef test_a():\n    assert __import__('b')\n"),
    ("# AC-007.1\ndef test_a():\n    assert f(1)\n", "# AC-007.1\ndef test_a():\n    assert f(2)\n"),
    ("# AC-007.1\ndef test_a():\n    assert f(1)\n", "# AC-007.1\n@pytest.mark.skip\ndef test_a():\n    assert f(1)\n"),
])
def test_other_changed_strings_calls_and_statements_are_refused_ac_205_2(old, new):  # AC-205.2
    assert judge(old, "import json\n" + new, "test_alerts.py") is None


# ---------------- AC-205.3: TypeScript/JavaScript, Go, Java ----------------

@pytest.mark.parametrize("name,old,new,kinds", [
    ("page.test.ts", TS, TS.replace("import { render } from './render';\n", "import { render, screen } from './render';\n"), "imports"),
    ("page.test.ts", TS, TS.replace("import { render }", "import type { Page } from './page';\nimport { render }"), "imports"),
    ("page.test.ts", TS, TS.replace("import { render } from './render';\n", "import { render } from './render';\nimport './setup';\n"), "imports"),
    ("page.test.ts", TS, TS.replace("import { render } from './render';", "import {\n  render,\n  screen,\n} from './render'"), "imports"),
    ("page.test.js", TS, TS.replace("import { render } from './render';\n", ""), "imports"),
    ("page.test.ts", TS, TS.replace("import { render } from './render';", "import { render } from './render'; // used below"), "comments"),
    ("page.test.ts", TS, TS.replace("import { render } from './render';", "import { render } from './other'; // moved"), "comments, imports"),
    ("report_test.go", GO, GO.replace('import "testing"', 'import (\n\t"fmt"\n\t"testing"\n)'), "imports"),
    ("report_test.go", GO, GO.replace('import "testing"', 'import (\n\t"testing"\n\tx "net/http"\n)'), "imports"),
    ("report_test.go", GO, GO.replace('import "testing"', '// the tests\nimport "net/http"'), "comments, imports"),
    ("report_test.go", GO, GO.replace('import "testing"\n\n', ""), "imports"),
    ("ReportTest.java", JAVA, JAVA.replace("import org.junit", "import java.util.List;\nimport org.junit"), "imports"),
    ("ReportTest.java", JAVA, JAVA.replace("import org.junit.jupiter.api.Test;", "import static org.junit.jupiter.api.Assertions.*;\nimport org.junit.jupiter.api.Test;"), "imports"),
    ("ReportTest.java", JAVA, JAVA.replace("import org.junit.jupiter.api.Test;\n\n", "\n// no imports\n"), "comments, imports"),
])
def test_static_imports_and_comments_pass_ac_205_3(name, old, new, kinds):  # AC-205.3
    assert judge(old, new, name) == PASS + kinds


@pytest.mark.parametrize("name,old,new", [
    ("page.test.ts", "// AC-007.1\ntest('x', async () => { const m = await import('./a'); expect(m).toBe(1); });\n",
     "// AC-007.1\ntest('x', async () => { const m = await import('./b'); expect(m).toBe(1); });\n"),
    ("page.test.js", "// AC-007.1\nconst m = require('./a');\ntest('x', () => { expect(m).toBe(1); });\n",
     "// AC-007.1\nconst m = require('./b');\ntest('x', () => { expect(m).toBe(1); });\n"),
    ("page.test.ts", "// AC-007.1\nimport m = require('./a');\ntest('x', () => { expect(m).toBe(1); });\n",
     "// AC-007.1\nimport m = require('./b');\ntest('x', () => { expect(m).toBe(1); });\n"),
    ("page.test.ts", TS, TS.replace("toHaveLength(3)", "toHaveLength(4)").replace("// AC-007.1", "// AC-007.1 x")),
    ("report_test.go", GO, GO.replace("!= 200", "!= 201").replace('import "testing"', 'import "fmt"\nimport "testing"')),
    ("ReportTest.java", JAVA, JAVA.replace("3, raw", "4, raw").replace("import org", "import java.util.List;\nimport org")),
    ("notes.rb", "# AC-007.1\nx = 1\n", "# AC-007.1\n# y\nx = 1\n"),
])
def test_dynamic_imports_requires_and_other_changes_are_refused_ac_205_3(name, old, new):  # AC-205.3
    assert judge("# AC-007.1\nx = 1\n", "# AC-007.1\n# y\nx = 1\n", "test_alerts.py") == PASS + "comments"   # the module exists and works
    assert judge(old, new, name) is None


# ---------------- AC-205.4: anything else, and criterion ids, keep today's result ----------------

def test_a_mixed_change_keeps_the_reason_of_before_ac_205_4(built, capsys):  # AC-205.4
    root, t = built
    old = t.read_text()
    new = old.replace("    password", "    # the secret\n    password").replace("assert send(password)", "assert send(password) is None")
    t.write_text(new)
    assert judge(old, new, "test_alerts.py") is None
    got = spec.test_diff(root, "HEAD", [FILE])[FILE]
    assert got == spec.formatting_only(old, new, "test_alerts.py") and not got[0]
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", FILE]) == 1


@pytest.mark.parametrize("name,old,new", [
    ("test_alerts.py", PY, PY.replace("# AC-007.1", "# AC-007.2")),
    ("test_alerts.py", PY, PY.replace("# AC-007.1", "")),
    ("test_alerts.py", PY, PY + "# AC-007.2\n"),
    ("test_alerts.py", PY_DOC, PY_DOC.replace("Sends one mail.", "Sends one mail. AC-007.2")),
    ("test_alerts.py", PY, PY.replace("    password", '    """AC-007.2"""\n    password')),
    ("page.test.ts", TS, TS.replace("// AC-007.1", "// AC-007.2")),
    ("report_test.go", GO, GO.replace("// AC-007.1", "// AC-007.1 AC-007.2")),
    ("ReportTest.java", JAVA, JAVA.replace("// AC-007.1\n", "")),
])
def test_an_added_dropped_or_changed_criterion_id_is_refused_ac_205_4(name, old, new):  # AC-205.4
    assert judge(old, new, name) is None
    assert judge(PY, PY + "# a plain note\n", "test_alerts.py") == PASS + "comments"     # the module exists and works


def test_a_second_mention_of_an_id_already_in_the_file_is_no_change_ac_205_4():  # AC-205.4
    assert judge(PY, PY + "# AC-007.1 again\n", "test_alerts.py") == PASS + "comments"


@pytest.mark.parametrize("name,old,new", [
    ("test_alerts.py", PY, PY.replace("password = 'x'", "password = 'x'  # noqa: S105")),
    ("test_alerts.py", PY, PY.replace("assert send(password)", "assert send(password)  # type: ignore[arg-type]")),
    ("report_test.go", GO, GO.replace('import "testing"', '//go:build unit\nimport "testing"')),
    ("page.test.ts", TS, "// @ts-nocheck\n" + TS),
])
def test_a_directive_comment_is_no_plain_comment_ac_205_4(name, old, new):  # AC-205.4
    assert judge(old, new, name) is None


@pytest.mark.parametrize("name,old,new", [
    ("test_alerts.py", PY, PY + "x = 'unterminated\n"),
    ("page.test.ts", TS, TS + "/* never closed\n"),
    ("test_alerts.py", PY, PY + "def (:\n"),
])
def test_text_that_does_not_lex_or_parse_is_refused_ac_205_4(name, old, new):  # AC-205.4
    assert judge(old, new, name) is None
    assert judge(PY, PY + "# ok\n", "test_alerts.py") == PASS + "comments"


def test_the_type_only_path_still_applies_to_a_change_with_an_annotation_ac_205_4(built):  # AC-205.4
    root, t = built
    new = "# AC-007.1\n# typed now\ndef test_alert() -> None:\n    password = 'x'\n    assert send(password)\n"
    assert judge(t.read_text(), new, "test_alerts.py") is None
    t.write_text(new)
    assert spec.test_diff(root, "HEAD", [FILE])[FILE] == (False, "type-only (test definitions, assertion lines and criterion ids unchanged)")


def test_the_helper_path_still_applies_to_a_file_without_tests_ac_205_4(built):  # AC-205.4
    root, t = built
    helper = root / "tests" / "helpers.py"
    helper.write_text("# AC-007.1\ndef make():\n    return 1\n")
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "test: helper", cwd=root)
    new = "# AC-007.1\ndef make():\n    return 2\n"
    assert judge(helper.read_text(), new, "helpers.py") is None
    helper.write_text(new)
    good, why = spec.test_diff(root, "HEAD", ["tests/helpers.py"])["tests/helpers.py"]
    assert not good and why.startswith("test helper (defines no test): ")
