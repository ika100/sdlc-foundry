"""`stopgate`: one pure module decides every stop of an owned ship run (spec 126, ADR-070).

Both gates and `cplat headless` call it: who is held, how many stops passed without progress, the no-progress reason
and the cause of the escalation. Callers supply their progress mark, their code-red evidence and their wording.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import escalation_rules
import feedback

NO_PROGRESS_LIMIT = 2
EXCERPT = 200


def session_of_env() -> str | None:
    for name in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def claim(st: dict, session: str | None) -> None:
    if session:
        st["owner"] = session
    else:
        st.pop("owner", None)
    st["stop_gate"] = {}


@dataclass(frozen=True)
class Verdict:
    action: str  # "silent" | "notice" | "block" | "escalate"
    no_progress: int


def check(st: dict, session: str | None, mark: dict) -> Verdict:
    owner = st.get("owner")
    if not owner:
        return Verdict("notice", 0)
    if session != owner:
        return Verdict("silent", 0)
    prev = st.get("stop_gate") or {}
    head, phase = mark.get("head"), mark.get("phase")
    progress = not prev or prev.get("head") != head or prev.get("phase") != phase
    n = 0 if progress else int(prev.get("no_progress", 0)) + 1
    st["stop_gate"] = {"head": head, "phase": phase, "no_progress": n}
    return Verdict("escalate" if n >= NO_PROGRESS_LIMIT else "block", n)


def _entry_text(entry: object) -> str:
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return ""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(p for p in parts if isinstance(p, str) and p)


def last_message(hook_input: dict) -> str:
    direct = hook_input.get("last_assistant_message")
    if isinstance(direct, str) and direct:
        return direct
    path = hook_input.get("transcript_path")
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, ValueError):
        return ""
    for line in reversed(lines):
        try:
            text = _entry_text(json.loads(line))
        except ValueError:
            continue
        if text:
            return text
    return ""


def excerpt(message: str) -> str:
    return " ".join(feedback.redact(message or "").split())[:EXCERPT]


def no_progress_reason(phase: str, message: str) -> str:
    reason = f"no progress: {NO_PROGRESS_LIMIT} stops in phase {phase} without a new commit or phase change"
    text = excerpt(message)
    return f"{reason}; last message: {text}" if text else reason


def cause(message: str, code_red: bool) -> str:
    rule = escalation_rules.classify(message)
    if rule is not None:
        return rule.cause
    return "code" if code_red else "decision"
