"""Spec 126 acceptance tests: the pure module `scripts/cplat/stopgate.py` (design.md "Contract", `stopgate.py`).

It decides who the Stop hook holds (AC-126.1 to AC-126.3), counts stops without progress (AC-126.4 to AC-126.6), builds the
no-progress reason and chooses the cause (AC-126.5, AC-126.7). Both gates and `cplat headless` call it (AC-126.8).
"""
import importlib
import json

import pytest


@pytest.fixture()
def sg(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)
    return importlib.import_module("stopgate")


def owned(sg, owner="A"):
    st = {"spec": "007-x", "phase": "build"}
    sg.claim(st, owner)
    return st


def mark(head="h1", phase="build"):
    return {"head": head, "phase": phase}


# ---------------- who owns a run (AC-126.2) ----------------

def test_ac_126_2_session_of_env_prefers_claude_code_then_cplat(sg, monkeypatch):  # AC-126.2
    assert sg.session_of_env() is None
    monkeypatch.setenv("CPLAT_SESSION_ID", " from-headless \n")
    assert sg.session_of_env() == "from-headless"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-claude")
    assert sg.session_of_env() == "from-claude"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "   ")
    assert sg.session_of_env() == "from-headless"
    monkeypatch.setenv("CPLAT_SESSION_ID", "")
    assert sg.session_of_env() is None


def test_ac_126_2_claim_sets_the_owner_and_resets_the_gate_bookkeeping(sg):  # AC-126.2
    st = {"spec": "007-x", "phase": "build", "stop_gate": {"head": "h", "phase": "build", "no_progress": 1}}
    sg.claim(st, "C")
    assert st["owner"] == "C" and st["stop_gate"] == {}
    sg.claim(st, None)                                   # no session id known: the key goes away, nobody is held
    assert "owner" not in st and st["stop_gate"] == {}


# ---------------- AC-126.1 / AC-126.3: who is held ----------------

def test_ac_126_1_a_session_that_is_not_the_owner_is_silent_and_changes_nothing(sg):  # AC-126.1
    st = owned(sg, "A")
    before = json.dumps(st, sort_keys=True)
    for session in ("B", None, ""):
        v = sg.check(st, session, mark())
        assert (v.action, v.no_progress) == ("silent", 0)
    assert json.dumps(st, sort_keys=True) == before


def test_ac_126_3_a_run_without_an_owner_only_gets_a_notice(sg):  # AC-126.3
    st = {"spec": "007-x", "phase": "build"}
    before = json.dumps(st, sort_keys=True)
    for session in ("A", None):
        v = sg.check(st, session, mark())
        assert (v.action, v.no_progress) == ("notice", 0)
    assert json.dumps(st, sort_keys=True) == before


# ---------------- AC-126.4 / AC-126.5: progress and the count ----------------

def test_ac_126_4_the_first_stop_after_a_start_counts_as_progress(sg):  # AC-126.4
    st = owned(sg)
    v = sg.check(st, "A", mark())
    assert (v.action, v.no_progress) == ("block", 0)
    assert st["stop_gate"] == {"head": "h1", "phase": "build", "no_progress": 0}


def test_ac_126_5_no_progress_counts_up_blocks_below_two_and_escalates_at_two(sg):  # AC-126.5
    st = owned(sg)
    assert sg.NO_PROGRESS_LIMIT == 2
    assert sg.check(st, "A", mark()).action == "block"
    v1 = sg.check(st, "A", mark())
    assert (v1.action, v1.no_progress) == ("block", 1) and st["stop_gate"]["no_progress"] == 1
    v2 = sg.check(st, "A", mark())
    assert (v2.action, v2.no_progress) == ("escalate", 2) and st["stop_gate"]["no_progress"] == 2


def test_ac_126_4_a_new_commit_resets_the_count_to_zero(sg):  # AC-126.4
    st = owned(sg)
    sg.check(st, "A", mark())
    assert sg.check(st, "A", mark()).no_progress == 1
    v = sg.check(st, "A", mark(head="h2"))
    assert (v.action, v.no_progress) == ("block", 0) and st["stop_gate"]["head"] == "h2"


def test_ac_126_4_a_phase_change_resets_the_count_to_zero(sg):  # AC-126.4
    st = owned(sg)
    sg.check(st, "A", mark())
    assert sg.check(st, "A", mark()).no_progress == 1
    v = sg.check(st, "A", mark(phase="pr"))
    assert (v.action, v.no_progress) == ("block", 0) and st["stop_gate"]["phase"] == "pr"


