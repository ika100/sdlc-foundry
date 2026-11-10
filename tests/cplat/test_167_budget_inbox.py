"""Spec 167 acceptance tests: the daily budget, the needs kinds, the inbox, notifications and the digest (AC-167.10, AC-167.12).

Contract: design.md "Budget" (the ledger `ledger[day] = {"units": {...}, "agent": n}` in `state.json`, local midnight, unknown usage,
the 200 000 tokens of an agent call without usage), "Needs" (kinds `budget` and `stuck` read from `dispatch/<owner>__<name>/needs.json`,
repo scope), "Notifications and digest". Seams: the fake headless (its result file carries `tokens`), the fake claude (`usage`), the
notify seams of spec 122 (`notify.desktop_send`, `notify.http_post`, `notify.gh`, `notify.now`), `notify.yaml` under XDG_CONFIG_HOME,
`world.set_now` for the clock.
"""
import datetime as dt
import json

import pytest
import yaml

from console_support import needs_json, q
from dispatch_world import world  # noqa: F401  (fixture)

TODAY = "2026-11-10"
WEBHOOK = "https://hooks.slack.test/services/T/B/X"
BUDGET_NEED = {"id": f"budget:acme/shop-api:{TODAY}", "kind": "budget", "stage": "Build",
               "object": {"type": "dispatch", "repo": "acme/shop-api", "spec": None, "run_id": None, "issue": None, "component": None,
                          "version": None, "pr": None, "url": None},
               "since": "2026-11-10T09:00:00Z", "reason": "daily token budget reached: 20104332 of 20000000 tokens",
               "command": "raise budget.tokens_per_day in .platform/dispatch.yml (starts continue after midnight)", "cwd_repo": "acme/shop-api",
               "consequence": {"used": 20104332, "limit": 20000000, "running": ["issue-123.1"]}, "way_back": None}
STUCK_NEED = {"id": "stuck:acme/shop-api:issue-123.1", "kind": "stuck", "stage": "Build",
              "object": {"type": "run", "repo": "acme/shop-api", "spec": None, "run_id": "20261110T090000Z-abcd1234", "issue": 123,
                         "log": "/tmp/logs/issue-123.1.log"},
              "since": "2026-11-10T09:30:00Z",
              "reason": "unit issue-123.1 ended twice without finishing (cause environment); log: /tmp/logs/issue-123.1.log",
              "command": "gh issue edit 123 --remove-label needs-decision", "cwd_repo": "acme/shop-api",
              "consequence": {"log": "/tmp/logs/issue-123.1.log", "starts": 2}, "way_back": None}


def _write_needs(world, *items):
    f = world.dispatch_dir() / "needs.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"items": list(items)}))


def _spent(world, agent=0, units=None, day=TODAY):
    ledger = {day: {"units": units or {}, "agent": agent}, "2026-11-09": {"units": {"issue-0.1": 99_999_999}, "agent": 5}}
    world.write_state(ledger=ledger, counted={})


def _cfg(world, doc, secrets=True, monkeypatch=None):
    p = world.tmp / "config" / "sdlc-foundry" / "notify.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc))
    if secrets and monkeypatch:
        monkeypatch.setenv("CPLAT_SLACK_WEBHOOK_SHOP_DEV", WEBHOOK)


# ---------------- AC-167.10: the daily budget ----------------

def test_once_the_limit_is_reached_no_unit_starts_and_no_agent_call_is_made_ac_167_10(world):  # AC-167.10
    world.policy(slots=2)
    for n in (1, 2):
        world.issue(n)
    _spent(world, agent=20_000_000)
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert "no starts: daily budget reached" in r.out
    assert world.calls() == [] and world.claude_calls() == [] and world.gh_writes() == []
    status = world.run("status", "--json").json()
    assert status["tokens"]["limit"] == 20_000_000 and status["tokens"]["used"] >= 20_000_000
    assert world.run("plan", "--json").json()["starts"] == {"allowed": False, "why_not": "daily budget reached"}


