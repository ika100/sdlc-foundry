"""Spec 124 acceptance tests: the events `review`, `signal` and `done-on-its-own` (AC-124.20).

Contract: design.md "Notifications". Reuses the spec 122 notify world (test_notify.World): its replaced `notify.collect` returns
`{"needs", "runs", "issues", "shipped"}`; spec 124 adds the key `"audit"` (the done-on-its-own events, engine audit events of the last
24 hours) to that document. The platform delivers; the engine sends nothing."""
import datetime as dt
import json

import pytest

import runs
from autonomy_support import ago, audit_event, iso, now, review_need, store  # noqa: F401
from test_notify import INSTANT, TUE_NOON, WEBHOOK, World, env, write_cfg  # noqa: F401  (env: the autouse state isolation)

ALL = {"github": "instant", "slack": "instant", "email": "off", "desktop": "instant"}


def cfg(**events):
    return {"events": {k: dict(v) for k, v in events.items()}, "slack": {"channels": ["#shop-dev"]}}


def sig_issue(n=57, env="env:prod", created="2026-10-27T11:00:00Z"):
    return {"repo": "acme/shop-api", "number": n, "title": "[auto] [signal] error-rate: shop-api in prod",
            "labels": [{"name": "triage"}, {"name": "signal"}, {"name": "engine:ai-ops"}, {"name": env}], "createdAt": created}


# ---------------- configuration ----------------

def test_the_three_events_are_available_per_channel_ac_124_20(tmp_path):  # AC-124.20
    """AC-124.20: the three events are available per channel."""
    import notify_config
    c = notify_config.load(tmp_path / "nowhere.yaml")
    for e in ("review", "signal", "done-on-its-own"):
        assert set(c.events[e]) == {"github", "slack", "email", "desktop"}, e
    assert {"review", "signal", "done-on-its-own"} <= set(notify_config.EVENTS)


def test_the_recommended_preset_for_the_new_events_ac_124_20(tmp_path):  # AC-124.20
    """AC-124.20: the recommended preset for the new events."""
    import notify_config
    ev = notify_config.load(tmp_path / "nowhere.yaml").events
    assert ev["review"] == {"github": "instant", "slack": "off", "email": "off", "desktop": "instant"}
    assert ev["signal"] == {"github": "instant", "slack": "off", "email": "off", "desktop": "instant"}
    assert ev["done-on-its-own"] == {"github": "off", "slack": "off", "email": "off", "desktop": "instant"}


def test_the_file_can_set_the_new_events_and_an_unknown_one_is_still_refused_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: the file can set the new events and an unknown one is still refused."""
    import notify_config
    from core import PlatformError
    p = write_cfg(tmp_path, monkeypatch, {"events": {"signal": {"slack": "digest"}, "done-on-its-own": {"email": "digest"}}})
    c = notify_config.load(p)
    assert c.events["signal"]["slack"] == "digest" and c.events["done-on-its-own"]["email"] == "digest"
    p = write_cfg(tmp_path, monkeypatch, {"events": {"autopilot": {"slack": "digest"}}})
    with pytest.raises(PlatformError) as e:
        notify_config.load(p)
    assert "autopilot" in str(e.value)


# ---------------- detection and delivery ----------------

def test_a_review_decision_asks_for_the_users_review_on_the_pull_request_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: a review decision asks for the users review on the pull request."""
    w = World(tmp_path, monkeypatch, cfg(review=ALL), TUE_NOON)
    w.needs = [review_need()]
    w.once()
    [edit] = w.calls("pr", "edit")
    assert "88" in edit and "acme/shop-api" in edit and "--add-reviewer" in edit
    assert len(w.posts) == 1 and "88" in json.dumps(w.posts[0][1]) and len(w.desktop) == 1
    w.once()
    assert len(w.posts) == 1 and len(w.calls("pr", "edit")) == 1, "one notification per event"


def test_the_review_event_resolves_when_the_item_leaves_needs_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: the review event resolves when the item leaves needs."""
    w = World(tmp_path, monkeypatch, cfg(review=ALL), TUE_NOON)
    w.needs = [review_need()]
    w.once()
    w.needs = []
    w.once()
    assert w.withdrawn == ["d1"]
    [(key, rec)] = w.state(tmp_path)["events"].items()
    assert key == "review:acme/shop-api#88" and rec["resolved_at"]


def test_a_signal_issue_assigns_the_user_and_notifies_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: a signal issue assigns the user and notifies."""
    w = World(tmp_path, monkeypatch, cfg(signal=ALL), TUE_NOON)
    w.issues = [sig_issue()]
    w.once()
    [edit] = w.calls("issue", "edit")
    assert "57" in edit and "--add-assignee" in edit and "acme/shop-api" in edit
    assert len(w.posts) == 1 and len(w.desktop) == 1
    assert set(w.state(tmp_path)["events"]) == {"signal:acme/shop-api#57"}


