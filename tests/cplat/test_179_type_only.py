"""Spec 179 acceptance tests: a type-only change to a frozen acceptance test is tightened without asking the person (AC-179.4).

Seams: `spec.type_only` on file contents; `spec.test_diff` and `spec.main` (`cplat spec test-diff`) on the spec 160 `built` repo
(one `building` spec and its acceptance test); the PR block of `cplat platform runs report --pr`; the build prompt.
Contract: design.md section 3.
"""
import re
from pathlib import Path

import pytest

import runs
import spec
from test_160_lint_suppressions import built, g  # noqa: F401  (fixture, helper)
from test_runs_built_133 import make_run, part, report, repo  # noqa: F401  (fixtures, helpers)

ROOT = Path(__file__).resolve().parents[2]
FILE = "tests/test_alerts.py"
WHY = "type-only (test definitions, assertion lines and criterion ids unchanged)"

OLD = """# AC-007.1
def test_alert(client):
    password = 'x'
    assert send(password)
    assert client.sent(
        password,
    )


def test_second():
    assert 1 == 1
"""
NEW_TYPED = """# AC-007.1
from typing import cast

from app import Client


def test_alert(client: Client) -> None:
    password = cast(str, 'x')
    assert send(password)
    assert client.sent(
        password,
    )


def test_second() -> None:
    assert 1 == 1
"""


def ok(old, new, name="test_alerts.py"):
    return spec.type_only(old, new, name)


# ---------------- the classification ----------------

def test_annotations_casts_and_imports_are_type_only_ac_179_4():  # AC-179.4
    good, _ = ok(OLD, NEW_TYPED)
    assert good


def test_reindenting_an_assertion_line_is_still_type_only_ac_179_4():  # AC-179.4
    good, _ = ok(OLD, OLD.replace("        password,\n    )", "            password,\n    )").replace("password = 'x'", "password: str = 'x'"))
    assert good


@pytest.mark.parametrize("new, why", [
    (OLD.replace("AC-007.1", "AC-007.2"), "criterion ids changed"),
    (OLD + "# AC-007.2\n", "criterion ids changed"),
    (OLD.replace("def test_second():", "def test_third():"), "test definitions changed"),
    (OLD.replace("def test_second():\n    assert 1 == 1\n", ""), "test definitions changed"),
    (OLD + "\n\ndef test_new():\n    pass\n", "test definitions changed"),
    (OLD.replace("def test_second():", "@pytest.mark.skip\ndef test_second():"), "adds a skip"),
    (OLD.replace("assert send(password)", "assert send(password) is not None"), "assertion lines changed"),
    (OLD.replace("        password,\n", "        'other',\n"), "assertion lines changed"),
    (OLD.replace("assert 1 == 1", "assert 1 == 1\n    assert 2 == 2"), "assertion lines changed"),
    (OLD.replace("    assert send(password)\n", "    send(password)\n"), "assertion lines changed"),
    (OLD, "unchanged"),
])
def test_anything_else_is_not_type_only_and_names_the_first_failed_rule_ac_179_4(new, why):  # AC-179.4
    good, reason = ok(OLD, new)
    assert not good and reason.startswith(why), reason


@pytest.mark.parametrize("name, old, new, edit", [
    ("page.test.ts", "// AC-007.1\ntest(\"lists\", async () => {\n  const res = await load();\n  expect(res.files).toHaveLength(3);\n});\n",
     "// AC-007.1\nimport type { Res } from './types';\ntest(\"lists\", async () => {\n  const res = (await load()) as Res;\n"
     "  expect(res.files).toHaveLength(3);\n});\n", ("toHaveLength(3)", "toHaveLength(4)")),
    ("report_test.go", "package s\n\n// AC-007.1\nfunc TestReport(t *testing.T) {\n\tresp := get(t)\n\tif resp.Code != 200 {\n\t\tt.Fatal(resp.Code)\n\t}\n}\n",
     "package s\n\nimport \"net/http\"\n\n// AC-007.1\nfunc TestReport(t *testing.T) {\n\tvar resp *http.Response = get(t)\n"
     "\tif resp.Code != 200 {\n\t\tt.Fatal(resp.Code)\n\t}\n}\n", ("t.Fatal(resp.Code)", "t.Fatal(resp.Status)")),
])
def test_other_languages_follow_the_same_rule_ac_179_4(name, old, new, edit):  # AC-179.4
    good, why = ok(old, new, name)
    assert good, why
    good, why = ok(old, new.replace(*edit), name)
    assert not good and why.startswith("assertion lines changed")


