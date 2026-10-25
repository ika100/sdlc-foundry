"""Spec 099 (ADR-035): which calls of which Claude Code sessions belong to a run.

  register(run_id, mode=, session=, project_dir=, started_at=, dir=)   record a claim / owned source; never raises
  for_run(rec, ended_at=, budget_s=10.0, peek=False) -> dict | None    the `usage` section; never raises (peek: claims stay open)
  for_session(session_id) -> dict                                      all calls of one session; LookupError if absent
  projects_root() -> Path                                              tests replace this

The ledger `<runs.state_dir()>/usage/sources.json` lives only on this machine and is changed under `runs._locked()`.
`runs` is imported lazily: it imports this module lazily too.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

import transcripts
import usage_cost

PRUNE_AFTER = datetime.timedelta(days=2)
_FOREVER = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)


def projects_root() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(env) if env else Path.home() / ".claude") / "projects"


def _ledger_path() -> Path:
    import runs
    return runs.state_dir() / "usage" / "sources.json"


def _load() -> list[dict]:
    try:
        data = json.loads(_ledger_path().read_text())
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def _time(text: object) -> datetime.datetime | None:
    try:
        when = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _save(entries: list[dict]) -> None:
    import runs
    cutoff = runs.utcnow() - PRUNE_AFTER
    keep = [e for e in entries if not e.get("ended_at") or (_time(e["ended_at"]) or cutoff) >= cutoff]
    runs._atomic_write(_ledger_path(), json.dumps(keep, indent=1) + "\n")


def register(run_id: str, *, mode: str, session: str | None = None, project_dir: str | None = None,
             started_at: str | None = None, dir: str | None = None) -> None:
    try:
        import runs
        entry = {"run_id": run_id, "mode": mode, "session": session, "project_dir": project_dir,
                 "dir": dir or os.getcwd(), "started_at": started_at or runs._iso(runs.utcnow()), "ended_at": None}
        with runs._locked():
            _save([e for e in _load() if not (e.get("run_id") == run_id and e.get("session") == session
                                              and e.get("mode") == mode)] + [entry])
    except Exception:  # noqa: BLE001
        pass


def _mark_ended(run_id: str, ended_at: str) -> None:
    import runs
    with runs._locked():
        entries = _load()
        for e in entries:
            if e.get("run_id") == run_id and not e.get("ended_at"):
                e["ended_at"] = ended_at
        _save(entries)


def _claims(entries: list[dict], session: str, run_id: str, ended: datetime.datetime) -> list[dict]:
    """Claims on `session` as {run_id, dir, start, end}; dead live ones are left out, the finishing run ends now."""
    import runs
    out = []
    for e in entries:
        if e.get("mode") != "claim" or e.get("session") != session:
            continue
        start = _time(e.get("started_at"))
        if start is None:
            continue
        if e.get("run_id") == run_id:
            end = ended
        elif e.get("ended_at"):
            end = _time(e["ended_at"])
        elif runs.active(e.get("run_id")) is not None:
            end = _FOREVER
        else:
            continue
        if end is not None:
            out.append({"run_id": e.get("run_id"), "dir": str(e.get("dir") or ""), "start": start, "end": end})
    return out


def _owner(claims: list[dict], agent_calls: list[transcripts.Call]) -> str | None:
    first = min(c.at for c in agent_calls)
    cand = [k for k in claims if k["start"] <= first <= k["end"]]
    if not cand:
        return None
    cwd = agent_calls[0].cwd or ""
    inside = [k for k in cand if k["dir"] and (cwd == k["dir"] or cwd.startswith(k["dir"].rstrip("/") + "/"))]
    if inside:
        return max(inside, key=lambda k: len(k["dir"]))["run_id"]
    return max(cand, key=lambda k: (k["start"], k["run_id"] or ""))["run_id"]


def _phase_of(phases: list[tuple[str, datetime.datetime, datetime.datetime]], at: datetime.datetime) -> str:
    hit = [p for p in phases if p[1] <= at <= p[2]]
    if not hit:
        return "unphased"
    return max(hit, key=lambda p: (p[0].count(":"), p[1]))[0]


def _attribute(rec: dict, session: transcripts.Session, entries: list[dict], own: bool, start: datetime.datetime,
               ended: datetime.datetime) -> list[tuple]:
    """(call, share, role) of the session's calls that belong to the run."""
    run_id = rec.get("run_id")
    if own:
        return [(c, 1.0, "main" if c.agent is None else c.role) for c in session.calls if start <= c.at <= ended]
    claims = _claims(entries, session.session_id, run_id, ended)
    out: list[tuple] = []
    agents: dict[str, list[transcripts.Call]] = {}
    for c in session.calls:
        if c.agent is not None:
            agents.setdefault(c.agent, []).append(c)
        elif start <= c.at <= ended:
            n = sum(1 for k in claims if k["start"] <= c.at <= k["end"]) or 1
            out.append((c, 1 / n, "main" if n == 1 else "main (shared)"))
    for calls in agents.values():
        if _owner(claims, calls) == run_id:
            out += [(c, 1.0, c.role) for c in calls if c.at <= ended]
    return out