def test_running_units_continue_and_one_budget_need_per_day_is_listed_ac_167_10(world):  # AC-167.10
    world.policy(slots=2)
    for n in (1, 2, 3):
        world.issue(n, labels=["triaged", "bug"], created=f"2026-11-0{n}T08:00:00Z")
    world.behave(mode="wait")
    world.run("start", "--once")
    pids = [c["pid"] for c in world.calls()]
    _spent(world, agent=20_000_000)
    for _ in range(2):                                                               # two cycles, one need
        assert world.run("start", "--once").rc == 0
    assert all(world.alive(p) for p in pids) and len(world.calls()) == 2
    items = world.needs("--json").json()["items"]
    [need] = [i for i in items if i["kind"] == "budget"]
    assert need["id"] == f"budget:acme/shop-api:{TODAY}" and need["object"]["repo"] == "acme/shop-api"
    assert "daily token budget reached" in need["reason"] and "20000000" in need["reason"]
    assert "tokens_per_day" in need["command"]


def test_starts_continue_after_midnight_and_when_the_limit_is_raised_ac_167_10(world):  # AC-167.10
    world.policy(slots=1)
    world.issue(1)
    _spent(world, agent=20_000_000)
    assert world.run("start", "--once").rc == 0 and world.calls() == []
    world.policy(slots=1, budget={"tokens_per_day": 30_000_000})                     # raised above the usage
    assert world.run("start", "--once").rc == 0 and [c["unit"] for c in world.calls()] == ["issue-1.1"]
    assert not [i for i in world.needs("--json").json()["items"] if i["kind"] == "budget"]


def test_the_day_counts_from_local_midnight_ac_167_10(world):  # AC-167.10
    world.policy(slots=1, budget={"tokens_per_day": 1_000_000})
    world.issue(1)
    _spent(world, agent=1_000_000)
    assert world.run("start", "--once").rc == 0 and world.calls() == []
    world.set_now(dt.datetime(2026, 11, 11, 0, 5))                                   # the next local day: yesterday's usage is gone
    r = world.run("start", "--once")
    assert r.rc == 0 and [c["unit"] for c in world.calls()] == ["issue-1.1"], r


def test_the_agent_calls_of_the_dispatcher_count_and_stop_at_the_limit_ac_167_10(world):  # AC-167.10
    world.policy(slots=2)
    for n in (1, 2):
        world.issue(n, created=f"2026-11-0{n}T08:00:00Z")
    _spent(world, agent=19_999_000)
    assert world.run("start", "--once").rc == 0
    assert len(world.claude_calls()) == 1                                            # 1000 + 500 tokens reach the limit: no second call
    assert world.state()["ledger"][TODAY]["agent"] == 19_999_000 + 1500
    assert [c["unit"] for c in world.calls()] in ([], ["issue-1.1"])


def test_an_agent_answer_without_usage_books_200000_tokens_ac_167_10(world):  # AC-167.10
    world.policy(slots=1)
    world.issue(1)
    world.claude(no_usage=True)
    assert world.run("start", "--once").rc == 0
    assert len(world.claude_calls()) == 1 and world.state()["ledger"][TODAY]["agent"] == 200_000


def test_the_tokens_of_every_unit_are_added_up_for_the_day_ac_167_10(world):  # AC-167.10
    world.policy(slots=1)
    world.issue(1)
    world.behave("issue-1.1", mode="now", then="escalate", tokens=4321)
    world.run("start", "--once")
    world.wait_ended("issue-1.1")
    world.run("start", "--once")
    status = world.run("status", "--json").json()
    assert status["tokens"]["used"] == 4321 + 1500 * len(world.claude_calls()) and status["tokens"]["unknown"] == []


def test_while_a_units_usage_is_unknown_no_unit_starts_and_status_names_it_ac_167_10(world):  # AC-167.10
    world.policy(slots=2)
    for n in (1, 2, 3):
        world.issue(n, created=f"2026-11-0{n}T08:00:00Z")
    world.behave(mode="wait")
    world.behave("issue-1.1", mode="now", then="escalate", tokens=None)
    world.run("start", "--once")
    world.wait_ended("issue-1.1")
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: usage unknown: issue-1.1" in r.out, r
    assert world.calls_of("issue-3.1") == []
    status = world.run("status", "--json").json()
    assert status["tokens"]["unknown"] == ["issue-1.1"]
    assert "issue-1.1" in world.run("status").out
    assert world.run("plan", "--json").json()["starts"] == {"allowed": False, "why_not": "usage unknown"}


# ---------------- AC-167.12: needs kinds, the inbox, notifications, the digest ----------------

