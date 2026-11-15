"""`triage_facts`: the facts the triage script finds for an issue (spec 176), as pure functions.

No GitHub access: `batch`, `show` and `list --waiting` hand in normalised issues (`number`, `title`, `body`, `author`,
`authorAssociation`, `createdAt`, `labels`, `comments`) and a fixed `now`, and share this one implementation.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import claim
import engine_issue

RECENT_DAYS = 30
STOPWORDS = frozenset("the and for with from that this when not are was has have into auto signal".split())
TITLE_THRESHOLD = 0.6
ENGINE_SURE = 0.7
CLASSES = ("bug", "small-change", "feature", "question", "duplicate", "wontfix", "needs-exploring", "needs-info")
ROUTE_CLASS = {**{c: c for c in CLASSES}, "fix": "bug", "spec": "feature"}
WRITERS = ("owner", "member", "collaborator")
_ROLES = {"OWNER": "owner", "MEMBER": "member", "COLLABORATOR": "collaborator",
          "CONTRIBUTOR": "contributor", "FIRST_TIME_CONTRIBUTOR": "contributor"}
_SIGNATURE = re.compile(r"^Signature: (\S+)\s*$", re.M)
_WORDS = re.compile(r"[a-z0-9]+")
_DUPLICATE_OF = re.compile(r"Duplicate of #(\d+)")


def role(association: str | None) -> str:
    """The author role of an `authorAssociation`."""
    return _ROLES.get(association or "", "none")


def is_writer(name: str) -> bool:
    """Owner, member and collaborator can write to the repository."""
    return name in WRITERS


def age(seconds: float) -> str:
    """`<m>m` under an hour, `<h>h` under 48 hours, else `<d>d` (rounded down)."""
    s = max(int(seconds), 0)
    if s < 3600:
        return f"{s // 60}m"
    if s < 48 * 3600:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _time(text: str | None) -> datetime:
    when = datetime.fromisoformat((text or "").replace("Z", "+00:00")) if text else datetime.fromtimestamp(0, timezone.utc)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _signature(text: str | None) -> str | None:
    m = _SIGNATURE.search(text or "")
    return m.group(1) if m else None


def _words(title: str | None) -> set[str]:
    return {w for w in _WORDS.findall((title or "").lower()) if len(w) >= 3 and w not in STOPWORDS}


def duplicates(issue: dict, open_issues: list[dict], closed_issues: list[dict], now: datetime) -> list[dict]:
    """Other issues with the same signature or a similar title, sorted by number; a hint only."""
    mine, words = _signature(issue.get("body")), _words(issue.get("title"))
    recent = now - timedelta(days=RECENT_DAYS)
    found: dict[int, dict] = {}
    for state, others in (("open", open_issues), ("closed", closed_issues)):
        for other in others:
            n = other["number"]
            if n == issue["number"] or n in found:
                continue
            reason = None
            if mine and _signature(other.get("body")) == mine and (state == "open" or (
                    other.get("closedAt") and _time(other["closedAt"]) >= recent)):
                reason = "same signature"
            elif state == "open":
                theirs = _words(other.get("title"))
                shared = words & theirs
                if len(shared) >= 2 and len(shared) / len(words | theirs) >= TITLE_THRESHOLD:
                    reason = "similar title"
            if reason:
                found[n] = {"number": n, "title": other.get("title") or "", "state": state, "reason": reason}
    return [found[n] for n in sorted(found)]


def engine(issue: dict) -> dict | None:
    """Route, confidence and suspected files of an engine-filed issue, with the class proposed from the route."""
    names = [lb.get("name") for lb in issue.get("labels") or []]
    if "signal" not in names:
        return None
    parsed = engine_issue.parse(issue.get("body") or "", names)
    tri = (parsed or {}).get("triage")
    if not tri:
        return None
    cls = ROUTE_CLASS.get(tri["route"])
    sure = cls is not None and tri["confidence"] >= ENGINE_SURE
    return {"route": tri["route"], "confidence": tri["confidence"], "suspected_files": tri["suspected_files"],
            "class": cls, "mark": "sure" if sure else "check"}


def _question(issue: dict) -> dict | None:
    """The newest comment by a writer who is not the issue's author."""
    found = [c for c in issue.get("comments") or []
             if is_writer(role(c.get("authorAssociation"))) and c.get("author") != issue.get("author")]
    return max(found, key=lambda c: _time(c.get("createdAt")), default=None) if found else None


def new_since(issue: dict, reply: dict | None = None) -> list[dict]:
    """The comments after the triage question (all of them when there is none)."""
    comments = issue.get("comments") or []
    q = _question(issue)
    if q is None:
        return list(comments)
    at = _time(q.get("createdAt"))
    return [c for c in comments if _time(c.get("createdAt")) > at]


def reply(issue: dict, now: datetime) -> dict | None:
    """Answered or silent, with the age, for a `needs-info` issue."""
    if "needs-info" not in {lb.get("name") for lb in issue.get("labels") or []}:
        return None
    q = _question(issue)
    since = q.get("createdAt") if q else issue.get("createdAt")
    answers = [c for c in new_since(issue) if c.get("author") == issue.get("author")]
    if answers:
        state, start = "answered", max(_time(c.get("createdAt")) for c in answers)
    else:
        state, start = "silent", _time(since)
    return {"state": state, "age": age((now - start).total_seconds()), "since": since}


def status(issue: dict, specs: list, open_numbers: set[int] | frozenset[int], merged_prs: list[dict]) -> dict:
    """Specs tracking the issue, its claim, merged pull requests and the open issue it duplicates."""
    n = issue["number"]
    mention = re.compile(rf"#{n}(?!\d)")
    tracking = sorted((s for s in specs if n in [int(t) for t in s.meta.get("tracks") or []]), key=lambda s: s.id)
    branch = claim.holder(issue)
    prs = [{"number": p["number"], "url": p.get("url") or ""} for p in merged_prs
           if n in [r.get("number") for r in ((p.get("closingIssuesReferences") or {}).get("nodes") or [])]
           or mention.search(p.get("title") or "") or mention.search(p.get("body") or "")]
    duplicate_of = None
    for c in sorted(issue.get("comments") or [], key=lambda c: _time(c.get("createdAt")), reverse=True):
        if is_writer(role(c.get("authorAssociation"))):
            m = _DUPLICATE_OF.match(c.get("body") or "")
            if m:
                duplicate_of = int(m.group(1)) if int(m.group(1)) in open_numbers else None
                break
    return {"specs": [{"id": s.id, "number": s.number, "status": s.status} for s in tracking],
            "claim": {"branch": branch} if branch else None, "merged_prs": sorted(prs, key=lambda p: p["number"]),
            "duplicate_of": duplicate_of}


def handled(facts: dict) -> dict | None:
    """The first of spec, claim, fix and duplicate that applies, as a short line."""
    if facts["specs"]:
        s = facts["specs"][0]
        return {"kind": "spec", "line": f"in spec {s['number']} ({s['status']})"}
    if facts["claim"]:
        return {"kind": "claimed", "line": f"being worked on ({facts['claim']['branch']})"}
    if facts["merged_prs"]:
        return {"kind": "fixed", "line": f"fixed by #{max(p['number'] for p in facts['merged_prs'])}"}
    if facts["duplicate_of"]:
        return {"kind": "duplicate", "line": f"duplicate of #{facts['duplicate_of']}"}
    return None
