"""Spec 124 acceptance tests: the engine client `scripts/cplat/engine.py` and its signals (AC-124.7, AC-124.9, AC-124.13, AC-124.21).

Contract: design.md "Engine HTTP" and contract.openapi.yaml. A fake engine replaces `engine._http` and the clock
(autonomy_support.FakeEngines); nothing reaches the network."""
import datetime as dt
import json
import re

import pytest

from autonomy_support import DEV_URL, PROD_URL, STG_URL, SHA, FakeEngines, audit_event, engines, iso, now  # noqa: F401

TARGETS = {"dev": DEV_URL, "prod": PROD_URL}


def eng():
    import engine
    return engine


def send(kind="pause", targets=None, policy_of=None, pr=None, **kw):
    return eng().send(TARGETS if targets is None else targets, kind, system="shop", actor="eike", policy_of=policy_of, pr=pr, **kw)


# ---------------- AC-124.7: pause and resume reach every engine ----------------

def test_a_pause_is_sent_to_the_engine_of_every_environment_with_the_bearer_token_ac_124_7(engines):  # AC-124.7
    """AC-124.7: a pause is sent to the engine of every environment with the bearer token."""
    res = send("pause")
    assert sorted(p["url"] for p in engines.posts) == sorted(TARGETS.values())
    assert {p["token"] for p in engines.posts} == {"tok-123"}
    for p in engines.posts:
        b = p["body"]
        assert b["kind"] == "pause" and b["system"] == "shop" and b["actor"] == "eike" and re.fullmatch(r"sig-[0-9a-f]{12}", b["id"])
        assert b["environment"] in TARGETS and TARGETS[b["environment"]] == p["url"]
        assert b["at"].endswith("Z") and b["policy"] is None and b["pr"] is None
    assert set(res) == {"dev", "prod"}
    for env, r in res.items():
        assert r["confirmed"] is True and r["effective"] == "observe" and re.fullmatch(r"sig-[0-9a-f]{12}", r["signal"])


def test_resume_is_sent_the_same_way_ac_124_7(engines):  # AC-124.7
    """AC-124.7: resume is sent the same way."""
    res = send("resume", pr="https://github.com/acme/shop-gitops/pull/3")
    assert {p["body"]["kind"] for p in engines.posts} == {"resume"}
    assert {p["body"]["pr"] for p in engines.posts} == {"https://github.com/acme/shop-gitops/pull/3"}
    assert all(r["confirmed"] for r in res.values())


def test_a_lower_signal_carries_the_policy_of_its_environment_ac_124_7(engines):  # AC-124.7
    """AC-124.7: a lower signal carries the policy of its environment."""
    policy = {"declared": "propose", "effective": "propose", "riskGate": {"maxLines": 100}}
    res = send("lower", targets={"dev": DEV_URL}, policy_of={"dev": policy})
    [p] = engines.posts
    assert p["body"]["kind"] == "lower" and p["body"]["policy"] == policy and p["body"]["environment"] == "dev"
    assert res["dev"]["confirmed"] is True and res["dev"]["effective"] == "propose"


def test_every_environment_gets_its_own_signal_id_and_each_post_has_a_10_second_timeout_ac_124_7(engines, monkeypatch):  # AC-124.7
    """AC-124.7: every environment gets its own signal id and each post has a 10 second timeout."""
    seen = []
    orig = engines.__call__
    monkeypatch.setattr(eng(), "_http", lambda m, u, b, t, timeout: seen.append(timeout) or orig(m, u, b, t, timeout))
    send("pause")
    assert len({p["body"]["id"] for p in engines.posts}) == 2 and set(seen) == {10}


def test_a_signal_never_raises_autonomy_ac_124_9(engines):  # AC-124.9
    """AC-124.9: a signal never raises autonomy."""
    try:
        res = send("raise", policy_of={"dev": {"declared": "act", "effective": "act"}})
    except (ValueError, KeyError):
        res = None
    assert engines.posts == [], "only pause, resume and lower exist"
    assert not res or not any(r["confirmed"] for r in res.values())


