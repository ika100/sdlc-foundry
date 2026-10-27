"""Spec 124 verification fixes: the issue panel's signal facts (AC-124.18), parallel signals (AC-124.21), the contract's event id
pattern (AC-124.16) and the notification resolution of `signal` and `done-on-its-own` (AC-124.20)."""
import threading

import pytest

from autonomy_support import DEV_URL, PROD_URL, STG_URL, audit_event, ago, engines, store  # noqa: F401
from console_support import needs_json, q, runs_json
from test_124_console import board_data, cons  # noqa: F401  (cons is a fixture)
from test_124_notify import ALL, cfg, sig_issue
from test_124_store import FACTS
from test_notify import TUE_NOON, World, env  # noqa: F401  (env: the autouse state isolation)


# ---------------- AC-124.18: the issue panel shows the whole signal ----------------

def test_the_issue_panel_shows_evidence_triage_and_policy_decision_ac_124_18(cons):  # AC-124.18
    """AC-124.18: the Board's issue panel carries the same signal facts as the Inbox triage detail."""
    root, _ = board_data(cons).panel("issue", "58")
    assert any("grafana" in (a.attrs.get("href") or "") for a in q(root, "a"))
    [tri] = q(root, "dl", data_triage=True)
    assert "0.82" in tri.text() and "src/shop_api/cart.py" in tri.text()
    [pol] = q(root, "p", data_policy_decision=True)
    assert pol.text().strip()


def test_before_triage_the_panel_says_none_ac_124_18(cons):  # AC-124.18
    """AC-124.18: without a triage the panel shows (none)."""
    c = cons()
    doc = needs_json()
    row = {**{"repo": "acme/shop-api", "number": 59, "title": "x", "labels": [], "created_at": "2026-10-26T07:00:00Z", "closed_at": None,
              "url": "https://github.com/acme/shop-api/issues/59", "engine": "ai-ops"},
           "signal": {k: v for k, v in FACTS.items() if k not in ("triage", "policy")}}
    doc["issues"] = [row]
    c.set("needs", doc)
    c.set("runs", runs_json())
    root, _ = c.panel("issue", "59")
    [tri] = q(root, "dl", data_triage=True)
    assert "(none)" in tri.text()


# ---------------- AC-124.21: signals go out in parallel ----------------

def test_unreachable_engines_are_tried_in_parallel_within_the_deadline_ac_124_21(engines, monkeypatch):  # AC-124.21
    """AC-124.21: two unreachable engines finish within the shared deadline, each retried on its own."""
    import engine
    engines.down |= {DEV_URL, PROD_URL}
    seen: dict[str, int] = {}
    lock = threading.Lock()
    orig = engines.__call__

    def counting(method, url, body, token, timeout):
        with lock:
            seen[url] = seen.get(url, 0) + 1
        return orig(method, url, body, token, timeout)
    monkeypatch.setattr(engine, "_http", counting)
    start = engines.clock.t
    res = engine.send({"dev": DEV_URL, "prod": PROD_URL}, "pause", system="shop", actor="eike")
    assert all(not r["confirmed"] and "no confirmation within 60 s" in r["reason"] for r in res.values())
    assert {u.removesuffix("/v1/signals") for u in seen} == {DEV_URL, PROD_URL} and sum(seen.values()) > 2, "both engines are tried and retried"
    assert engines.clock.t - start <= 60 * 2 + 20, "the clock never ran sequentially engine after engine"


# ---------------- AC-124.16: the contract's event id ----------------

@pytest.mark.parametrize("eid,ok", [("20261026T091733Z-ai-ops", True), ("20261026T091733Z-ai-ops-3f9c2a71", True),
                                    ("20261026T091733Z-" + "a" * 41, False),
                                    ("-20261026T091733Z-x", False), ("20261026T091733Z-a/b", False)])
def test_the_undo_event_id_follows_the_contract_ac_124_16(eid, ok):  # AC-124.16
    """AC-124.16: the console accepts the contract's event id pattern and nothing option-like or path-like."""
    from console import actions
    assert bool(actions.EVENT.match(eid)) is ok


# ---------------- AC-124.20: resolution ----------------

def test_a_routed_signal_issue_resolves_though_still_open_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: a signal issue resolves when its `triage` label is removed, not only when it is closed."""
    w = World(tmp_path, monkeypatch, cfg(signal=ALL), TUE_NOON)
    w.issues = [sig_issue()]
    w.once()
    routed = sig_issue()
    routed["labels"] = [x for x in routed["labels"] if x["name"] != "triage"]
    w.issues = [routed]
    w.once()
    assert w.state(tmp_path)["events"]["signal:acme/shop-api#57"]["resolved_at"]


def test_done_on_its_own_lives_as_long_as_the_environments_undo_window_ac_124_20(tmp_path, monkeypatch, store):  # AC-124.20
    """AC-124.20: with prod `undoWindow: 48h` a 30 hour old event is still listed; with the default it is not."""
    import needs
    import notify
    from autonomy_support import with_autonomy
    from system_fixtures import rich5, write_system
    monkeypatch.setattr(needs, "collect", lambda repo_dir, *a, **k: {"schema": 1, "system": "shop", "items": [], "unavailable": []})
    monkeypatch.setattr(notify, "gh", lambda args: "[]")
    store.add_event(audit_event("merge", at=ago(hours=30)))
    long_repo = tmp_path / "long"
    write_system(long_repo, with_autonomy(rich5(), prod={"level": "act", "undoWindow": "48h"}))
    assert [e["kind"] for e in notify.collect(long_repo)["audit"]] == ["merge"]
    short_repo = tmp_path / "short"
    write_system(short_repo, rich5())
    assert notify.collect(short_repo)["audit"] == []
