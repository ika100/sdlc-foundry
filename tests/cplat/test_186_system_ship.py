"""Spec 186 acceptance tests: a system ship answers an escalated repo while the others build (AC-186.1 to AC-186.3; #684).

Seams: the system ship world of spec 097 / 155 (`test_appship_097.World`: real git on a local bare origin, fake `gh`), the repo session
process `appship_proc.spawn` (replaced here by a recorder that takes the new `answer` keyword; the conftest's fake has none), the clock of
`next --wait` (`test_143_shipwait.Clock`) and the clone's ship state, written with `ship.save_state` as a repo session leaves it. The CLI
is called as `appship.main` (through `World.app`) and, where the one-line `ERROR:` refusal is the contract, as `cplat.main`.
"""
import importlib
import json

import pytest

import appship_proc
import appship_report
import cplat
import ship
from prompts186_support import ROOT, collapsed, prompt, sourced
from test_143_shipwait import Clock
from test_155_repo_sessions import repo_spec, running
from test_appship_097 import GITOPS, SPEC, World
from test_ship import repo as ship_repo  # noqa: F401  (fixture)

REASON = 'the plan splits "store" from "switch": which first? (needs your call)'
PLAN = [(GITOPS, "gitops-app", [], ["AC-012.1"], False), ("shop-api", "service-python", [], ["AC-012.1"], False),
        ("shop-worker", "service-python", [], ["AC-012.3"], False), ("shop-web", "web-nextjs", ["shop-api"], ["AC-012.2"], False)]
QUESTIONS = [{"text": "Which store holds the alerts?", "suggested": "redis"}, {"text": "How long do they live?", "suggested": None}]


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(importlib.import_module("preflight"), "check_repo", lambda *a, **k: None)
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
    return world


@pytest.fixture()
def tick(monkeypatch):
    return Clock(monkeypatch)


@pytest.fixture()
def spawned(monkeypatch):
    """Every start of a repo session, with the answer it was given."""
    seen = []

    def fake(clone, spec_id, gitops, parent_run, starts=1, answer=None):
        seen.append({"clone": str(clone), "spec": spec_id, "gitops": str(gitops), "run": parent_run, "starts": starts, "answer": answer})
        return {"pid": 5000 + len(seen), "log": f"{clone}/session.log", "started": "2026-11-12T10:00:00", "starts": starts}
    monkeypatch.setattr(appship_proc, "spawn", fake)
    return seen


def api_and_worker(w, *, escalated=REASON, cause="decision", questions=QUESTIONS, record=True):
    """shop-api escalated (its repo ship ended with a reason and questions) while shop-worker still builds."""
    w.started(PLAN, states={GITOPS: "passed"})
    for rid in ("shop-api", "shop-worker"):
        assert w.app("repo", "start", rid).rc == 0
    running(w, "shop-worker", "build")
    extra = {"questions": questions} if questions is not None else {}
    running(w, "shop-api", "build", escalated=escalated, cause=cause, **extra)
    if record:
        assert w.app("repo", "result", "shop-api").rc == 1
    return w.state()


def parsed(out):
    return json.JSONDecoder().raw_decode(out[out.index("{"):])[0]


def next_json(w, *args):
    r = w.app("next", "--json", *args)
    return parsed(r.out)


def system_ship(capsys, w, *args):
    capsys.readouterr()
    rc = cplat.main(["system", "ship", "--repo", str(w.gitops), *args])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ---------------- AC-186.1: the action answer ----------------

def test_result_keeps_the_questions_of_the_escalation_ac_186_1(w):  # AC-186.1
    st = api_and_worker(w)
    e = st["repos"]["shop-api"]
    assert e["state"] == "escalated" and e["reason"] == REASON and e["cause"] == "decision" and e["questions"] == QUESTIONS


