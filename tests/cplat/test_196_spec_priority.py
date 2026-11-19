"""Spec 196 acceptance tests: `cplat spec new` resolves and records a new spec's priority with its provenance, `cplat spec priority`
proposes or changes it, `show` and `list --json` report it, and an unattended run only proposes (AC-196.6, AC-196.10, AC-196.11,
AC-196.12). Git worlds come from support_183; `gh` (the labels of tracked issues) is a fake on PATH and in `claim`."""
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

import spec
import waiting
from support_183 import world

FALLBACK = "P1: normal bug or feature"
ID = "176-fresh-feature"

GH = """#!{py}
import json, os, sys
a = sys.argv[1:]
cfg = json.load(open(os.environ["FAKE_LABELS"]))
if a[:2] == ["issue", "view"] and "labels" in a:
    if a[2] in cfg.get("fail", []):
        sys.stderr.write("boom\\n")
        sys.exit(1)
    print(json.dumps({{"labels": [{{"name": x}} for x in cfg.get("labels", {{}}).get(a[2], [])]}}))
    sys.exit(0)
print("[]")
"""


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    monkeypatch.delenv("CPLAT_HEADLESS", raising=False)
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    r = world(tmp_path, main_specs=("175-base",))
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(waiting.with_prelude(GH.format(py=sys.executable)))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LABELS", str(tmp_path / "labels.json"))
    labels(tmp_path, monkeypatch)
    return r


def labels(tmp_path, monkeypatch, by_issue=None, fail=()):
    """The labels `gh issue view N --json labels` answers, on PATH and through `claim.gh`."""
    cfg = {"labels": {str(k): v for k, v in (by_issue or {}).items()}, "fail": [str(n) for n in fail]}
    (tmp_path / "labels.json").write_text(json.dumps(cfg))
    import claim

    def fake(args, *, cwd):
        if args[:2] == ["issue", "view"] and "labels" in args:
            if args[2] in cfg["fail"]:
                return 1, ""
            return 0, json.dumps({"labels": [{"name": x} for x in cfg["labels"].get(args[2], [])]})
        return (0, '{"state": "CLOSED"}') if args[:2] == ["issue", "view"] else (0, "")

    monkeypatch.setattr(claim, "gh", fake)


def run(repo, capsys, *argv):
    capsys.readouterr()
    rc = spec.main(["--repo", str(repo), *argv])
    out = capsys.readouterr()
    return rc, out.out, out.err


def new(repo, capsys, *args, title="Fresh feature"):
    rc, out, err = run(repo, capsys, "new", "--no-shape", *args, title)
    assert rc == 0, err
    return out.strip().splitlines()[0].split("/")[2], err


def text_of(repo, sid):
    return (repo / "docs" / "specs" / sid / "spec.md").read_text()


def front(repo, sid):
    return dict(re.findall(r"^(\w+): (.*)$", text_of(repo, sid).split("---")[1], re.M))


def changelog(repo, sid):
    """The Changelog entries without their dates."""
    body = text_of(repo, sid).split("## Changelog", 1)[1]
    return [re.sub(r"^- \d{4}-\d{2}-\d{2} ", "", l) for l in body.splitlines() if l.startswith("- ")]


def priority_lines(repo, sid):
    return [l for l in changelog(repo, sid) if l.startswith("priority ")]


def state(repo, sid):
    import spec_priority
    return spec_priority.state(spec.read(repo / "docs" / "specs" / sid))


def shown(repo, capsys, sid, *extra):
    rc, out, err = run(repo, capsys, "show", sid, *extra)
    assert rc == 0, err
    return out


def append_changelog(repo, sid, line):
    path = repo / "docs" / "specs" / sid / "spec.md"
    path.write_text(path.read_text().rstrip("\n") + f"\n- 2026-11-17 {line}\n")


# ---------------- AC-196.10: a new spec gets a proposed priority ----------------