def test_a_signal_issue_that_is_closed_or_routed_resolves_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: a signal issue that is closed or routed resolves."""
    w = World(tmp_path, monkeypatch, cfg(signal=ALL), TUE_NOON)
    w.issues = [sig_issue()]
    w.once()
    w.issues = []
    w.once()
    assert w.state(tmp_path)["events"]["signal:acme/shop-api#57"]["resolved_at"]


def test_quiet_hours_let_a_prod_signal_through_and_hold_the_others_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: quiet hours let a prod signal through and hold the others."""
    doc = dict(cfg(signal=ALL), quiet_hours="22:00-07:00")
    w = World(tmp_path, monkeypatch, doc, dt.datetime(2026, 10, 27, 23, 30))
    w.issues = [sig_issue(57, "env:prod"), sig_issue(58, "env:staging")]
    w.once()
    text = json.dumps([p for _, p in w.posts])
    assert len(w.posts) == 1 and "57" in text and "58" not in text
    assert [c for c in w.calls("issue", "edit") if "58" in c] == []


def test_things_done_on_their_own_are_a_notification_event_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: things done on their own are a notification event."""
    w = World(tmp_path, monkeypatch, cfg(**{"done-on-its-own": ALL}), TUE_NOON)
    ev = audit_event("merge", at="2026-10-27T10:30:00Z", eid="20261027T103000Z-ai-ops-aaaaaaaa")
    w.collect = lambda repo: {"needs": {"schema": 1, "system": "shop", "items": [], "unavailable": []}, "runs": {"schema": 1, "runs": []},
                              "issues": [], "shipped": [], "audit": [ev]}
    monkeypatch.setattr(w.notify, "collect", w.collect)
    w.once()
    [create] = w.calls("issue", "create")
    joined = " ".join(create)
    assert "notify" in joined and "Signature:" in joined and "merge" in joined
    assert len(w.posts) == 1 and len(w.desktop) == 1
    w.once()
    assert len(w.posts) == 1 and len(w.calls("issue", "create")) == 1
    assert set(w.state(tmp_path)["events"]) == {"done-on-its-own:20261027T103000Z-ai-ops-aaaaaaaa"}


def test_a_done_on_its_own_event_resolves_when_undone_or_its_window_passed_ac_124_20(tmp_path, monkeypatch):  # AC-124.20
    """AC-124.20: a done on its own event resolves when undone or its window passed."""
    w = World(tmp_path, monkeypatch, cfg(**{"done-on-its-own": ALL}), TUE_NOON)
    ev = audit_event("merge", at="2026-10-27T10:30:00Z", eid="20261027T103000Z-ai-ops-aaaaaaaa")
    docs = {"audit": [ev]}
    monkeypatch.setattr(w.notify, "collect", lambda repo: {"needs": {"schema": 1, "system": "shop", "items": [], "unavailable": []},
                                                           "runs": {"schema": 1, "runs": []}, "issues": [], "shipped": [], **docs})
    w.once()
    docs["audit"] = []                                         # undone, or out of the undo window: it leaves the list
    w.once()
    assert w.calls("issue", "close") and w.state(tmp_path)["events"]["done-on-its-own:20261027T103000Z-ai-ops-aaaaaaaa"]["resolved_at"]


def test_the_engine_sends_no_message_the_platform_collects_events_itself_ac_124_20(tmp_path, monkeypatch, store):  # AC-124.20
    """`notify.collect` sweeps the `signal` label and reads the done-on-its-own events from the run store."""
    import needs
    import notify
    from system_fixtures import rich5, write_system
    repo = tmp_path / "gitops"
    write_system(repo, rich5())
    monkeypatch.setattr(needs, "collect", lambda repo_dir, *a, **k: {"schema": 1, "system": "shop", "items": [], "unavailable": []})
    store.add_event(audit_event("merge", at=ago(hours=1)))
    store.add_event(audit_event("issue", at=ago(hours=1), eid="20261027T100000Z-ai-ops-bbbbbbbb"))
    calls = []
    monkeypatch.setattr(notify, "gh", lambda args: calls.append(list(args)) or "[]")
    doc = notify.collect(repo)
    assert any("--label" in c and "signal" in c for c in calls), "open signal issues are swept"
    assert [e["kind"] for e in doc["audit"]] == ["merge"], "only the done-on-its-own kinds"