def test_next_names_the_escalated_repo_to_answer_while_another_runs_ac_186_1(w):  # AC-186.1
    api_and_worker(w)
    nxt = next_json(w)
    assert nxt["action"] == "answer"
    assert nxt["running"] == ["shop-worker"] and nxt["escalated"] == ["shop-api"] and nxt["held"] == [] and nxt["start"] == []
    ans = nxt["answer"]
    assert (ans["id"], ans["cause"], ans["reason"]) == ("shop-api", "decision", REASON)       # word for word
    assert ans["questions"] == QUESTIONS                                                       # `suggested` is null without one
    assert ans["resume"].startswith("cplat system ship repo resume shop-api --answer ")
    assert ans["hold"] == "cplat system ship repo hold shop-api"


def test_the_text_form_of_answer_lists_the_reason_and_each_question_ac_186_1(w):  # AC-186.1
    api_and_worker(w)
    lines = w.app("next").out.splitlines()
    assert lines[0] == "action: answer"
    assert lines[1] == f"answer shop-api (cause decision): {REASON}"
    assert "  question: Which store holds the alerts? (suggested: redis)" in lines
    assert "  question: How long do they live?" in lines
    assert "running shop-worker" in lines and "escalated shop-api" in lines


def test_a_reason_ending_in_a_suggestion_is_read_as_one_question_ac_186_1(w):  # AC-186.1
    api_and_worker(w, escalated="Which store holds the alerts? (suggested: redis)", questions=None)
    ans = next_json(w)["answer"]
    assert ans["reason"] == "Which store holds the alerts? (suggested: redis)"
    assert ans["questions"] == [{"text": "Which store holds the alerts?", "suggested": "redis"}]


def test_an_escalation_without_questions_lists_none_ac_186_1(w):  # AC-186.1
    api_and_worker(w, escalated="CI red after 3 rounds", cause="code", questions=None)
    nxt = next_json(w)
    assert nxt["action"] == "answer" and nxt["answer"]["questions"] == [] and nxt["answer"]["cause"] == "code"


def test_next_wait_returns_answer_at_the_first_poll_after_the_result_ac_186_1(w, tick):  # AC-186.1
    api_and_worker(w, record=False)                     # the repo's ship ended; `next --wait` itself records it
    before = w.state()["repos"]["shop-worker"]
    r = w.app("next", "--wait", "--timeout", "60", "--json")
    assert r.rc == 0
    nxt = parsed(r.out)
    assert nxt["action"] == "answer" and nxt["answer"]["id"] == "shop-api" and nxt["running"] == ["shop-worker"]
    assert tick.slept == 0                              # it did not wait for the worker's phase to change
    assert w.state()["repos"]["shop-worker"] == before


def test_next_is_what_it_was_without_an_escalated_repo_ac_186_1(w):  # AC-186.1
    w.started(PLAN, states={GITOPS: "passed"})
    assert w.app("repo", "start", "shop-worker").rc == 0
    nxt = next_json(w)
    assert nxt["action"] == "wait" and nxt["running"] == ["shop-worker"] and nxt["held"] == [] and "answer" not in nxt
    assert set(nxt) == {"phase", "start", "running", "blocked", "escalated", "held", "action"}


def test_the_first_escalated_repo_in_plan_order_is_answered_first_ac_186_1(w, spawned):  # AC-186.1
    api_and_worker(w)
    running(w, "shop-worker", "build", escalated="the worker needs a decision too", cause="decision")
    assert w.app("repo", "result", "shop-worker").rc == 1
    assert next_json(w)["answer"]["id"] == "shop-api"
    assert w.app("repo", "resume", "shop-api", "--answer", "use redis").rc == 0
    nxt = next_json(w)
    assert nxt["action"] == "answer" and nxt["answer"]["id"] == "shop-worker"


def test_a_repo_escalation_can_carry_questions_with_suggestions_ac_186_1(w):  # AC-186.1
    w.started(PLAN, states={GITOPS: "passed"})
    r = w.app("repo", "escalate", "shop-api", "needs a store", "--cause", "decision",
              "--question", "Which store? (suggested: redis)", "--question", "How long?")
    assert r.rc == 0, r.out
    e = w.state()["repos"]["shop-api"]
    assert e["state"] == "escalated" and e["questions"] == [{"text": "Which store?", "suggested": "redis"},
                                                            {"text": "How long?", "suggested": None}]