def test_ac_126_5_a_first_commit_after_no_head_is_progress(sg):  # AC-126.4 AC-126.5
    st = owned(sg)
    sg.check(st, "A", mark(head=None))
    assert sg.check(st, "A", mark(head=None)).no_progress == 1
    assert sg.check(st, "A", mark(head="h1")).no_progress == 0


def test_ac_126_6_a_session_that_progresses_at_every_stop_is_never_escalated(sg):  # AC-126.6
    st = owned(sg)
    for i in range(50):
        v = sg.check(st, "A", mark(head=f"h{i}"))
        assert (v.action, v.no_progress) == ("block", 0)


# ---------------- last message, excerpt, reason ----------------

def test_ac_126_5_the_last_message_comes_from_the_hook_input_first(sg, tmp_path):  # AC-126.5
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "from transcript"}]}}) + "\n")
    assert sg.last_message({"last_assistant_message": "from input", "transcript_path": str(t)}) == "from input"


def test_ac_126_5_the_last_message_falls_back_to_the_last_assistant_text_in_the_transcript(sg, tmp_path):  # AC-126.5
    t = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"role": "user", "content": "go"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "first thought"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "the real last words"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}},
    ]
    t.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert sg.last_message({"transcript_path": str(t)}) == "the real last words"


@pytest.mark.parametrize("hook", [{}, {"transcript_path": "/nonexistent/t.jsonl"}, {"transcript_path": None}])
def test_ac_126_5_a_missing_message_or_transcript_is_the_empty_string(sg, hook):  # AC-126.5
    assert sg.last_message(hook) == ""


def test_ac_126_5_a_broken_transcript_is_the_empty_string(sg, tmp_path):  # AC-126.5
    t = tmp_path / "t.jsonl"
    t.write_text("not json\n{\n")
    assert sg.last_message({"transcript_path": str(t)}) == ""


def test_ac_126_5_the_excerpt_is_redacted_collapsed_and_cut_to_200_characters(sg):  # AC-126.5
    assert sg.EXCERPT == 200
    token = "ghp_" + "a1B2c3D4e5" * 3
    out = sg.excerpt(f"  I tried   with\n\n{token}   and failed " + "x " * 300)
    assert "ghp_" not in out and "<github-token>" in out
    assert "  " not in out and "\n" not in out and out == out.strip()
    assert len(out) == 200
    assert sg.excerpt("short\nmessage") == "short message"
    assert sg.excerpt("   ") == ""


def test_ac_126_5_the_reason_names_the_phase_and_ends_with_the_excerpt(sg):  # AC-126.5
    base = "no progress: 2 stops in phase build without a new commit or phase change"
    assert sg.no_progress_reason("build", "") == base
    assert sg.no_progress_reason("build", "  ") == base
    assert sg.no_progress_reason("land", "I am stuck\nhere") == base.replace("build", "land") + "; last message: I am stuck here"
    long = sg.no_progress_reason("build", "y " * 400)
    assert len(long) - len(base + "; last message: ") == 200
    assert "gave up" not in long


# ---------------- AC-126.7: the cause ----------------

@pytest.mark.parametrize("message, code_red, want", [
    ("I am waiting for approval to push the branch", False, "environment"),    # AC-088.16 rule first, even when code is red
    ("I am waiting for approval to push the branch", True, "environment"),
    ("the acceptance test contradicts AC-012.3", True, "decision"),
    ("left for the user to review", True, "decision"),
    ("I could not get further", True, "code"),
    ("", True, "code"),
    ("I could not get further", False, "decision"),
    ("", False, "decision"),
])
def test_ac_126_7_the_cause_is_the_rule_then_code_then_decision(sg, message, code_red, want):  # AC-126.7
    assert sg.cause(message, code_red) == want


@pytest.mark.parametrize("message", ["", "x", "waiting for approval to commit", "tests fail", "platform bug in cplat"])
@pytest.mark.parametrize("code_red", [True, False])
def test_ac_126_7_the_cause_is_never_platform_and_never_unknown(sg, message, code_red):  # AC-126.7
    assert sg.cause(message, code_red) in {"code", "decision", "environment"}