def _wrap(items: list[tuple], sessions: list[str], reasons: list[str], with_phase: bool) -> dict:
    prices = usage_cost.load_prices()
    out = usage_cost.section(items, prices)
    if with_phase:
        out.setdefault("by_phase", {})
    return {"sessions": sessions, "price_table": prices.taken, "incomplete": "; ".join(reasons) or None, **out}


def for_run(rec: dict, *, ended_at: str, budget_s: float = 10.0, peek: bool = False) -> dict | None:
    items: list[tuple] = []
    sessions: list[str] = []
    reasons: list[str] = []
    try:
        import runs
        run_id = rec.get("run_id")
        mine = [e for e in _load() if e.get("run_id") == run_id]
        if not mine:
            return None
        entries = _load()
        ended = _time(ended_at) or runs.utcnow()
        start = _time(rec.get("started_at")) or ended
        limit = runs.monotonic() + budget_s
        out_of_time = lambda: runs.monotonic() >= limit   # noqa: E731
        phases = [(str(p.get("name")), _time(p.get("started_at")) or start, _time(p.get("ended_at")) or ended)
                  for p in rec.get("phases") or [] if isinstance(p, dict)]
        malformed = 0
        for e in mine:
            own = e.get("mode") == "own"
            if e.get("session"):
                found = [transcripts.read_session(e["session"], projects_root(), deadline=out_of_time)]
            elif e.get("project_dir"):
                found = transcripts.read_project_dir(Path(e["project_dir"]), since=start, deadline=out_of_time)
            else:
                continue
            for s in found:
                if not s.found:
                    reasons.append(f"transcript not found: {s.session_id}")
                    continue
                if s.session_id not in sessions:
                    sessions.append(s.session_id)
                malformed += s.malformed
                reasons += s.problems
                items += [(c, share, _phase_of(phases, c.at), role)
                          for c, share, role in _attribute(rec, s, entries, own, start, ended)]
        if malformed:
            reasons.insert(0, f"{malformed} malformed lines")
        if out_of_time():
            reasons.append("time budget of 10 s used up")
        if not peek:
            _mark_ended(run_id, ended_at)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"error: {type(exc).__name__}")
    try:
        return _wrap(items, sessions, reasons, True)
    except Exception as exc:  # noqa: BLE001
        return {"sessions": sessions, "price_table": None, "incomplete": f"error: {type(exc).__name__}"}


def for_session(session_id: str) -> dict:
    session = transcripts.read_session(session_id, projects_root(), deadline=lambda: False)
    if not session.found:
        raise LookupError(f"no transcript for session {session_id} on this machine")
    reasons = ([f"{session.malformed} malformed lines"] if session.malformed else []) + session.problems
    items = [(c, 1.0, None, "main" if c.agent is None else c.role) for c in session.calls]
    return _wrap(items, [session_id], reasons, False)
