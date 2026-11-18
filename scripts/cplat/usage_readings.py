"""Spec 210: the machine-wide plan usage files (design.md "Usage files"). Readers never raise: a missing or broken file reads empty.

  readings() -> dict                            `readings.json` as written by the sensor ({} when missing)
  any_reading_since(epoch) -> bool              some window has a reading at or after `epoch`
  append_booked(tokens, at=None)                one `booked.jsonl` line per booking with tokens > 0
  booked_between(t0, t1) -> int                 tokens booked with t0 <= at < t1
  record_limit(until, reset_known, message, at=None)   `limit.json`; replaced only by a later `until`
  limit() -> dict | None                        the content of `limit.json`

The file functions come from `usage_sensor`, so there is one writer of the format. The tape keeps 8 days and is rewritten at most
once per local day. Times are Unix seconds.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import time
from pathlib import Path

import usage_sensor as us

TAPE_KEEP = 8 * 86400.0
MESSAGE_MAX = 300
UNKNOWN_RESET_SECONDS = 3600


def _load(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def readings() -> dict:
    return _load(us.usage_dir() / "readings.json") or {}


def any_reading_since(epoch: float) -> bool:
    try:
        for w in us.WINDOWS:
            last = (readings().get(w) or {}).get("last")
            if isinstance(last, dict) and float(last.get("at") or 0) >= epoch:
                return True
    except (AttributeError, TypeError, ValueError):
        pass
    return False


def _tape() -> Path:
    return us.usage_dir() / "booked.jsonl"


def _rows() -> list[dict]:
    rows = []
    try:
        for line in _tape().read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("at"), (int, float)) and isinstance(row.get("tokens"), int):
                rows.append(row)
    except OSError:
        pass
    return rows


def _trim(now: float) -> None:
    """Drop lines older than 8 days; at most once per local day (the mark is the day of the tape's last rewrite)."""
    mark = us.usage_dir() / "booked.trimmed"
    today = dt.date.fromtimestamp(now).isoformat()
    with contextlib.suppress(OSError):
        if mark.read_text().strip() == today:
            return
    rows = [r for r in _rows() if now - r["at"] <= TAPE_KEEP]
    path = _tape()
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    os.replace(tmp, path)
    mark.write_text(today)


def append_booked(tokens: int, at: float | None = None) -> None:
    if tokens <= 0:
        return
    try:
        now = time.time() if at is None else at
        d = us.usage_dir()
        d.mkdir(parents=True, exist_ok=True)
        with us.lock():
            if _tape().exists():
                _trim(now)
            fd = os.open(_tape(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, (json.dumps({"at": now, "tokens": int(tokens)}) + "\n").encode())
            finally:
                os.close(fd)
    except OSError:
        pass


def booked_between(t0: float, t1: float) -> int:
    return sum(r["tokens"] for r in _rows() if t0 <= r["at"] < t1)


def limit() -> dict | None:
    doc = _load(us.usage_dir() / "limit.json")
    if doc is None or not isinstance(doc.get("until"), (int, float)):
        return None
    return doc


def record_limit(until: float | None, reset_known: bool, message: str, at: float | None = None) -> None:
    try:
        now = time.time() if at is None else at
        end = until if until is not None else now + UNKNOWN_RESET_SECONDS
        with us.lock():
            cur = limit()
            if cur is not None and cur["until"] >= end:
                return
            us.write_json_atomic(us.usage_dir() / "limit.json", {
                "at": now, "until": end, "reset_known": bool(reset_known), "message": str(message)[:MESSAGE_MAX]})
    except OSError:
        pass