# ---------------- AC-186.1 / AC-186.2: the repo session's side (cplat component ship) ----------------

def test_a_ship_escalation_stores_its_questions_with_the_suggested_answer_ac_186_1(ship_repo):  # AC-186.1
    assert ship.main(["--repo", str(ship_repo), "start", "7"]) == 0
    assert ship.main(["--repo", str(ship_repo), "escalate", "which store holds the alerts", "--cause", "decision",
                      "--question", "Which store? (suggested: redis; alternatives: postgres)", "--question", "How long?"]) == 0
    st = ship.load_state(ship_repo)
    assert st["questions"] == [{"text": "Which store?", "suggested": "redis"}, {"text": "How long?", "suggested": None}]
    assert ship.main(["--repo", str(ship_repo), "escalate", "CI is red", "--cause", "code"]) == 0
    assert "questions" not in ship.load_state(ship_repo)


def test_a_resumed_ship_prints_and_records_the_answer_once_ac_186_2(ship_repo, monkeypatch, capsys):  # AC-186.2
    ship.main(["--repo", str(ship_repo), "start", "7"])
    ship.main(["--repo", str(ship_repo), "escalate", "which store", "--cause", "decision", "--question", "Which store? (suggested: redis)"])
    monkeypatch.setenv("CPLAT_SHIP_ANSWER", "use redis")
    capsys.readouterr()
    assert ship.main(["--repo", str(ship_repo), "start", "7"]) == 0
    assert "answer from the system ship: use redis" in capsys.readouterr().out
    st = ship.load_state(ship_repo)
    assert [a["text"] for a in st["answers"]] == ["use redis"] and "escalated" not in st
    assert ship.main(["--repo", str(ship_repo), "start", "7"]) == 0                    # a second start of the same session
    assert [a["text"] for a in ship.load_state(ship_repo)["answers"]] == ["use redis"]
    monkeypatch.setenv("CPLAT_SHIP_ANSWER", "use postgres")
    assert ship.main(["--repo", str(ship_repo), "start", "7"]) == 0
    st = ship.load_state(ship_repo)
    assert [a["text"] for a in st["answers"]] == ["use redis", "use postgres"]
    assert "answer from the system ship: use postgres" in ship.describe(st)


# ---------------- AC-186.2: resume ----------------

def test_resume_starts_the_repo_again_with_the_answer_and_touches_no_other_repo_ac_186_2(w, spawned):  # AC-186.2
    api_and_worker(w)
    before = w.state()
    worker_before = before["repos"]["shop-worker"]
    r = w.app("repo", "resume", "shop-api", "--answer", "use redis")
    assert r.rc == 0, r.out
    line = r.out.strip().splitlines()[-1]
    assert line.startswith("shop-api: resumed with your answer (pid ") and line.endswith("next: cplat system ship next --wait")
    st = w.state()
    e = st["repos"]["shop-api"]
    assert e["state"] == "running" and not {"reason", "cause", "questions", "held"} & set(e)
    (a,) = e["answers"]
    assert a["text"] == "use redis" and a["cause"] == "decision" and a["reason"] == REASON and a["questions"] == QUESTIONS and a["at"]
    assert st["repos"]["shop-worker"] == worker_before
    last = spawned[-1]
    assert last["clone"] == str(w.clone("shop-api").absolute()) or last["clone"].endswith("shop-api")
    assert (last["spec"], last["gitops"], last["run"], last["starts"], last["answer"]) == \
           (repo_spec(w, "shop-api").id, str(w.gitops), st["run_id"], 1, "use redis")
    assert [s["clone"].rsplit("/", 1)[-1] for s in spawned if s["answer"]] == ["shop-api"]      # B's session is not touched
    assert e["proc"]["pid"] == 5000 + len(spawned)
    nxt = next_json(w)
    assert nxt["action"] == "wait" and sorted(nxt["running"]) == ["shop-api", "shop-worker"] and nxt["escalated"] == []