def test_needs_json_lists_budget_and_stuck_with_object_reason_and_command_ac_167_12(world):  # AC-167.12
    world.policy()
    _write_needs(world, BUDGET_NEED, STUCK_NEED)
    r = world.needs("--json")
    assert r.rc == 0, r
    items = {i["kind"]: i for i in r.json()["items"]}
    assert set(items) >= {"budget", "stuck"}
    b, s = items["budget"], items["stuck"]
    assert b["object"]["repo"] == "acme/shop-api" and b["reason"] == BUDGET_NEED["reason"] and b["command"] == BUDGET_NEED["command"]
    assert s["object"]["issue"] == 123 and s["reason"] == STUCK_NEED["reason"] and s["command"] == STUCK_NEED["command"]
    assert "budget" in world.needs().out and "stuck" in world.needs().out


def test_the_dispatcher_inbox_lists_only_the_six_kinds_of_the_repo_ac_167_12(world):  # AC-167.12
    world.policy()
    world.issue(57, title="alert: checkout 5xx", labels=["triage"])
    _write_needs(world, BUDGET_NEED, STUCK_NEED)
    r = world.run("inbox", "--json")
    assert r.rc == 0, r
    kinds = [i["kind"] for i in r.json()["items"]]
    assert {"triage", "budget", "stuck"} <= set(kinds)
    assert set(kinds) <= {"approve", "answer", "escalation", "triage", "budget", "stuck"}
    text = world.run("inbox").out
    assert "budget" in text and "stuck" in text and "57" in text


def test_the_console_inbox_shows_budget_and_stuck_and_opens_their_panels_ac_167_12(console):  # AC-167.12
    c = console()
    doc = needs_json()
    doc["items"] = doc["items"] + [BUDGET_NEED, STUCK_NEED]
    c.set("needs", doc)
    root, _ = c.page("/inbox")
    [b] = q(root, None, data_need=BUDGET_NEED["id"])
    [s] = q(root, None, data_need=STUCK_NEED["id"])
    assert "budget" in b.text() and "stuck" in s.text()
    _, text = c.panel("need", BUDGET_NEED["id"])
    assert "20000000" in text and "tokens_per_day" in text
    _, text = c.panel("need", STUCK_NEED["id"])
    assert "issue-123.1" in text and "needs-decision" in text and "/tmp/logs/issue-123.1.log" in text


def test_notify_config_knows_the_new_events_with_the_recommended_preset_ac_167_12(tmp_path):  # AC-167.12
    import notify_config
    cfg = notify_config.load(tmp_path / "nowhere.yaml")
    assert cfg.events["triage"]["desktop"] == "instant" and cfg.events["triage"]["github"] == "off"
    assert cfg.events["budget"]["desktop"] == "instant"
    assert cfg.events["stuck"]["github"] == "instant" and cfg.events["stuck"]["desktop"] == "instant"


def test_a_budget_need_is_notified_once_and_nothing_else_is_ac_167_12(world):  # AC-167.12
    world.policy(slots=2)
    world.issue(1)
    world.issue(2, labels=["triaged", "bug"])
    world.behave(mode="wait")
    assert world.run("start", "--once").rc == 0                                      # units start: not an event
    assert world.desktop == [] and world.posts == [] and world.notify_gh == []
    _spent(world, agent=20_000_000)
    world.run("start", "--once")
    world.run("start", "--once")
    assert len(world.desktop) == 1 and "budget" in json.dumps(world.desktop[0]).lower()


def test_the_unit_that_ends_or_lands_is_no_notification_ac_167_12(world):  # AC-167.12
    world.policy(slots=1)
    world.issue(1)
    world.behave("issue-1.1", mode="now", then="done")
    assert world.run("start", "--once").rc == 0 and world.calls_of("issue-1.1")
    world.wait_ended("issue-1.1")
    outs = [world.run("start", "--once").out for _ in range(3)]
    assert any("landing issue-1.1" in o for o in outs)
    assert world.desktop == [] and world.posts == [] and world.mails == []


