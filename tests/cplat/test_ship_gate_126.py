"""Spec 126 acceptance tests: the component Stop hook (`cplat component ship gate`, `ship.gate`) as design.md "Contract" describes it.

AC-126.1 to AC-126.7: only the owning session is held, progress is a new commit or a phase change, two stops without progress
escalate with a reason and a cause chosen by fixed rules. The hook input is JSON with `session_id`, `cwd`, `transcript_path`
and `last_assistant_message`. `ship.gate(repo, hook_input, run_tests=True)` has no `max_blocks` any more; `--max-blocks` is gone.
"""
import io
import json
import subprocess

import pytest

import core
import ship
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import FakeGh, check, git, repo  # noqa: F401  (fixtures, helpers)

SPEC = "007-price-alerts"
BRANCH = f"feature/{SPEC}"
FIRST = f"The ship run of {SPEC} is not finished (phase build, stops without progress: 0/2)."


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)


def begin(repo, monkeypatch, session="A"):
    """Start (or resume) the run as `session`, like `cplat component ship start` inside that Claude session."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    return ship.start(repo, "7", True)


def stop(repo, session="A", message=None, run_tests=False, **extra):
    hook = {"session_id": session, "cwd": str(repo), **extra}
    if message is not None:
        hook["last_assistant_message"] = message
    return ship.gate(repo, hook, run_tests=run_tests)


def commit(repo, name="f.txt"):
    cur = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if cur != BRANCH:
        git(repo, "checkout", "-q", "-B", BRANCH)
    (repo / name).write_text(name + str(len(list(repo.iterdir()))))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"work {name}")


def state_text(repo):
    return ship.state_path(repo).read_text()


# ---------------- AC-126.1: a session that is not the owner ----------------

def test_ac_126_1_another_session_stops_without_being_blocked_and_nothing_changes(repo, monkeypatch):  # AC-126.1
    begin(repo, monkeypatch, "A")
    before = state_text(repo)
    assert stop(repo, "B") is None
    assert stop(repo, "B", message="a research question") is None
    assert state_text(repo) == before                    # no write at all: phase, counters and escalation unchanged


def test_ac_126_1_the_hook_prints_nothing_for_another_session(repo, monkeypatch, capsys):  # AC-126.1
    begin(repo, monkeypatch, "A")
    before = state_text(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "B", "cwd": str(repo), "stop_hook_active": False})))
    assert ship.main(["gate"]) == 0
    assert capsys.readouterr().out == ""
    assert state_text(repo) == before


def test_ac_126_1_a_session_without_an_id_is_not_held_either(repo, monkeypatch):  # AC-126.1
    begin(repo, monkeypatch, "A")
    before = state_text(repo)
    assert ship.gate(repo, {"cwd": str(repo)}, run_tests=False) is None
    assert state_text(repo) == before


# ---------------- AC-126.2: resume takes over ----------------

def test_ac_126_2_start_stores_the_session_as_owner(repo, monkeypatch):  # AC-126.2
    st = begin(repo, monkeypatch, "A")
    assert st["owner"] == "A" and ship.load_state(repo)["owner"] == "A"
    assert "blocks" not in ship.load_state(repo)


def test_ac_126_2_the_owner_comes_from_cplat_session_id_when_there_is_no_claude_session(repo, monkeypatch):  # AC-126.2
    monkeypatch.setenv("CPLAT_SESSION_ID", "from-headless")
    assert ship.start(repo, "7", True)["owner"] == "from-headless"


def test_ac_126_2_a_session_that_resumes_the_run_owns_it_from_then_on(repo, monkeypatch):  # AC-126.2
    begin(repo, monkeypatch, "A")
    assert stop(repo, "A")["decision"] == "block"
    st = begin(repo, monkeypatch, "C")
    assert st["owner"] == "C"
    assert stop(repo, "A") is None                      # A is no longer blocked
    ans = stop(repo, "C")
    assert ans["decision"] == "block" and ans["reason"].splitlines()[0] == FIRST   # first stop after a resume is progress


def test_ac_126_2_status_shows_the_owning_session(repo, monkeypatch, capsys):  # AC-126.2
    begin(repo, monkeypatch, "sess-123")
    assert ship.main(["--repo", str(repo), "status"]) == 0
    out = capsys.readouterr().out.splitlines()
    i = next(i for i, ln in enumerate(out) if ln.startswith(f"ship {SPEC}: phase build"))
    assert out[i + 1] == "  session: sess-123"
    assert ship.main(["--repo", str(repo), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["owner"] == "sess-123"


def test_ac_126_2_status_of_a_run_without_an_owner_says_how_to_own_it(repo, capsys):  # AC-126.2
    ship.start(repo, "7", True)                          # no session env: no owner
    assert "owner" not in ship.load_state(repo)
    assert ship.main(["--repo", str(repo), "status"]) == 0
    assert f"  session: none (resume with /component:ship {SPEC} to own the run)" in capsys.readouterr().out.splitlines()


# ---------------- AC-126.3: a run without an owner ----------------

def test_ac_126_3_a_run_without_an_owner_blocks_nobody_and_prints_one_line(repo, monkeypatch):  # AC-126.3
    ship.start(repo, "7", True)
    before = state_text(repo)
    for session in ("A", "B", None):
        ans = ship.gate(repo, {"session_id": session, "cwd": str(repo)} if session else {"cwd": str(repo)}, run_tests=False)
        assert set(ans) == {"systemMessage"}
        assert ans["systemMessage"] == (f"ship {SPEC}: unfinished in phase build, no session owns it; "
                                        f"resume it with /component:ship {SPEC}")
    assert state_text(repo) == before


def test_ac_126_3_the_cli_prints_a_single_json_object_for_an_ownerless_run(repo, capsys, monkeypatch):  # AC-126.3
    ship.start(repo, "7", True)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "A", "cwd": str(repo)})))
    assert ship.main(["gate"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "decision" not in json.loads(out)
    assert "no session owns it" in json.loads(out)["systemMessage"]


@pytest.mark.parametrize("how", ["no state", "done", "escalated"])
def test_ac_126_3_runs_that_are_over_print_nothing(repo, monkeypatch, how):  # AC-126.3
    if how != "no state":
        begin(repo, monkeypatch, "A")
        if how == "done":
            ship.set_phase(repo, "done")
        else:
            ship.escalate(repo, "merge conflict in alerts.go")
    assert stop(repo, "A") is None


# ---------------- AC-126.4 / AC-126.5: progress and the count ----------------

def test_ac_126_4_the_first_stop_of_the_owner_is_blocked_with_a_zero_count(repo, monkeypatch):  # AC-126.4
    begin(repo, monkeypatch)
    ans = stop(repo)
    assert ans["decision"] == "block"
    assert ans["reason"].splitlines()[0] == FIRST
    assert "Next: " in ans["reason"] and "cplat component ship escalate" in ans["reason"]
    assert ship.load_state(repo)["stop_gate"]["no_progress"] == 0
    assert "blocks" not in ship.load_state(repo)


def test_ac_126_5_a_stop_without_progress_counts_up_and_the_reason_shows_it(repo, monkeypatch):  # AC-126.5
    begin(repo, monkeypatch)
    stop(repo)
    ans = stop(repo)
    assert ans["decision"] == "block"
    assert "stops without progress: 1/2" in ans["reason"].splitlines()[0]
    assert ship.load_state(repo)["stop_gate"]["no_progress"] == 1


def test_ac_126_4_a_new_commit_on_the_feature_branch_is_progress(repo, monkeypatch):  # AC-126.4
    begin(repo, monkeypatch)
    commit(repo, "a.txt")
    stop(repo)
    assert "1/2" in stop(repo)["reason"].splitlines()[0]
    commit(repo, "b.txt")
    ans = stop(repo)
    assert ans["decision"] == "block" and "stops without progress: 0/2" in ans["reason"].splitlines()[0]
    assert ship.load_state(repo)["stop_gate"]["no_progress"] == 0


def test_ac_126_4_a_phase_change_is_progress(repo, monkeypatch):  # AC-126.4
    begin(repo, monkeypatch)
    stop(repo)
    assert "1/2" in stop(repo)["reason"].splitlines()[0]
    ship.set_phase(repo, "pr")
    ans = stop(repo)
    assert ans["decision"] == "block"
    assert ans["reason"].splitlines()[0] == f"The ship run of {SPEC} is not finished (phase pr, stops without progress: 0/2)."


def test_ac_126_5_uncommitted_edits_are_not_progress(repo, monkeypatch):  # AC-126.5
    begin(repo, monkeypatch)
    commit(repo, "a.txt")
    stop(repo)
    (repo / "dirty.txt").write_text("edit")
    git(repo, "add", "dirty.txt")                       # even staged, it is not a commit
    assert "1/2" in stop(repo)["reason"].splitlines()[0]


def test_ac_126_5_the_second_stop_without_progress_lets_the_session_go_and_escalates(repo, monkeypatch):  # AC-126.5
    begin(repo, monkeypatch)
    stop(repo)
    stop(repo)
    ans = stop(repo, message="I am not sure how to continue")
    assert "decision" not in ans and set(ans) == {"systemMessage"}
    st = ship.load_state(repo)
    why = st["escalated"]
    assert why.startswith("no progress: 2 stops in phase build without a new commit or phase change; last message: I am not sure")
    assert ans["systemMessage"] == f"ship {SPEC}: escalated ({why}); resume it with /component:ship {SPEC}"
    assert "gave up" not in why
    assert stop(repo) is None                           # an escalated run holds nobody


def test_ac_126_5_the_last_message_is_cut_to_200_characters_and_redacted(repo, monkeypatch):  # AC-126.5
    begin(repo, monkeypatch)
    stop(repo)
    stop(repo)
    token = "ghp_" + "a1B2c3D4e5" * 3
    stop(repo, message=f"token {token} " + "word " * 100)
    why = ship.load_state(repo)["escalated"]
    head, _, tail = why.partition("; last message: ")
    assert head == "no progress: 2 stops in phase build without a new commit or phase change"
    assert len(tail) <= 200 and "ghp_" not in tail and "<github-token>" in tail


def test_ac_126_5_the_last_message_is_read_from_the_transcript_when_the_hook_input_lacks_it(repo, monkeypatch, tmp_path):  # AC-126.5
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "text", "text": "stuck on the migration"}]}}) + "\n")
    begin(repo, monkeypatch)
    stop(repo, transcript_path=str(t))
    stop(repo, transcript_path=str(t))
    stop(repo, transcript_path=str(t))
    assert ship.load_state(repo)["escalated"].endswith("; last message: stuck on the migration")


def test_ac_126_5_an_escalation_without_a_message_has_no_excerpt(repo, monkeypatch):  # AC-126.5
    begin(repo, monkeypatch)
    for _ in range(3):
        stop(repo)
    assert ship.load_state(repo)["escalated"] == "no progress: 2 stops in phase build without a new commit or phase change"


def test_ac_126_5_the_hook_prints_one_json_object_when_it_escalates(repo, monkeypatch, capsys):  # AC-126.5
    begin(repo, monkeypatch)
    for i in range(3):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "A", "cwd": str(repo), "last_assistant_message": "stuck"})))
        assert ship.main(["gate"]) == 0
        out = capsys.readouterr().out
        assert out.count("\n") == 1                      # nothing else on stdout, also while escalating
        assert json.loads(out)
    assert "no progress" in ship.load_state(repo)["escalated"]


def test_ac_126_5_max_blocks_is_gone(repo, monkeypatch):  # AC-126.5
    begin(repo, monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    monkeypatch.setattr(ship, "build_status", lambda *a, **k: [])
    with pytest.raises(SystemExit):
        ship.main(["gate", "--max-blocks", "3"])
    with pytest.raises(TypeError):
        ship.gate(repo, {"session_id": "A"}, 8, run_tests=False)


# ---------------- AC-126.6: progress is never escalated by count ----------------

def test_ac_126_6_a_session_that_progresses_at_every_stop_is_never_escalated(repo, monkeypatch):  # AC-126.6
    begin(repo, monkeypatch)
    for i in range(12):
        commit(repo, f"w{i}.txt")
        ans = stop(repo)
        assert ans["decision"] == "block" and "stops without progress: 0/2" in ans["reason"].splitlines()[0]
    assert "escalated" not in ship.load_state(repo)


# ---------------- AC-126.7: the cause ----------------

def esc_record(store):
    return stored(store)[-1]["escalation"]


def three_stops(repo, message, run_tests=False):
    for m in (None, None, message):
        stop(repo, message=m, run_tests=run_tests)
    return ship.load_state(repo)


def test_ac_126_7_a_matching_rule_gives_its_cause_recorded_as_given(repo, monkeypatch, store):  # AC-126.7
    begin(repo, monkeypatch)
    st = three_stops(repo, "waiting for approval to push the branch")
    assert st["cause"] == "environment"
    esc = esc_record(store)
    assert (esc["cause"], esc["cause_source"]) == ("environment", "given")


def test_ac_126_7_a_rule_for_a_decision_wins_over_red_tests(repo, monkeypatch):  # AC-126.7
    begin(repo, monkeypatch)
    st = three_stops(repo, "the acceptance test contradicts AC-007.1", run_tests=True)
    assert st["cause"] == "decision"


def test_ac_126_7_criteria_without_a_test_in_build_are_code(repo, monkeypatch, store):  # AC-126.7
    begin(repo, monkeypatch)                            # the fixture's criteria have no test yet
    st = three_stops(repo, "I could not get further", run_tests=True)
    assert st["cause"] == "code"
    esc = esc_record(store)
    assert (esc["cause"], esc["cause_source"]) == ("code", "given")


def test_ac_126_7_nothing_red_in_build_is_a_decision(repo, monkeypatch):  # AC-126.7
    begin(repo, monkeypatch)
    st = three_stops(repo, "I could not get further", run_tests=False)   # run_tests False: the evidence is not red
    assert st["cause"] == "decision"


def test_ac_126_7_other_phases_without_red_evidence_are_a_decision(repo, monkeypatch, store):  # AC-126.7
    begin(repo, monkeypatch)
    ship.set_phase(repo, "pr")
    st = three_stops(repo, "unsure", run_tests=True)
    assert st["cause"] == "decision"
    esc = esc_record(store)
    assert (esc["cause"], esc["cause_source"]) == ("decision", "given")


@pytest.fixture()
def landing(repo, monkeypatch):
    """A run in phase land with an open PR; `gh` answers `pr checks` from the fake."""
    fake = FakeGh()
    monkeypatch.setattr(ship, "gh", fake)
    begin(repo, monkeypatch)
    git(repo, "checkout", "-q", "-b", BRANCH)
    st = ship.load_state(repo)
    st.update(phase="land", pr="https://github.com/acme/shop-api/pull/7")
    ship.save_state(repo, st)
    return fake


@pytest.mark.parametrize("phase", ["land", "deploy"])
def test_ac_126_7_a_red_required_check_in_land_or_deploy_is_code(repo, monkeypatch, landing, phase):  # AC-126.7
    landing.checks = [[check("test", "fail"), check("quality", "pass")]]
    st = ship.load_state(repo)
    st["phase"] = phase
    ship.save_state(repo, st)
    result = three_stops(repo, "the merge is stuck")
    assert result["cause"] == "code"
    assert any(c[:3] == ["pr", "checks", "https://github.com/acme/shop-api/pull/7"] and "--required" in c for c in landing.calls)


def test_ac_126_7_a_cancelled_required_check_is_code_too(repo, monkeypatch, landing):  # AC-126.7
    landing.checks = [[check("test", "cancel")]]
    assert three_stops(repo, "x")["cause"] == "code"


def test_ac_126_7_green_checks_in_land_are_a_decision(repo, monkeypatch, landing):  # AC-126.7
    landing.checks = [[check("test", "pass"), check("quality", "pass")]]
    assert three_stops(repo, "x")["cause"] == "decision"


def test_ac_126_7_when_gh_fails_the_evidence_is_not_red(repo, monkeypatch, landing):  # AC-126.7
    monkeypatch.setattr(ship, "gh", lambda args, *, cwd, check=True: "")
    assert three_stops(repo, "x")["cause"] == "decision"


@pytest.mark.parametrize("message", ["", "unsure", "waiting for approval to commit", "cplat is broken, platform bug"])
@pytest.mark.parametrize("run_tests", [True, False])
def test_ac_126_7_the_cause_is_never_platform_and_never_unknown(repo, monkeypatch, message, run_tests):  # AC-126.7
    begin(repo, monkeypatch)
    st = ship.load_state(repo)
    assert ship.no_progress_cause(repo, st, message, run_tests=run_tests) in {"code", "decision", "environment"}


def test_ac_126_7_no_progress_cause_combines_the_evidence_with_the_rules(repo, monkeypatch):  # AC-126.7
    begin(repo, monkeypatch)
    st = ship.load_state(repo)
    assert ship.no_progress_cause(repo, st, "waiting for approval to push the branch", run_tests=True) == "environment"
    assert ship.no_progress_cause(repo, st, "stuck", run_tests=True) == "code"
    assert ship.no_progress_cause(repo, st, "stuck", run_tests=False) == "decision"
