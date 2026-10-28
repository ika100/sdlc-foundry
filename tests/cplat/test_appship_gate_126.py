"""Spec 126 acceptance tests: the product Stop hook (`cplat system ship gate`, `appship_state.gate`) follows AC-126.1 to AC-126.7
in the same way as the component hook (AC-126.8).

The world (git gitops-app checkout, fake `gh`, `kubectl`, `devbox` on PATH) is the one of the spec 097 tests. Progress of a product
run is the gitops-app `HEAD` plus the run phase plus each repo's state: a run sits for hours in phase `repos` while its repo ships move.
"""
import json
import subprocess

import pytest

import appship_state
from test_appship_097 import SPEC, World, git, w  # noqa: F401  (fixtures, helpers)

FIRST = f"The product ship of {SPEC} is not finished (phase publish, stops without progress: 0/2)."


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)


def begin(w, monkeypatch, session="A"):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    return w.started()


def stop(w, session="A", message=None, **extra):
    hook = {"session_id": session, "cwd": str(w.gitops), **extra}
    if message is not None:
        hook["last_assistant_message"] = message
    return w.app("gate", stdin=json.dumps(hook))


def block(r):
    assert r.rc == 0
    ans = r.json
    assert ans["decision"] == "block", ans
    return ans["reason"].splitlines()[0]


# ---------------- AC-126.8 with AC-126.1 / AC-126.3 ----------------

def test_ac_126_8_another_session_stops_silently_and_the_state_file_is_untouched(w, monkeypatch):  # AC-126.8 AC-126.1
    begin(w, monkeypatch, "A")
    before = w.state_file.read_text()
    r = stop(w, "B")
    assert r.rc == 0 and r.out.strip() == ""
    assert w.state_file.read_text() == before


def test_ac_126_8_a_run_without_an_owner_gets_a_one_line_notice(w, monkeypatch):  # AC-126.8 AC-126.3
    w.started()                                          # no session env: no owner
    assert "owner" not in w.state()
    before = w.state_file.read_text()
    r = stop(w, "A")
    assert r.out.count("\n") == 1
    assert r.json == {"systemMessage": f"product ship {SPEC}: unfinished in phase publish, no session owns it; "
                                       f"resume it with /system:ship {SPEC}"}
    assert w.state_file.read_text() == before


# ---------------- AC-126.8 with AC-126.2 ----------------

def test_ac_126_8_start_stores_the_owner_and_a_resume_takes_it_over(w, monkeypatch):  # AC-126.8 AC-126.2
    begin(w, monkeypatch, "A")
    assert w.state()["owner"] == "A" and "blocks" not in w.state()
    assert block(stop(w, "A")) == FIRST
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "C")
    assert w.app("start", SPEC, "--context", "kind-shop").rc == 0
    assert w.state()["owner"] == "C"
    assert stop(w, "A").out.strip() == ""
    assert block(stop(w, "C")) == FIRST


def test_ac_126_8_status_shows_the_owning_session(w, monkeypatch):  # AC-126.8 AC-126.2
    begin(w, monkeypatch, "sess-9")
    out = w.app("status").out.splitlines()
    i = next(i for i, ln in enumerate(out) if ln.startswith(f"product ship {SPEC}: phase publish"))
    assert out[i + 1] == "  session: sess-9"
    assert json.loads(w.app("status", "--json").out)["owner"] == "sess-9"


def test_ac_126_8_status_without_an_owner_says_how_to_own_the_run(w):  # AC-126.8 AC-126.2
    w.started()
    assert f"  session: none (resume with /system:ship {SPEC} to own the run)" in w.app("status").out.splitlines()


# ---------------- AC-126.8 with AC-126.4 / AC-126.5 / AC-126.6 ----------------

