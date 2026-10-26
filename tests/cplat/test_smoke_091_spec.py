"""Spec 091 acceptance tests, spec side: the `(smoke)` marker, the smoke trace, the per-shape smoke tags (AC-091.1) and
the tester rules for writing smoke tests (AC-091.5). Contract: docs/specs/091-*/design.md "Spec marker"."""
import json
import re

import pytest

import core
import spec

ROOT = core.PLATFORM_ROOT

SPEC = """---
spec_id: 007-price-alerts
title: Price alerts
status: {status}
priority: P1
shape: {shape}
---

# 007 — Price alerts

## Problem

Traders miss moves.

## Acceptance criteria

- **AC-007.1** Given a rule, when the price crosses it, then the alert list shows it. (smoke)
- **AC-007.2** Given a rule, when a webhook is set, then it is called.
- **AC-007.3** Given a rule, when it is deleted, then it is gone.
  - sub-bullet that ends with the marker (smoke)
- ~~**AC-007.4**~~ withdrawn: SMS is out of scope. (smoke)

## Non-goals

- SMS

## Open questions

None.

## Changelog

- 2026-10-01 created
"""

SMOKE_PY = "import pytest\n\n\n@pytest.mark.smoke\ndef test_alert_list_shows_the_rule(smoke_base_url):  # AC-007.1\n    ...\n"
PLAIN_PY = "def test_alert_list_shows_the_rule():  # AC-007.1\n    ...\n\n\ndef test_webhook():  # AC-007.2\n    ...\n\n\ndef test_delete():  # AC-007.3\n    ...\n"


def make(root, status="building", shape="service-python"):
    d = root / "docs" / "specs" / "007-price-alerts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(SPEC.format(status=status, shape=shape))
    return spec.read(d)


def put(root, rel, text):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)


# ---------------- AC-091.1: the marker ----------------

def test_the_marker_makes_a_criterion_smoke_checkable_ac_091_1(tmp_path):  # AC-091.1
    s = make(tmp_path)
    assert [a.smoke for a in s.acs() if a.id in {"AC-007.1", "AC-007.2", "AC-007.3"}] == [True, False, False]
    assert s.smoke_acs() == ["AC-007.1"]          # a sub-bullet does not count, a withdrawn criterion is ignored


def test_check_accepts_the_marker_on_active_criteria_ac_091_1(tmp_path):  # AC-091.1
    s = make(tmp_path, status="approved")
    assert not [e for e in spec.check(s) if "smoke" in e]
    assert s.smoke_acs() == ["AC-007.1"]                 # the marker is understood, not just ignored


def test_check_refuses_the_marker_without_a_deployable_shape_ac_091_1(tmp_path):  # AC-091.1
    s = make(tmp_path, shape="library-python")
    errs = spec.check(s)
    assert "AC-007.1: (smoke) needs a deployable shape (library-python has no smoke tests)" in errs


@pytest.mark.parametrize("shape, tag_example, other", [
    ("service-python", "@pytest.mark.smoke", "def test_x():"),
    ("service-java", '@Tag("smoke")', '@Tag("slow")'),
    ("service-go", "func TestSmokeHealth(t *testing.T) {", "func TestHealth(t *testing.T) {"),
    ("web-nextjs", "test('the root page loads @smoke', async () => {})", "test('the root page loads', async () => {})"),
])
def test_each_deployable_shape_has_a_smoke_tag_ac_091_1(shape, tag_example, other):  # AC-091.1
    tag = spec.smoke_tag(shape)
    assert tag is not None and tag.search(tag_example) and not tag.search(other)


def test_libraries_have_no_smoke_tag_ac_091_1():  # AC-091.1
    assert spec.smoke_tag("library-python") is None and spec.smoke_tag("gitops-app") is None


def test_shapes_yml_declares_the_tag_per_deployable_shape_ac_091_1():  # AC-091.1
    deployable = [s for s in core.registry.load() if s.get("deployable")]
    assert deployable
    for s in deployable:
        assert isinstance(s.get("smoke_tag"), str) and re.compile(s["smoke_tag"]), s["id"]
    web = next(s for s in deployable if s["id"] == "web-nextjs")
    assert web["smoke_globs"] == ["e2e/**/*.ts"]
    assert spec.smoke_globs("web-nextjs") == ["e2e/**/*.ts"]
    assert spec.smoke_globs("service-go") == spec.test_globs("service-go")        # default: test_globs


# ---------------- AC-091.1: the smoke trace ----------------

