"""Spec 090: proposals (`retro_proposals`): format, evidence from the report, covers, limits, prompt changes, rendering."""
import json

import pytest

from retro_world import WEEK, Lazy, build, open_issues, specs

retro_proposals = Lazy("retro_proposals")
PLAT = "escalations.platform"
COD = "agents.svc:coder|service-python|sonnet"


def spec_p(title="Merges stop failing", **over):
    p = {"title": title, "problem": "Merges fail often. It costs hours.", "priority": "P1", "spec_line": "Merges land on a fresh base",
         "evidence": [{"ref": "escalations.platform.reason1", "value": 2}], "covers": None}
    p.update(over)
    return p


def prompt_p(**over):
    p = {"agent": "svc:coder", "shape": "service-python", "metrics": [{"ref": f"{COD}.fix_rounds.avg", "value": 0.5}],
         "change": "Ask the coder to run the linter before each commit."}
    p.update(over)
    return p


def check(report, specs_=(), prompts=()):
    return retro_proposals.validate({"specs": list(specs_), "prompts": list(prompts)}, report)


# ---------------- AC-090.7 format, evidence, limits ----------------

def test_a_proposal_with_evidence_from_the_report_is_accepted_and_ranked():
    """AC-090.7: ranked 1 to n, title, problem, priority, spec line and evidence kept."""
    r = build()
    c = check(r, [spec_p("First"), spec_p("Second", priority="P0", evidence=[{"ref": "issues.#101", "value": 2}])])
    assert [p["rank"] for p in c.specs] == [1, 2] and [p["title"] for p in c.specs] == ["First", "Second"] and c.refused == []
    assert c.specs[0]["priority"] == "P1" and c.specs[0]["spec_line"] == "Merges land on a fresh base"


def test_a_proposal_without_evidence_is_refused_and_named():
    """AC-090.7: no evidence at all, or a value the report does not have, or a ref it does not have: refused, with the title."""
    r = build()
    bad = [spec_p("No list", evidence=[]), spec_p("Wrong value", evidence=[{"ref": "escalations.platform.reason1", "value": 99}]),
           spec_p("Unknown ref", evidence=[{"ref": "made.up", "value": 2}]), spec_p("Not a list", evidence="lots")]
    c = check(r, bad)
    assert c.specs == []
    assert c.refused == [f'refused spec proposal {i} "{t}": no evidence from this report'
                         for i, t in enumerate(["No list", "Wrong value", "Unknown ref", "Not a list"], 1)]


def test_only_the_matching_evidence_pairs_are_kept():
    """AC-090.7: at least one pair must match; the others are dropped from the accepted proposal."""
    good = {"ref": "escalations.platform.reason1", "value": 2}
    c = check(build(), [spec_p(evidence=[{"ref": "made.up", "value": 1}, good, {"ref": "records", "value": 1000}])])
    assert c.specs[0]["evidence"] == [good]


def test_a_float_value_matches_by_closeness():
    """AC-090.7: a metric cited as 0.5 matches 0.5000000001."""
    c = check(build(), [spec_p(evidence=[{"ref": f"{COD}.fix_rounds.avg", "value": 0.5000000001}])])
    assert len(c.specs) == 1


@pytest.mark.parametrize("over", [
    {"title": ""}, {"title": "two\nlines"}, {"title": "x" * 101},
    {"problem": ""}, {"problem": "One. Two. Three. Four. Five. Six."},
    {"priority": "P3"}, {"priority": "high"},
    {"spec_line": ""}, {"spec_line": "a\nb"}, {"spec_line": "x" * 201},
])
def test_a_proposal_that_breaks_the_format_is_refused(over):
    """AC-090.7: title one line of at most 100 characters, problem of at most five sentences, priority P0 to P2, a one-line spec line."""
    c = check(build(), [spec_p(**{"title": "Bad one", **over})])
    assert c.specs == [] and len(c.refused) == 1 and c.refused[0].startswith("refused spec proposal 1 ")


def test_five_sentences_are_fine():
    """AC-090.7: a problem statement of exactly five sentences passes."""
    assert len(check(build(), [spec_p(problem="One. Two! Three? Four. Five.")]).specs) == 1


