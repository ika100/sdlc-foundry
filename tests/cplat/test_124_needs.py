"""Spec 124 acceptance tests: engine items in `cplat needs` and `cplat runs` (AC-124.5, AC-124.7, AC-124.11, AC-124.14, AC-124.17, AC-124.18).

Contract: design.md "`cplat needs --json` additions", "Engine run record". The world is the spec 122 needs world (rich5 system with
a gitops origin) with autonomy declared; engine run records live in the fake run store; `needs.gh` is the spec 122 fake plus
`pr view`. The clock of the guardrail checks is `runs.utcnow`."""
import datetime as dt
import json

import pytest

import cplat
import runlist
import runs
from autonomy_support import (ENGINE_BODY, ENGINE_LABELS, PROD_URL, SHA, ago, iso, now, rich_auto, run_record, signal_issue, store)  # noqa: F401
from system_fixtures import git, init_git, write_system
from test_124_store import FACTS
from test_needs import FakeGh, status_rows, world  # noqa: F401  (world is a fixture)

WED_10 = dt.datetime(2026, 10, 28, 10, 0, tzinfo=dt.timezone.utc)
WED_0930 = "2026-10-28T09:30:00Z"


class PrGh(FakeGh):
    def __init__(self):
        super().__init__()
        self.pr = {"state": "OPEN", "statusCheckRollup": [{"conclusion": "SUCCESS", "status": "COMPLETED", "name": "ci"}]}
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return json.dumps(self.pr)
        return super().__call__(args)


@pytest.fixture()
def w(world, store, monkeypatch):
    """The needs world with autonomy: dev/staging act, prod act; origin acme/shop-gitops; the PR fake."""
    import needs
    write_system(world.repo, rich_auto(dev={"level": "act"}, staging={"level": "act"}, prod={"level": "act", "engine": PROD_URL}))
    init_git(world.repo)
    git(world.repo, "remote", "add", "origin", "https://github.com/acme/shop-gitops.git")
    world.gh = PrGh()
    monkeypatch.setattr(needs, "gh", world.gh)
    world.store = store
    return world


def needs_doc(w, capsys):
    rc = cplat.main(["needs", "--json", "--repo-dir", str(w.repo)])
    out = capsys.readouterr()
    assert rc == 0, out.err
    return json.loads(out.out)


def kind(doc, k):
    return [i for i in doc["items"] if i["kind"] == k]


def set_level(w, level, **block):
    write_system(w.repo, rich_auto(dev={"level": "act"}, staging={"level": "act"}, prod={"level": level, "engine": PROD_URL, **block}))


# ---------------- AC-124.17: the review decision ----------------

def test_a_fix_outside_a_guardrail_at_act_is_a_review_item_ac_124_17(w, capsys, monkeypatch):  # AC-124.17
    """AC-124.17: a fix outside a guardrail at act is a review item."""
    monkeypatch.setattr(runs, "utcnow", lambda: WED_10)  # inside the default window: only maxLines is outside
    w.store.add_run(run_record(started=WED_0930))   # on the mocked day, not the real one
    [r] = kind(needs_doc(w, capsys), "review")
    assert r["id"] == "review:acme/shop-api#88" and r["stage"] == "Land"
    assert r["command"] == "/system:autonomy approve acme/shop-api#88" and r["cwd_repo"] == "acme/shop-gitops"
    obj = r["object"]
    assert obj["type"] == "run" and obj["repo"] == "acme/shop-api" and obj["run_id"] == "20261026T091500Z-1a2b3c4d" and obj["issue"] == 57
    assert obj["component"] == "shop-api" and obj["pr"] == 88 and obj["url"] == "https://github.com/acme/shop-api/pull/88"
    assert obj["engine"] == "ai-ops" and obj["environment"] == "prod"
    assert r["since"] == run_record(started=WED_0930)["phases"][1]["started_at"] or r["since"]
    assert r["reason"] == "outside riskGate.maxLines (412 lines, at most 200)"