def test_ac_126_8_the_count_goes_up_and_two_stops_without_progress_escalate(w, monkeypatch):  # AC-126.8 AC-126.5
    begin(w, monkeypatch)
    assert block(stop(w)) == FIRST
    assert "stops without progress: 1/2" in block(stop(w))
    r = stop(w, message="I do not know how to go on")
    st = w.state()
    why = st["escalated"]
    assert why == ("no progress: 2 stops in phase publish without a new commit or phase change; "
                   "last message: I do not know how to go on")
    assert r.out.count("\n") == 1 and "decision" not in r.json
    assert r.json["systemMessage"] == f"product ship {SPEC}: escalated ({why}); resume it with /system:ship {SPEC}"
    assert "gave up" not in why
    assert stop(w).out.strip() == ""                    # an escalated run holds nobody


def test_ac_126_8_a_commit_in_the_gitops_checkout_is_progress(w, monkeypatch):  # AC-126.8 AC-126.4
    begin(w, monkeypatch)
    stop(w)
    assert "1/2" in block(stop(w))
    (w.gitops / "note.txt").write_text("work")
    git(w.gitops, "add", "-A")
    git(w.gitops, "commit", "-qm", "work")
    assert "stops without progress: 0/2" in block(stop(w))


def test_ac_126_8_uncommitted_edits_are_not_progress(w, monkeypatch):  # AC-126.8 AC-126.5
    begin(w, monkeypatch)
    stop(w)
    (w.gitops / "note.txt").write_text("uncommitted")
    assert "1/2" in block(stop(w))


def test_ac_126_8_a_phase_change_is_progress(w, monkeypatch):  # AC-126.8 AC-126.4
    begin(w, monkeypatch)
    stop(w)
    assert "1/2" in block(stop(w))
    assert w.app("phase", "repos").rc == 0
    assert block(stop(w)) == f"The product ship of {SPEC} is not finished (phase repos, stops without progress: 0/2)."


def test_ac_126_8_a_repo_ship_that_moves_is_progress_inside_the_same_phase(w, monkeypatch):  # AC-126.8 AC-126.4
    begin(w, monkeypatch)
    w.app("phase", "repos")
    stop(w)
    assert "1/2" in block(stop(w))
    w.edit(lambda st: st["repos"]["shop-lib"].update(state="building"))
    assert "stops without progress: 0/2" in block(stop(w))
    assert "1/2" in block(stop(w))


def test_ac_126_8_a_session_that_progresses_every_stop_is_never_escalated(w, monkeypatch):  # AC-126.8 AC-126.6
    begin(w, monkeypatch)
    w.app("phase", "repos")
    for i in range(8):
        w.edit(lambda st, i=i: st["repos"]["shop-lib"].update(state="ready" if i % 2 else "building"))
        assert "stops without progress: 0/2" in block(stop(w))
    assert not w.state().get("escalated")


def test_ac_126_8_max_blocks_is_gone(w, monkeypatch):  # AC-126.8
    begin(w, monkeypatch)
    with pytest.raises(SystemExit):
        w.app("gate", "--max-blocks", "3", stdin="{}")
    with pytest.raises(TypeError):
        appship_state.gate(w.gitops, {"session_id": "A"}, 8)


# ---------------- AC-126.8 with AC-126.7 ----------------

def test_ac_126_8_a_matching_rule_gives_its_cause_recorded_as_given(w, monkeypatch):  # AC-126.8 AC-126.7
    begin(w, monkeypatch)
    stop(w)
    stop(w)
    stop(w, message="waiting for approval to push the branch")
    assert w.state()["cause"] == "environment"


def test_ac_126_8_without_a_rule_or_red_evidence_the_cause_is_a_decision(w, monkeypatch):  # AC-126.8 AC-126.7
    begin(w, monkeypatch)
    stop(w)
    stop(w)
    stop(w, message="stuck")
    assert w.state()["cause"] == "decision"              # never environment, platform or unknown


def test_ac_126_8_the_last_message_comes_from_the_transcript_when_the_input_lacks_it(w, monkeypatch, tmp_path):  # AC-126.8 AC-126.5
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "text", "text": "blocked on the plan"}]}}) + "\n")
    begin(w, monkeypatch)
    for _ in range(3):
        stop(w, transcript_path=str(t))
    assert w.state()["escalated"].endswith("; last message: blocked on the plan")
