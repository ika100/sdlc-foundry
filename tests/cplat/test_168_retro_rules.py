"""Spec 168 acceptance tests: "Rules to retire" in the weekly retro (AC-168.8).

The covered week is 2026-W43 (Monday 2026-10-19 to Sunday 2026-10-25); the window is the 4 complete weeks 2026-W40 to 2026-W43
(2026-09-28 to 2026-10-25). Seams: a fixture tree with a register, fake run records, the issue-state callable of
`retro_rules.section`, `FakeRetroTracker.issue_states` (retro_world) and a fake `gh` for `GhRetroTracker`."""
import hashlib
import json

import pytest

import cplat
import core
import retro_github
from retro_world import WEEK, Lazy, build, tracker  # noqa: F401  (fixture)
from rules_support import STATEMENT, e, entries_path, entries_text, put, register_text
from test_retro_cli import world  # noqa: F401  (fixture)
from test_runs import clock, mem, store  # noqa: F401  (fixtures of `world`)
from test_runs_report import rec

retro_rules = Lazy("retro_rules")
retro_report = Lazy("retro_report")

BUILD = "plugins/component/commands/build.md"
TESTER = "plugins/svc/agents/tester.md"
WEEKS = ["2026-W40", "2026-W41", "2026-W42", "2026-W43"]
SIG = "0123456789abcdef"
IN_W43, IN_W42, IN_W40 = "2026-10-20T10:00:00Z", "2026-10-14T10:00:00Z", "2026-09-29T10:00:00Z"
BEFORE_W40, AFTER_W43 = "2026-09-27T23:59:59Z", "2026-10-26T00:00:00Z"


def nb(text):
    return len(text.encode("utf-8"))


def tree(tmp_path, items, path=BUILD):
    """A platform tree: `path` holds one paragraph per item `(sentence, entry fields)`; entries get ids R1, R2, …;
    workflows have the jobs `dco` (name `DCO sign-off`) and `security` (name `security`)."""
    body = "\n\n".join(s for s, _ in items) + "\n"
    put(tmp_path, path, "---\ndescription: Demo\n---\nYou are the demo.\n\n" + STATEMENT + "\n\n" + body)
    put(tmp_path, entries_path(path), entries_text([e(f"R{i}", text_of(s), **f) for i, (s, f) in enumerate(items, 1)]))
    put(tmp_path, "docs/rules/register.yml", register_text({}, 10_000_000))
    put(tmp_path, ".github/workflows/ci.yml",
        "name: ci\njobs:\n  dco:\n    name: DCO sign-off\n    runs-on: ubuntu-latest\n  security:\n    name: security\n    runs-on: ubuntu-latest\n")
    return tmp_path


def text_of(sentence):
    return sentence.rstrip(".").split(",")[0]


def issues_of(table):
    return lambda numbers: {n: table[n] for n in numbers if n in table}


def closed(n, sig=SIG):
    return {"state": "closed", "body": f"Something broke.\n\nSignature: platform:{sig}\n"}


def run(name, ended, **extra):
    return rec(f"r-{name}", ended, **extra)


def red(name, ended, *checks):
    return run(name, ended, kind="pr-wait", outcome="failed", pr_wait={"result": "red", "checks": list(checks)})


def section(root, recs, table=None, week=WEEK):
    return retro_rules.section(root, recs, week=week, issues=issues_of(table or {}))


def by_entry(sec):
    return {x["entry"]: x for x in sec["entries"]}


ENFORCED = "Always sign off every commit, because the DCO check refuses unsigned ones today."
QUIET = "Never pipe cplat output into head, because its last lines carry the decisions and fixes (é)."
CMD = "Never poll for a PR in a loop, because the wait command reports every check."
JOB = "Never commit a secret, because the security job refuses it."


def standard(tmp_path):
    return tree(tmp_path, [(ENFORCED, dict(cls="practice", source="#476", enforced_by="ci:dco")),
                           (QUIET, dict(cls="experience", source="spec 048, #478")),
                           (CMD, dict(cls="practice", enforced_by="cplat pr wait")),
                           (JOB, dict(cls="experience", source="#500", enforced_by="ci:security"))])


