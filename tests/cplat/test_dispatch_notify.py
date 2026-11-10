"""Module-level tests of dispatch_notify (spec 167): the needs file, the inbox filter, the notification pass and the digest."""
import datetime as dt
import json

import pytest
import yaml

import dispatch_notify as dn
import dispatch_state as ds
import needs
import notify

SLUG = "acme/shop-api"
WEBHOOK = "https://hooks.slack.test/services/T/B/X"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CPLAT_SLACK_WEBHOOK_SHOP_DEV", WEBHOOK)
    clock = {"now": dt.datetime(2026, 11, 10, 9, 5)}
    monkeypatch.setattr(ds, "now", lambda: clock["now"])
    monkeypatch.setattr(notify, "now", lambda: clock["now"])
    sent = {"desktop": [], "posts": []}
    monkeypatch.setattr(notify, "desktop_send", lambda title, text: sent["desktop"].append(title) or "ref")
    monkeypatch.setattr(notify, "http_post", lambda url, payload: sent["posts"].append((url, payload)))
    sent["clock"] = clock
    return sent


def _config(tmp_path, doc):
    p = tmp_path / "config" / "sdlc-foundry" / "notify.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc))


UNIT = {"unit": "issue-123.1", "item": "#123", "key": "issue-123", "run_id": "r1", "log": "/tmp/x.log", "starts": 2}
SPEC_UNIT = {"unit": "spec-007.1", "item": "spec-007", "key": "spec-007", "run_id": "r2", "log": "/tmp/y.log", "starts": 2}


def test_a_stuck_need_names_the_log_and_the_command_that_resolves_it():
    issue, spec = dn.stuck_need(SLUG, UNIT), dn.stuck_need(SLUG, SPEC_UNIT)
    assert issue["id"] == "stuck:acme/shop-api:issue-123.1" and issue["object"]["issue"] == 123
    assert issue["command"] == "gh issue edit 123 --remove-label needs-decision" and "/tmp/x.log" in issue["reason"]
    assert spec["command"] == "cplat dispatch resume spec-007" and spec["object"]["issue"] is None


def test_the_needs_file_keeps_open_stuck_items_and_drops_resolved_ones(home):
    stuck = dn.stuck_need(SLUG, UNIT)
    budget = {"id": "budget:acme/shop-api:2026-11-10", "kind": "budget", "since": "2026-11-10T09:00:00Z", "object": {"repo": SLUG}}
    dn.write_needs(SLUG, [stuck, budget], issues=[])
    path = ds.needs_path(SLUG)
    assert [i["kind"] for i in json.loads(path.read_text())["items"]] in (["budget", "stuck"], ["stuck", "budget"])
    labelled = [{"number": 123, "labels": [{"name": "needs-decision"}]}]
    assert [i["kind"] for i in dn.write_needs(SLUG, [], issues=labelled)] == ["stuck"]       # budget gone, stuck open
    assert [i["kind"] for i in dn.write_needs(SLUG, [], issues=None)] == ["stuck"]           # unknown: kept
    assert dn.write_needs(SLUG, [], issues=[{"number": 123, "labels": []}]) == []            # label removed: resolved
    assert json.loads(path.read_text()) == {"items": []}


def test_a_stuck_spec_stays_while_it_is_held(home):
    dn.write_needs(SLUG, [dn.stuck_need(SLUG, SPEC_UNIT)], issues=[])
    ds.hold(SLUG, "spec-007", "stuck", "spec-007.1")
    assert len(dn.write_needs(SLUG, [], issues=[])) == 1
    ds.resume_item(SLUG, "spec-007")
    assert dn.write_needs(SLUG, [], issues=[]) == []


def test_the_inbox_lists_only_the_six_kinds(home, monkeypatch, tmp_path):
    doc = {"items": [{"kind": k, "id": k} for k in ("approve", "review", "promote", "triage", "budget", "stuck", "escalation")],
           "unavailable": []}
    monkeypatch.setattr(needs, "collect_repo", lambda repo: doc)
    assert [i["kind"] for i in dn.inbox(tmp_path)["items"]] == ["approve", "triage", "budget", "stuck", "escalation"]


def test_a_repo_linked_to_a_system_notifies_only_budget_and_stuck(tmp_path):
    assert dn.notify_kinds(tmp_path) == dn.KINDS
    (tmp_path / ".platform-app.yml").write_text("system: shop\n")
    assert dn.notify_kinds(tmp_path) == ("budget", "stuck")


def test_the_pass_sends_a_new_item_once_and_never_an_unknown_kind(home, tmp_path):
    doc = {"items": [{"id": "budget:x", "kind": "budget", "reason": "daily token budget reached", "since": "", "object": {"repo": SLUG}},
                     {"id": "review:y", "kind": "review", "reason": "r", "since": "", "object": {"repo": SLUG}}]}
    dn.notify_pass(tmp_path, SLUG, doc)
    dn.notify_pass(tmp_path, SLUG, doc)
    assert home["desktop"] == ["budget"]
    assert (notify.state_path(f"dispatch-{ds.slug_dir(SLUG)}")).is_file()


def _digest_config(tmp_path):
    _config(tmp_path, {"events": {"budget": {"slack": "digest", "desktop": "off", "github": "off", "email": "off"}},
                       "slack": {"channels": ["#shop-dev"]}, "digest": {"at": "09:00"}})


def test_the_digest_has_its_five_sections_and_is_sent_once_a_day(home, tmp_path):
    _digest_config(tmp_path)
    ds.update(SLUG, lambda st: st.update(
        history=[{"unit": "issue-7.1", "item": "#7", "kind": "fix", "outcome": "done", "pr": "https://x/pull/70", "tokens": 900,
                  "reason": None, "started_at": "2026-11-09T21:00:00", "ended_at": "2026-11-09T22:00:00"},
                 {"unit": "issue-8.1", "item": "#8", "kind": "fix", "outcome": "escalated", "pr": None, "tokens": 100,
                  "reason": "tests keep failing", "started_at": "2026-11-09T21:00:00", "ended_at": "2026-11-09T22:30:00"}],
        last_cycle={"queue": [{"item": "#9", "kind": "fix", "mode": "single"}], "held": [{"item": "#10", "reason": "claimed"}]},
        ledger={"2026-11-09": {"units": {"issue-7.1": 900}, "agent": 1500}}))
    dn.notify_pass(tmp_path, SLUG, {"items": []})
    dn.notify_pass(tmp_path, SLUG, {"items": []})
    [(url, payload)] = home["posts"]
    text = payload["text"]
    assert url == WEBHOOK
    for needle in ("Delivered:", "issue-7.1 #7 https://x/pull/70", "Escalated:", "tests keep failing", "Held:", "#10: claimed",
                   "Queue:", "#9 (fix, single)", "Tokens: 2,400"):
        assert needle in text, (needle, text)
    home["clock"]["now"] = dt.datetime(2026, 11, 11, 9, 5)       # nothing new, nothing queued: not sent
    ds.update(SLUG, lambda st: st.update(last_cycle={}))
    dn.notify_pass(tmp_path, SLUG, {"items": []})
    assert len(home["posts"]) == 1


def test_an_empty_digest_is_not_sent_and_does_not_count_as_sent(home, tmp_path):
    _digest_config(tmp_path)
    dn.notify_pass(tmp_path, SLUG, {"items": []})
    assert home["posts"] == []
    state = notify.load_state(dn.notify_path(SLUG))
    assert state["last_digest"] is None
