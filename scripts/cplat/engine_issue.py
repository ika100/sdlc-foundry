"""`engine_issue`: the issue an autonomy engine files from a signal (spec 124, AC-124.10).

One module owns the format: `title`, `labels`, `body`, `signature`, `parse` and `seen_again`. The engine writes
with it, `needs` and the console read with it, and the fixture tests use the same code. Every value is one line,
redacted with `autoissue.scrub`, and evidence is links only.
"""
from __future__ import annotations

import hashlib
import re

import autoissue

TITLE_LIMIT = 100
SIGNATURE_RE = re.compile(r"^Signature: (signal:[0-9a-f]{16})\s*$", re.M)
_NONE = "(none)"
_SIGNAL_KEYS = (("component", "component"), ("environment", "environment"), ("category", "category"),
                ("criticality", "criticality"), ("dedupe key", "dedupe_key"), ("seen", "seen"),
                ("first seen", "first_seen"), ("last seen", "last_seen"), ("engine", "engine"))
_EVIDENCE_RE = re.compile(r"^- \[(.*)\]\((\S*)\)\s*$")
_LABEL_FALLBACK = (("engine", "engine:"), ("environment", "env:"), ("criticality", "criticality:"))


def signature(dedupe_key: str) -> str:
    """`signal:` plus the first 16 hex of the sha256 of the dedupe key."""
    return "signal:" + hashlib.sha256(dedupe_key.encode()).hexdigest()[:16]


def title(component: str, env: str, category: str) -> str:
    """`[auto] [signal] <category>: <component> in <env>`, cut to 100 characters."""
    return f"[auto] [signal] {category}: {component} in {env}"[:TITLE_LIMIT]


def labels(engine: str, env: str, criticality: str) -> list[str]:
    """The six labels of an engine issue."""
    return ["triage", "auto-filed", "signal", f"engine:{engine}", f"env:{env}", f"criticality:{criticality}"]


def _line(value: object) -> str:
    """One redacted line."""
    return " ".join(autoissue.scrub(str(value)).split())


def _section(name: str, lines: list[str] | None) -> str:
    return f"## {name}\n" + ("\n".join(lines) if lines else _NONE)


def body(facts: dict) -> str:
    """Render the sections in the documented order, ending with the `Signature:` line."""
    signal = [f"- {label}: {_line(facts[key])}" for label, key in _SIGNAL_KEYS]
    evidence = [f"- [{_line(e['text'])}]({_line(e['url'])})" for e in facts.get("evidence") or []]
    tri, pol = facts.get("triage"), facts.get("policy")
    triage = None if not tri else [f"- route: {_line(tri['route'])}", f"- confidence: {tri['confidence']}",
                                   f"- suspected files: {', '.join(_line(f) for f in tri.get('suspected_files') or [])}"]
    policy = None if not pol else [f"- level: {_line(pol['level'])}", f"- decision: {_line(pol['decision'])}",
                                   f"- commit: {_line(pol['commit'])}"]
    parts = [_section("Signal", signal), _section("Evidence", evidence), _section("Triage", triage), _section("Policy", policy),
             f"_Filed automatically by {_line(facts['engine'])} (spec 124). Secrets were removed. Route it with /issue:triage._",
             f"Signature: {signature(facts['dedupe_key'])}"]
    return "\n\n".join(parts) + "\n"


def _sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in text.splitlines():
        if raw.startswith("## "):
            current = out.setdefault(raw[3:].strip(), [])
        elif current is not None and raw.strip() and raw.strip() != _NONE:
            current.append(raw.rstrip())
    return out


def _fields(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        m = re.match(r"^- ([^:]+): ?(.*)$", line)
        if m:
            out.setdefault(m.group(1).strip(), m.group(2).strip())
    return out


def _number(text: str, kind: type, default):
    try:
        return kind(text)
    except ValueError:
        return default


def parse(text: str, label_names: list[str]) -> dict | None:
    """The facts of an engine issue, or None when the body has no `## Signal` section."""
    sections = _sections(text or "")
    if not sections.get("Signal"):
        return None
    raw = _fields(sections["Signal"])
    facts: dict = {key: raw.get(label, "") for label, key in _SIGNAL_KEYS}
    for key, prefix in _LABEL_FALLBACK:
        if not facts[key]:
            facts[key] = next((n[len(prefix):] for n in label_names if n.startswith(prefix)), "")
    facts["seen"] = _number(facts["seen"], int, 0)
    facts["evidence"] = [{"text": m.group(1), "url": m.group(2)}
                         for m in map(_EVIDENCE_RE.match, sections.get("Evidence", [])) if m]
    tri, pol = _fields(sections.get("Triage", [])), _fields(sections.get("Policy", []))
    files = tri.get("suspected files", "")
    facts["triage"] = {"route": tri.get("route", ""), "confidence": _number(tri.get("confidence", ""), float, 0.0),
                       "suspected_files": [f.strip() for f in files.split(",") if f.strip()]} if tri else None
    facts["policy"] = {"level": pol.get("level", ""), "decision": pol.get("decision", ""),
                       "commit": pol.get("commit", "")} if pol else None
    return facts


def seen_again(text: str, at: str) -> tuple[str, str]:
    """Rewrite `- seen:` and `- last seen:` for one more occurrence and return the new body and the comment."""
    count = (parse(text, []) or {}).get("seen", 0) + 1
    new = re.sub(r"^- seen: .*$", f"- seen: {count}", text, count=1, flags=re.M)
    new = re.sub(r"^- last seen: .*$", f"- last seen: {at}", new, count=1, flags=re.M)
    return new, f"**Seen again** (occurrence {count}) at {at}"
