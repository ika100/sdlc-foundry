"""Spec 099: helpers shared by the usage acceptance tests (synthetic transcripts, a run with phases, record sums)."""
import datetime as dt
import json
from pathlib import Path

import pytest

import runs

T0 = dt.datetime(2026, 10, 24, 8, 0, 0, tzinfo=dt.timezone.utc)
OPUS = "claude-opus-4-5"
FIELDS = ("calls", "failed_calls", "input", "output", "cache_read", "cache_write")
SESSION = "11111111-2222-3333-4444-555555555555"


def ts(sec: float) -> str:
    return (T0 + dt.timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int((sec % 1) * 1000):03d}Z"


def iso(sec: float) -> str:
    return (T0 + dt.timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def call(mid, sec, *, model=OPUS, i=10, o=20, cr=100, cw=5, cwd=None, text="hello"):
    """One transcript line of an assistant message (with some content that must never be stored)."""
    line = {"type": "assistant", "uuid": f"u-{mid}-{sec}", "timestamp": ts(sec),
            "message": {"id": mid, "model": model, "role": "assistant",
                        "content": [{"type": "text", "text": text}],
                        "usage": {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr,
                                  "cache_creation_input_tokens": cw}}}
    if cwd:
        line["cwd"] = str(cwd)
    return line


def write_session(root: Path, sid: str, main=(), subagents=None, *, slug="-proj", raw_tail="", raw_head=""):
    """<root>/<slug>/<sid>.jsonl plus <root>/<slug>/<sid>/subagents/agent-<id>.jsonl (+ .meta.json).
    subagents: {agent_id: (meta dict, [lines])}. raw_head / raw_tail: text put before / after the main lines."""
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.jsonl").write_text(raw_head + "".join(json.dumps(x) + "\n" for x in main) + raw_tail)
    for aid, (meta, lines) in (subagents or {}).items():
        sd = d / sid / "subagents"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / f"agent-{aid}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
        (sd / f"agent-{aid}.meta.json").write_text(json.dumps(meta))


@pytest.fixture()
def projects(tmp_path, monkeypatch):
    """A fake ~/.claude/projects, and a Claude Code session id for runs started in this test."""
    import runs_usage
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(runs_usage, "projects_root", lambda: root)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    return root


def run_with_phases(clock, store, phases, end, *, kind="ship", outcome="done", sid=SESSION, **kw):
    """Start a run at T0, open each (name, at_sec) phase at its time, finish at `end` seconds. Returns the record."""
    clock.now = T0
    rid = runs.start(kind, repo="acme/shop-api", spec=kw.pop("spec", None))
    for name, at in phases:
        clock.now = T0 + dt.timedelta(seconds=at)
        runs.phase(rid, name)
    clock.now = T0 + dt.timedelta(seconds=end)
    runs.finish(rid, outcome, **kw)
    return next(r for r in stored_records(store) if r["run_id"] == rid)


def stored_records(store):
    out = [json.loads(t) for p, t in sorted(store.files.items()) if ".filed." not in p]
    return sorted(out, key=lambda r: r["ended_at"])


def assert_sums_equal_totals(usage):
    """AC-099.1: by_phase, by_role and by_model each sum to totals (known costs, within 1e-6)."""
    t = usage["totals"]
    for key in ("by_phase", "by_role", "by_model"):
        for f in FIELDS:
            assert sum(b[f] for b in usage[key].values()) == pytest.approx(t[f], abs=1e-6), (key, f)
        known = sum(b["cost_usd"] for b in usage[key].values() if b["cost_usd"] != "unknown")
        assert known == pytest.approx(t["cost_usd"], abs=1e-6), (key, "cost_usd")