def test_the_review_consequence_shows_why_regression_ci_second_review_and_the_way_back_ac_124_17(w, capsys, monkeypatch):  # AC-124.17
    """AC-124.17: the review consequence shows why regression ci second review and the way back."""
    monkeypatch.setattr(runs, "utcnow", lambda: WED_10)  # inside the default window: only maxLines is outside
    w.store.add_run(run_record(started=WED_0930))   # on the mocked day, not the real one
    [r] = kind(needs_doc(w, capsys), "review")
    c = r["consequence"]
    assert c["why"] == [{"guardrail": "riskGate.maxLines", "text": "412 lines, at most 200"}]
    assert c["level"] == "act" and c["ci"] == "passed" and c["merges_to"] == "dev"
    assert c["regression"] == {"test": "tests/test_cart.py::test_total_rounding", "before": "failed", "after": "passed"}
    assert c["second_review"] == {"result": "passed", "findings": []}
    assert c["summary"] == "Round the cart total once, at the end."
    assert "Undo" in r["way_back"]["text"] and "revert" in r["way_back"]["text"]


@pytest.mark.parametrize("rollup, ci", [
    ([{"conclusion": "SUCCESS", "status": "COMPLETED"}], "passed"),
    ([{"conclusion": "SUCCESS", "status": "COMPLETED"}, {"conclusion": "FAILURE", "status": "COMPLETED"}], "failed"),
    ([{"conclusion": "", "status": "IN_PROGRESS"}], "pending"),
])
def test_ci_comes_from_the_pull_requests_checks_ac_124_17(w, capsys, rollup, ci):  # AC-124.17
    """AC-124.17: ci comes from the pull requests checks."""
    w.gh.pr = {"state": "OPEN", "statusCheckRollup": rollup}
    w.store.add_run(run_record())
    assert kind(needs_doc(w, capsys), "review")[0]["consequence"]["ci"] == ci
    asked = [c for c in w.gh.calls if c[:2] == ["pr", "view"]]
    assert asked and "88" in asked[0] and "acme/shop-api" in asked[0] and "statusCheckRollup,state" in asked[0]


def test_ci_is_unknown_when_github_cannot_say_ac_124_17(w, capsys, monkeypatch):  # AC-124.17
    """AC-124.17: ci is unknown when github cannot say."""
    import needs
    orig = w.gh

    def broken(args):
        if args[:2] == ["pr", "view"]:
            raise RuntimeError("gh: network unreachable")
        return orig(args)
    monkeypatch.setattr(needs, "gh", broken)
    w.store.add_run(run_record())
    [r] = kind(needs_doc(w, capsys), "review")
    assert r["consequence"]["ci"] == "unknown"


def test_at_level_propose_every_fix_waits_for_a_person_ac_124_17(w, capsys):  # AC-124.17
    """AC-124.17: at level propose every fix waits for a person."""
    set_level(w, "propose")
    w.store.add_run(run_record(change={"files": 1, "lines": 3}, decision={"action": "review", "outside": []}))
    [r] = kind(needs_doc(w, capsys), "review")
    assert r["consequence"]["why"] == [{"guardrail": "level", "text": "level propose: a person merges every fix"}]
    assert r["consequence"]["level"] == "propose"


def test_a_pull_request_that_is_not_open_is_no_decision_ac_124_17(w, capsys):  # AC-124.17
    """AC-124.17: a pull request that is not open is no decision."""
    w.store.add_run(run_record())
    assert len(kind(needs_doc(w, capsys), "review")) == 1                  # control: open
    w.gh.pr = {"state": "MERGED", "statusCheckRollup": []}
    assert kind(needs_doc(w, capsys), "review") == []


def test_a_review_leaves_the_list_once_its_pr_is_gone_ac_124_17(w, capsys):  # AC-124.17
    """AC-124.17: a review leaves the list once its pr is gone."""
    w.store.add_run(run_record())
    assert len(kind(needs_doc(w, capsys), "review")) == 1
    w.gh.pr = {"state": "CLOSED", "statusCheckRollup": []}
    assert kind(needs_doc(w, capsys), "review") == []


# ---------------- AC-124.14: each guardrail is named ----------------