def test_a_new_spec_with_no_priority_given_gets_the_fallback_proposal_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    assert front(repo, sid)["priority"] == "P1"
    assert changelog(repo, sid)[:2] == ["created", f"priority P1 proposed: {FALLBACK}"]
    assert state(repo, sid) == {"state": "proposed", "reason": FALLBACK, "decide": False}


def test_show_prints_the_priority_line_after_the_counts_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    lines = shown(repo, capsys, sid).splitlines()
    assert f"Priority: P1 ({FALLBACK})" in lines
    assert lines.index(f"Priority: P1 ({FALLBACK})") > 0


def test_show_and_list_json_carry_priority_state_and_reason_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    one = json.loads(shown(repo, capsys, sid, "--json"))
    assert (one["priority_state"], one["priority_reason"]) == ("proposed", FALLBACK)
    for extra in ((), ("--detail",)):
        rc, out, _ = run(repo, capsys, "list", "--all", "--json", *extra)
        table = {r["id"]: r for r in json.loads(out)}
        assert (table[sid]["priority_state"], table[sid]["priority_reason"]) == ("proposed", FALLBACK)
        assert (table["175-base"]["priority_state"], table["175-base"]["priority_reason"]) == ("unset", "")


def test_a_spec_without_a_priority_line_shows_no_priority_line_ac_196_10(repo, capsys):  # AC-196.10
    assert not [l for l in shown(repo, capsys, "175-base").splitlines() if l.startswith("Priority:")]
    assert json.loads(shown(repo, capsys, "175-base", "--json"))["priority_state"] == "unset"


def test_a_broken_spec_is_listed_with_state_unset_ac_196_10(repo, capsys):  # AC-196.10
    broken = repo / "docs" / "specs" / "180-broken"
    broken.mkdir()
    (broken / "spec.md").write_text("no front matter at all\n")
    rc, out, _ = run(repo, capsys, "list", "--all", "--json")
    row = {r["id"]: r for r in json.loads(out)}["180-broken"]
    assert (row["priority_state"], row["priority_reason"]) == ("unset", "")


def test_the_skeleton_holds_the_levels_comment_directly_above_the_changelog_ac_196_10(repo, capsys):  # AC-196.10
    import priority
    sid, _ = new(repo, capsys)
    body = text_of(repo, sid)
    above = body.split("## Changelog", 1)[0].rstrip().splitlines()[-1]
    assert above == priority.skeleton_comment().strip()


def test_the_product_manager_proposal_replaces_the_fallback_line_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    rc, out, err = run(repo, capsys, "priority", sid, "P0", "--propose", "P0: data loss")
    assert rc == 0, err
    assert out.strip() == f"{sid}: priority P0 proposed (P0: data loss)"
    assert front(repo, sid)["priority"] == "P0"
    assert priority_lines(repo, sid) == ["priority P0 proposed: P0: data loss"]
    assert state(repo, sid)["state"] == "proposed" and state(repo, sid)["reason"] == "P0: data loss"
    rc, out, _ = run(repo, capsys, "priority", sid, "P2", "--propose", "P2: easy workaround")     # an earlier proposal is replaced again
    assert rc == 0 and priority_lines(repo, sid) == ["priority P2 proposed: P2: easy workaround"] and front(repo, sid)["priority"] == "P2"


def test_a_proposal_reason_that_names_no_definition_is_refused_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    before = text_of(repo, sid)
    rc, out, err = run(repo, capsys, "priority", sid, "P0", "--propose", "it is important")
    assert rc == 1 and "the reason must be" in err + out
    assert text_of(repo, sid) == before


def test_a_user_change_sets_the_priority_and_records_changed_by_you_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    rc, out, err = run(repo, capsys, "priority", sid, "P0")
    assert rc == 0, err
    assert out.strip() == f"{sid}: priority P0 (changed by you)"
    assert front(repo, sid)["priority"] == "P0"
    assert priority_lines(repo, sid)[-1] == "priority P0 changed by you"
    assert state(repo, sid) == {"state": "changed", "reason": "changed by you", "decide": False}
    assert f"Priority: P0 (changed by you)" in shown(repo, capsys, sid).splitlines()