# ---------------- AC-168.8 the section: enforced rules ----------------

def test_an_enforced_rule_is_proposed_with_the_failures_of_its_check_in_the_covered_week_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(ENFORCED, dict(cls="practice", source="#476", enforced_by="ci:dco"))])
    recs = [red("a", IN_W43, "dco"), red("b", "2026-10-21T10:00:00Z", "DCO sign-off"),
            red("c", "2026-10-22T10:00:00Z", "other", "DCO sign-off", "dco"),            # one record counts once
            red("d", IN_W42, "dco"),                                                     # not the covered week
            run("e", "2026-10-23T10:00:00Z", kind="pr-wait", pr_wait={"result": "green", "checks": ["dco"]}),   # not red
            red("f", "2026-10-24T10:00:00Z", "dcox")]                                    # another check
    sec = section(root, recs)
    [x] = sec["entries"]
    assert sec["weeks"] == WEEKS and x["entry"] == f"{BUILD}#R1" and x["rank"] == 1 and x["class"] == "practice"
    assert x["evidence"] == {"kind": "enforced", "by": "ci:dco", "failures": 3}
    assert x["bytes"] == nb(ENFORCED) and "DCO check refuses unsigned ones" in x["reason"] and "Always sign off every commit" in x["text"]


def test_a_ci_check_matches_by_its_name_followed_by_a_parenthesis_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(JOB, dict(cls="practice", enforced_by="ci:security"))])
    recs = [red("a", IN_W43, "security (ubuntu)"), red("b", IN_W43, "security"), red("c", IN_W43, "security-scan")]
    assert section(root, recs)["entries"][0]["evidence"] == {"kind": "enforced", "by": "ci:security", "failures": 2}


def test_a_cplat_command_counts_the_escalations_that_name_it_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(CMD, dict(cls="practice", enforced_by="cplat pr wait"))])
    recs = [run("a", IN_W43, outcome="escalated", escalation={"reason": "cplat pr wait stopped: red check"}),
            run("b", "2026-10-22T10:00:00Z", outcome="escalated", escalation={"reason": "merge failed after cplat pr wait"}),
            run("c", IN_W42, outcome="escalated", escalation={"reason": "cplat pr wait stopped"}),
            run("d", IN_W43, outcome="escalated", escalation={"reason": "disk full"})]
    assert section(root, recs)["entries"][0]["evidence"] == {"kind": "enforced", "by": "cplat pr wait", "failures": 2}


def test_an_enforced_rule_without_failures_is_still_proposed_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(ENFORCED, dict(cls="experience", source="#476", enforced_by="ci:dco"))])
    assert section(root, [run("a", IN_W43)])["entries"][0]["evidence"] == {"kind": "enforced", "by": "ci:dco", "failures": 0}


# ---------------- AC-168.8 the section: quiet experience rules ----------------

def quiet_tree(tmp_path, source="#478"):
    return tree(tmp_path, [(QUIET, dict(cls="experience", source=source))])


QUIET_RUNS = [run("a", IN_W43), run("b", IN_W42), run("c", IN_W40), run("d", "2026-10-08T10:00:00Z")]


def test_a_quiet_experience_rule_of_a_closed_issue_is_proposed_with_the_run_count_ac_168_8(tmp_path):  # AC-168.8
    root = quiet_tree(tmp_path, "spec 048, #478")
    recs = [*QUIET_RUNS, run("old", BEFORE_W40), run("new", AFTER_W43), run("a", IN_W43),         # a duplicate run id counts once
            run("bad", "garbage")]
    sec = section(root, recs, {478: closed(478)})
    [x] = sec["entries"]
    assert sec["runs"] == 4 and sec["weeks"] == WEEKS
    assert x["class"] == "experience" and x["bytes"] == nb(QUIET) and x["entry"] == f"{BUILD}#R1"
    assert x["evidence"] == {"kind": "quiet", "issue": 478, "occurrences": 0, "runs": 4}


