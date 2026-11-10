"""Module-level tests of dispatch_view (spec 167): the plan, status, report and wait documents and their text, from fixture state."""
import datetime as dt
import subprocess

import pytest

import dispatch_policy
import dispatch_state as ds
import dispatch_units
import dispatch_view as dv
import runs

SLUG = "acme/shop-api"
NOW = dt.datetime(2026, 11, 10, 12, 0, 0)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(ds, "now", lambda: NOW)
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [])
    return tmp_path


def _policy(tmp_path, **raw):
    (tmp_path / ".platform").mkdir(exist_ok=True)
    import yaml
    (tmp_path / ".platform" / "dispatch.yml").write_text(yaml.safe_dump(raw))
    return dispatch_policy.load(tmp_path)


def _unit(home, key, n=1, **fields):
    wt = ds.worktree_path(SLUG, key)
    wt.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    unit = {"unit": f"{key}.{n}", "item": ds.item_of(key), "key": key, "kind": "fix", "mode": "single", "branch": f"fix/{key}",
            "worktree": str(wt), "slot": 1, "pid": 4242, "log": "/tmp/log", "status": "running", "pr": None,
            "started_at": "2026-11-10T09:05:00", **fields}
    ds.write_unit(wt, unit)
    return unit


def test_report_groups_the_history_by_day_newest_first_and_leaves_empty_days_out(home):
    ds.update(SLUG, lambda st: st["history"].extend([
        {"unit": "issue-1.1", "item": "#1", "kind": "fix", "outcome": "done", "pr": "u/1", "tokens": 5, "reason": None,
         "started_at": "2026-11-08T08:00:00", "ended_at": "2026-11-08T09:00:00"},
        {"unit": "issue-2.1", "item": "#2", "kind": "fix", "outcome": "stuck", "pr": None, "tokens": None, "reason": "boom",
         "started_at": "2026-11-10T08:00:00", "ended_at": "2026-11-10T09:00:00"}]))
    ds.days_held(SLUG, "2026-11-10", "#3", "blocked")
    doc = dv.report_doc(SLUG)
    assert [d["day"] for d in doc["days"]] == ["2026-11-10", "2026-11-08"]
    assert doc["days"][0]["escalated"] == [{"item": "#2", "unit": "issue-2.1", "reason": "boom"}]
    assert doc["days"][0]["held"] == [{"item": "#3", "reason": "blocked"}]
    assert [d["day"] for d in dv.report_doc(SLUG, 2)["days"]] == ["2026-11-10"]
    text = dv.render_report(doc)
    assert "2026-11-10  delivered 0  escalated 1  held 1  tokens 0" in text and "  escalated #2  issue-2.1: boom" in text
    assert dv.render_report(dv.report_doc("nobody/none")) == "nothing to report"


def test_status_shows_the_units_the_queue_the_limit_and_the_unknown_usage(home):
    _unit(home, "issue-1")
    _unit(home, "issue-2", slot=2, status="paused")
    _unit(home, "issue-3", status="done")
    ds.update(SLUG, lambda st: st.update(counted={"issue-1.1": 1500}, unknown={"issue-2.1": "2026-11-10", "old.1": "2026-11-01"},
                                         last_cycle={"at": "2026-11-10T11:59:00", "queue": [{"item": "#4", "kind": "fix", "mode": "single"}],
                                                     "held": [{"item": "#5", "reason": "blocked", "detail": "#1 is open"}]}))
    ds.pause(SLUG)
    doc = dv.status_doc(home, SLUG, _policy(home, slots=3, budget={"tokens_per_day": 20_000_000}))
    assert doc["paused"] == "pause" and doc["slots"]["total"] == 3 and doc["loop"] == {"running": False, "pid": None}
    assert [(u["unit"], u["phase"], u["tokens"]) for u in doc["slots"]["units"]] == [("issue-1.1", "running", 1500),
                                                                                    ("issue-2.1", "paused", None)]
    assert doc["tokens"]["unknown"] == ["issue-2.1"] and doc["tokens"]["limit"] == 20_000_000
    text = dv.render_status(doc)
    for needle in ("not running", "[pause]", "issue-1.1", "since 09:05", "tokens 1,500", "#4  fix  single", "#5  blocked (#1 is open)",
                   "of 20,000,000", "usage unknown: issue-2.1"):
        assert needle in text, (needle, text)


