"""Spec 124 acceptance tests: the engine's issue, run records and audit events (AC-124.10, AC-124.11, AC-124.12, AC-124.16 eligibility).

Contract: design.md "The engine's issue", "Engine run record", "Audit events". The fixture documents of autonomy_support are the
shared examples with ai-ops. Run store: `autonomy_support.AutoStore`; the GitHub transport: `test_runs_store.FakeGitHub`."""
import datetime as dt
import hashlib
import json
import re

import pytest

import runs
import runs_store
from autonomy_support import (ENGINE_BODY, ENGINE_LABELS, SHA, AutoStore, ago, audit_event, declared_system, engines, iso, now,  # noqa: F401
                              run_record, store)
from test_runs_store import FakeGitHub, hub  # noqa: F401  (hub is a fixture)
from system_fixtures import write_system

KEY = "shop-api/prod/error-rate/HTTP 500 on POST /cart"

FACTS = {"component": "shop-api", "environment": "prod", "category": "error-rate", "criticality": "high", "dedupe_key": KEY, "seen": 3,
         "first_seen": "2026-10-26T07:00:00Z", "last_seen": "2026-10-26T09:12:00Z", "engine": "ai-ops",
         "evidence": [{"text": "Grafana: error rate", "url": "https://grafana.example.com/d/abc"}],
         "triage": {"route": "fix", "confidence": 0.82, "suspected_files": ["src/shop_api/cart.py", "src/shop_api/totals.py"]},
         "policy": {"level": "act", "decision": "review: outside riskGate.maxLines", "commit": "1a2b3c4d5e6f"}}


def ei():
    import engine_issue
    return engine_issue


# ---------------- AC-124.10: the issue format ----------------

def test_the_title_has_the_documented_form_and_at_most_100_characters_ac_124_10():  # AC-124.10
    """AC-124.10: the title has the documented form and at most 100 characters."""
    assert ei().title("shop-api", "prod", "error-rate") == "[auto] [signal] error-rate: shop-api in prod"
    assert len(ei().title("c" * 80, "prod", "x" * 80)) <= 100


def test_the_labels_are_the_documented_six_ac_124_10():  # AC-124.10
    """AC-124.10: the labels are the documented six."""
    assert sorted(ei().labels("ai-ops", "prod", "high")) == sorted(["triage", "auto-filed", "signal", "engine:ai-ops", "env:prod", "criticality:high"])


def test_the_signal_label_is_one_the_platform_creates_ac_124_10():  # AC-124.10
    """AC-124.10: the signal label is one the platform creates."""
    import triage
    assert "signal" in triage.LABELS and triage.LABELS["signal"][0] == "5319e7"


def test_the_signature_is_the_first_16_hex_of_the_sha256_of_the_dedupe_key_ac_124_10():  # AC-124.10
    """AC-124.10: the signature is the first 16 hex of the sha256 of the dedupe key."""
    assert ei().signature(KEY) == "signal:" + hashlib.sha256(KEY.encode()).hexdigest()[:16]
    assert ei().signature(KEY) != ei().signature(KEY + "x")


def test_the_body_has_the_sections_in_order_and_ends_with_the_signature_ac_124_10():  # AC-124.10
    """AC-124.10: the body has the sections in order and ends with the signature."""
    body = ei().body(FACTS)
    heads = [body.index(h) for h in ("## Signal", "## Evidence", "## Triage", "## Policy")]
    assert heads == sorted(heads)
    for line in ("- component: shop-api", "- environment: prod", "- category: error-rate", "- criticality: high", f"- dedupe key: {KEY}",
                 "- seen: 3", "- first seen: 2026-10-26T07:00:00Z", "- last seen: 2026-10-26T09:12:00Z", "- engine: ai-ops",
                 "- [Grafana: error rate](https://grafana.example.com/d/abc)", "- route: fix", "- confidence: 0.82",
                 "- suspected files: src/shop_api/cart.py, src/shop_api/totals.py", "- level: act", "- decision: review: outside riskGate.maxLines"):
        assert line in body, line
    assert body.rstrip().endswith("Signature: " + ei().signature(KEY))
    assert body.count("Signature:") == 1


def test_the_body_round_trips_through_parse_ac_124_10():  # AC-124.10
    """AC-124.10: the body round trips through parse."""
    got = ei().parse(ei().body(FACTS), ei().labels("ai-ops", "prod", "high"))
    assert got == FACTS