def test_the_same_level_after_a_user_change_writes_nothing_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    run(repo, capsys, "priority", sid, "P0")
    before = text_of(repo, sid)
    rc, out, _ = run(repo, capsys, "priority", sid, "P0")
    assert rc == 0 and out.strip() == f"{sid}: priority already P0" and text_of(repo, sid) == before


def test_confirming_the_proposed_level_by_a_change_records_that_the_user_chose_it_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    rc, _, _ = run(repo, capsys, "priority", sid, "P1")
    assert rc == 0 and priority_lines(repo, sid)[-1] == "priority P1 changed by you"


def test_a_proposal_never_replaces_a_choice_of_the_user_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    run(repo, capsys, "priority", sid, "P2")
    before = text_of(repo, sid)
    rc, out, _ = run(repo, capsys, "priority", sid, "P0", "--propose", "P0: data loss")
    assert rc == 0 and text_of(repo, sid) == before
    assert out.strip() == f"{sid}: priority kept P2 (changed by you); a proposal replaces only a proposal"


def test_priority_json_reports_the_state_and_whether_it_wrote_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    rc, out, _ = run(repo, capsys, "priority", sid, "P0", "--json")
    assert rc == 0
    assert json.loads(out) == {"id": sid, "priority": "P0", "priority_state": "changed", "priority_reason": "changed by you", "written": True}


def test_a_change_of_a_done_or_superseded_spec_is_refused_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    path = repo / "docs" / "specs" / sid / "spec.md"
    path.write_text(path.read_text().replace("status: draft", "status: superseded"))
    before = text_of(repo, sid)
    rc, out, err = run(repo, capsys, "priority", sid, "P0")
    assert rc == 1 and "ERROR:" in err + out and text_of(repo, sid) == before


def test_approving_the_spec_approves_the_shown_priority_ac_196_10(repo, capsys):  # AC-196.10
    sid, _ = new(repo, capsys)
    append_changelog(repo, sid, "approved")
    assert state(repo, sid) == {"state": "approved", "reason": FALLBACK, "decide": False}
    assert json.loads(shown(repo, capsys, sid, "--json"))["priority_state"] == "approved"


def test_an_approval_by_the_dispatcher_leaves_the_priority_a_proposal_ac_196_12(repo, capsys):  # AC-196.12
    sid, _ = new(repo, capsys)
    append_changelog(repo, sid, "approved by cplat dispatch")
    assert state(repo, sid)["state"] == "proposed"
    append_changelog(repo, sid, "approved by eike")
    assert state(repo, sid)["state"] == "approved"


# ---------------- AC-196.11: a priority that is already given is taken, none is proposed ----------------

@pytest.mark.parametrize("given", ["P0", "p0"])
def test_a_priority_passed_with_the_option_is_given_by_you_ac_196_11(repo, capsys, given):  # AC-196.11
    sid, _ = new(repo, capsys, "--priority", given)
    assert front(repo, sid)["priority"] == "P0"
    assert changelog(repo, sid) == ["created", "priority P0 given by you"]
    assert state(repo, sid) == {"state": "given", "reason": "given by you", "decide": False}
    assert "Priority: P0 (given by you)" in shown(repo, capsys, sid).splitlines()


def test_the_priority_option_is_limited_to_p0_p1_p2_ac_196_11(repo, capsys):  # AC-196.11
    with pytest.raises(SystemExit) as e:
        spec.main(["--repo", str(repo), "new", "--no-shape", "--priority", "P3", "Fresh feature"])
    assert e.value.code == 2
    assert not (repo / "docs" / "specs" / ID).exists()


