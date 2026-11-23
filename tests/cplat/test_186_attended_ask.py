"""Spec 186 acceptance tests, amended for #986: an attended system ship asks a held repo's question at once (AC-186.12).

Seams as in `test_186_system_ship`: the system ship world of spec 097 / 155 (real git on a local bare origin, fake `gh`),
the repo session process `appship_proc.spawn` (a recorder), the clock of `next --wait`, and the environment that tells an
unattended session (`CPLAT_HEADLESS`, `CPLAT_UNIT`) from the person's own. The conftest clears every `CPLAT_*` variable, so a
test without one is attended.
"""
import pytest

from prompts186_support import collapsed, prompt
from test_186_system_ship import (QUESTIONS, REASON, api_and_worker, next_json, parsed, spawned, tick,  # noqa: F401  (fixtures)
                                  w)

SUGGESTED = [{"text": "Which store holds the alerts?", "suggested": "redis"}]


# ---------------- AC-186.12: `do` names what the coordinator does ----------------

def test_an_attended_run_asks_a_question_without_a_suggestion_at_once_ac_186_12(w):  # AC-186.12
    api_and_worker(w)                                   # one of the two questions has no suggested answer
    nxt = next_json(w)
    assert nxt["action"] == "answer" and nxt["answer"]["do"] == "ask"
    assert nxt["running"] == ["shop-worker"]            # asked while the other repo still builds


@pytest.mark.parametrize("var", ["CPLAT_HEADLESS", "CPLAT_UNIT"])
def test_an_unattended_run_holds_what_it_cannot_settle_ac_186_12(w, monkeypatch, var):  # AC-186.12
    monkeypatch.setenv(var, "1")
    api_and_worker(w)
    assert next_json(w)["answer"]["do"] == "hold"


@pytest.mark.parametrize("env", [{}, {"CPLAT_HEADLESS": "1"}])
def test_a_decision_with_every_answer_suggested_is_resumed_attended_or_not_ac_186_12(w, monkeypatch, env):  # AC-186.12
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    api_and_worker(w, questions=SUGGESTED)
    assert next_json(w)["answer"]["do"] == "resume"


@pytest.mark.parametrize("cause,questions", [("code", None), ("environment", None), ("decision", [])])
def test_an_attended_run_asks_every_other_escalation_ac_186_12(w, cause, questions):  # AC-186.12
    api_and_worker(w, escalated="CI red after 3 rounds", cause=cause, questions=questions)
    assert next_json(w)["answer"]["do"] == "ask"


def test_the_text_form_prints_do_after_the_questions_ac_186_12(w):  # AC-186.12
    api_and_worker(w)
    lines = w.app("next").out.splitlines()
    assert lines[1] == f"answer shop-api (cause decision): {REASON}"
    assert lines.index("  do: ask") == 2 + len(QUESTIONS)


def test_next_wait_returns_the_ask_at_the_first_poll_ac_186_12(w, tick):  # AC-186.12
    api_and_worker(w, record=False)
    r = w.app("next", "--wait", "--timeout", "60", "--json")
    nxt = parsed(r.out)
    assert r.rc == 0 and nxt["action"] == "answer" and nxt["answer"]["do"] == "ask"
    assert tick.slept == 0


# ---------------- AC-186.12: the reply resumes the repo, the others run on ----------------

def test_the_persons_reply_resumes_the_repo_and_leaves_the_other_running_ac_186_12(w, spawned):  # AC-186.12
    api_and_worker(w)
    worker = w.state()["repos"]["shop-worker"]
    assert next_json(w)["answer"]["do"] == "ask"
    before = len(spawned)                               # the two repo starts
    assert w.app("repo", "resume", "shop-api", "--answer", "redis, for 7 days").rc == 0
    st = w.state()
    assert st["repos"]["shop-api"]["state"] == "running" and st["repos"]["shop-worker"] == worker
    assert [s["answer"] for s in spawned[before:]] == ["redis, for 7 days"]   # one new session, for shop-api only
    assert spawned[-1]["clone"].endswith("shop-api")
    assert next_json(w)["action"] == "wait"


def test_a_hold_reply_keeps_a3_for_the_repo_ac_186_12(w):  # AC-186.12
    api_and_worker(w)
    assert w.app("repo", "hold", "shop-api").rc == 0
    nxt = next_json(w)
    assert nxt["action"] == "wait" and nxt["held"] == ["shop-api"] and "answer" not in nxt


# ---------------- AC-186.12: the system ship prompt acts on `do` ----------------

def test_the_system_ship_prompt_asks_on_do_ask_and_resumes_or_holds_ac_186_12():  # AC-186.12
    text = collapsed(prompt("plugins/system/commands/ship.md"))
    bullet = text[text.index("`action: answer`"):text.index("`action: escalate`")]
    assert "`ask`" in bullet and "AskUserQuestion" in bullet
    assert "repo resume" in bullet and "repo hold" in bullet and "`resume`" in bullet and "`hold`" in bullet
