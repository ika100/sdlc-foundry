"""Spec 177 acceptance tests, pure part: the issue forms and missing fields (AC-177.1), the plain-comment checks and the fixed
texts (AC-177.2, AC-177.4) of `triage_reporter`, and the `needs_info_close_days` setting (AC-177.4). The module is imported inside
each test, so a missing module fails that test and not the collection."""
import importlib

import pytest

import core

BUG = """name: Bug report
description: Something broke
body:
  - type: markdown
    attributes: {value: "a tip"}
  - type: textarea
    id: what
    attributes: {label: What happened}
    validations: {required: true}
  - type: textarea
    id: steps
    attributes: {label: Steps to reproduce}
    validations: {required: true}
  - type: input
    id: env
    attributes: {label: Environment}
"""
FEATURE = """name: Feature request
body:
  - type: textarea
    id: problem
    attributes: {label: Problem to solve}
    validations: {required: true}
  - type: textarea
    id: idea
    attributes: {label: Idea}
"""


def reporter():
    try:
        return importlib.import_module("triage_reporter")
    except ModuleNotFoundError:
        pytest.fail("triage_reporter is missing (AC-177.1, AC-177.2, AC-177.4)")


def write_forms(root, **files):
    d = root / ".github" / "ISSUE_TEMPLATE"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text)
    return d


# ---------------- AC-177.1: forms and the missing fields ----------------

def test_forms_reads_every_issue_form_but_config_sorted_by_id_ac_177_1(tmp_path):  # AC-177.1
    write_forms(tmp_path, **{"feature_request.yml": FEATURE, "bug_report.yml": BUG, "config.yml": "blank_issues_enabled: false\n"})
    got = reporter().forms(tmp_path)
    assert [f["id"] for f in got] == ["bug_report", "feature_request"]
    bug = got[0]
    assert bug["name"] == "Bug report"
    assert bug["fields"] == [{"label": "What happened", "required": True}, {"label": "Steps to reproduce", "required": True},
                             {"label": "Environment", "required": False}]


def test_forms_skips_a_broken_file_and_a_missing_directory_ac_177_1(tmp_path):  # AC-177.1
    assert reporter().forms(tmp_path) == []
    write_forms(tmp_path, **{"bug_report.yml": BUG, "broken.yml": "body: [unclosed\n  - : :"})
    assert [f["id"] for f in reporter().forms(tmp_path)] == ["bug_report"]


def test_form_of_lists_the_required_fields_that_are_absent_blank_or_no_response_ac_177_1(tmp_path):  # AC-177.1
    write_forms(tmp_path, **{"bug_report.yml": BUG, "feature_request.yml": FEATURE})
    forms = reporter().forms(tmp_path)
    body = "### What happened\n\n_No response_\n\n### Environment\n\nmac\n"
    assert reporter().form_of(body, forms) == {"id": "bug_report", "missing": ["What happened", "Steps to reproduce"]}
    body = "### What happened\n\n   \n\n### Steps to reproduce\n\nrun it\n"
    assert reporter().form_of(body, forms) == {"id": "bug_report", "missing": ["What happened"]}
    full = "### What happened\n\nx\n\n### Steps to reproduce\n\ny\n"
    assert reporter().form_of(full, forms) == {"id": "bug_report", "missing": []}


def test_form_of_picks_the_form_with_the_most_matching_headings_ac_177_1(tmp_path):  # AC-177.1
    write_forms(tmp_path, **{"bug_report.yml": BUG, "feature_request.yml": FEATURE})
    got = reporter().form_of("### Problem to solve\n\n_No response_\n\n### Idea\n\nmaybe\n", reporter().forms(tmp_path))
    assert got == {"id": "feature_request", "missing": ["Problem to solve"]}


def test_form_of_finds_no_form_for_a_body_without_headings_ac_177_1(tmp_path):  # AC-177.1
    write_forms(tmp_path, **{"bug_report.yml": BUG})
    assert reporter().form_of("it just broke, please fix", reporter().forms(tmp_path)) == {"id": None, "missing": []}


