"""Spec 122 acceptance tests: `cplat spec list --json --detail` (AC-122.13 .. AC-122.17).

Contract: design.md "cplat spec list --json --detail". Specs are real spec folders in a tmp repo."""
import json
from pathlib import Path

import pytest

import spec
from test_spec import SPEC, make

QUESTION = "- Should a user be limited? (suggested: 50 per user; alternatives: no limit, 10 per hour)\n- Which mail provider?"
VERIFICATION = """# Verification — 007 Price alerts

**Result:** fail

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-007.1 | met | `tests/test_alerts.py::test_alert_email_on_cross` | `src/a.py:1` | |
"""


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def detail(root, capsys, *extra):
    assert spec.main(["--repo", str(root), "list", "--all", "--detail", "--json", *extra]) == 0
    rows = json.loads(capsys.readouterr().out)
    return next(r for r in rows if r["id"] == "007-price-alerts")


def folder(root: Path) -> Path:
    return root / "docs" / "specs" / "007-price-alerts"


def test_each_criterion_has_id_text_tests_and_verdict_ac_122_14(tmp_path, capsys):  # AC-122.14
    make(tmp_path, status="building")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_alerts.py").write_text("def test_alert_email_on_cross():  # AC-007.1\n    pass\n")
    (folder(tmp_path) / "verification.md").write_text(VERIFICATION)
    crit = {c["id"]: c for c in detail(tmp_path, capsys)["criteria"]}
    assert set(crit) == {"AC-007.1", "AC-007.2"}
    assert crit["AC-007.1"]["text"].startswith("Given a rule, when the price crosses it")
    assert crit["AC-007.1"]["tests"] == ["tests/test_alerts.py"] and crit["AC-007.1"]["verdict"] == "met"
    assert crit["AC-007.2"]["tests"] == [] and crit["AC-007.2"]["verdict"] == "not judged"
    assert crit["AC-007.1"]["smoke"] is False


def test_a_criterion_without_verification_is_not_judged_ac_122_14(tmp_path, capsys):  # AC-122.14
    make(tmp_path, status="approved")
    assert {c["verdict"] for c in detail(tmp_path, capsys)["criteria"]} == {"not judged"}


def test_a_smoke_criterion_is_flagged_ac_122_14(tmp_path, capsys):  # AC-122.14
    make(tmp_path, status="approved")
    p = folder(tmp_path) / "spec.md"
    p.write_text(p.read_text().replace("then it is called.", "then it is called. (smoke)"))
    crit = {c["id"]: c for c in detail(tmp_path, capsys)["criteria"]}
    assert crit["AC-007.2"]["smoke"] is True and crit["AC-007.1"]["smoke"] is False


def test_the_existing_row_keys_stay_and_detail_adds_the_new_ones_ac_122_13(tmp_path, capsys):  # AC-122.13
    make(tmp_path, status="approved")
    row = detail(tmp_path, capsys)
    assert {"id", "title", "status", "priority", "acs", "open_questions", "tracks", "next", "path"} <= set(row)
    assert {"level", "criteria", "questions", "check", "slices", "contract_change", "draft_pr", "parent"} <= set(row)
    assert row["title"] == "Price alerts" and row["level"] == "component" and row["slices"] == []


def test_without_detail_the_rows_are_unchanged_ac_122_13(tmp_path, capsys):  # AC-122.13
    make(tmp_path, status="approved")
    assert spec.main(["--repo", str(tmp_path), "list", "--all", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert "criteria" not in row and "questions" not in row


def test_the_contract_change_is_the_design_contract_cut_to_600_characters_ac_122_15(tmp_path, capsys):  # AC-122.15
    make(tmp_path, status="approved")
    (folder(tmp_path) / "design.md").write_text("# Design\n\n## Contract\n\nPOST /cart " + "x" * 1000 + "\n")
    c = detail(tmp_path, capsys)["contract_change"]
    assert c.startswith("POST /cart") and len(c) <= 600


def test_no_contract_means_none_ac_122_15(tmp_path, capsys):  # AC-122.15
    make(tmp_path, status="approved")
    assert detail(tmp_path, capsys)["contract_change"] is None


def test_the_draft_pull_request_is_read_from_the_mirror_file_ac_122_15(tmp_path, capsys):  # AC-122.15
    make(tmp_path)
    (folder(tmp_path) / ".cplat-draft-pr.json").write_text(json.dumps({"number": 41, "url": "https://github.com/acme/shop-api/pull/41"}))
    assert detail(tmp_path, capsys)["draft_pr"] == {"number": 41, "url": "https://github.com/acme/shop-api/pull/41"}


def test_without_a_mirror_file_there_is_no_draft_pr_ac_122_15(tmp_path, capsys):  # AC-122.15
    make(tmp_path)
    assert detail(tmp_path, capsys)["draft_pr"] is None


def test_open_questions_come_with_the_suggested_answer_first_ac_122_16(tmp_path, capsys):  # AC-122.16
    make(tmp_path, questions=QUESTION)
    row = detail(tmp_path, capsys)
    first, second = row["questions"]
    assert first["text"].startswith("Should a user be limited?") and first["answered"] is False
    assert first["options"][0] == "50 per user" and "no limit" in first["options"]
    assert second["options"] == [] or isinstance(second["options"], list)
    assert row["open_questions"] == 2


def test_struck_questions_are_not_listed_ac_122_16(tmp_path, capsys):  # AC-122.16
    make(tmp_path, questions="- ~~Rate limit?~~ 10/min\n- Which mail provider?")
    assert [q["text"] for q in detail(tmp_path, capsys)["questions"]] == ["Which mail provider?"]


def test_a_draft_without_questions_has_an_empty_list_ac_122_16(tmp_path, capsys):  # AC-122.16
    make(tmp_path, questions="None.")
    assert detail(tmp_path, capsys)["questions"] == []


def test_the_check_result_says_why_a_spec_cannot_be_approved_ac_122_17(tmp_path, capsys):  # AC-122.17
    make(tmp_path, status="approved", hash_="deadbeef0000")
    chk = detail(tmp_path, capsys)["check"]
    assert chk["ok"] is False and chk["errors"] and all(isinstance(e, str) for e in chk["errors"])


def test_a_valid_spec_checks_ok_ac_122_17(tmp_path, capsys):  # AC-122.17
    make(tmp_path, status="approved")
    assert detail(tmp_path, capsys)["check"] == {"ok": True, "errors": []}