def test_smoke_trace_needs_one_file_with_the_id_and_the_tag_ac_091_1(tmp_path):  # AC-091.1
    s = make(tmp_path)
    put(tmp_path, "tests/test_plain.py", PLAIN_PY)                                    # names the id, no tag
    put(tmp_path, "tests/test_tagged_other.py", "import pytest\n\n\n@pytest.mark.smoke\ndef test_other():\n    ...\n")   # tag, no id
    put(tmp_path, "tests/test_smoke_alerts.py", SMOKE_PY)
    got = spec.smoke_trace(tmp_path, s, spec.smoke_globs("service-python"), spec.smoke_tag("service-python"))
    assert got == {"AC-007.1": ["tests/test_smoke_alerts.py"]}


def test_trace_misses_a_smoke_criterion_with_only_plain_tests_ac_091_1(tmp_path, capsys):  # AC-091.1
    make(tmp_path)
    put(tmp_path, "tests/test_plain.py", PLAIN_PY)
    assert spec.main(["--repo", str(tmp_path), "trace", "7"]) == 1
    out = capsys.readouterr().out
    assert "MISS AC-007.1  smoke: no smoke-tagged test" in out
    assert "ok   AC-007.2" in out and "ok   AC-007.3" in out         # non-smoke criteria are traced as before


def test_trace_passes_with_a_smoke_tagged_test_ac_091_1(tmp_path, capsys):  # AC-091.1
    make(tmp_path)
    put(tmp_path, "tests/test_plain.py", PLAIN_PY)
    put(tmp_path, "tests/test_smoke_alerts.py", SMOKE_PY)
    assert spec.main(["--repo", str(tmp_path), "trace", "7"]) == 0
    assert "smoke: no smoke-tagged test" not in capsys.readouterr().out
    assert spec.main(["--repo", str(tmp_path), "trace", "7", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["smoke"] == {"AC-007.1": ["tests/test_smoke_alerts.py"]}


def test_trace_json_lists_the_smoke_files_and_the_missing_one_ac_091_1(tmp_path, capsys):  # AC-091.1
    make(tmp_path)
    put(tmp_path, "tests/test_plain.py", PLAIN_PY)
    assert spec.main(["--repo", str(tmp_path), "trace", "7", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["missing"] == ["AC-007.1"] and data["smoke"] == {"AC-007.1": []}
    put(tmp_path, "tests/test_smoke_alerts.py", SMOKE_PY)
    assert spec.main(["--repo", str(tmp_path), "trace", "7", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["missing"] == [] and data["smoke"] == {"AC-007.1": ["tests/test_smoke_alerts.py"]}


def test_ci_names_the_smoke_criterion_of_a_building_spec_ac_091_1(tmp_path):  # AC-091.1
    make(tmp_path, status="building")
    put(tmp_path, "tests/test_plain.py", PLAIN_PY)
    msgs = [m for _, m in spec.ci_problems(tmp_path)]
    assert "AC-007.1 smoke: no smoke-tagged test" in msgs
    put(tmp_path, "tests/test_smoke_alerts.py", SMOKE_PY)
    assert not [m for _, m in spec.ci_problems(tmp_path) if "smoke" in m]


# ---------------- AC-091.5: the agents write smoke tests the right way ----------------

TESTERS = ["plugins/svc/agents/tester.md", "plugins/svc-java/agents/tester.md", "plugins/svc-go/agents/tester.md",
           "plugins/web/agents/tester.md"]


@pytest.mark.parametrize("rel", TESTERS)
def test_tester_agents_state_the_smoke_rules_ac_091_5(rel):  # AC-091.5
    text = (ROOT / rel).read_text()
    assert "(smoke)" in text and "SMOKE_BASE_URL" in text
    assert re.search(r"unique", text, re.I) and re.search(r"repeat", text, re.I) and re.search(r"delet", text, re.I)
    assert re.search(r"base URL", text, re.I)


@pytest.mark.parametrize("rel", ["plugins/svc/skills/spec-format/references/spec.md",
                                 "plugins/svc/skills/spec-format/references/testing.md"])
def test_spec_format_references_document_the_marker_and_the_rules_ac_091_5(rel):  # AC-091.5
    text = (ROOT / rel).read_text()
    assert "(smoke)" in text and "SMOKE_BASE_URL" in text


def test_spec_format_testing_reference_states_the_data_rule_ac_091_5():  # AC-091.5
    text = (ROOT / "plugins/svc/skills/spec-format/references/testing.md").read_text()
    assert re.search(r"unique", text, re.I) and re.search(r"repeat", text, re.I) and re.search(r"delet", text, re.I)


def test_build_command_hands_smoke_criteria_to_the_tester_ac_091_5():  # AC-091.5
    text = (ROOT / "plugins/component/commands/build.md").read_text()
    assert "(smoke)" in text
