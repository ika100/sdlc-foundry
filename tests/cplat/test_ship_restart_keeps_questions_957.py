"""#957: a held repo reaches the user when the run escalates (AC-186.3); the user answers by starting `/system:ship` again. That
start set every escalated repo back to `ready` and dropped its questions, so `repo resume --answer` was refused ("is ready, not
escalated") and the repo rebuilt without the answer (journey 25: three restart cycles, about 19 minutes). A repo escalated with
questions now stays escalated with them, and only `held` is cleared, so `next` asks `answer` again; one without questions restarts."""
from test_186_system_ship import QUESTIONS, next_json, spawned, w  # noqa: F401  (fixtures)
from test_appship_097 import SPEC


def escalated_run(w, questions):
    extra = {"questions": questions} if questions else {}
    return w.started(states={"shop-gitops": "passed", "shop-lib": "passed",
                             "shop-api": {"state": "escalated", "reason": "needs a store", "cause": "decision", "held": True,
                                          "clone": "/tmp/shop-api", "spec": "001-store", **extra},
                             "shop-worker": "passed"},
                     escalated="shop-api: needs a store", cause="decision")


def test_a_restart_keeps_the_questions_so_the_answer_can_be_given_957(w, spawned):
    escalated_run(w, QUESTIONS)
    assert w.app("start", SPEC, "--context", "kind-shop").rc == 0
    api = w.state()["repos"]["shop-api"]
    assert api["state"] == "escalated" and api["questions"] == QUESTIONS and "held" not in api
    nxt = next_json(w)
    assert nxt["action"] == "answer" and nxt["answer"]["id"] == "shop-api"
    r = w.app("repo", "resume", "shop-api", "--answer", "use redis")
    assert r.rc == 0, r.out
    assert w.state()["repos"]["shop-api"]["state"] == "running"


def test_a_repo_escalated_without_questions_restarts_as_before_957(w):
    escalated_run(w, None)
    assert w.app("start", SPEC, "--context", "kind-shop").rc == 0
    api = w.state()["repos"]["shop-api"]
    assert api["state"] == "ready" and "reason" not in api and "held" not in api