def test_at_most_five_specs_are_proposed():
    """AC-090.7: the sixth and seventh are refused as over the limit."""
    c = check(build(), [spec_p(f"S{i}") for i in range(1, 8)])
    assert [p["rank"] for p in c.specs] == [1, 2, 3, 4, 5]
    assert c.refused == ['refused spec proposal 6 "S6": over the limit of 5 proposed specs',
                         'refused spec proposal 7 "S7": over the limit of 5 proposed specs']


def test_a_missing_or_wrongly_typed_list_counts_as_empty():
    """AC-090.7: no crash on a sloppy file."""
    c = retro_proposals.validate({"specs": "nope", "prompts": None}, build())
    assert c.specs == [] and c.prompts == [] and c.refused == []
    assert retro_proposals.validate({}, build()).specs == []


def test_load_reads_the_file_and_names_the_problem(tmp_path):
    """AC-090.7: an unreadable or non-object proposals.json is a ValueError that starts with `proposals.json:`."""
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"specs": []}))
    assert retro_proposals.load(good) == {"specs": []}
    for text in ("[1, 2", "[1]", ""):
        bad = tmp_path / "bad.json"
        bad.write_text(text)
        with pytest.raises(ValueError, match="^proposals.json: "):
            retro_proposals.load(bad)
    with pytest.raises(ValueError, match="^proposals.json: "):
        retro_proposals.load(tmp_path / "missing.json")


def test_not_generated_has_the_fixed_form():
    """AC-090.7: the line the retro posts when no proposals could be made (also AC-090.12)."""
    assert retro_proposals.not_generated("claude exited with 3") == "Proposals: not generated (claude exited with 3)"


def test_each_proposal_renders_with_its_evidence_and_spec_command():
    """AC-090.7: title, priority, problem, the evidence with the previous value, and the line to pass to /svc:spec."""
    r = build()
    c = check(r, [spec_p("Merges stop failing", evidence=[{"ref": PLAT, "value": 4}, {"ref": "issues.#101", "value": 2}])])
    s = retro_proposals.render_public_section(c)
    assert s.startswith("## Proposed specs\n1. **Merges stop failing** (P1)")
    assert "Merges fail often. It costs hours." in s
    assert f"Evidence: `{PLAT}` = 4 (prev 1), #101 (2 this week)" in s
    assert "`/svc:spec Merges land on a fresh base`" in s
    assert "## Agent prompt proposals\nnone" in s


def test_an_empty_list_prints_none_under_its_heading():
    """AC-090.7: nothing accepted prints `none`."""
    s = retro_proposals.render_public_section(check(build()))
    assert "## Proposed specs\nnone" in s and "## Agent prompt proposals\nnone" in s and "refused" not in s


def test_the_public_section_counts_refusals_and_the_private_one_lists_them():
    """AC-090.7: the public text says how many were refused; the private text has each refused line."""
    c = check(build(), [spec_p("Fine"), spec_p("Bogus plan", evidence=[])])
    pub = retro_proposals.render_public_section(c)
    assert "1 proposal(s) refused (no evidence from this report, invalid, or over the limit)" in pub and "Bogus plan" not in pub
    priv = retro_proposals.render_private_section(c)
    assert pub.strip() in priv and 'refused spec proposal 2 "Bogus plan": no evidence from this report' in priv


# ---------------- AC-090.8 covers ----------------

def test_a_finding_an_open_spec_covers_is_named_as_an_amendment():
    """AC-090.8: covers {"spec": N} names the spec: `amends spec 087`, not a new spec."""
    c = check(build(), [spec_p(covers={"spec": "087"})])
    assert c.specs[0]["covers"] == {"spec": "087"}
    assert "**Merges stop failing** (P1) — amends spec 087" in retro_proposals.render_public_section(c)


def test_a_finding_an_open_issue_covers_is_named_as_see():
    """AC-090.8: covers {"issue": N}: `see #101`."""
    c = check(build(), [spec_p(covers={"issue": 101})])
    assert c.specs[0]["covers"] == {"issue": 101}
    assert "(P1) — see #101" in retro_proposals.render_public_section(c)


def test_a_spec_that_does_not_exist_or_is_done_cannot_be_amended():
    """AC-090.8: only specs that are not done (and not superseded) can be named."""
    c = check(build(), [spec_p("Gone", covers={"spec": "001"})])
    assert c.specs == [] and c.refused == ['refused spec proposal 1 "Gone": spec 001 does not exist or is done']


