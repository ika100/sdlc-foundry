"""Spec 200 acceptance tests: an interactive `ship start --detach` hands the run to its own headless process (AC-200.1, AC-200.2,
the start side of AC-200.4 and AC-200.5).

Seams: the spec 067 `repo` fixture (spec 007 approved, valid plan), `cplat.main` as the CLI entry, and `ship200_support.Procs`
(fake detached process + liveness, see there). Nothing starts a real `cplat headless` or `claude`.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import runs
import ship
from ship200_support import BRANCH, SESSION_VARS, SPEC, WAIT_COMMAND, cli, detach, handoff_file, headless_line, interactive, procs  # noqa: F401
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import repo  # noqa: F401  (fixture)
from test_spec import make


def state(repo):
    return ship.load_state(repo)


def ledgers():
    return [json.loads(p.read_text()) for p in (runs.state_dir() / "budgets").glob("*.json")]


# ---------------- AC-200.1: the hand-off ----------------

def test_detach_starts_the_headless_ship_as_its_own_process_ac_200_1(repo, procs, monkeypatch, capsys, tmp_path):  # AC-200.1
    p = procs()
    interactive(monkeypatch)
    for name in ("CPLAT_SYSTEM_DIR", "CPLAT_SHIP_ANSWER", "CPLAT_SHIP_ANSWER_FROM"):    # variables of other sessions never leak in
        monkeypatch.setenv(name, "leak")
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    (spawned,) = p.spawned
    argv = spawned["argv"]
    assert argv[0] == sys.executable and argv[2] == "headless" and argv[-1] == f"/component:ship {SPEC}"
    assert Path(spawned["cwd"]).resolve() == Path(repo).resolve()
    kw = spawned["kw"]
    assert kw["stdin"] == subprocess.DEVNULL and kw["start_new_session"] is True      # its own session: it outlives this one
    env = spawned["env"]
    assert not [v for v in SESSION_VARS if v in env]
    st = state(repo)
    assert env["CPLAT_RUN_PARENT"] == st["run_id"]                                      # a child run of this session's ship run
    h = st["headless"]
    assert h["pid"] == spawned["pid"] and h["starts"] == 1 and h["run_id"] == st["run_id"] and h["started"]
    assert h["log"].endswith("-ship.log") and str(tmp_path / "cache") in h["log"]       # the repo's headless log folder (A3)
    assert headless_line(out) == f"headless: pid {h['pid']}, log {h['log']}"
    assert f"next: {WAIT_COMMAND}" in out.splitlines()


def test_detach_passes_no_merge_and_full_through_ac_200_1(repo, procs, monkeypatch, capsys):  # AC-200.1
    p = procs()
    interactive(monkeypatch)
    rc, out, err = detach(capsys, repo, "--no-merge", "--full")
    assert rc == 0, out + err
    assert p.last["argv"][-1] == f"/component:ship {SPEC} --no-merge --full"
    st = state(repo)
    assert st["merge"] is False and st["headless"]["flags"] == ["--no-merge", "--full"]


def test_detach_counts_no_invocation_for_the_interactive_session_ac_200_1(repo, procs, monkeypatch, capsys):  # AC-200.1
    procs()
    interactive(monkeypatch)
    assert detach(capsys, repo)[0] == 0
    (ledger,) = ledgers()
    assert ledger["used"]["invocations"] == 0       # the headless sessions use the invocations as they would by hand


def _refuse_unapproved(repo, monkeypatch):
    make(repo, status="draft")


def _refuse_token(repo, monkeypatch):
    (repo / ".platform-app.yml").write_text("gitops_apps:\n  - acme/shop-gitops\n")
    monkeypatch.setattr(ship, "gh", lambda args, *, cwd, check=True: "[]")


def _refuse_claimed(repo, monkeypatch):
    """Spec 007 tracks issue #42, which another branch has claimed."""
    import claim
    issue = {"state": "OPEN", "labels": [{"name": claim.LABEL}],
             "comments": [{"body": f"{claim.MARK}\nClaimed for branch `feature/other-work`."}]}
    monkeypatch.setattr(claim, "gh", lambda args, *, cwd: (0, json.dumps(issue)) if args[:2] == ["issue", "view"] else (0, ""))


@pytest.mark.parametrize("setup", [_refuse_unapproved, _refuse_token, _refuse_claimed],
                         ids=["unapproved-spec", "missing-gitops-token", "claimed-issue"])