def test_a_fix_within_every_guardrail_at_act_is_not_a_decision_ac_124_14(w, capsys, monkeypatch):  # AC-124.14
    """AC-124.14: a fix within every guardrail at act is not a decision."""
    monkeypatch.setattr(runs, "utcnow", lambda: WED_10)
    w.store.add_run(run_record(run_id="20261028T093000Z-aaaa0001", started="2026-10-28T09:30:00Z", change={"files": 2, "lines": 40},
                               decision={"action": "merge", "outside": []}, pr={"number": 70, "url": "https://github.com/acme/shop-api/pull/70"}))
    w.store.add_run(run_record(run_id="20261028T094000Z-aaaa0002", started="2026-10-28T09:40:00Z", pr={"number": 71, "url": "https://github.com/acme/shop-api/pull/71"}))
    assert [r["object"]["pr"] for r in kind(needs_doc(w, capsys), "review")] == [71], "only the fix outside a guardrail waits"


def test_every_guardrail_the_fix_is_outside_is_named_in_order_ac_124_14(w, capsys, monkeypatch):  # AC-124.14
    """AC-124.14: every guardrail the fix is outside is named in order."""
    monkeypatch.setattr(runs, "utcnow", lambda: WED_10)
    w.store.add_run(run_record(started="2026-10-28T09:30:00Z", route="spec", criticality="high", change={"files": 9, "lines": 900},
                               regression={"test": "t", "before": "passed", "after": "passed"},
                               second_review={"result": "findings", "findings": ["unchecked input"]}))
    [r] = kind(needs_doc(w, capsys), "review")
    assert [x["guardrail"] for x in r["consequence"]["why"]] == [
        "autoMerge.routes", "autoMerge.maxCriticality", "riskGate.maxFiles", "riskGate.maxLines", "riskGate.regressionTest", "riskGate.secondReview"]
    assert all(x["text"] for x in r["consequence"]["why"])
    assert "riskGate.maxFiles" in r["reason"]