@pytest.mark.parametrize("occurrence", [
    run("o1", IN_W40, filed=[{"signature": SIG, "url": None, "result": "new"}]),                  # the earliest week of the window
    run("o2", IN_W43, filed=[{"signature": SIG, "url": None, "result": "+1"}]),
    run("o3", IN_W42, outcome="escalated", escalation={"reason": "see #478 for the cause"}),
    run("o4", IN_W42, outcome="escalated", escalation={"reason": "#478"}),
])
def test_an_occurrence_of_the_cause_keeps_the_rule_ac_168_8(tmp_path, occurrence):  # AC-168.8
    assert section(quiet_tree(tmp_path), [*QUIET_RUNS, occurrence], {478: closed(478)})["entries"] == []


@pytest.mark.parametrize("other", [
    run("n1", IN_W43, filed=[{"signature": "ffffffffffffffff", "url": None, "result": "new"}]),   # another signature
    run("n2", IN_W42, outcome="escalated", escalation={"reason": "see #4781 and #47"}),            # other issue numbers
    run("n3", BEFORE_W40, filed=[{"signature": SIG, "url": None, "result": "new"}]),               # before the window
    run("n4", AFTER_W43, outcome="escalated", escalation={"reason": "#478"}),                      # after the window
])
def test_other_causes_and_other_weeks_do_not_count_ac_168_8(tmp_path, other):  # AC-168.8
    sec = section(quiet_tree(tmp_path), [*QUIET_RUNS, other], {478: closed(478)})
    assert [x["evidence"]["kind"] for x in sec["entries"]] == ["quiet"]


@pytest.mark.parametrize("table", [{478: {"state": "open", "body": f"Signature: platform:{SIG}\n"}}, {}],
                         ids=["issue-still-open", "issue-unreadable"])
def test_an_open_or_unreadable_issue_makes_no_candidate_ac_168_8(tmp_path, table):  # AC-168.8
    assert section(quiet_tree(tmp_path), QUIET_RUNS, table)["entries"] == []


def test_no_runs_in_the_window_make_no_quiet_candidate_ac_168_8(tmp_path):  # AC-168.8
    assert section(quiet_tree(tmp_path), [run("old", BEFORE_W40)], {478: closed(478)})["entries"] == []


def test_only_experience_rules_with_a_source_issue_can_be_quiet_ac_168_8(tmp_path):  # AC-168.8
    table = {478: closed(478)}
    assert section(tree(tmp_path / "a", [(QUIET, dict(cls="practice", source="#478"))]), QUIET_RUNS, table)["entries"] == []
    assert section(tree(tmp_path / "b", [(QUIET, dict(cls="experience", source="spec 048"))]), QUIET_RUNS, table)["entries"] == []
    assert section(tree(tmp_path / "c", [(QUIET, dict(cls="experience"))]), QUIET_RUNS, table)["entries"] == []


def test_the_issue_states_are_asked_for_the_source_issues_ac_168_8(tmp_path):  # AC-168.8
    asked = []

    def issues(numbers):
        asked.extend(numbers)
        return {478: closed(478)}
    retro_rules.section(quiet_tree(tmp_path), QUIET_RUNS, week=WEEK, issues=issues)
    assert 478 in asked


def test_hard_not_a_rule_and_retired_entries_are_never_proposed_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(ENFORCED, dict(cls="not a rule", enforced_by="ci:dco")), ("Never reuse a branch, because it is stale.", dict(
        cls="retired", retired="2026-11-10", reason="a cplat command now refuses it", enforced_by="ci:dco"))])
    assert section(root, [run("a", IN_W43)])["entries"] == []


# ---------------- AC-168.8 ranking, cap, none ----------------

def test_at_most_three_entries_ranked_by_bytes_saved_ac_168_8(tmp_path):  # AC-168.8
    root = standard(tmp_path)
    sec = section(root, [run("a", IN_W43)], {478: closed(478)})
    assert [x["entry"] for x in sec["entries"]] == [f"{BUILD}#R2", f"{BUILD}#R1", f"{BUILD}#R3"]
    assert [x["rank"] for x in sec["entries"]] == [1, 2, 3]
    assert [x["bytes"] for x in sec["entries"]] == [nb(QUIET), nb(ENFORCED), nb(CMD)]
    assert nb(QUIET) > nb(ENFORCED) > nb(CMD) > nb(JOB)                                # the shortest, R4, is left out by the cap


