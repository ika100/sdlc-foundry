"""Spec 099 (ADR-035): read Claude Code session transcripts into token `Call`s. Knows nothing about runs or prices.

  find(session_id, root) -> Path | None            <root>/*/<session_id>.jsonl
  read_session(session_id, root, deadline=) -> Session   main session plus its subagents, deduped by message id
  read_project_dir(path, since=, deadline=) -> [Session]  every *.jsonl in a project directory modified since
  cwd_slug(path) -> str

Only token counts, model, role, timestamp and cwd are kept; never message content, tool fields or descriptions.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_SAFE = re.compile(r"^[A-Za-z0-9._:@/-]{1,80}$")
_CHECK_EVERY = 1000
SYNTHETIC = "<synthetic>"


@dataclass(frozen=True)
class Call:
    key: str
    at: datetime.datetime
    model: str
    failed: bool
    input: int
    output: int
    cache_read: int
    cache_write: int
    agent: str | None
    role: str
    cwd: str | None


@dataclass
class Session:
    session_id: str
    calls: list[Call] = field(default_factory=list)
    found: bool = False
    malformed: int = 0
    problems: list[str] = field(default_factory=list)


def find(session_id: str, root: Path) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", session_id or ""):
        return None
    try:
        return next(iter(sorted(Path(root).glob(f"*/{session_id}.jsonl"))), None)
    except OSError:
        return None


def cwd_slug(path: Path) -> str:
    return os.path.realpath(path).replace("/", "-").replace(".", "-")


def _safe(value: object) -> str:
    return value if isinstance(value, str) and _SAFE.match(value) else "unknown"


def _num(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _when(text: object) -> datetime.datetime | None:
    try:
        when = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _read_file(path: Path, agent: str | None, role: str, deadline: Callable[[], bool]) -> tuple[list[Call], int, bool]:
    """(calls, malformed lines, stopped by deadline). Lines with isSidechain in a main file use role `unknown`."""
    first: dict[str, tuple[datetime.datetime, bool]] = {}
    last: dict[str, dict] = {}
    cwd: str | None = None
    malformed, stopped = 0, False
    with open(path, "rb") as f:
        for n, raw in enumerate(f, 1):
            if n % _CHECK_EVERY == 0 and deadline():
                stopped = True
                break
            if not raw.endswith(b"\n"):
                break                                               # still being written
            try:
                obj = json.loads(raw)
            except ValueError:
                obj = None
            if not isinstance(obj, dict):
                malformed += 1
                continue
            if cwd is None and isinstance(obj.get("cwd"), str):
                cwd = obj["cwd"]
            msg = obj.get("message")
            if obj.get("type") != "assistant" or not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                continue
            key = msg.get("id") if isinstance(msg.get("id"), str) else obj.get("uuid")
            at = _when(obj.get("timestamp"))
            if not isinstance(key, str) or at is None:
                continue
            first.setdefault(key, (at, obj.get("isSidechain") is True))
            last[key] = {"msg": msg, "side": obj.get("isSidechain") is True}
    calls = []
    for key, item in last.items():
        msg, usage = item["msg"], item["msg"]["usage"]
        model = _safe(msg.get("model"))
        side = agent is None and item["side"]
        calls.append(Call(
            key=key, at=first[key][0], model=model, failed=msg.get("model") == SYNTHETIC,
            input=_num(usage.get("input_tokens")), output=_num(usage.get("output_tokens")),
            cache_read=_num(usage.get("cache_read_input_tokens")),
            cache_write=_num(usage.get("cache_creation_input_tokens")),
            agent="agent-sidechain" if side else agent, role="unknown" if side else role,
            cwd=cwd if agent is not None else None))
    return calls, malformed, stopped


def _read_main(main: Path, session_id: str, deadline: Callable[[], bool]) -> Session:
    out = Session(session_id, found=True)
    if deadline():
        return out
    try:
        calls, bad, stopped = _read_file(main, None, "main", deadline)
    except OSError:
        out.problems.append("main transcript unreadable")
        return out
    out.calls, out.malformed = calls, bad
    if stopped:
        return out
    subdir = main.parent / session_id / "subagents"
    try:
        files = sorted(subdir.glob("agent-*.jsonl"))
    except OSError:
        files = []
    for path in files:
        if deadline():
            break
        aid = path.stem
        role = "unknown"
        try:
            meta = json.loads(path.with_name(f"{aid}.meta.json").read_text())
            role = _safe(meta.get("agentType")) if isinstance(meta, dict) else "unknown"
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            out.problems.append(f"subagent {aid} unreadable")
        try:
            calls, bad, stopped = _read_file(path, aid, role, deadline)
        except OSError:
            out.problems.append(f"subagent {aid} unreadable")
            continue
        out.calls += calls
        out.malformed += bad
        if stopped:
            break
    return out


def read_session(session_id: str, root: Path, *, deadline: Callable[[], bool]) -> Session:
    main = find(session_id, root)
    if main is None:
        return Session(session_id, found=False)
    return _read_main(main, session_id, deadline)


def read_project_dir(path: Path, *, since: datetime.datetime, deadline: Callable[[], bool]) -> list[Session]:
    out: list[Session] = []
    try:
        files = sorted(Path(path).glob("*.jsonl"))
    except OSError:
        return out
    for f in files:
        try:
            if datetime.datetime.fromtimestamp(f.stat().st_mtime, datetime.timezone.utc) < since:
                continue
        except OSError:
            continue
        out.append(_read_main(f, f.stem, deadline))
    return out