def test_the_single_priority_label_of_the_tracked_issue_is_taken_ac_196_11(repo, capsys, tmp_path, monkeypatch):  # AC-196.11
    labels(tmp_path, monkeypatch, {5: ["triaged", "p2"]})
    sid, _ = new(repo, capsys, "--tracks", "5")
    assert front(repo, sid)["priority"] == "P2"
    assert changelog(repo, sid)[:2] == ["created", "priority P2 set on the issue #5"]
    assert state(repo, sid)["state"] == "issue" and state(repo, sid)["decide"] is False


def test_several_priority_labels_take_the_most_urgent_and_mark_the_decision_ac_196_11(repo, capsys, tmp_path, monkeypatch):  # AC-196.11
    labels(tmp_path, monkeypatch, {5: ["triaged", "p2", "p0"]})
    sid, _ = new(repo, capsys, "--tracks", "5")
    assert front(repo, sid)["priority"] == "P0"
    assert priority_lines(repo, sid) == ["priority P0 set on the issue #5 (p0, p2: decide)"]
    assert state(repo, sid)["state"] == "issue" and state(repo, sid)["decide"] is True


def test_a_tracked_issue_without_a_priority_label_gets_the_proposal_ac_196_11(repo, capsys, tmp_path, monkeypatch):  # AC-196.11
    labels(tmp_path, monkeypatch, {5: ["triaged", "bug"]})
    sid, _ = new(repo, capsys, "--tracks", "5")
    assert priority_lines(repo, sid) == [f"priority P1 proposed: {FALLBACK}"]


def test_a_priority_given_with_the_option_wins_over_the_label_of_the_issue_ac_196_11(repo, capsys, tmp_path, monkeypatch):  # AC-196.11
    labels(tmp_path, monkeypatch, {5: ["triaged", "p2"]})
    sid, _ = new(repo, capsys, "--priority", "P0", "--tracks", "5")
    assert front(repo, sid)["priority"] == "P0" and priority_lines(repo, sid) == ["priority P0 given by you"]


def test_a_label_that_cannot_be_read_counts_as_none_with_a_note_ac_196_11(repo, capsys, tmp_path, monkeypatch):  # AC-196.11
    labels(tmp_path, monkeypatch, {}, fail=(5,))
    sid, err = new(repo, capsys, "--tracks", "5")
    assert "note: could not read the labels of #5; the priority is a proposal" in err
    assert priority_lines(repo, sid) == [f"priority P1 proposed: {FALLBACK}"]


def test_a_spec_made_from_a_confirmed_feature_takes_the_confirmed_priority_ac_196_6(repo, capsys, tmp_path, monkeypatch):  # AC-196.6
    labels(tmp_path, monkeypatch, {5: ["triaged", "p0"]})      # the issue got its label from the confirmed priority in the same run
    sid, _ = new(repo, capsys, "--priority", "P0", "--tracks", "5")
    assert front(repo, sid)["priority"] == "P0" and front(repo, sid)["tracks"] == "[5]"
    assert priority_lines(repo, sid) == ["priority P0 given by you"]


# ---------------- AC-196.12 / unattended: only proposals ----------------

def test_an_unattended_new_spec_records_a_proposal_even_for_a_given_priority_ac_196_12(repo, capsys, monkeypatch):  # AC-196.12
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    sid, _ = new(repo, capsys, "--priority", "P0")
    assert front(repo, sid)["priority"] == "P0" and front(repo, sid)["status"] == "draft"
    assert priority_lines(repo, sid) == ["priority P0 proposed: P0: named in the request"]
    assert state(repo, sid)["state"] == "proposed"