def test_a_refusal_starts_nothing_and_prints_the_same_hint_ac_200_1(repo, procs, monkeypatch, capsys, setup):  # AC-200.1
    p = procs()
    interactive(monkeypatch)
    setup(repo, monkeypatch)
    plain = cli(capsys, repo, "start", "7")
    assert plain[0] == 1 and plain[2].startswith("ERROR:") and "fix:" in plain[2]
    rc, out, err = detach(capsys, repo)
    assert (rc, err) == (plain[0], plain[2])        # the same message and hint as without --detach
    assert p.spawned == [] and "headless:" not in out
    assert state(repo) is None


def test_a_process_that_cannot_start_is_an_error_and_leaves_no_headless_entry_ac_200_1(repo, procs, monkeypatch, capsys):  # AC-200.1
    p = procs()
    interactive(monkeypatch)
    p.fail = "no such file: cplat.py"
    rc, out, err = detach(capsys, repo)
    assert rc == 1 and "ERROR: cannot start cplat headless: no such file: cplat.py" in err
    assert "headless" not in (state(repo) or {})


# ---------------- AC-200.2: one process per run; a headless session never hands off ----------------

def test_a_live_process_is_reused_and_no_second_one_starts_ac_200_2(repo, procs, monkeypatch, capsys):  # AC-200.2
    p = procs()
    interactive(monkeypatch)
    _, first, _ = detach(capsys, repo)
    before = ship.state_path(repo).read_text()
    interactive(monkeypatch, "S2")                    # a new session, or a second "ship it"
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert len(p.spawned) == 1
    assert headless_line(out) == headless_line(first) and f"next: {WAIT_COMMAND}" in out.splitlines()
    assert ship.state_path(repo).read_text() == before                      # the shipping side writes no ship state
    assert json.loads(handoff_file(repo).read_text())["by"] == "S2"         # the new session is the one the Stop hook holds


@pytest.mark.parametrize("var", ["CPLAT_HEADLESS", "CPLAT_UNIT"])
def test_a_headless_or_unit_session_hands_off_nothing_ac_200_2(repo, procs, monkeypatch, capsys, var):  # AC-200.2
    p = procs()
    interactive(monkeypatch)
    monkeypatch.setenv(var, "1" if var == "CPLAT_HEADLESS" else "t1")
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert any(ln.startswith("headless:") and "not handed off" in ln for ln in out.splitlines())
    assert p.spawned == [] and not any(ln.startswith("headless: pid") for ln in out.splitlines())
    st = state(repo)
    assert st["phase"] in ("plan", "build") and "headless" not in st            # the ship runs in this session as today


def test_a_fake_headless_session_never_starts_another_process_ac_200_2(repo, procs, monkeypatch, capsys):  # AC-200.2
    p = procs()
    interactive(monkeypatch)
    assert detach(capsys, repo)[0] == 0
    (child,) = p.spawned
    for name in SESSION_VARS:
        monkeypatch.delenv(name, raising=False)
    for k, v in child["env"].items():                     # the child's world: what the spawn gave it, plus what cplat headless sets
        if k.startswith("CPLAT_"):
            monkeypatch.setenv(k, v)
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    for _ in range(3):                                    # whatever its prompt says, however often
        rc, out, err = detach(capsys, repo)
        assert rc == 0, out + err
        assert any(ln.startswith("headless:") and "not handed off" in ln for ln in out.splitlines())
    assert len(p.spawned) == 1


def test_a_headless_ship_start_does_not_make_the_ship_run_a_child_of_its_own_child_ac_200_2(repo, procs, monkeypatch, capsys, store):  # AC-200.2
    procs()
    interactive(monkeypatch)
    assert detach(capsys, repo)[0] == 0
    run = state(repo)["run_id"]
    child = runs.start("headless", repo="acme/shop-api", spec=SPEC, parent=run)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    monkeypatch.setenv("CPLAT_RUN_PARENT", child)
    assert cli(capsys, repo, "start", "7")[0] == 0
    assert state(repo)["run_id"] == run
    assert (runs.active(run) or {}).get("parent") != child            # the run tree stays acyclic


def test_answer_without_detach_is_a_usage_error_ac_200_2(repo, procs, monkeypatch, capsys):  # AC-200.2
    p = procs()
    interactive(monkeypatch)
    rc, out, err = cli(capsys, repo, "start", "7", "--answer", "use redis")
    assert rc == 2 and "ERROR:" in err and "needs --detach" in err
    assert p.spawned == [] and state(repo) is None


# ---------------- AC-200.4: a process that ended is started once more, a second end escalates ----------------