def test_the_engine_answering_409_does_not_confirm_and_says_why_ac_124_9(engines):  # AC-124.9
    """AC-124.9: the engine answering 409 does not confirm and says why."""
    engines.refuse[DEV_URL] = (409, {"error": "raises autonomy", "detail": None, "fields": ["riskGate.maxLines"]})
    res = send("lower", targets={"dev": DEV_URL}, policy_of={"dev": {"declared": "act", "effective": "act"}})
    assert res["dev"]["confirmed"] is False
    assert "raises autonomy" in res["dev"]["reason"] and "riskGate.maxLines" in res["dev"]["reason"]
    assert len(engines.posts) == 1, "a 409 is final: it is not retried"


# ---------------- AC-124.21: an engine that cannot be reached ----------------

def test_an_engine_that_does_not_answer_is_not_confirmed_after_60_seconds_and_the_others_are_ac_124_21(engines):  # AC-124.21
    """AC-124.21: an engine that does not answer is not confirmed after 60 seconds and the others are."""
    engines.down.add(PROD_URL)
    start = engines.clock.t
    res = send("pause")
    assert res["dev"]["confirmed"] is True
    assert res["prod"]["confirmed"] is False and res["prod"]["reason"] and re.fullmatch(r"sig-[0-9a-f]{12}", res["prod"]["signal"])
    assert engines.clock.t - start >= 60, "the signal is retried until 60 s after the command started"
    assert engines.clock.t - start < 600


def test_a_flaky_engine_is_retried_and_confirms_ac_124_21(engines, monkeypatch):  # AC-124.21
    """AC-124.21: a flaky engine is retried and confirms."""
    import engine
    calls = {"n": 0}
    orig = engines.__call__

    def flaky(method, url, body, token, timeout):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError("timed out")
        return orig(method, url, body, token, timeout)
    monkeypatch.setattr(engine, "_http", flaky)
    res = send("pause", targets={"dev": DEV_URL})
    assert res["dev"]["confirmed"] is True and calls["n"] == 3
    assert len({p["body"]["id"] for p in engines.posts}) == 1


@pytest.mark.parametrize("code", [401, 403, 404, 400])
def test_an_error_answer_is_not_a_confirmation_ac_124_21(engines, code):  # AC-124.21
    """AC-124.21: an error answer is not a confirmation."""
    engines.refuse[DEV_URL] = (code, {"error": "nope", "detail": None})
    res = send("pause", targets={"dev": DEV_URL})
    assert res["dev"]["confirmed"] is False and res["dev"]["reason"]


def test_a_200_without_confirmed_true_is_not_a_confirmation_ac_124_21(engines):  # AC-124.21
    """AC-124.21: a 200 without confirmed true is not a confirmation."""
    engines.refuse[DEV_URL] = (200, {"id": "sig-x", "environment": "dev", "confirmed": False, "effective": "act", "at": iso(now())})
    assert send("pause", targets={"dev": DEV_URL})["dev"]["confirmed"] is False


def test_without_a_token_nothing_is_sent_and_the_reason_says_so_ac_124_21(engines, monkeypatch):  # AC-124.21
    """AC-124.21: without a token nothing is sent and the reason says so."""
    import notify_config
    monkeypatch.delenv("CPLAT_ENGINE_TOKEN")
    monkeypatch.setattr(notify_config, "secret", lambda *a, **k: None)
    res = send("pause")
    assert engines.posts == []
    assert all(r["confirmed"] is False and r["reason"] == "no engine token" for r in res.values())


def test_the_token_comes_from_the_environment_else_the_keychain_account_of_the_host_ac_124_21(engines, monkeypatch):  # AC-124.21
    """AC-124.21: the token comes from the environment else the keychain account of the host."""
    import notify_config
    assert eng().token(PROD_URL) == "tok-123"
    monkeypatch.delenv("CPLAT_ENGINE_TOKEN")
    asked = []
    monkeypatch.setattr(notify_config, "secret", lambda *a, **k: asked.append((a, k)) or "from-keychain")
    assert eng().token(PROD_URL) == "from-keychain"
    assert any("engine:ai-ops.prod.example.com" in list(a) + list(k.values()) for a, k in asked)