def test_equal_sizes_rank_by_entry_key_ac_168_8(tmp_path):  # AC-168.8
    a = "Always sign off every commit, because the DCO check refuses it."
    b = a.replace("commit", "branch")
    assert nb(a) == nb(b)
    root = tree(tmp_path, [(b, dict(cls="practice", enforced_by="ci:dco")), (a, dict(cls="practice", enforced_by="ci:dco"))])
    sec = section(root, [run("x", IN_W43)])
    assert [x["entry"] for x in sec["entries"]] == [f"{BUILD}#R1", f"{BUILD}#R2"]


def test_entries_of_several_prompts_share_one_ranking_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(ENFORCED, dict(cls="practice", enforced_by="ci:dco"))])
    tree(root, [(QUIET, dict(cls="experience", source="#478"))], path=TESTER)
    sec = section(root, [run("a", IN_W43)], {478: closed(478)})
    assert [x["entry"] for x in sec["entries"]] == [f"{TESTER}#R1", f"{BUILD}#R1"]


def test_no_candidate_and_no_register_say_none_this_week_ac_168_8(tmp_path):  # AC-168.8
    sec = section(tree(tmp_path, [("Never reuse a branch, because it is stale.", dict(cls="practice"))]), [run("a", IN_W43)])
    assert sec["entries"] == [] and sec["weeks"] == WEEKS and sec["runs"] == 1
    assert retro_rules.render(sec).strip().splitlines() == ["## Rules to retire", "none this week"]
    empty = section(tmp_path / "nothing", [])
    assert empty["entries"] == [] and retro_rules.render(empty).strip().splitlines() == ["## Rules to retire", "none this week"]


def test_the_runs_of_the_window_are_counted_once_each_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(ENFORCED, dict(cls="practice", enforced_by="ci:dco"))])
    recs = [run("a", IN_W43), run("a", IN_W43), run("b", IN_W40), run("c", BEFORE_W40), run("d", AFTER_W43),
            run("e", "2026-10-25T23:59:59Z"), run("f", "2026-09-28T00:00:00Z")]
    assert section(root, recs)["runs"] == 4


def test_the_four_weeks_end_with_the_covered_week_ac_168_8(tmp_path):  # AC-168.8
    root = tree(tmp_path, [(ENFORCED, dict(cls="practice", enforced_by="ci:dco"))])
    assert section(root, [], week="2026-W43")["weeks"] == WEEKS
    assert section(root, [], week="2026-W02")["weeks"] == ["2025-W51", "2025-W52", "2026-W01", "2026-W02"]


# ---------------- AC-168.8 rendering ----------------

SECTION = {"weeks": WEEKS, "runs": 37, "entries": [
    {"rank": 1, "entry": "plugins/component/commands/build.md#R7", "class": "practice", "bytes": 142, "text": "Always sign off",
     "reason": "because the DCO check refuses it", "evidence": {"kind": "enforced", "by": "ci:dco", "failures": 3}},
    {"rank": 2, "entry": "plugins/svc/agents/tester.md#R4", "class": "experience", "bytes": 120, "text": "Never pipe it",
     "reason": "so that the decisions stay visible", "evidence": {"kind": "quiet", "issue": 478, "occurrences": 0, "runs": 37}}]}


def test_the_section_renders_entry_reason_and_evidence_ac_168_8(tmp_path):  # AC-168.8
    assert retro_rules.render(SECTION).strip().splitlines() == [
        "## Rules to retire",
        '1. **plugins/component/commands/build.md#R7** (practice, 142 bytes): "Always sign off"',
        "   Reason: because the DCO check refuses it",
        "   Evidence: enforced by `ci:dco`; 3 failure(s) of it in 2026-W43",
        '2. **plugins/svc/agents/tester.md#R4** (experience, 120 bytes): "Never pipe it"',
        "   Reason: so that the decisions stay visible",
        "   Evidence: #478 is closed; its cause occurred in 0 of 37 runs (2026-W40 to 2026-W43)"]