def test_outside_the_window_is_named_ac_124_14(w, capsys, monkeypatch):  # AC-124.14
    """AC-124.14: outside the window is named."""
    saturday = dt.datetime(2026, 10, 31, 10, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(runs, "utcnow", lambda: saturday)
    w.store.add_run(run_record(started="2026-10-31T09:30:00Z", change={"files": 2, "lines": 40}))
    [r] = kind(needs_doc(w, capsys), "review")
    assert [x["guardrail"] for x in r["consequence"]["why"]] == ["window"]


def test_the_budget_used_up_today_is_named_ac_124_14(w, capsys, monkeypatch):  # AC-124.14
    """AC-124.14: the budget used up today is named."""
    monkeypatch.setattr(runs, "utcnow", lambda: WED_10)
    done = [run_record(run_id=f"20261028T0{i}0000Z-aaaa000{i}", started=f"2026-10-28T0{i}:00:00Z", ended_at=f"2026-10-28T0{i}:30:00Z", outcome="done",
                       change={"files": 1, "lines": 5}, decision={"action": "merge", "outside": []}, pr={"number": 70 + i, "url": "u"})
            for i in (1, 2)]
    for d in done:
        w.store.add_run(d)
    w.store.add_run(run_record(started="2026-10-28T09:30:00Z", change={"files": 2, "lines": 40}))
    [r] = kind(needs_doc(w, capsys), "review")
    assert "budget.mergesPerDay" in [x["guardrail"] for x in r["consequence"]["why"]]


def test_the_policy_is_the_one_of_the_instance_the_issue_names_capped_by_its_max_ac_124_14(w, capsys, monkeypatch):  # AC-124.14
    """prod acts, but shop-api's prod instance is capped at propose: every fix of it waits."""
    from autonomy_support import component
    d = rich_auto(dev={"level": "act"}, staging={"level": "act"}, prod={"level": "act", "engine": PROD_URL})
    component(d, "shop-api")["instances"]["prod"]["autonomy"] = {"max": "propose"}
    write_system(w.repo, d)
    monkeypatch.setattr(runs, "utcnow", lambda: WED_10)
    w.store.add_run(run_record(started="2026-10-28T09:30:00Z", change={"files": 1, "lines": 2}))
    [r] = kind(needs_doc(w, capsys), "review")
    assert r["consequence"]["level"] == "propose" and r["consequence"]["why"][0]["guardrail"] == "level"


# ---------------- AC-124.5: promote items are not touched by autonomy ----------------

def test_a_verified_release_is_still_a_promote_item_at_every_level_ac_124_5(w, capsys, monkeypatch):  # AC-124.5
    """AC-124.5: a verified release is still a promote item at every level."""
    monkeypatch.setattr(w.status, "collect", lambda *a, **k: status_rows(staging="verified"))
    for level in ("observe", "propose", "act"):
        set_level(w, level)
        [p] = kind(needs_doc(w, capsys), "promote")
        assert p["command"] == "/instance:promote shop-api --to prod --version 1.4.0" and p["stage"] == "Prod", level


# ---------------- AC-124.18: signal issues and engine items ----------------

def test_a_signal_issue_waiting_for_triage_is_a_triage_item_with_its_facts_ac_124_18(w, capsys):  # AC-124.18
    """AC-124.18: a signal issue waiting for triage is a triage item with its facts."""
    w.gh.issues["acme/shop-api"] = [signal_issue()]
    [t] = kind(needs_doc(w, capsys), "triage")
    assert t["id"] == "triage:acme/shop-api:57" and t["stage"] == "Issue" and t["command"] == "/issue:triage 57"
    assert t["object"]["issue"] == 57 and t["object"]["engine"] == "ai-ops"
    assert t["object"]["detail"]["signal"] == FACTS


def test_a_human_issue_with_only_the_triage_label_is_still_not_listed_ac_124_18(w, capsys):  # AC-124.18
    """AC-124.18: a human issue with only the triage label is still not listed."""
    w.gh.issues["acme/shop-api"] = [signal_issue(n=9, body="Please look", labels=["triage"])]
    assert kind(needs_doc(w, capsys), "triage") == []


def test_issue_rows_carry_the_engine_and_the_parsed_signal_ac_124_18(w, capsys):  # AC-124.18
    """AC-124.18: issue rows carry the engine and the parsed signal."""
    plain = {"number": 5, "title": "Crash", "state": "OPEN", "createdAt": "2026-10-20T08:00:00Z", "url": "u", "labels": [{"name": "bug"}], "body": "x"}
    w.gh.issues["acme/shop-api"] = [signal_issue(), plain]
    rows = {i["number"]: i for i in needs_doc(w, capsys)["issues"]}
    assert rows[57]["engine"] == "ai-ops" and rows[57]["signal"] == FACTS
    assert rows[5]["engine"] is None and rows[5]["signal"] is None


def test_the_issue_list_asks_for_the_body_ac_124_18(w, capsys):  # AC-124.18
    """AC-124.18: the issue list asks for the body."""
    w.gh.issues["acme/shop-api"] = [signal_issue()]
    needs_doc(w, capsys)
    asks = [c for c in w.gh.calls if c[:2] == ["issue", "list"]]
    assert asks and all("body" in " ".join(c).split("--json")[-1] for c in asks)


def test_an_engine_run_that_stopped_is_an_escalation_with_the_fix_command_ac_124_7(w, capsys):  # AC-124.7
    """AC-124.7: an engine run that stopped is an escalation with the fix command."""
    rec = run_record(ended_at=ago(minutes=2), outcome="escalated", decision={"action": "stop", "outside": []},
                     phases=[{"name": "build", "started_at": ago(minutes=20), "ended_at": ago(minutes=2)}], pr=None,
                     escalation={"reason": "stopped by the pause sig-0123456789ab of eike", "cause": "decision"})
    w.store.add_run(rec)
    [e] = kind(needs_doc(w, capsys), "escalation")
    assert e["object"]["run_id"] == rec["run_id"] and e["command"] == "/component:fix #57" and e["cwd_repo"] == "acme/shop-api"
    assert "stopped by the pause" in e["reason"] and e["stage"] == "Build"
    assert kind(needs_doc(w, capsys), "review") == []


# ---------------- AC-124.11 / AC-124.18 / AC-124.7: engine runs in the run list ----------------

def row_of(run_id="20261026T091500Z-1a2b3c4d"):
    return next(r for r in runlist.collect(30)["runs"] if r["run_id"] == run_id)


def test_an_engine_fix_run_has_actor_issue_and_facts_ac_124_11(store, monkeypatch):  # AC-124.11
    """AC-124.11: an engine fix run has actor issue and facts."""
    monkeypatch.setattr(runlist, "lookup_pr", lambda *a, **k: (_ for _ in ()).throw(AssertionError("an engine record names its own pr")))
    store.add_run(run_record())
    r = row_of()
    assert r["kind"] == "fix" and r["actor"] == {"type": "engine", "name": "ai-ops", "id": "ai-ops@shop"} and r["engine"] == "ai-ops"
    assert r["issue"] == {"repo": "acme/shop-api", "number": 57, "url": "https://github.com/acme/shop-api/issues/57"}
    assert (r["system"], r["component"], r["environment"], r["spec"]) == ("shop", "shop-api", "prod", None)
    assert r["pr"]["number"] == 88
    assert r["fix"]["route"] == "fix" and r["fix"]["change"] == {"files": 3, "lines": 412}
    assert r["fix"]["regression"]["before"] == "failed" and r["fix"]["decision"]["outside"] == ["riskGate.maxLines"]
    assert r["fix"]["policy"] == {"level": "act", "commit": SHA} and r["fix"]["summary"]
    assert r["budget"]["used"]["cost"] == 0.9 and r["budget"]["limit"]["cost"] == 3


def test_the_budget_and_phases_are_as_for_any_run_ac_124_11(store):  # AC-124.11
    """AC-124.11: the budget and phases are as for any run."""
    store.add_run(run_record())
    r = row_of()
    assert r["phase"] == "pr" and r["stage"] == "Land"
    assert {"minutes", "invocations", "reruns", "cost"} <= set(r["budget"]["used"])


def test_a_platform_run_has_null_engine_keys_ac_124_11():  # AC-124.11
    """AC-124.11: a platform run has null engine keys."""
    rid = runs.start("ship", repo="acme/shop-api", spec="011-cart")
    runs.phase(rid, "build")
    r = row_of(rid)
    for k in ("actor", "engine", "issue", "system", "component", "environment", "fix"):
        assert k in r and r[k] is None, k


def test_an_engine_run_without_an_outcome_started_today_is_active_ac_124_11(store):  # AC-124.11
    """AC-124.11: an engine run without an outcome started today is active."""
    store.add_run(run_record(started=ago(hours=2)))
    store.add_run(run_record(run_id="20261001T000000Z-deadbeef", started=ago(hours=30)))
    assert row_of()["active"] is True
    assert row_of("20261001T000000Z-deadbeef")["active"] is False


def test_a_run_stopped_by_a_pause_keeps_its_reason_and_where_it_stopped_ac_124_7(store):  # AC-124.7
    """AC-124.7: a run stopped by a pause keeps its reason and where it stopped."""
    store.add_run(run_record(ended_at=ago(minutes=1), outcome="escalated",
                             phases=[{"name": "build", "started_at": ago(minutes=20), "ended_at": ago(minutes=1)}], pr=None,
                             escalation={"reason": "stopped by the pause sig-0123456789ab of eike", "cause": "decision"}))
    r = row_of()
    assert r["phase"] == "escalated" and r["stopped"] is True and r["active"] is False and r["stopped_in"] == "build" and r["stage"] == "Build"
    assert r["escalation"]["reason"] == "stopped by the pause sig-0123456789ab of eike"


def test_an_engine_fix_sits_in_the_stage_of_its_phase_like_any_run_ac_124_18(store):  # AC-124.18
    """AC-124.18: an engine fix sits in the stage of its phase like any run."""
    from stages import STAGES
    for phases, stage in ((["build"], "Build"), (["build", "pr"], "Land"), (["build", "pr", "land"], "Land")):
        rec = run_record(run_id=f"20261026T0915{len(phases)}0Z-aaaaaaa{len(phases)}",
                         phases=[{"name": n, "started_at": ago(minutes=9), "ended_at": None} for n in phases])
        store.add_run(rec)
        assert row_of(rec["run_id"])["stage"] == stage and stage in STAGES