def test_an_issue_that_is_not_open_cannot_be_named():
    """AC-090.8: a closed or unknown issue is refused."""
    c = check(build(), [spec_p("Shut", covers={"issue": 999})])
    assert c.specs == [] and c.refused == ['refused spec proposal 1 "Shut": #999 is not an open issue']


def test_evidence_of_an_issue_turns_a_new_spec_into_see_issue():
    """AC-090.8: covers null and an `issues.#N` ref for an open issue: the proposal becomes `see #N`."""
    c = check(build(), [spec_p(evidence=[{"ref": "issues.#101", "value": 2}])])
    assert c.specs[0]["covers"] == {"issue": 101}


def test_a_spec_that_tracks_the_issue_wins_over_the_issue():
    """AC-090.8: when a spec that is not done tracks the issue, the proposal amends that spec."""
    r = build(specs=specs(tracks=[101]))
    c = check(r, [spec_p(evidence=[{"ref": "issues.#101", "value": 2}])])
    assert c.specs[0]["covers"] == {"spec": "087"}


def test_an_issue_that_is_not_open_does_not_turn_the_proposal_into_see():
    """AC-090.8: evidence from issue #102, which is closed and not in the open list: the proposal stays new."""
    c = check(build(), [spec_p(evidence=[{"ref": "issues.#102", "value": 1}])])
    assert c.specs[0]["covers"] is None
    assert "see #" not in retro_proposals.render_public_section(c) and "amends" not in retro_proposals.render_public_section(c)


# ---------------- AC-090.9 prompt proposals ----------------

def test_a_prompt_proposal_names_agent_shape_metrics_and_change():
    """AC-090.9: agent, shape, the cited metric with previous value and difference, and the change in prose."""
    c = check(build(), prompts=[prompt_p()])
    assert len(c.prompts) == 1 and c.refused == []
    s = retro_proposals.render_public_section(c)
    assert "## Agent prompt proposals\n- **svc:coder** on service-python: Ask the coder to run the linter before each commit." in s
    assert "Metrics: `fix_rounds.avg` = 0.50 (prev 1.50, -1.00)" in s


def test_a_prompt_proposal_for_an_agent_without_a_row_is_refused():
    """AC-090.9: the agent and shape must be a row of the report."""
    c = check(build(), prompts=[prompt_p(shape="web-nextjs"), prompt_p(agent="svc:ghost")])
    assert c.prompts == []
    assert c.refused[0].startswith('refused prompt proposal 1 "svc:coder web-nextjs": ')
    assert c.refused[1].startswith('refused prompt proposal 2 "svc:ghost service-python": ')


def test_a_prompt_proposal_needs_a_metric_of_that_agent_from_the_report():
    """AC-090.9: metrics of another agent, a wrong value, or none are no evidence; an empty change is refused."""
    other = [{"ref": "agents.web:coder|web-nextjs|sonnet.fix_rounds.avg", "value": 0.0}]
    c = check(build(), prompts=[prompt_p(metrics=other), prompt_p(metrics=[{"ref": f"{COD}.fix_rounds.avg", "value": 7}]),
                                prompt_p(metrics=[]), prompt_p(change="  ")])
    assert c.prompts == [] and len(c.refused) == 4


def test_at_most_three_prompt_changes_are_proposed():
    """AC-090.9: the fourth is refused as over the limit."""
    c = check(build(), prompts=[prompt_p(change=f"Change {i}.") for i in range(4)])
    assert len(c.prompts) == 3
    assert c.refused == ['refused prompt proposal 4 "svc:coder service-python": over the limit of 3 prompt proposals']


# ---------------- AC-090.12 the prompt of the headless run ----------------

def test_the_prompt_tells_the_agent_what_to_read_write_and_not_to_do(tmp_path):
    """AC-090.12: the prompt for the headless run names the directory and week, the limits and the single output file."""
    (tmp_path / "report.json").write_text(json.dumps(build()))
    text = retro_proposals.prompt(tmp_path)
    assert str(tmp_path) in text and WEEK in text and "proposals.json" in text and "report.json" in text
    assert "5" in text and "3" in text and "covers" in text
    assert "{dir}" not in text and "{week}" not in text and "{max_specs}" not in text and "{max_prompts}" not in text
