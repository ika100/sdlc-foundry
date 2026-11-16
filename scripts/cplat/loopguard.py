"""The guard against a looping session (spec 202, AC-202.4, AC-202.5).

A call is one main-chain assistant message id of the session's transcript; it is idle when none of its lines holds a
`tool_use` block, judged `SETTLE` seconds after its last line. Progress is a call with `tool_use`, a growing subagent
transcript, or a change of the mark (git HEAD, ship phase, unit statuses). `Guard.observe(now)` returns the reason once
`calls` idle calls started within the last `minutes` minutes, after the last progress; then it stays tripped.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

import runs_usage
import stopgate
import transcripts
from core import PlatformError

DEFAULT = (10, 5)
CALLS = (3, 100)
MINUTES = (1, 60)
SETTLE = 3.0          # seconds after its last line that a call is judged


def parse(text: str) -> tuple[int, int]:
    """`<calls>/<minutes>` -> (calls, minutes), or a PlatformError naming the allowed values."""
    parts = (text or "").split("/")
    ok = len(parts) == 2 and all(re.fullmatch(r"[0-9]+", p) for p in parts)
    if ok:
        calls, minutes = int(parts[0]), int(parts[1])
        ok = CALLS[0] <= calls <= CALLS[1] and MINUTES[0] <= minutes <= MINUTES[1]
    if not ok:
        raise PlatformError(
            f"--loop-guard: {text} is not allowed (allowed: <calls>/<minutes>, calls an integer "
            f"{CALLS[0]}..{CALLS[1]}, minutes an integer {MINUTES[0]}..{MINUTES[1]})")
    return calls, minutes


def mark(repo: Path) -> tuple:
    """(git HEAD, ship phase, unit statuses) of the checkout; never raises."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = ""
    phase = ""
    try:
        import ship
        phase = str((ship.load_state(repo) or {}).get("phase", ""))
    except Exception:  # noqa: BLE001  (a judge that must not break the run it watches)
        pass
    statuses: tuple = ()
    try:
        import units
        statuses = tuple((r["id"], r["status"]) for r in units.rows(repo))
    except Exception:  # noqa: BLE001
        pass
    return head, phase, statuses


def _stamp(value: object, fallback: dt.datetime) -> dt.datetime:
    if not isinstance(value, str):
        return fallback
    try:
        ts = dt.datetime.fromisoformat(value)
    except ValueError:
        return fallback
    return ts.astimezone().replace(tzinfo=None) if ts.tzinfo else ts


class Guard:
    def __init__(self, calls: int, minutes: int, repo: Path, session_id: str,
                 phase: str | Callable[[], str] = "") -> None:
        self.calls, self.minutes = calls, minutes
        self.repo, self.session_id = Path(repo), session_id
        self._phase = phase
        self._path: Path | None = None
        self._offset = 0
        self._pending: dict[str, list] = {}      # message id -> [last line time, has tool_use]
        self._idle: list[dt.datetime] = []       # start times of settled idle calls since the last progress
        self._sub_size = 0
        self._mark = mark(self.repo)
        self._tripped: str | None = None

    def phase(self) -> str:
        return str(self._phase() if callable(self._phase) else self._phase)

    def observe(self, now: dt.datetime) -> str | None:
        if self._tripped:
            return self._tripped
        try:
            self._read(now)
            self._progress(now)
            self._settle(now)
        except OSError:
            return None
        window = now - dt.timedelta(minutes=self.minutes)
        n = len([t for t in self._idle if t >= window])
        if n >= self.calls:
            self._tripped = self.reason(n)
        return self._tripped

    def reason(self, n: int) -> str:
        text = f"looping: {n} model calls in {self.minutes} min without progress in phase {self.phase()}"
        message = stopgate.excerpt(stopgate.last_message({"transcript_path": str(self._path)})) if self._path else ""
        return f"{text}; last message: {message}" if message else text

    def _reset(self, now: dt.datetime) -> None:
        self._idle = []

    def _progress(self, now: dt.datetime) -> None:
        current = mark(self.repo)
        grew = False
        if self._path is not None:
            size = 0
            for f in (self._path.with_suffix("") / "subagents").glob("*.jsonl"):
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
            grew, self._sub_size = size > self._sub_size, size
        if current != self._mark or grew:
            self._mark = current
            self._reset(now)

    def _read(self, now: dt.datetime) -> None:
        if self._path is None:
            self._path = transcripts.find(self.session_id, runs_usage.projects_root())
            if self._path is None:
                return
        with self._path.open("rb") as fh:
            fh.seek(self._offset)
            data = fh.read()
        end = data.rfind(b"\n") + 1               # only complete lines
        self._offset += end
        for raw in data[:end].splitlines():
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            msg = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(msg, dict) or entry.get("type") != "assistant" or entry.get("isSidechain"):
                continue
            mid = msg.get("id")
            if not isinstance(mid, str):
                continue
            content = msg.get("content")
            tool = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
            at = _stamp(entry.get("timestamp"), now)
            call = self._pending.setdefault(mid, [at, False])
            call[0], call[1] = max(call[0], at), call[1] or tool

    def _settle(self, now: dt.datetime) -> None:
        for mid, (last, tool) in list(self._pending.items()):
            if tool:
                del self._pending[mid]
                self._reset(last)
                self._idle = [t for t in self._idle if t > last]
            elif (now - last).total_seconds() >= SETTLE:
                del self._pending[mid]
                self._idle.append(last)
