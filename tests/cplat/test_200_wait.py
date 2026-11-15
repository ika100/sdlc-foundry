"""Spec 200 acceptance tests: `cplat component ship wait` of a handed-off run (AC-200.3, the wait side of AC-200.4).

Seams as in spec 143's tests (`test_143_shipwait`): the scripted clock (`waits.now` / `waits.sleep`; each sleep applies the next
scripted change to the clone's ship state, units file or branch) and the clone's `<git dir>/cplat-ship.json`. A handed-off run
carries `headless` in its state (design.md "Ship state"); `ship_handoff.alive` is the liveness seam (`Procs`).
"""
import re

import pytest

import runs
import ship
import units
from ship200_support import BRANCH, SPEC, handoff_module, procs, wait_cli  # noqa: F401
from test_143_shipwait import TIME, Clock, state
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import git, repo  # noqa: F401  (fixtures, helpers)

LOG = "/logs/shop-api/2026-11-15_101500-ship.log"
WAIT = "WAIT: run still going, progress in the last {t}s; run the same wait again"


@pytest.fixture()
def tick(monkeypatch):
    return Clock(monkeypatch)


def headless(starts=1, pid=4242, **kw):
    return {"headless": {"pid": pid, "log": LOG, "started": "2026-11-05T08:00:00", "starts": starts,
                         "run_id": "20261105T080000Z-abcd", "flags": [], **kw}}


def put_units(repo, *done):
    ids = ["u1", "u2", "u3"]
    units._write(repo, {"version": 1, "spec": SPEC, "command": "ship",
                        "units": [{"id": u, "status": "done" if u in done else "open", "sessions": 0, "stalls": 0,
                                   "commit": None, "at": None, "hold": None} for u in ids]})


def result(lines, first):
    i = next(i for i, ln in enumerate(lines) if ln.startswith(first))
    return lines[i:]


# ---------------- AC-200.3: progress is exit 0 with one WAIT line, nothing new is exit 2 ----------------

def test_a_new_phase_during_the_call_ends_it_with_wait_and_exit_0_ac_200_3(repo, tick, capsys):  # AC-200.3
    ship.save_state(repo, state("build", **headless()))
    tick.script = [lambda: None, lambda: ship.save_state(repo, state("pr", **headless()))]
    rc, out, _ = wait_cli(capsys, repo, "--timeout", "30")
    assert rc == 0
    assert [ln for ln in out if ln.startswith("WAIT:")] == [WAIT.format(t=30)]
    assert not [ln for ln in out if ln.startswith(("TIMEOUT:", "ESCALATED:", "ENDED:"))]
    assert tick.slept <= 40                                                 # no later than T + 10 s after it started


def test_a_new_unit_checkpoint_is_progress_and_prints_a_unit_line_ac_200_3(repo, tick, capsys):  # AC-200.3
    ship.save_state(repo, state("build", **headless()))
    put_units(repo, "u1")
    tick.script = [lambda: put_units(repo, "u1", "u2")]
    rc, out, _ = wait_cli(capsys, repo, "--timeout", "20")
    assert rc == 0 and [ln for ln in out if ln.startswith("WAIT:")] == [WAIT.format(t=20)]
    assert any(re.match(rf"^\d\d:\d\d:\d\d ship {SPEC}: unit u2 done$", ln) for ln in out)
    assert not any("unit u1 done" in ln for ln in out)                       # done before the call: not news


def test_a_new_commit_on_the_feature_branch_is_progress_ac_200_3(repo, tick, capsys):  # AC-200.3
    git(repo, "checkout", "-qb", BRANCH)
    ship.save_state(repo, state("build", **headless()))

    def commit():
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "feat: t1")
    tick.script = [commit]
    rc, out, _ = wait_cli(capsys, repo, "--timeout", "20")
    assert rc == 0 and [ln for ln in out if ln.startswith("WAIT:")] == [WAIT.format(t=20)]


def test_nothing_new_is_a_timeout_with_exit_2_and_the_log_ac_200_3(repo, tick, capsys):  # AC-200.3
    ship.save_state(repo, state("build", **headless()))
    put_units(repo, "u1")
    rc, out, _ = wait_cli(capsys, repo, "--timeout", "30")
    assert rc == 2
    lines = result(out, "TIMEOUT:")
    assert "build" in lines[0] and "30s" in lines[0] and re.search(r"in it for \S+", lines[0])
    assert f"log: {LOG}" in lines and any("same wait again" in ln for ln in lines)
    assert not [ln for ln in out if ln.startswith("WAIT:")]
    assert tick.slept <= 40


def test_a_wait_without_a_handed_off_run_has_no_log_line_ac_200_3(repo, tick, capsys):  # AC-200.3
    ship.save_state(repo, state("build"))
    rc, out, _ = wait_cli(capsys, repo, "--timeout", "30")
    assert rc == 2 and not [ln for ln in out if ln.startswith("log:")]
    ship.save_state(repo, state("build", **headless()))
    tick.script = [lambda: ship.save_state(repo, state("pr", **headless()))]      # and progress still ends in exit 0
    assert wait_cli(capsys, repo, "--timeout", "30")[0] == 0