# ---------------- the check, the recorded tightening and the PR block ----------------

@pytest.fixture()
def typed(built):  # noqa: F811
    root, t = built
    t.write_text(OLD)
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "test: acceptance tests for 007 (more)", cwd=root)
    return root, t


def test_the_check_names_a_type_only_change_in_its_line_and_exits_1_ac_179_4(typed, capsys):  # AC-179.4
    root, t = typed
    t.write_text(NEW_TYPED)
    good, why = spec.test_diff(root, "HEAD", [FILE])[FILE]
    assert not good and why == WHY
    capsys.readouterr()
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", FILE]) == 1
    assert f"{FILE}: changed — {WHY}" in capsys.readouterr().out


def test_a_change_of_an_assertion_line_is_not_called_type_only_ac_179_4(typed, capsys):  # AC-179.4
    root, t = typed
    t.write_text(NEW_TYPED)
    assert spec.test_diff(root, "HEAD", [FILE])[FILE] == (False, WHY)               # the same change without the assertion edit
    t.write_text(NEW_TYPED.replace("assert send(password)", "assert send(password) is not None"))
    good, why = spec.test_diff(root, "HEAD", [FILE])[FILE]
    assert not good and "type-only" not in why
    capsys.readouterr()
    spec.main(["--repo", str(root), "test-diff", "HEAD", FILE])
    assert "type-only" not in capsys.readouterr().out


def test_a_type_only_change_is_recorded_without_asking_and_listed_in_the_pr_ac_179_4(typed, monkeypatch, capsys, repo):  # AC-179.4
    root, t = typed
    added = []
    monkeypatch.setattr(runs, "current_run", lambda r: "run-1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **k: added.append((rid, name, item)))
    t.write_text(NEW_TYPED)
    assert spec.test_diff(root, "HEAD", [])[FILE] == (False, WHY)                     # the check names it ...
    why = "the type check needs the Client annotation"
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", "--tighten", FILE, "--task", "t2", "--reason", why]) == 0   # ... it is recorded
    good, reason = spec.test_diff(root, "HEAD", [])[FILE]
    assert good and reason == f"tightened by an agent: {why}"                         # ... and accepted
    (rid, name, item), = added
    assert name == "approved_test_diffs"
    assert item == {"file": FILE, "task": "t2", "reason": why, "kind": "tightened"}
    capsys.readouterr()
    block = part(report(make_run(approved_test_diffs=[item]), repo, capsys)[1], "User decisions")
    assert f"test tightened by an agent `{FILE}` (task t2): {why}" in block


def test_tightening_does_not_accept_an_assertion_change_as_type_only_ac_179_4(typed, capsys):  # AC-179.4
    root, t = typed
    t.write_text(NEW_TYPED.replace("assert 1 == 1", "pass"))                 # an assertion line changed: removed
    capsys.readouterr()
    spec.main(["--repo", str(root), "test-diff", "HEAD", "--tighten", FILE, "--task", "t2", "--reason", "x"])
    assert "type-only" not in capsys.readouterr().out
    assert not spec.test_diff(root, "HEAD", [FILE])[FILE][0]            # still not accepted unless it is a tightening of spec 165


# ---------------- the prompts ----------------

def read(rel):
    return (ROOT / rel).read_text()


def test_the_build_tightens_a_type_only_line_without_asking_the_person_ac_179_4():  # AC-179.4
    lines = [ln for rel in ("plugins/component/commands/build.md", "plugins/component/references/build-tighten.md")
             for ln in read(rel).splitlines()]
    hit = [ln for ln in lines if "type-only" in ln and "--tighten" in ln]
    assert hit, "a line says what the build does with a `type-only` line: cplat spec test-diff $RED --tighten <file>"
    assert any(re.search(r"without asking|does not ask|never ask", ln) for ln in hit)


def test_the_coder_may_change_a_frozen_test_only_by_an_annotation_cast_or_import_ac_179_4():  # AC-179.4
    build = read("plugins/component/commands/build.md")
    assert any("type annotation" in ln and "cast" in ln and "import" in ln and "assertion" in ln for ln in build.splitlines())
    assert "Hard rule" in build
    assert "Never loosen, delete or skip" in read("plugins/component/references/build-tighten.md")