# ---------------- AC-177.2: plain words for outside reporters ----------------

@pytest.mark.parametrize("text,terms", [
    ("see spec 176 for it", ["spec 176"]),
    ("it is 177-triage-asks-reporters", ["177-triage-asks-reporters"]),
    ("AC-12 and ADR-25 apply", ["AC-12", "ADR-25"]),
    ("the label needs-info is set", ["needs-info"]),
    ("run /component:fix then cplat issue", ["/component:fix", "cplat"]),
    ("we set `bug` and `wontfix` today", ["bug", "wontfix"]),
    ("it is triaged and needs-decision", ["triaged", "needs-decision"]),
    ("it is P0, or p1, maybe p2", ["p0", "p1", "p2"]),
])
def test_internal_terms_finds_spec_numbers_labels_and_commands_ac_177_2(text, terms):  # AC-177.2
    got = reporter().internal_terms(text)
    assert [g.strip("`").lower() for g in got] == [t.lower() for t in terms], got


def test_internal_terms_lets_the_public_commands_and_plain_words_through_ac_177_2():  # AC-177.2
    r = reporter()
    assert r.PUBLIC_COMMANDS == ("/platform:doctor", "/issue:report")
    assert r.internal_terms("Run /platform:doctor and file it with /issue:report. Which version do you use?") == []
    assert r.internal_terms("Thanks, we need small changes to the text") == []


def test_internal_terms_are_distinct_in_order_of_first_appearance_ac_177_2():  # AC-177.2
    got = reporter().internal_terms("spec 12, then /component:fix, then spec 12 again")
    assert len(got) == 2 and got[0].lower() == "spec 12" and got[1] == "/component:fix"


def test_thanks_recognises_a_thank_you_ac_177_2():  # AC-177.2
    r = reporter()
    assert r.thanks("Thank you for the report") and r.thanks("Many thanks!") and not r.thanks("Please add the steps")


def test_the_footer_names_the_days_and_the_reopen_promise_ac_177_2():  # AC-177.2
    assert reporter().footer(14) == ("If there is no answer within 14 days, this issue is closed; "
                                     "a comment from you here reopens the review.")
    assert "within 30 days" in reporter().footer(30)


# ---------------- AC-177.4: the final comment and the setting ----------------

def test_the_final_comment_invites_the_reporter_to_comment_to_reopen_ac_177_4():  # AC-177.4
    text = reporter().final_comment(14)
    assert text.startswith("Thanks again for the report.") and "14 or more days ago" in text
    assert "Comment here with the details and it goes back into review." in text
    assert reporter().internal_terms(text) == []


def test_needs_info_close_days_defaults_to_14_ac_177_4(tmp_path):  # AC-177.4
    import settings
    assert settings.needs_info_close_days(tmp_path) == 14
    (tmp_path / ".platform-settings.yml").write_text("shape: platform\n")
    assert settings.needs_info_close_days(tmp_path) == 14


def test_needs_info_close_days_reads_the_project_file_ac_177_4(tmp_path):  # AC-177.4
    import settings
    (tmp_path / ".platform-settings.yml").write_text("needs_info_close_days: 30\n")
    assert settings.needs_info_close_days(tmp_path) == 30


@pytest.mark.parametrize("value", ["0", "-3", "1.5", "soon", "true"])
def test_needs_info_close_days_refuses_anything_but_a_whole_number_of_at_least_one_ac_177_4(tmp_path, value):  # AC-177.4
    import settings
    (tmp_path / ".platform-settings.yml").write_text(f"needs_info_close_days: {value}\n")
    with pytest.raises(core.PlatformError) as err:
        settings.needs_info_close_days(tmp_path)
    assert "needs_info_close_days must be a whole number of days, at least 1" in str(err.value)