def test_an_ended_process_is_resumed_once_in_a_new_process_ac_200_4(repo, procs, monkeypatch, capsys):  # AC-200.4
    p = procs()
    interactive(monkeypatch)
    detach(capsys, repo)
    first = state(repo)["headless"]
    p.live.clear()                                         # a crash, a killed process, a closed laptop
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert len(p.spawned) == 2
    h = state(repo)["headless"]
    assert h["starts"] == 2 and h["pid"] == p.last["pid"] != first["pid"] and h["run_id"] == first["run_id"]
    assert headless_line(out) == f"headless: pid {h['pid']}, log {h['log']}"


def test_a_third_start_of_the_same_run_escalates_it_as_environment_ac_200_4(repo, procs, monkeypatch, capsys):  # AC-200.4
    p = procs()
    interactive(monkeypatch)
    detach(capsys, repo)
    p.live.clear()
    detach(capsys, repo)
    log = state(repo)["headless"]["log"]
    p.live.clear()
    rc, out, err = detach(capsys, repo)
    assert rc == 1 and len(p.spawned) == 2
    assert out.splitlines()[0].startswith("ESCALATED:") and log in out
    st = state(repo)
    assert st["cause"] == "environment" and log in st["escalated"]


# ---------------- AC-200.5: the answer reaches the headless session ----------------

def _escalated_on_a_question(repo, p, capsys):
    detach(capsys, repo)
    p.live.clear()                                         # the headless session ended by escalating
    assert ship.main(["--repo", str(repo), "escalate", "which store holds the alerts", "--cause", "decision",
                      "--question", "Which store? (suggested: redis)"]) == 0


def test_detach_with_an_answer_hands_it_to_the_headless_session_in_its_environment_ac_200_5(repo, procs, monkeypatch, capsys):  # AC-200.5
    p = procs()
    interactive(monkeypatch)
    _escalated_on_a_question(repo, p, capsys)
    rc, out, err = detach(capsys, repo, "--answer", "use redis")
    assert rc == 0, out + err
    assert len(p.spawned) == 2
    env = p.last["env"]
    assert env["CPLAT_SHIP_ANSWER"] == "use redis" and env["CPLAT_SHIP_ANSWER_FROM"] == "shipping session"
    st = state(repo)
    assert "answers" not in st                              # the headless session records it, not this call
    assert headless_line(out) == f"headless: pid {st['headless']['pid']}, log {st['headless']['log']}"


def test_a_process_started_without_an_answer_gets_none_ac_200_5(repo, procs, monkeypatch, capsys):  # AC-200.5
    p = procs()
    interactive(monkeypatch)
    monkeypatch.setenv("CPLAT_SHIP_ANSWER", "stale")
    monkeypatch.setenv("CPLAT_SHIP_ANSWER_FROM", "stale")
    assert detach(capsys, repo)[0] == 0
    assert "CPLAT_SHIP_ANSWER" not in p.last["env"] and "CPLAT_SHIP_ANSWER_FROM" not in p.last["env"]


def test_the_headless_start_prints_and_records_the_answer_from_the_shipping_session_ac_200_5(repo, procs, monkeypatch, capsys):  # AC-200.5
    p = procs()
    interactive(monkeypatch)
    _escalated_on_a_question(repo, p, capsys)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    monkeypatch.setenv("CPLAT_SHIP_ANSWER", "use redis")
    monkeypatch.setenv("CPLAT_SHIP_ANSWER_FROM", "shipping session")
    rc, out, err = cli(capsys, repo, "start", "7")
    assert rc == 0, out + err
    assert "answer from the shipping session: use redis" in out.splitlines()
    st = state(repo)
    (a,) = st["answers"]
    assert a["text"] == "use redis" and a["from"] == "shipping session" and "escalated" not in st
    assert "answer from the shipping session: use redis" in ship.describe(st)


def test_an_answer_without_a_source_is_still_from_the_system_ship_ac_200_5(repo, procs, monkeypatch, capsys):  # AC-200.5
    p = procs()
    interactive(monkeypatch)
    _escalated_on_a_question(repo, p, capsys)
    monkeypatch.setenv("CPLAT_SHIP_ANSWER", "use redis")
    rc, out, err = cli(capsys, repo, "start", "7")
    assert rc == 0 and "answer from the system ship: use redis" in out
    assert state(repo)["answers"][-1]["from"] == "system ship"


def test_the_real_branch_of_the_repo_is_the_feature_branch_after_a_detach_ac_200_1(repo, procs, monkeypatch, capsys):  # AC-200.1
    procs()
    interactive(monkeypatch)
    assert detach(capsys, repo)[0] == 0
    head = subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    assert head == BRANCH                                   # `start` and its branch switch stay as they are (A1)
