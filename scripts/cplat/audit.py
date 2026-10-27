# SPDX-FileCopyrightText: 2026 Eike Hensler
#
# SPDX-License-Identifier: Apache-2.0
"""Audit events of autonomy (spec 124, AC-124.7, AC-124.12, AC-124.16).

Engine and person events live in the private run store under `audit/YYYY/MM/DD/<event_id>.json`; `cplat` never asks an engine for
its history. This module reads them (store plus the local buffer), builds the events `cplat` writes itself, and decides where
Undo is allowed. Reading never raises.
"""
from __future__ import annotations

import datetime
import json
import secrets

import autonomy
import runs

SCHEMA = 1
KINDS_ENGINE = ("issue", "triage", "run", "merge", "rollback", "promotion", "dismissal", "signal-honoured")
KINDS_PERSON = ("pause", "resume", "set", "undo", "approve")
UNDOABLE = ("merge", "promotion", "rollback", "dismissal")


def _ts(value) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    except ValueError:
        return None


def _iso(when: datetime.datetime) -> str:
    return when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_store(since_days: int) -> list[dict]:
    slug = runs.configured_repo()
    if slug is None:
        return []
    try:
        today = runs.utcnow().date()
        days = [today - datetime.timedelta(days=n) for n in range(max(since_days, 0), -1, -1)]
        files = runs.open_store(slug).read(days, prefix="audit")
    except Exception:  # noqa: BLE001  (an unreadable store gives no events)
        return []
    out = []
    for _, text in files:
        for line in text.splitlines():
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict):
                out.append(doc)
    return out


def _from_buffer() -> list[dict]:
    try:
        return runs._read_audit_buffer()
    except Exception:  # noqa: BLE001
        return []


def read(since_days: int = 1) -> list[dict]:
    """The audit events of the last days from the run store and the local buffer, newest first."""
    chosen: dict[str, dict] = {}
    for ev in _from_store(since_days) + _from_buffer():
        if ev.get("event_id") and _ts(ev.get("at")) is not None:
            chosen[ev["event_id"]] = ev
    cutoff = runs.utcnow() - datetime.timedelta(days=since_days + 1)
    kept = [e for e in chosen.values() if (_ts(e["at"]) or cutoff) >= cutoff]
    return sorted(kept, key=lambda e: (str(e["at"]), str(e["event_id"])), reverse=True)


def person_event(kind: str, *, actor: str, system: str, environment: str | None, object: dict, policy: dict, detail: dict,
                 undoes: str | None = None) -> dict:
    """An audit event written by `cplat` (actor type person, no store_ref)."""
    now = runs.utcnow()
    return {"schema": SCHEMA, "event_id": f"{now.astimezone(datetime.timezone.utc):%Y%m%dT%H%M%SZ}-cplat-{secrets.token_hex(4)}",
            "at": _iso(now), "actor": {"type": "person", "name": actor, "id": actor}, "system": system,
            "environment": environment, "component": None, "kind": kind, "object": object, "policy": policy,
            "store_ref": None, "detail": detail, "undoes": undoes}


def done_on_its_own(events: list[dict], now: datetime.datetime, hours: int = 24) -> list[dict]:
    """The undoable events an engine did in the last `hours`."""
    cutoff = now - datetime.timedelta(hours=hours)
    return [e for e in events
            if (e.get("actor") or {}).get("type") == "engine" and e.get("kind") in UNDOABLE
            and (at := _ts(e.get("at"))) is not None and at >= cutoff]


def _window(model_doc: dict, environment) -> str:
    for env in model_doc.get("environments") or []:
        if env.get("name") == environment:
            return str((env.get("autonomy") or {}).get("undoWindow") or autonomy.DEFAULTS["undoWindow"])
    return str(autonomy.DEFAULTS["undoWindow"])


def _no(reason: str) -> dict:
    return {"allowed": False, "reason": reason, "command": None}


def undo_state(event: dict, model_doc: dict, events: list[dict], now: datetime.datetime) -> dict:
    """{"allowed", "reason", "command"}: may a person undo this engine event now."""
    if (event.get("actor") or {}).get("type") != "engine":
        return _no("not done on its own")
    if event.get("kind") not in UNDOABLE:
        return _no("this kind cannot be undone")
    level = (event.get("policy") or {}).get("effective")
    if level != "act":
        return _no(f"done at level {level}, only level act can be undone")
    window = _window(model_doc, event.get("environment"))
    at = _ts(event.get("at"))
    try:
        late = at is None or now - at > autonomy.parse_duration(window)
    except ValueError:
        late = True
    if late:
        return _no(f"the undo window of {window} has passed")
    for other in events:
        if other.get("undoes") == event.get("event_id"):
            who = (other.get("actor") or {}).get("name") or "someone"
            return _no(f"already undone by {who} at {other.get('at')}")
    return {"allowed": True, "reason": None, "command": f"/system:autonomy undo {event['event_id']}"}
