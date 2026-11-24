"""`triage_reporter`: what an outside reporter sees from `cplat issue triage` (spec 177).

Pure functions, no GitHub access and no clock: the fields of the issue forms, which required fields an issue body left
empty, the internal terms a comment to a reporter must not contain, and the fixed texts of the reminder and the closing.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import triage

PUBLIC_COMMANDS = ("/platform:doctor", "/issue:report")

_HEADING = re.compile(r"^### (.+?)\s*$", re.MULTILINE)
_BARE_LABELS = ("needs-info", "needs-decision", "needs-exploring", "small-change", "auto-filed", "stale-premise",
                "triaged", "p0", "p1", "p2")
_SPEC_PATTERNS = (re.compile(r"\bspec\s+\d{1,4}\b", re.IGNORECASE), re.compile(r"\b\d{3}-[a-z][a-z0-9-]+"),
                  re.compile(r"\bAC-\d+"), re.compile(r"\bADR-\d+"))
_BARE_LABEL = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in _BARE_LABELS) + r")\b", re.IGNORECASE)
_COMMAND = re.compile(r"(?<![\w/])/[a-z][a-z-]*:[a-z][a-z-]*")
_CPLAT = re.compile(r"\bcplat\b")
_THANKS = re.compile(r"\bthank", re.IGNORECASE)


def forms(root: Path) -> list[dict]:
    """The issue forms of `root/.github/ISSUE_TEMPLATE`, sorted by id; a broken file is skipped."""
    found: list[dict] = []
    directory = Path(root) / ".github" / "ISSUE_TEMPLATE"
    try:
        files = [p for p in directory.iterdir() if p.suffix in (".yml", ".yaml") and p.name != "config.yml"]
    except OSError:
        return []
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            fields = []
            for entry in data.get("body") or []:
                if entry.get("type") == "markdown":
                    continue
                label = str((entry.get("attributes") or {}).get("label") or "").strip()
                if not label:
                    continue
                required = bool((entry.get("validations") or {}).get("required"))
                fields.append({"label": label, "required": required})
            found.append({"id": path.stem, "name": str(data.get("name") or path.stem), "fields": fields})
        except (OSError, ValueError, AttributeError, TypeError, yaml.YAMLError):
            continue
    return sorted(found, key=lambda form: form["id"])


def _sections(body: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(body or ""))
    out: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        out.setdefault(match.group(1).strip().lower(), body[match.end():end].strip())
    return out


def form_of(body: str, forms: list[dict]) -> dict:
    """The form whose labels match most headings of `body` and its required fields left empty."""
    sections = _sections(body)
    best: dict | None = None
    best_count = 0
    for form in forms:
        count = sum(1 for field in form["fields"] if field["label"].strip().lower() in sections)
        if count > best_count:
            best, best_count = form, count
    if best is None:
        return {"id": None, "missing": []}
    missing = [field["label"] for field in best["fields"]
               if field["required"] and sections.get(field["label"].strip().lower(), "") in ("", "_No response_")]
    return {"id": best["id"], "missing": missing}


def internal_terms(text: str) -> list[str]:
    """The distinct internal terms of `text`, in order of first appearance."""
    hits: list[tuple[int, str]] = []
    for pattern in (*_SPEC_PATTERNS, _BARE_LABEL, _CPLAT):
        hits.extend((m.start(), m.group(0)) for m in pattern.finditer(text))
    for name in triage.LABELS:
        hits.extend((m.start(), m.group(0)) for m in re.finditer(re.escape(f"`{name}`"), text))
    hits.extend((m.start(), m.group(0)) for m in _COMMAND.finditer(text) if m.group(0) not in PUBLIC_COMMANDS)
    terms: list[str] = []
    for _, term in sorted(hits, key=lambda hit: hit[0]):
        if term not in terms:
            terms.append(term)
    return terms


def thanks(text: str) -> bool:
    """Whether `text` thanks the reporter."""
    return bool(_THANKS.search(text))


def footer(days: int) -> str:
    """The closing line of a question to a reporter."""
    return f"If there is no answer within {days} days, this issue is closed; a comment from you here reopens the review."


def final_comment(days: int) -> str:
    """The comment posted when a silent needs-info issue is closed."""
    return (f"Thanks again for the report. We asked for more details {days} or more days ago and have not heard back, "
            "so this issue is closed for now. Comment here with the details and it goes back into review.")