def test_an_escalated_run_lists_each_question_with_its_suggestion_and_the_log_ac_200_3(repo, tick, capsys):  # AC-200.3
    ship.save_state(repo, state("land", **headless()))
    questions = [{"text": "Which store?", "suggested": "redis"}, {"text": "How long?", "suggested": None}]
    tick.script = [lambda: ship.save_state(repo, state("land", **headless(), escalated="needs a store", cause="decision",
                                                      questions=questions))]
    rc, out, _ = wait_cli(capsys, repo)
    lines = result(out, "ESCALATED:")
    assert rc == 1
    assert lines[0] == f"ESCALATED: ship {SPEC}: needs a store (cause decision)"
    assert "question: Which store? (suggested: redis)" in lines and "question: How long? (no suggestion)" in lines
    assert f"log: {LOG}" in lines and f"resume it with /component:ship {SPEC}" in lines


def test_a_phase_line_per_change_and_a_unit_line_per_unit_ac_200_3(repo, tick, capsys):  # AC-200.3
    ship.save_state(repo, state("build", **headless()))
    put_units(repo)
    tick.script = [lambda: put_units(repo, "u1"), lambda: ship.save_state(repo, state("pr", **headless())),
                   lambda: ship.save_state(repo, state("done", **headless()))]
    rc, out, _ = wait_cli(capsys, repo)
    assert rc == 0
    timed = [ln.split(" ", 1)[1] for ln in out if TIME.match(ln)]
    assert timed == [f"ship {SPEC}: phase build", f"ship {SPEC}: unit u1 done", f"ship {SPEC}: phase pr", f"ship {SPEC}: phase done"]
    assert result(out, "REACHED:")


def test_the_wait_result_words_are_recorded_as_progress_and_ended_ac_200_3(repo, tick, capsys, store, monkeypatch, procs):  # AC-200.3
    p = procs()
    rid = runs.start("ship", repo="acme/shop-api", spec=SPEC)
    monkeypatch.setenv("CPLAT_RUN_PARENT", rid)
    ship.save_state(repo, state("build", **headless()))
    p.live.add(4242)
    tick.script = [lambda: ship.save_state(repo, state("pr", **headless()))]
    assert wait_cli(capsys, repo, "--timeout", "20")[0] == 0
    assert runs.active(rid)["waits"][-1]["result"] == "progress"
    p.live.clear()
    assert wait_cli(capsys, repo)[0] == 1
    assert runs.active(rid)["waits"][-1]["result"] == "ended"


# ---------------- AC-200.4: a headless process that ended ----------------

def test_a_dead_process_of_an_unfinished_run_is_ended_with_the_phase_and_the_log_ac_200_4(repo, tick, capsys, procs):  # AC-200.4
    p = procs()
    p.live.clear()
    ship.save_state(repo, state("build", **headless()))
    rc, out, _ = wait_cli(capsys, repo)
    lines = result(out, "ENDED:")
    assert rc == 1 and tick.slept == 0                                            # seen at once, not after the timeout
    assert lines[0] == f"ENDED: headless session ended in phase build; log {LOG}"
    assert f"resume it with cplat component ship start {SPEC} --detach" in lines


def test_a_live_process_is_not_ended_ac_200_4(repo, tick, capsys, procs):  # AC-200.4
    p = procs()
    p.live.add(4242)
    ship.save_state(repo, state("build", **headless()))
    rc, out, _ = wait_cli(capsys, repo, "--timeout", "20")
    assert rc == 2 and not [ln for ln in out if ln.startswith("ENDED:")] and f"log: {LOG}" in out


def test_a_process_that_finished_the_run_before_it_ended_is_reached_not_ended_ac_200_4(repo, tick, capsys, procs):  # AC-200.4
    p = procs()
    p.live.clear()
    ship.save_state(repo, state("done", **headless()))
    rc, out, _ = wait_cli(capsys, repo)
    assert rc == 0 and result(out, "REACHED:") and not [ln for ln in out if ln.startswith("ENDED:")]


def test_the_second_end_of_a_run_escalates_it_as_environment_naming_the_log_ac_200_4(repo, tick, capsys, procs):  # AC-200.4
    p = procs()
    p.live.clear()
    ship.save_state(repo, state("build", **headless(starts=2)))
    rc, out, _ = wait_cli(capsys, repo)
    lines = result(out, "ESCALATED:")
    assert rc == 1 and "environment" in lines[0] and LOG in lines[0]
    assert not [ln for ln in out if ln.startswith("ENDED:")]
    st = ship.load_state(repo)
    assert st["cause"] == "environment" and LOG in st["escalated"] and "phase build" in st["escalated"]