def test_the_report_stores_and_both_renderings_print_the_section_after_the_proposals_ac_168_8():  # AC-168.8
    report = build(rules_to_retire=SECTION)
    assert report["rules_to_retire"] == SECTION
    for render in (retro_report.render_private, retro_report.render_public):
        text = render(report, "## Proposals\n1. A proposal")
        assert text.index("## Proposals") < text.index("## Rules to retire") < text.index("## Phases"), text[:400]
        assert "plugins/svc/agents/tester.md#R4" in text and "Evidence: enforced by `ci:dco`" in text
    plain = build()
    assert "rules_to_retire" not in plain
    assert "## Rules to retire" not in retro_report.render_private(plain, "## Proposals\n1. A proposal")


def test_a_report_without_proposals_still_prints_the_section_ac_168_8():  # AC-168.8
    assert "## Rules to retire" in retro_report.render_text(build(rules_to_retire=SECTION))


# ---------------- AC-168.8 the retro run and the tracker ----------------

def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_retro_adds_the_section_and_changes_no_prompt_or_register_file_ac_168_8(world, tmp_path, monkeypatch, capsys):  # AC-168.8
    root = tree(tmp_path / "platform", [(ENFORCED, dict(cls="practice", enforced_by="ci:dco")),
                                        (QUIET, dict(cls="experience", source="#478"))])
    monkeypatch.setattr(core, "PLATFORM_ROOT", root)
    world.tracker.states[478] = closed(478)
    before = snapshot(root)
    assert cplat.main(["platform", "retro", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    sec = report["rules_to_retire"]
    assert sec["weeks"] == WEEKS and sec["runs"] == 14                        # the 15 fixture records, minus the one of the next week
    assert [x["entry"] for x in sec["entries"]] == [f"{BUILD}#R2", f"{BUILD}#R1"]
    assert sec["entries"][0]["evidence"] == {"kind": "quiet", "issue": 478, "occurrences": 0, "runs": 14}
    assert sec["entries"][1]["evidence"] == {"kind": "enforced", "by": "ci:dco", "failures": 0}
    assert snapshot(root) == before and world.tracker.writes == []


def test_the_retro_text_report_and_the_files_it_writes_carry_the_section_ac_168_8(world, tmp_path, monkeypatch, capsys):  # AC-168.8
    root = tree(tmp_path / "platform", [(ENFORCED, dict(cls="practice", enforced_by="ci:dco"))])
    monkeypatch.setattr(core, "PLATFORM_ROOT", root)
    out_dir = tmp_path / "retro"
    assert cplat.main(["platform", "retro", "--out", str(out_dir)]) == 0
    text = capsys.readouterr().out
    assert "## Rules to retire" in text and f"{BUILD}#R1" in text
    assert "## Rules to retire" in (out_dir / "report.md").read_text()
    assert json.loads((out_dir / "report.json").read_text())["rules_to_retire"]["entries"][0]["entry"] == f"{BUILD}#R1"


class FakeGh:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, args, *, input=None, timeout=30.0):
        self.calls.append(list(args))
        line = " ".join(args)
        for fragment, reply in self.replies.items():
            if fragment in line:
                return reply
        return 1, "", "HTTP 404: Not Found"


def test_the_tracker_reads_issue_states_and_leaves_out_unreadable_ones_ac_168_8(monkeypatch):  # AC-168.8
    assert hasattr(retro_github.RetroTracker, "issue_states")
    fake = FakeGh({"issues/478": (0, json.dumps({"number": 478, "state": "closed", "body": "Signature: platform:0123456789abcdef"}), ""),
                   "issues/500": (0, json.dumps({"number": 500, "state": "open", "body": None}), ""),
                   "issues/501": (127, "", "gh is missing")})
    monkeypatch.setattr(retro_github, "gh", fake)
    got = retro_github.tracker().issue_states("ika100/sdlc-foundry", [478, 500, 501, 999])
    assert set(got) == {478, 500}
    assert got[478]["state"] == "closed" and "platform:0123456789abcdef" in got[478]["body"]
    assert got[500]["state"] == "open"
    assert any(c[:2] == ["api", "repos/ika100/sdlc-foundry/issues/478"] for c in fake.calls)
