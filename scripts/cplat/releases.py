"""What lies between two refs of a component repo (spec 122): commits, specs, fixes, migrations, the next version, digests.

The console and `cplat needs` use it for the consequence of a promotion, the way back and Cut release. `gh` goes through
one replaceable function; nothing here raises: what cannot be read becomes `None` with a reason under `unavailable`.
"""
from __future__ import annotations

import base64
import json
import re

from core import run

SPEC_PATH = re.compile(r"^docs/specs/([^/]+)/")
SPEC_LINE = re.compile(r"^\s*(?:spec:|refs?:?)\s*(.+)$", re.IGNORECASE | re.MULTILINE)
SPEC_ID = re.compile(r"\b(\d{3,}-[a-z0-9][a-z0-9-]*)\b")
FIX_SUBJECT = re.compile(r"^fix(\([^)]*\))?!?:", re.IGNORECASE)
ISSUE_REF = re.compile(r"#(\d+)")
MIGRATION_DIRS = ("migrations/", "src/main/resources/db/migration/", "db/migrations/")
NON_ADDITIVE = re.compile(
    r"\bdrop\s+(column|table)\b|\bdrop_(column|table)\b|\brename\s+(column|to|table)\b|\brename_(column|table)\b"
    r"|\balter\s+column\b.*\b(type|set\s+data\s+type)\b|\balter_column\b.*\btype_\s*=|\bmodify\s+column\b",
    re.IGNORECASE)
BREAKING = re.compile(r"^\w+(\([^)]*\))?!:|^BREAKING[ -]CHANGE", re.MULTILINE)
TYPE = re.compile(r"^(\w+)(\([^)]*\))?(!)?:")
SEMVER = re.compile(r"^(v?)(\d+)\.(\d+)\.(\d+)")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
CRITERION = re.compile(r"^\s*[-*]\s+(?:\*\*)?AC-\d+\.\d+")


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


def _call(args: list[str]) -> tuple[str | None, str | None]:
    """(output, None) or (None, reason); never raises."""
    try:
        return gh(args), None
    except Exception as e:  # noqa: BLE001 - the caller wants a reason, not a crash
        return None, str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__


def _empty(reason: str) -> dict:
    return {"commits": None, "specs": [], "fixes": [], "criteria": None, "migrations": [], "unavailable": reason}


def _specs_of(messages: list[str], files: list[dict]) -> list[str]:
    found: list[str] = []
    for f in files:
        m = SPEC_PATH.match(f.get("filename", ""))
        if m and m.group(1) not in found:
            found.append(m.group(1))
    for msg in messages:
        for line in SPEC_LINE.findall(msg):
            for sid in SPEC_ID.findall(line):
                if sid not in found:
                    found.append(sid)
    return found


def _fixes_of(messages: list[str]) -> list[str]:
    fixes: list[str] = []
    for msg in messages:
        if FIX_SUBJECT.match(msg.splitlines()[0] if msg else ""):
            fixes.extend(f"#{n}" for n in ISSUE_REF.findall(msg) if f"#{n}" not in fixes)
    return fixes


def additive(patch: str) -> bool:
    """False when the added lines drop or rename a column or table, or alter a type."""
    added = [ln[1:] for ln in (patch or "").splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    return not any(NON_ADDITIVE.search(ln) for ln in added)


def _migrations_of(files: list[dict]) -> list[dict]:
    out = []
    for f in files:
        name = f.get("filename", "")
        if f.get("status") == "added" and any(name.startswith(d) or f"/{d}" in name for d in MIGRATION_DIRS):
            out.append({"file": name, "additive": additive(f.get("patch", ""))})
    return out


def _criteria_count(repo_slug: str, spec_id: str, ref: str) -> int:
    out, _ = _call(["api", f"repos/{repo_slug}/contents/docs/specs/{spec_id}/spec.md?ref={ref}",
                    "-H", "Accept: application/vnd.github.raw"])
    text = out or ""
    if text and not text.lstrip().startswith("#"):    # a contents document instead of the raw file
        try:
            text = base64.b64decode(json.loads(text).get("content", "")).decode("utf-8", "replace")
        except (ValueError, AttributeError):
            pass
    return sum(1 for ln in text.splitlines() if CRITERION.match(ln) and "~~" not in ln)


def between(repo_slug: str, base: str, head: str) -> dict:
    """Commits, specs, fixes, criteria and migrations of `base...head`; `commits` is None (with `unavailable`) on failure."""
    out, why = _call(["api", f"repos/{repo_slug}/compare/{base}...{head}"])
    if out is None:
        return _empty(why or "unreadable")
    try:
        doc = json.loads(out)
        commits = doc.get("commits") or []
        messages = [(c.get("commit") or {}).get("message", "") for c in commits]
        files = doc.get("files") or []
        specs = _specs_of(messages, files)
        result = {"commits": len(commits), "specs": specs, "fixes": _fixes_of(messages),
                  "criteria": sum(_criteria_count(repo_slug, s, head) for s in specs),
                  "migrations": _migrations_of(files), "subjects": [m.splitlines()[0] if m else "" for m in messages]}
        return result
    except (ValueError, AttributeError, TypeError) as e:
        return _empty(f"unreadable compare document: {e}")


def next_version(last_tag: str, commit_subjects: list[str]) -> str:
    """The next version by conventional commits: `!`/`BREAKING` major, `feat` minor, otherwise patch. Keeps a `v` prefix."""
    m = SEMVER.match(last_tag or "")
    prefix, major, minor, patch = (m.group(1), *map(int, m.groups()[1:])) if m else ("", 0, 0, 0)
    if any(BREAKING.search(s) for s in commit_subjects):
        return f"{prefix}{major + 1}.0.0"
    if any((TYPE.match(s) or [None, ""])[1].lower() == "feat" for s in commit_subjects):
        return f"{prefix}{major}.{minor + 1}.0"
    return f"{prefix}{major}.{minor}.{patch + 1}"


def previous_release(repo_slug: str, current: str) -> str | None:
    """The release tag before `current` (the way back), or None."""
    out, _ = _call(["api", f"repos/{repo_slug}/releases?per_page=100"])
    try:
        tags = [r.get("tag_name", "") for r in json.loads(out or "[]") if not r.get("draft")]
    except (ValueError, AttributeError):
        return None
    norm = current.lstrip("v")
    for i, t in enumerate(tags):
        if t.lstrip("v") == norm:
            return tags[i + 1] if i + 1 < len(tags) else None
    return None


def digest(repo_slug: str, tag: str) -> str | None:
    """The image digest recorded in the body of release `tag`, or None."""
    out, _ = _call(["api", f"repos/{repo_slug}/releases/tags/{tag}"])
    try:
        body = json.loads(out or "{}").get("body") or ""
    except (ValueError, AttributeError):
        return None
    m = SHA256.search(body)
    return m.group(0) if m else None