def test_quiet_hours_keep_an_instant_notification_back_ac_167_12(world, monkeypatch):  # AC-167.12
    _cfg(world, {"quiet_hours": "22:00-07:00"}, monkeypatch=monkeypatch)
    world.policy(slots=1)
    world.issue(1)
    _spent(world, agent=20_000_000)
    world.set_now(dt.datetime(2026, 11, 10, 23, 30))
    world.run("start", "--once")
    assert world.desktop == [] and world.posts == []
    assert [i for i in world.needs("--json").json()["items"] if i["kind"] == "budget"]    # it still waits in the inbox


def test_in_a_repo_linked_to_a_system_the_dispatcher_sends_only_budget_and_stuck_ac_167_12(world):  # AC-167.12
    (world.repo / ".platform-app.yml").write_text("system: shop\n")
    world.policy(slots=1)
    world.issue(57, title="alert: checkout 5xx", labels=["triage"])
    _spent(world, agent=20_000_000)
    world.run("start", "--once")
    texts = [json.dumps(d).lower() for d in world.desktop]
    assert len(texts) == 1 and "budget" in texts[0]                                   # the console notifier owns `triage`


def test_in_any_other_repo_the_dispatcher_sends_the_triage_event_too_ac_167_12(world):  # AC-167.12
    world.policy(slots=1)
    world.issue(57, title="alert: checkout 5xx", labels=["triage"])
    world.run("start", "--once")
    assert len(world.desktop) == 1


def _digest_cfg(world, monkeypatch):
    _cfg(world, {"events": {"budget": {"slack": "digest", "desktop": "off", "github": "off", "email": "off"}},
                 "slack": {"channels": ["#shop-dev"]}, "digest": {"at": "09:00"}}, monkeypatch=monkeypatch)


def test_a_daily_digest_lists_delivered_escalated_held_queue_and_tokens_once_ac_167_12(world, monkeypatch):  # AC-167.12
    _digest_cfg(world, monkeypatch)
    world.policy(slots=1)
    world.write_state(history=[
        {"unit": "issue-7.1", "item": "#7", "kind": "fix", "outcome": "done", "pr": "https://github.com/acme/shop-api/pull/70",
         "tokens": 900, "reason": None, "started_at": "2026-11-09T21:00:00", "ended_at": "2026-11-09T22:00:00"},
        {"unit": "issue-8.1", "item": "#8", "kind": "fix", "outcome": "escalated", "pr": None, "tokens": 100,
         "reason": "tests keep failing", "started_at": "2026-11-09T21:00:00", "ended_at": "2026-11-09T22:30:00"}])
    world.set_now(dt.datetime(2026, 11, 10, 8, 0))
    world.run("start", "--once")
    assert world.posts == []                                                          # before 09:00
    world.set_now(dt.datetime(2026, 11, 10, 9, 5))
    world.run("start", "--once")
    world.run("start", "--once")
    [(url, payload)] = world.posts                                                    # once
    text = json.dumps(payload)
    assert url == WEBHOOK
    for needle in ("Delivered", "Escalated", "issue-7.1", "pull/70", "issue-8.1", "tests keep failing", "Tokens"):
        assert needle in text, (needle, text)
    world.set_now(dt.datetime(2026, 11, 11, 9, 5))                                    # every day, not weekdays only; nothing new: empty
    world.run("start", "--once")
    assert len(world.posts) == 1


def test_an_empty_digest_is_not_sent_ac_167_12(world, monkeypatch):  # AC-167.12
    _digest_cfg(world, monkeypatch)
    world.policy(slots=1)
    world.set_now(dt.datetime(2026, 11, 10, 9, 5))
    assert world.run("start", "--once").rc == 0
    assert world.posts == [] and world.mails == []


@pytest.mark.parametrize("day", [dt.datetime(2026, 11, 14, 9, 5), dt.datetime(2026, 11, 15, 9, 5)])
def test_the_digest_goes_out_on_weekends_too_ac_167_12(world, monkeypatch, day):  # AC-167.12
    _digest_cfg(world, monkeypatch)
    world.policy(slots=1)
    world.write_state(history=[{"unit": "issue-7.1", "item": "#7", "kind": "fix", "outcome": "done",
                                "pr": "https://github.com/acme/shop-api/pull/70", "tokens": 900, "reason": None,
                                "started_at": day.replace(hour=1).isoformat(), "ended_at": day.replace(hour=2).isoformat()}])
    world.set_now(day)
    world.run("start", "--once")
    assert len(world.posts) == 1 and "issue-7.1" in json.dumps(world.posts[0][1])