def test_a_spawn_failure_on_resume_escalates_the_repo_as_environment_ac_186_2(w, monkeypatch):  # AC-186.2
    api_and_worker(w)

    def broken(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr(appship_proc, "spawn", broken)
    r = w.app("repo", "resume", "shop-api", "--answer", "use redis")
    assert r.rc == 1
    e = w.state()["repos"]["shop-api"]
    assert e["state"] == "escalated" and e["cause"] == "environment" and "no such file" in e["reason"]


@pytest.mark.parametrize("args, line", [
    (["nope", "--answer", "x"], "ERROR: 'nope' is not a repo of the plan of " + SPEC),
    (["shop-worker", "--answer", "x"], "ERROR: shop-worker is running, not escalated: nothing to resume"),
])
def test_resume_of_a_repo_that_is_unknown_or_not_escalated_is_one_line_and_changes_nothing_ac_186_2(w, spawned, capsys, args, line):  # AC-186.2
    api_and_worker(w)
    before, started = w.state_file.read_text(), len(spawned)
    rc, out, err = system_ship(capsys, w, "repo", "resume", *args)
    assert rc == 1 and out == "" and err.splitlines() == [line]
    assert w.state_file.read_text() == before and len(spawned) == started


def test_resume_while_the_run_is_escalated_is_refused_ac_186_2(w, spawned, capsys):  # AC-186.2
    api_and_worker(w)
    w.edit(lambda st: st.update(escalated="stopped", cause="code"))
    before, started = w.state_file.read_text(), len(spawned)
    rc, out, err = system_ship(capsys, w, "repo", "resume", "shop-api", "--answer", "x")
    assert rc == 1 and err.splitlines() == [f"ERROR: the run of {SPEC} is escalated: resume it with /system:ship {SPEC}"]
    assert w.state_file.read_text() == before and len(spawned) == started


def test_the_real_spawn_hands_the_answer_to_the_session_in_its_environment_ac_186_2(tmp_path, monkeypatch):  # AC-186.2
    seen = {}

    class P:
        pid = 777

    def popen(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return P()
    monkeypatch.setattr(appship_proc.subprocess, "Popen", popen)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    clone = tmp_path / "shop-api"
    clone.mkdir()
    appship_proc.REAL_SPAWN(clone, "003-x", tmp_path / "shop-gitops", "run-1", 1, answer="use redis")
    assert seen["env"]["CPLAT_SHIP_ANSWER"] == "use redis" and seen["env"]["CPLAT_RUN_PARENT"] == "run-1"

def test_an_answer_counts_as_a_decision_taken_for_the_user_ac_186_2(w, spawned):  # AC-186.2
    api_and_worker(w)
    assert w.app("repo", "resume", "shop-api", "--answer", "use redis").rc == 0
    w.edit(lambda st: [st["repos"][i].update(state="passed") for i in ("shop-api", "shop-worker")])
    st = w.state()
    assert appship_report.decision_count(st) == 1
    lines = appship_report.final_report(st, "Shop")
    taken = lines[[i for i, ln in enumerate(lines) if ln.startswith("Decisions taken for you")][0]:]
    assert any("use redis" in ln for ln in taken)


# ---------------- AC-186.3: hold ----------------

def test_hold_keeps_the_repo_escalated_and_next_stops_returning_answer_ac_186_3(w):  # AC-186.3
    api_and_worker(w)
    r = w.app("repo", "hold", "shop-api")
    assert r.rc == 0, r.out
    assert r.out.strip() == f"shop-api: held for you ({REASON}); the run escalates once nothing runs"
    assert w.state()["repos"]["shop-api"]["state"] == "escalated"
    nxt = next_json(w)
    assert nxt["action"] == "wait" and "answer" not in nxt
    assert nxt["held"] == ["shop-api"] and nxt["escalated"] == ["shop-api"] and nxt["running"] == ["shop-worker"]
    assert nxt["start"] == [] and {"id": "shop-web", "waits_for": ["shop-api"]} in nxt["blocked"]      # nothing that depends on it starts
    assert "held shop-api" in w.app("next").out.splitlines()


def test_once_nothing_runs_a_held_repo_ends_the_run_escalated_ac_186_3(w):  # AC-186.3
    api_and_worker(w)
    assert w.app("repo", "hold", "shop-api").rc == 0
    w.edit(lambda st: st["repos"]["shop-worker"].update(state="passed"))                # the running repo finishes
    nxt = next_json(w)
    assert nxt["action"] == "escalate" and nxt["running"] == [] and nxt["start"] == [] and nxt["held"] == ["shop-api"]
    r = w.app("escalate", "a repo is held for you", "--cause", "decision")
    assert r.rc == 0 and w.state()["escalated"]
    status = w.app("status").out
    assert "shop-api" in status and "escalated: " + REASON in status and "passed" in status


def test_a_held_repo_does_not_hide_the_next_escalated_one_ac_186_3(w):  # AC-186.3
    api_and_worker(w)
    running(w, "shop-worker", "build", escalated="the worker needs a decision too", cause="decision")
    assert w.app("repo", "result", "shop-worker").rc == 1
    assert w.app("repo", "hold", "shop-api").rc == 0
    nxt = next_json(w)
    assert nxt["action"] == "answer" and nxt["answer"]["id"] == "shop-worker" and nxt["held"] == ["shop-api"]


def test_holding_a_held_repo_again_is_fine_and_a_resume_clears_the_hold_ac_186_3(w, spawned):  # AC-186.3
    api_and_worker(w)
    assert w.app("repo", "hold", "shop-api").rc == 0 and w.app("repo", "hold", "shop-api").rc == 0
    assert w.app("repo", "resume", "shop-api", "--answer", "use redis").rc == 0         # allowed, held or not
    assert "held" not in w.state()["repos"]["shop-api"] and next_json(w)["held"] == []


@pytest.mark.parametrize("args, line", [
    (["nope"], "ERROR: 'nope' is not a repo of the plan of " + SPEC),
    (["shop-worker"], "ERROR: shop-worker is running, not escalated: nothing to hold"),
])
def test_hold_of_a_repo_that_is_unknown_or_not_escalated_is_one_line_and_changes_nothing_ac_186_3(w, capsys, args, line):  # AC-186.3
    api_and_worker(w)
    before = w.state_file.read_text()
    rc, out, err = system_ship(capsys, w, "repo", "hold", *args)
    assert rc == 1 and out == "" and err.splitlines() == [line]
    assert w.state_file.read_text() == before


# ---------------- AC-186.2 / AC-186.3: the system ship prompt and the component ship prompt ----------------

def test_the_system_ship_prompt_answers_or_holds_an_escalated_repo_and_registers_it_ac_186_2():  # AC-186.2
    path = "plugins/system/commands/ship.md"
    text = prompt(path)
    assert "repo resume" in text and "repo hold" in text
    found = sourced(path, "#684")
    assert found and all(e["class"] == "experience" for e in found)


def test_the_system_ship_prompt_holds_what_it_does_not_answer_ac_186_3():  # AC-186.3
    text = collapsed(prompt("plugins/system/commands/ship.md"))
    assert "action: answer" in text and "action: escalate" in text
    assert "repo hold" in text


def test_the_component_ship_prompt_passes_questions_and_applies_the_answer_and_registers_it_ac_186_2():  # AC-186.2
    path = "plugins/component/commands/ship.md"
    text = prompt(path)
    assert "--question" in text and "system ship" in text
    found = sourced(path, "#684")
    assert found and {e["class"] for e in found} <= {"practice", "experience"}


def test_the_rule_register_still_checks_with_the_system_ship_entries_ac_186_2():  # AC-186.2
    import rulescheck
    assert sourced("plugins/system/commands/ship.md", "#684") and sourced("plugins/component/commands/ship.md", "#684")
    result = rulescheck.check(ROOT)
    assert result.ok, [f"{f.file}:{f.line} {f.kind}" for f in result.failures][:5]
