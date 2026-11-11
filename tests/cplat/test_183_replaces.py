"""Spec 183 acceptance tests: replaced criteria, `(replaces AC-…)` and "superseded by" (AC-183.5, AC-183.6, the strike of AC-183.8)."""
import json

import pytest

import spec
from support_183 import SPEC_TEXT

OLD = """---
spec_id: 007-old
title: Old
status: done
priority: P1
---

# 007 - Old

## Problem

Something.

## Acceptance criteria

{criteria}

## Non-goals

- None

## Open questions

None.

## Changelog

- 2026-10-01 created
"""

NEW_CRITERION = "- **AC-008.1** Given a thing, when it runs, then it works differently (replaces AC-007.1)"
ACTIVE = "- **AC-007.1** Given a thing, when it runs, then it works.\n- **AC-007.2** Given b, when c, then d."
STRUCK = ("- ~~**AC-007.1**~~ superseded by AC-008.1 on 2026-11-11: Given a thing, when it runs, then it works.\n"
          "- **AC-007.2** Given b, when c, then d.")


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def put(repo, name, text):
    d = repo / "docs" / "specs" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(text)
    return d


def two_specs(repo, old_criteria, new_criterion=NEW_CRITERION):
    put(repo, "007-old", OLD.format(criteria=old_criteria))
    new_text = SPEC_TEXT.format(name="008-new", num="008", title="New").replace(
        "- **AC-008.1** Given a thing, when it runs, then it works.", new_criterion)
    put(repo, "008-new", new_text)


def check(repo, capsys):
    capsys.readouterr()
    rc = spec.main(["--repo", str(repo), "check"])
    return rc, capsys.readouterr().out


def test_replacing_an_active_criterion_is_an_error_ac_183_5(tmp_path, capsys):  # AC-183.5
    two_specs(tmp_path, ACTIVE)
    rc, out = check(tmp_path, capsys)
    assert rc == 1
    assert "AC-008.1" in out and "AC-007.1" in out and "superseded by" in out


def test_replacing_a_missing_criterion_is_an_error_ac_183_5(tmp_path, capsys):  # AC-183.5
    two_specs(tmp_path, ACTIVE, NEW_CRITERION.replace("replaces AC-007.1", "replaces AC-007.9"))
    rc, out = check(tmp_path, capsys)
    assert rc == 1 and "AC-007.9" in out and "does not exist" in out
    two_specs(tmp_path, ACTIVE, NEW_CRITERION.replace("replaces AC-007.1", "replaces AC-099.1"))
    rc, out = check(tmp_path, capsys)
    assert rc == 1 and "AC-099.1" in out and "does not exist" in out


def test_replacing_a_struck_through_criterion_passes_ac_183_5(tmp_path, capsys):  # AC-183.5
    two_specs(tmp_path, STRUCK)
    old = spec.read(tmp_path / "docs" / "specs" / "007-old")
    assert {a.id: a for a in old.acs()}["AC-007.1"].superseded_by == "AC-008.1"
    rc, out = check(tmp_path, capsys)
    assert rc == 0, out


def test_a_superseded_criterion_is_withdrawn_for_every_count_ac_183_6(tmp_path, capsys):  # AC-183.6
    two_specs(tmp_path, STRUCK)
    old = spec.read(tmp_path / "docs" / "specs" / "007-old")
    assert old.active_acs() == ["AC-007.2"]
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_b():  # AC-007.2\n    ...\n")
    capsys.readouterr()
    assert spec.main(["--repo", str(tmp_path), "trace", "007"]) == 0
    out = capsys.readouterr().out
    assert "1/1 criteria traced" in out
    assert "superseded AC-007.1  superseded by AC-008.1" in out
    assert "MISS" not in out


def test_trace_json_lists_what_was_superseded_ac_183_6(tmp_path, capsys):  # AC-183.6
    two_specs(tmp_path, STRUCK)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_b():  # AC-007.2\n    ...\n")
    capsys.readouterr()
    assert spec.main(["--repo", str(tmp_path), "trace", "007", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["superseded"] == {"AC-007.1": "AC-008.1"} and list(doc["criteria"]) == ["AC-007.2"] and doc["missing"] == []


def test_strike_rewrites_the_old_line_and_logs_it_ac_183_8(tmp_path, capsys):  # AC-183.8
    import spec_replace
    d = put(tmp_path, "007-old", OLD.format(criteria=ACTIVE))
    assert spec_replace.strike(d, "AC-007.1", "AC-008.1") is True
    text = (d / "spec.md").read_text()
    assert "~~**AC-007.1**~~ superseded by AC-008.1 on " in text and "Given a thing, when it runs, then it works." in text
    assert "- **AC-007.1**" not in text and "status: done" in text
    changelog = text.split("## Changelog", 1)[1]
    assert "AC-007.1 superseded by AC-008.1" in changelog
    assert spec_replace.strike(d, "AC-007.1", "AC-008.1") is False       # no longer an active criterion
    assert spec_replace.strike(d, "AC-007.9", "AC-008.1") is False


def test_a_plan_slice_with_a_replaces_criterion_leaves_check_green_ac_183_8(tmp_path, capsys):  # AC-183.8
    from test_spec import PRODUCT, PRODUCT_PLAN
    app = tmp_path / "shop-gitops"
    (app / "docs" / "specs" / "012-billing").mkdir(parents=True)
    (app / "docs" / "specs" / "012-billing" / "spec.md").write_text(PRODUCT)
    (app / "docs" / "plan").mkdir()
    plan = app / "docs" / "plan" / "012-billing.md"
    plan.write_text(PRODUCT_PLAN.replace(
        'depends_on: [], done: false}\n  - {id: shop-web',
        'depends_on: [], done: false, criteria: ["Given a cart, when POST /billing/checkout, then 201 (system AC-012.1) '
        '(replaces AC-001.1)"]}\n  - {id: shop-web'))
    repo = tmp_path / "shop-api"
    put(repo, "001-old", OLD.format(criteria="- **AC-001.1** Given a, when b, then c.").replace("007", "001"))
    s = spec.new_from_plan(repo, plan, "shop-api", shape=None)
    assert s.number == "002"
    old_text = (repo / "docs" / "specs" / "001-old" / "spec.md").read_text()
    assert "~~**AC-001.1**~~ superseded by AC-002.1 on " in old_text
    capsys.readouterr()
    assert spec.main(["--repo", str(repo), "check"]) == 0, capsys.readouterr().out
