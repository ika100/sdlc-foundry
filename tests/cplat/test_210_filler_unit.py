"""Spec 210 module-level tests of the filler candidates (AC-210.9): the split, the retro parsing, the retro-draft hold."""
from types import SimpleNamespace

import dispatch_backlog
import dispatch_filler
import dispatch_ready
from dispatch_backlog import Candidate, Snapshot

BODY = "## Proposed specs\n\n1. **Alpha thing** (P1)\n   `/component:spec add alpha`\n2. **Beta** (P2)\n   `/component:spec add beta`\n\n## Other\n"


def _policy(filler_only=("label:enhancement",)):
    return SimpleNamespace(values={"budget": {"mode": "plan", "plan": {"filler_only": list(filler_only)}}})


def _verdict(labels):
    c = Candidate(key="issue-1", item="#1", kind="fix", title="t", labels=labels, created="", text="", number=1)
    return dispatch_ready.Verdict(c, "ready", labels=labels)


def test_split_holds_filler_only_outside_the_window_ac_210_9():  # AC-210.9
    plain, nice = _verdict(["bug"]), _verdict(["enhancement"])
    assert dispatch_filler.split(_policy(), [plain, nice], False)[0] == [plain]
    _, filler, held = dispatch_filler.split(_policy(), [plain, nice], False)
    assert filler == [] and held[0].reason == "filler only" and held[0].detail is None
    regular, filler, held = dispatch_filler.split(_policy(), [plain, nice], True)
    assert regular == [plain] and filler == [nice] and held == []


def test_a_pinned_filler_only_candidate_is_regular_outside_the_window_issue_1110():
    nice = _verdict(["enhancement"])
    regular, filler, held = dispatch_filler.split(_policy(), [nice], False, ["issue-1"])
    assert regular == [nice] and filler == [] and held == []


def test_retro_proposals_are_parsed_and_a_missing_section_gives_none_ac_210_9():  # AC-210.9
    got = dispatch_filler.retro_proposals(BODY)
    assert [(p.rank, p.title, p.priority, p.request) for p in got] == [(1, "Alpha thing", "P1", "add alpha"), (2, "Beta", "P2", "add beta")]
    assert dispatch_filler.retro_proposals("## Weekly retro\n\nnothing") == []


def _snap(**kw):
    return Snapshot(read_at="2026-11-18T00:00:00", **kw)


def _draft_spec(tracks):
    rec = {"id": "9-x", "key": "spec-009", "title": "x", "status": "draft", "priority": "P2", "tracks": tracks, "created": "", "text": "",
           "plan": None}
    return dispatch_backlog._spec_candidate(rec)


def test_a_draft_spec_tracking_a_retro_issue_is_held_even_with_self_approval_ac_210_9():  # AC-210.9
    policy = SimpleNamespace(values={"gates": {"approve_specs": "self"}})
    snap = _snap(issues=[{"number": 90, "title": "Weekly retro 2026-W45", "labels": []}])
    [v] = dispatch_ready.judge([_draft_spec([90])], snap, {}, [], policy)
    assert (v.verdict, v.reason, v.detail) == ("held", "needs-approval", "a retro draft: approve it yourself")
    state = {"filler": {"drafted": {"retro-5-1": {"unit": "u", "branch": "feature/9-x", "pr": None}}}}
    [v] = dispatch_ready.judge([_draft_spec([5])], _snap(issues=[{"number": 5, "title": "other", "labels": []}]), state, [], policy)
    assert v.reason == "needs-approval" and v.detail == "a retro draft: approve it yourself"