def test_a_ship_unit_shows_the_phase_of_its_ship_state(home, monkeypatch):
    _unit(home, "spec-007", kind="ship", mode="team")
    monkeypatch.setattr(dispatch_units, "_ship_state", lambda wt: {"phase": "build"})
    [row] = dv.status_doc(home, SLUG, _policy(home))["slots"]["units"]
    assert row["phase"] == "build"


def test_starts_say_why_not_in_the_order_paused_budget_unknown(home):
    policy = _policy(home, budget={"tokens_per_day": 100})
    assert dv.starts_doc(SLUG, policy) == {"allowed": True, "why_not": None}
    ds.update(SLUG, lambda st: st.update(unknown={"issue-1.1": "2026-11-10"}))
    assert dv.starts_doc(SLUG, policy)["why_not"] == "usage unknown"
    assert dv.no_starts_line("usage unknown", ["issue-1.1"]) == "no starts: usage unknown: issue-1.1"
    ds.update(SLUG, lambda st: st.update(ledger={"2026-11-10": {"units": {}, "agent": 100}}))
    assert dv.starts_doc(SLUG, policy)["why_not"] == "daily budget reached"
    ds.pause(SLUG, drain=True)
    assert dv.starts_doc(SLUG, policy)["why_not"] == "drain"
    assert dv.no_starts_line(None) is None


def test_plan_text_marks_defaults_the_unset_limit_and_the_candidate_rows(home):
    policy = dispatch_policy.load(home)
    cands = [{"item": "#2", "key": "issue-2", "kind": "fix", "title": "a bug", "verdict": "ready", "reason": None, "detail": None,
              "mode": "single", "slot": 1, "premise": "holds", "approve": None},
             {"item": "#3", "key": "issue-3", "kind": "fix", "title": "late", "verdict": "ready", "reason": None, "detail": None,
              "mode": "single", "slot": None, "premise": "unchecked", "approve": None},
             {"item": "#4", "key": "issue-4", "kind": "fix", "title": "no", "verdict": "held", "reason": "skipped", "detail": "later",
              "mode": None, "slot": None, "premise": None, "approve": None}]
    doc = dv.plan_doc(home, SLUG, policy, cands)
    assert doc["policy"]["file"] is None and doc["policy"]["unset"] == ["budget.tokens_per_day"] and len(doc["policy"]["usage_hint"]) == 7
    assert doc["slots"] == {"total": 1, "running": 0, "free": 1}
    text = dv.render_plan(doc)
    assert text.startswith("policy: defaults (no .platform/dispatch.yml)")
    assert "  slots: 1 (default)" in text and "budget.tokens_per_day: unset (required by start and resume) — last 7 days: 2026-11-04 0" in text
    assert "#2  fix  ready  single  slot 1  premise holds  a bug" in text and "#3  fix  ready  single  queued  premise unchecked  late" in text
    assert "#4  fix  held: skipped: later  -  -  premise -  no" in text


def test_wait_reports_an_event_once_then_idle_then_a_timeout(home):
    ds.events_add(SLUG, "red", "issue-1.1", "#1", "build failed", "https://github.com/acme/shop-api/pull/9")
    ds.events_add(SLUG, "escalated", "issue-1.1", "#1", "the checks\nstayed red")
    ds.events_add(SLUG, "done", "issue-9.1", "#9", None)
    code, lines = dv.wait_result(SLUG, 1, sleep=lambda s: None)
    assert code == 1 and lines == ["RED: issue-1.1 #1 https://github.com/acme/shop-api/pull/9: build failed",
                                   "ESCALATED: issue-1.1 #1: the checks stayed red"]
    code, lines = dv.wait_result(SLUG, 1, sleep=lambda s: None)
    assert code == 0 and lines[0].startswith("IDLE:") and "no dispatcher loop" in lines[1]
    _unit(home, "issue-2")
    ticks = iter(range(0, 100))
    code, lines = dv.wait_result(SLUG, 3, sleep=lambda s: None, clock=lambda: next(ticks))
    assert code == 2 and lines[0] == "TIMEOUT: 1 unit(s) running after 3s" and lines[1] == "  issue-2.1 #2 running since 09:05"