def test_parse_reads_the_documented_example_exactly_ac_124_10():  # AC-124.10
    """AC-124.10: parse reads the documented example exactly."""
    got = ei().parse(ENGINE_BODY, ENGINE_LABELS)
    assert got == FACTS


def test_before_triage_the_triage_and_policy_sections_are_none_ac_124_10():  # AC-124.10
    """AC-124.10: before triage the triage and policy sections are none."""
    facts = dict(FACTS, triage=None, policy=None)
    body = ei().body(facts)
    assert "## Triage\n(none)" in body and "## Policy\n(none)" in body
    got = ei().parse(body, ei().labels("ai-ops", "prod", "high"))
    assert got["triage"] is None and got["policy"] is None and got["seen"] == 3 and isinstance(got["seen"], int)


def test_a_body_without_a_signal_section_parses_to_none_ac_124_10():  # AC-124.10
    """AC-124.10: a body without a signal section parses to none."""
    assert ei().parse("A human wrote this issue.\n\nSignature: alert:abc", ["triage"]) is None
    assert ei().parse("", []) is None


def test_the_body_redacts_secrets_and_keeps_evidence_as_links_only_ac_124_10():  # AC-124.10
    """AC-124.10: the body redacts secrets and keeps evidence as links only."""
    facts = dict(FACTS, dedupe_key="shop-api/prod/error-rate/mail alice@example.com failed",
                 evidence=[{"text": "log of alice@example.com", "url": "https://logs.example.com/q?id=1"}])
    body = ei().body(facts)
    assert "alice@example.com" not in body
    assert "https://logs.example.com/q?id=1" in body


def test_a_repeat_of_the_dedupe_key_adds_to_the_issue_instead_of_opening_one_ac_124_10():  # AC-124.10
    """AC-124.10: a repeat of the dedupe key adds to the issue instead of opening one."""
    new_body, comment = ei().seen_again(ENGINE_BODY, "2026-10-26T10:00:00Z")
    assert "- seen: 4" in new_body and "- last seen: 2026-10-26T10:00:00Z" in new_body
    assert "- first seen: 2026-10-26T07:00:00Z" in new_body
    assert comment == "**Seen again** (occurrence 4) at 2026-10-26T10:00:00Z"
    assert ei().parse(new_body, ENGINE_LABELS)["seen"] == 4
    assert new_body.count("Signature:") == 1 and new_body.rstrip().endswith("Signature: signal:0123456789abcdef")
    again, comment2 = ei().seen_again(new_body, "2026-10-26T11:00:00Z")
    assert "- seen: 5" in again and "(occurrence 5)" in comment2


# ---------------- AC-124.12: audit events in the run store ----------------

def test_the_audit_path_is_per_day_of_the_event_ac_124_12():  # AC-124.12
    """AC-124.12: the audit path is per day of the event."""
    ev = audit_event("merge", at="2026-10-26T09:17:33Z", eid="20261026T091733Z-ai-ops-3f9c2a71")
    assert runs_store.audit_path(ev) == "audit/2026/10/26/20261026T091733Z-ai-ops-3f9c2a71.json"


def test_read_lists_the_audit_directory_of_each_day_asked_ac_124_12(hub):  # AC-124.12
    """AC-124.12: read lists the audit directory of each day asked."""
    hub.dirs["audit/2026/10/23"] = {"a.json": "A\n"}
    hub.dirs["audit/2026/10/24"] = {"c.json": "C\n"}
    hub.dirs["runs/2026/10/24"] = {"r.json": "R\n"}
    days = [dt.date(2026, 10, 23), dt.date(2026, 10, 24)]
    got = runs_store.GitHubStore("acme/runs").read(days, prefix="audit")
    assert sorted(got) == [("audit/2026/10/23/a.json", "A\n"), ("audit/2026/10/24/c.json", "C\n")]
    assert sorted(runs_store.GitHubStore("acme/runs").read(days)) == [("runs/2026/10/24/r.json", "R\n")], "existing callers are unchanged"


def test_record_audit_writes_one_file_in_one_commit_ac_124_12(store):  # AC-124.12
    """AC-124.12: record audit writes one file in one commit."""
    ev = audit_event("pause", name="eike", at=iso(now()))
    assert runs.record_audit(ev) is None
    [put] = store.puts
    [(path, text)] = put.items()
    assert path == runs_store.audit_path(ev) and json.loads(text)["event_id"] == ev["event_id"]


