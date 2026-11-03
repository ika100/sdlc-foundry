"""#355: escalations the notifier has not sent yet are signed by what they say, deduplicated and dropped when stale."""
import datetime as dt
import json

from console_support import need
from test_notify import INSTANT, World, env  # noqa: F401 - the autouse fixture

NOW = dt.datetime(2026, 11, 1, 17, 0)
RECENT = "2026-11-01T12:00:00Z"


def esc(run_id, reason, spec="013-orders", since=RECENT):
    return need("escalation", spec=spec, id=f"escalation:{run_id}", since=since, reason=reason,
                object={"type": "run", "run_id": run_id, "spec": spec})


def gh_only(tmp_path, monkeypatch):
    doc = {"events": {"escalation": {"github": "instant", "slack": "off", "email": "off", "desktop": "off"}}}
    return World(tmp_path, monkeypatch, doc, NOW)


def test_identical_messages_of_different_runs_get_one_signature_and_one_issue_355(tmp_path, monkeypatch, capsys):
    """#355: run ids, counts and times do not make a signature; one flush files the message once."""
    w = gh_only(tmp_path, monkeypatch)
    w.needs = [esc("20261027T101500Z-aaaa1111", "gave up after 8 attempts to stop in phase build"),
               esc("20261027T113000Z-bbbb2222", "gave up after 9 attempts to stop in phase build"),
               esc("20261027T120000Z-cccc3333", "budget exhausted: minutes")]
    w.once()
    creates = w.calls("issue", "create")
    assert len(creates) == 2
    state = w.state(tmp_path)["events"]
    sigs = {k: r["signature"] for k, r in state.items()}
    assert sigs["escalation:20261027T101500Z-aaaa1111"] == sigs["escalation:20261027T113000Z-bbbb2222"]
    assert sigs["escalation:20261027T120000Z-cccc3333"] != sigs["escalation:20261027T101500Z-aaaa1111"]
    assert state["escalation:20261027T113000Z-bbbb2222"]["dropped"] == "duplicate"
    assert json.loads(capsys.readouterr().err.strip().splitlines()[-1])["dropped"]["duplicate"] == 1
    w.once()
    assert len(w.calls("issue", "create")) == 2


def test_the_signature_differs_per_spec_and_stage_355(tmp_path, monkeypatch):
    """#355: the same message of another spec is another escalation."""
    w = gh_only(tmp_path, monkeypatch)
    w.needs = [esc("r1", "no progress"), esc("r2", "no progress", spec="014-stock")]
    w.once()
    assert len(w.calls("issue", "create")) == 2


def test_an_escalation_older_than_the_cutoff_is_dropped_355(tmp_path, monkeypatch, capsys):
    """#355: a notifier started days later does not post old escalations."""
    w = gh_only(tmp_path, monkeypatch)
    w.needs = [esc("r1", "gave up", since="2026-10-27T10:00:00Z"), esc("r2", "no progress")]
    w.once()
    assert len(w.calls("issue", "create")) == 1
    assert w.state(tmp_path)["events"]["escalation:r1"]["dropped"] == "stale"
    assert "1 older than 72 h" in capsys.readouterr().err
    w.once()
    assert len(w.calls("issue", "create")) == 1


def test_an_escalation_of_a_spec_that_finished_since_is_dropped_355(tmp_path, monkeypatch):
    """#355: a done run of the spec after the escalation, or the spec done in its repo, makes it stale."""
    w = gh_only(tmp_path, monkeypatch)
    w.runs = [{"run_id": "p1", "repo": "acme/shop-api", "spec": "013-orders", "phase": "done",
               "started_at": "2026-11-01T11:00:00Z", "ended_at": "2026-11-01T14:00:00Z"}]
    spec_md = "---\nid: 014-stock\nstatus: done\n---\n# Stock\n"
    base = w.gh
    w.gh = lambda args: spec_md if args[:2] == ["api", "repos/acme/shop-api/contents/docs/specs/014-stock/spec.md"] else base(args)
    monkeypatch.setattr(w.notify, "gh", w.gh)
    w.needs = [esc("r1", "gave up"), esc("r2", "no progress", spec="014-stock"), esc("r3", "no progress", spec="015-cart")]
    w.once()
    [create] = w.calls("issue", "create")
    assert "escalation: 015-cart" in create
    events = w.state(tmp_path)["events"]
    assert events["escalation:r1"]["dropped"] == events["escalation:r2"]["dropped"] == "finished"


def test_a_done_run_that_ended_before_the_escalation_does_not_drop_it_355(tmp_path, monkeypatch):
    """#355: only a run finished after the escalation counts."""
    w = gh_only(tmp_path, monkeypatch)
    w.runs = [{"run_id": "p0", "repo": "acme/shop-api", "spec": "013-orders", "phase": "done",
               "started_at": "2026-10-20T11:00:00Z", "ended_at": "2026-10-20T14:00:00Z"}]
    w.needs = [esc("r1", "gave up")]
    w.once()
    assert len(w.calls("issue", "create")) == 1


def test_an_open_notify_issue_with_the_signature_is_reused_355(tmp_path, monkeypatch):
    """#355: a fresh state file does not file an escalation a second time."""
    import notify
    w = gh_only(tmp_path, monkeypatch)
    e = esc("r1", "gave up after 8 attempts")
    ev = notify.events_of({"needs": {"items": [e]}})["escalation:r1"]
    sig = notify._signature(notify._signature_key("escalation:r1", ev))
    url = "https://github.com/acme/shop-api/issues/63"
    base = w.gh
    w.gh = lambda args: (json.dumps([{"url": url, "body": f"gave up\n\n{sig}\n"}]) if args[:2] == ["issue", "list"]
                         else base(args))
    monkeypatch.setattr(w.notify, "gh", w.gh)
    w.needs = [esc("r2", "gave up after 3 attempts")]
    w.once()
    assert not w.calls("issue", "create")
    assert w.state(tmp_path)["events"]["escalation:r2"]["sent"]["github"]["ref"] == url