def test_an_unattended_new_spec_with_no_priority_is_a_proposal_ac_196_12(repo, capsys, monkeypatch):  # AC-196.12
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    sid, _ = new(repo, capsys)
    assert priority_lines(repo, sid) == [f"priority P1 proposed: {FALLBACK}"]
    lines = "\n".join(changelog(repo, sid))
    assert "changed by you" not in lines and "given by you" not in lines
    assert front(repo, sid)["status"] == "draft"
    one = json.loads(shown(repo, capsys, sid, "--json"))
    assert (one["priority_state"], one["priority_reason"]) == ("proposed", FALLBACK)
    rc, out, _ = run(repo, capsys, "list", "--json")
    assert {r["id"]: r for r in json.loads(out)}[sid]["priority_state"] == "proposed"


def test_an_unattended_issue_label_is_a_proposal_too_ac_196_12(repo, capsys, tmp_path, monkeypatch):  # AC-196.12
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    labels(tmp_path, monkeypatch, {5: ["p2"]})
    sid, _ = new(repo, capsys, "--tracks", "5")
    assert priority_lines(repo, sid) == ["priority P2 proposed: P2: set on the issue #5"]
    labels(tmp_path, monkeypatch, {5: ["p2", "p1"]})
    sid, _ = new(repo, capsys, "--tracks", "5", title="Another feature")
    assert front(repo, sid)["priority"] == "P1" and priority_lines(repo, sid) == ["priority P1 proposed: P1: set on the issue #5"]


def test_an_unattended_run_may_propose_but_not_change_a_priority_ac_196_12(repo, capsys, monkeypatch):  # AC-196.12
    sid, _ = new(repo, capsys)
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    rc, out, err = run(repo, capsys, "priority", sid, "P0", "--propose", "P0: outage")
    assert rc == 0, err
    assert priority_lines(repo, sid) == ["priority P0 proposed: P0: outage"]
    before = text_of(repo, sid)
    rc, out, err = run(repo, capsys, "priority", sid, "P2")
    assert rc == 1 and "a priority change needs the user" in err + out and "run it in a Claude Code session" in err + out
    assert text_of(repo, sid) == before


# ---------------- the prompts name what cplat does (structure only: short names, no sentences) ----------------

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("plugin", ["component", "system"])
def test_the_spec_commands_propose_show_and_change_the_priority_through_cplat_ac_196_10(plugin):  # AC-196.10
    text = (ROOT / "plugins" / plugin / "commands" / "spec.md").read_text()
    assert "cplat spec priority" in text and "--propose" in text and "Priority:" in text and "--priority" in text


def test_the_product_manager_replies_with_a_priority_line_ac_196_10():  # AC-196.10
    assert "PRIORITY:" in (ROOT / "plugins" / "svc" / "agents" / "product-manager.md").read_text()


def test_an_amend_leaves_the_priority_and_its_changelog_line_untouched_ac_196_11(repo, capsys):  # AC-196.11
    sid, _ = new(repo, capsys, "--priority", "P2")
    run(repo, capsys, "priority", sid, "P0")
    lines, level, st = priority_lines(repo, sid), front(repo, sid)["priority"], state(repo, sid)
    # the cplat step of an amend: an approved spec goes back to draft; the spec itself is then edited
    path = repo / "docs" / "specs" / sid / "spec.md"
    path.write_text(path.read_text().replace("status: draft", "status: approved", 1))
    rc, _, err = run(repo, capsys, "set-status", sid, "draft", "--reason", "amend: reword")
    assert rc == 0, err
    assert front(repo, sid)["priority"] == level == "P0"
    assert priority_lines(repo, sid) == lines
    assert state(repo, sid) == st


@pytest.mark.parametrize("plugin", ["component", "system"])
def test_the_amend_path_of_the_spec_command_runs_no_priority_step_ac_196_11(plugin):  # AC-196.11
    # structure of the prompt: section C (--amend) must not propose or change a priority
    text = (ROOT / "plugins" / plugin / "commands" / "spec.md").read_text()
    section = re.search(r"^## C\. --amend.*?(?=^## )", text, re.M | re.S)
    assert section, "section C (--amend) not found"
    assert "spec priority" not in section.group(0)