def test_record_audit_scrubs_secrets_ac_124_12(store):  # AC-124.12
    """AC-124.12: record audit scrubs secrets."""
    ev = audit_event("set", name="eike", at=iso(now()), detail={"note": "contact alice@example.com"})
    runs.record_audit(ev)
    assert store.puts and "alice@example.com" not in json.dumps(store.puts)


def test_without_a_store_the_event_is_buffered_and_flushed_later_ac_124_12(monkeypatch, capsys):  # AC-124.12
    """AC-124.12: without a store the event is buffered and flushed later."""
    ev = audit_event("pause", name="eike", at=iso(now()))
    reason = runs.record_audit(ev)
    assert reason, "the reason it was only buffered"
    buf = runs.state_dir() / "audit-buffer.jsonl"
    assert json.loads(buf.read_text().splitlines()[0])["event_id"] == ev["event_id"]
    assert capsys.readouterr().out == "", "recording never prints to stdout"
    s = AutoStore()
    monkeypatch.setenv("CPLAT_RUNS_REPO", s.slug)
    monkeypatch.setattr(runs, "open_store", lambda slug: s)
    runs.flush()
    assert runs_store.audit_path(ev) in s.files
    assert not buf.exists() or buf.read_text().strip() == ""
    assert runs.buffered_count() == 0


def test_recording_never_raises_even_for_a_broken_event_or_store_ac_124_12(monkeypatch, capsys):  # AC-124.12
    """AC-124.12: recording never raises even for a broken event or store."""
    runs.record_audit({"kind": "pause"})                          # required keys missing
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")

    def boom(slug):
        raise RuntimeError("offline")
    monkeypatch.setattr(runs, "open_store", boom)
    assert runs.record_audit(audit_event("pause", name="eike", at=iso(now()))) is not None
    assert capsys.readouterr().out == ""


def test_the_audit_events_are_read_newest_first_from_the_store_and_the_buffer_ac_124_12(store, tmp_path):  # AC-124.12
    """AC-124.12: the audit events are read newest first from the store and the buffer."""
    import audit
    store.add_event(audit_event("merge", at=ago(hours=5), eid="20261026T040000Z-ai-ops-aaaaaaaa"))
    store.add_event(audit_event("rollback", at=ago(hours=1), eid="20261026T080000Z-ai-ops-bbbbbbbb"))
    runs.state_dir().mkdir(parents=True, exist_ok=True)
    (runs.state_dir() / "audit-buffer.jsonl").write_text(json.dumps(audit_event("pause", name="eike", at=ago(minutes=5), eid="20261026T085500Z-cplat-cccccccc")) + "\n")
    got = audit.read(1)
    assert [e["kind"] for e in got] == ["pause", "rollback", "merge"]


def test_audit_read_never_asks_the_engine_ac_124_12(store, engines, monkeypatch):  # AC-124.12
    """AC-124.12: audit read never asks the engine."""
    import audit
    import engine

    def forbidden(*a, **k):
        raise AssertionError("cplat reads the audit from the run store, never from the engine")
    monkeypatch.setattr(engine, "_http", forbidden)
    store.add_event(audit_event("merge", at=ago(hours=1)))
    assert len(audit.read(1)) == 1


def test_an_unreadable_store_gives_no_events_not_an_error_ac_124_12(monkeypatch):  # AC-124.12
    """AC-124.12: an unreadable store gives no events not an error."""
    import audit
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")
    monkeypatch.setattr(runs, "open_store", lambda slug: (_ for _ in ()).throw(RuntimeError("offline")))
    assert audit.read(1) == []


def test_a_person_event_has_the_documented_shape_ac_124_12():  # AC-124.12
    """AC-124.12: a person event has the documented shape."""
    import audit
    ev = audit.person_event("pause", actor="eike", system="shop", environment="prod", object={"type": "policy"}, policy={"level": "act"},
                            detail={"signal": "sig-aaaaaaaaaaaa", "confirmed": ["prod"], "unconfirmed": [], "pr": None})
    assert re.fullmatch(r"\d{8}T\d{6}Z-cplat-[0-9a-f]{8}", ev["event_id"])
    assert ev["schema"] == 1 and ev["kind"] == "pause" and ev["actor"]["type"] == "person" and ev["actor"]["name"] == "eike"
    assert ev["store_ref"] is None and ev["undoes"] is None and ev["environment"] == "prod" and ev["at"].endswith("Z")
    assert audit.person_event("undo", actor="eike", system="shop", environment="prod", object={}, policy={}, detail={}, undoes="x")["undoes"] == "x"