def test_a_not_confirmed_environment_counts_as_confirmed_later_by_one_of_three_rules_ac_124_21(engines):  # AC-124.21
    """AC-124.21: a not confirmed environment counts as confirmed later by one of three rules."""
    e = eng()
    pending = {"signal": "sig-aaaaaaaaaaaa", "kind": "pause", "environment": "prod"}
    idle = {"engine": {"name": "ai-ops", "version": "1"}, "heartbeat_at": iso(now()),
            "environments": {"prod": {"policy_commit": SHA, "applied_at": iso(now()), "declared": "act", "effective": "act", "paused": False, "signals": []}}}
    assert e.confirmed_later(pending, idle, []) is False
    listed = json.loads(json.dumps(idle))
    listed["environments"]["prod"]["signals"] = [{"id": "sig-aaaaaaaaaaaa", "kind": "pause", "at": iso(now())}]
    assert e.confirmed_later(pending, listed, []) is True                     # the engine status lists the id
    paused = json.loads(json.dumps(idle))
    paused["environments"]["prod"].update(paused=True, effective="observe")
    assert e.confirmed_later(pending, paused, []) is True                     # the status shows the requested state
    honoured = audit_event("signal-honoured", env="prod", obj={"type": "signal", "signal": "sig-aaaaaaaaaaaa"})
    assert e.confirmed_later(pending, idle, [honoured]) is True               # a signal-honoured event with that id
    other = audit_event("signal-honoured", env="prod", obj={"type": "signal", "signal": "sig-bbbbbbbbbbbb"})
    assert e.confirmed_later(pending, idle, [other]) is False


def test_resume_and_lower_are_confirmed_by_the_requested_state_ac_124_21(engines):  # AC-124.21
    """AC-124.21: resume and lower are confirmed by the requested state."""
    e = eng()

    def status(paused, effective):
        return {"heartbeat_at": iso(now()), "environments": {"prod": {"declared": "act", "effective": effective, "paused": paused, "signals": []}}}
    assert e.confirmed_later({"signal": "sig-1", "kind": "resume", "environment": "prod"}, status(False, "act"), []) is True
    assert e.confirmed_later({"signal": "sig-1", "kind": "resume", "environment": "prod"}, status(True, "observe"), []) is False
    low = {"signal": "sig-2", "kind": "lower", "environment": "prod", "level": "propose"}
    assert e.confirmed_later(low, status(False, "propose"), []) is True
    assert e.confirmed_later(low, status(False, "advise"), []) is True
    assert e.confirmed_later(low, status(False, "act"), []) is False


# ---------------- AC-124.13: the heartbeat ----------------

def test_status_asks_for_the_system_and_returns_the_document_ac_124_13(engines):  # AC-124.13
    """AC-124.13: status asks for the system and returns the document."""
    doc = eng().status(DEV_URL, "shop")
    assert doc["engine"]["name"] == "ai-ops" and "heartbeat_at" in doc
    assert engines.gets and engines.gets[0].startswith(DEV_URL + "/v1/status") and "system=shop" in engines.gets[0]


def test_a_fresh_heartbeat_is_ok_and_an_old_one_is_unreachable_ac_124_13(engines):  # AC-124.13
    """AC-124.13: a fresh heartbeat is ok and an old one is unreachable."""
    e = eng()
    n = now()
    assert e.state({"heartbeat_at": iso(n - dt.timedelta(minutes=4, seconds=50))}, n) == "ok"
    assert e.state({"heartbeat_at": iso(n - dt.timedelta(minutes=5, seconds=30))}, n) == "unreachable"
    assert e.state({"heartbeat_at": iso(n - dt.timedelta(hours=2))}, n) == "unreachable"


def test_an_unreachable_engine_gives_no_status_and_never_raises_ac_124_13(engines):  # AC-124.13
    """AC-124.13: an unreachable engine gives no status and never raises."""
    engines.down.add(DEV_URL)
    assert eng().status(DEV_URL, "shop") is None


def test_the_last_heartbeat_is_cached_per_system_ac_124_13(engines, tmp_path):  # AC-124.13
    """AC-124.13: the last heartbeat is cached per system."""
    engines.heartbeat[DEV_URL] = "2026-10-26T09:19:00Z"
    eng().status(DEV_URL, "shop")
    cache = tmp_path / "xdg-state" / "sdlc-foundry" / "autonomy" / "shop.json"
    assert cache.is_file() and "2026-10-26T09:19:00Z" in cache.read_text()