def test_done_on_its_own_lists_the_undoable_engine_events_of_the_last_24_hours_ac_124_12(store):  # AC-124.12
    """AC-124.12: done on its own lists the undoable engine events of the last 24 hours."""
    import audit
    evs = [audit_event(k, at=ago(hours=2), eid=f"20261026T07{i:02d}00Z-ai-ops-aaaaaaa{i}") for i, k in enumerate(["merge", "rollback", "promotion", "dismissal", "issue", "triage"])]
    evs.append(audit_event("merge", at=ago(hours=30), eid="20261025T010000Z-ai-ops-bbbbbbbb"))
    evs.append(audit_event("pause", name="eike", at=ago(hours=1), eid="20261026T080000Z-cplat-cccccccc"))
    got = audit.done_on_its_own(evs, now())
    assert sorted(e["kind"] for e in got) == ["dismissal", "merge", "promotion", "rollback"]


# ---------------- AC-124.16: who may undo ----------------

@pytest.fixture()
def model_doc(tmp_path, capsys):
    import cplat
    write_system(tmp_path, declared_system(prod={"level": "act", "engine": "https://p.example.com", "undoWindow": "48h"}))
    assert cplat.main(["model", "show", "--json", "--repo-dir", str(tmp_path)]) == 0
    return json.loads(capsys.readouterr().out)


def state(ev, model_doc, events=()):
    import audit
    return audit.undo_state(ev, model_doc, list(events), now())


@pytest.mark.parametrize("kind", ["merge", "promotion", "rollback", "dismissal"])
def test_an_engine_action_at_act_inside_the_window_may_be_undone_ac_124_16(model_doc, kind):  # AC-124.16
    """AC-124.16: an engine action at act inside the window may be undone."""
    ev = audit_event(kind, env="dev", at=ago(hours=3))
    st = state(ev, model_doc)
    assert st == {"allowed": True, "reason": None, "command": f"/system:autonomy undo {ev['event_id']}"}


def test_a_person_event_is_not_done_on_its_own_ac_124_16(model_doc):  # AC-124.16
    """AC-124.16: a person event is not done on its own."""
    st = state(audit_event("merge", name="eike", env="dev", at=ago(hours=1)), model_doc)
    assert st["allowed"] is False and st["reason"] == "not done on its own" and st["command"] is None


@pytest.mark.parametrize("kind", ["issue", "triage", "run", "signal-honoured"])
def test_other_engine_kinds_cannot_be_undone_ac_124_16(model_doc, kind):  # AC-124.16
    """AC-124.16: other engine kinds cannot be undone."""
    st = state(audit_event(kind, env="dev", at=ago(hours=1)), model_doc)
    assert st["allowed"] is False and st["reason"] == "this kind cannot be undone"


def test_an_action_below_level_act_cannot_be_undone_ac_124_16(model_doc):  # AC-124.16
    """AC-124.16: an action below level act cannot be undone."""
    st = state(audit_event("merge", env="dev", at=ago(hours=1), level="propose", effective="propose"), model_doc)
    assert st["allowed"] is False and st["reason"]


def test_the_window_is_the_environments_undo_window_ac_124_16(model_doc):  # AC-124.16
    """AC-124.16: the window is the environments undo window."""
    assert state(audit_event("merge", env="dev", at=ago(hours=25)), model_doc) == {
        "allowed": False, "reason": "the undo window of 24h has passed", "command": None}
    assert state(audit_event("merge", env="prod", at=ago(hours=30)), model_doc)["allowed"] is True, "prod declares 48h"
    assert state(audit_event("merge", env="prod", at=ago(hours=49)), model_doc)["reason"] == "the undo window of 48h has passed"


def test_an_action_that_was_undone_says_by_whom_ac_124_16(model_doc):  # AC-124.16
    """AC-124.16: an action that was undone says by whom."""
    ev = audit_event("merge", env="dev", at=ago(hours=3))
    undo = audit_event("undo", name="eike", env="dev", at=ago(hours=1), undoes=ev["event_id"], eid="20261026T080000Z-cplat-dddddddd")
    st = state(ev, model_doc, [ev, undo])
    assert st["allowed"] is False and st["reason"].startswith("already undone by eike at ")
