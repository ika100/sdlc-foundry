"""Spec 210: the filler work of mode plan, started in the last day before the weekly reset (design.md "Filler").

  split(policy, ready, filler_open) -> (regular, filler_only, held)   filler-only verdicts leave the regular order; outside the
                                            window they are held (`filler only`)
  extra(repo, slug, policy, snap, state, window_id, *, want_drafts) -> [Candidate]   the filler tasks not yet run in this window,
                                            then at most one draft of the latest `Weekly retro` issue
  window_rollover(slug, window_id)          `state.filler` tasks and drafts start again when the weekly window changes
  retro_proposals(body) -> [Proposal]       the `## Proposed specs` section of a retro issue (none without the section)
  RETRO_TITLE, MAX_DRAFTS                   the title of a retro issue; the drafts allowed in one weekly window

`state.filler = {"window", "tasks": {name: unit}, "drafts": [unit], "drafted": {"retro-<N>-<rank>": {unit, branch, pr}}}`; this
module reads it and only `window_rollover` writes it (the unit code records tasks, drafts and `drafted`). A failed read of the
retro issue raises `PlatformError`: the cycle records it as unavailable `retro`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import dispatch_backlog
import dispatch_policy
import dispatch_ready
import dispatch_state
import spec as specmod
from core import PlatformError
from dispatch_backlog import Candidate, Snapshot

RETRO_TITLE = dispatch_ready.RETRO_TITLE
ITEM = re.compile(r"^(\d+)\. \*\*(.+?)\*\* \((P\d)\)")
REQUEST = re.compile(r"`/component:spec (.+)`")
MAX_DRAFTS = 3


@dataclass
class Proposal:
    rank: int
    title: str
    priority: str
    request: str


def split(policy, ready: list[dispatch_ready.Verdict], filler_open: bool, pins: list[str] | None = None):
    """(regular, filler_only, held): in the window the filler-only verdicts stay ready, outside it they are held `filler only`.
    A pinned item (`cplat dispatch prioritize`) is regular: the pin is the owner's order to start it first."""
    regular: list = []
    filler: list = []
    held: list = []
    for v in ready:
        if v.cand.key in (pins or []) or not dispatch_policy.filler_match(policy, v.labels):
            regular.append(v)
        elif filler_open:
            filler.append(v)
        else:
            held.append(dispatch_ready.hold_filler(v))
    return regular, filler, held


# ---------------- the window ----------------

def _filler(state: dict) -> dict:
    f = state.get("filler")
    return f if isinstance(f, dict) else {}


def window_rollover(slug: str, window_id) -> None:
    """Forget the tasks and drafts of an earlier weekly window; `drafted` is kept for good."""
    def fn(st: dict) -> None:
        f = st.get("filler") if isinstance(st.get("filler"), dict) else {}
        if f.get("window") != window_id:
            st["filler"] = {"drafted": f.get("drafted") or {}, "window": window_id, "tasks": {}, "drafts": []}
    if _filler(dispatch_state.load(slug)).get("window") != window_id:
        dispatch_state.update(slug, fn)


# ---------------- the retro issue ----------------

def retro_proposals(body: str) -> list[Proposal]:
    """The proposals of the `## Proposed specs` section: rank, title, priority and the `/component:spec` request of each."""
    out: list[Proposal] = []
    inside = False
    cur: tuple[int, str, str] | None = None
    for line in (body or "").splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == "## proposed specs"
            cur = None
            continue
        if not inside:
            continue
        if m := ITEM.match(line):
            cur = (int(m.group(1)), m.group(2), m.group(3))
        elif cur and (m := REQUEST.search(line)):
            out.append(Proposal(cur[0], cur[1], cur[2], m.group(1).strip()))
            cur = None
    return out


def _latest_retro(repo, slug: str) -> dict | None:
    raw = dispatch_backlog.gh(["issue", "list", *dispatch_backlog._repo_args(slug), "--label", "retro", "--state", "all", "--limit",
                               "10", "--json", "number,title,body,createdAt"], cwd=repo)
    rows = dispatch_backlog._json(raw)
    if not isinstance(rows, list):
        raise PlatformError("gh issue list (retro) did not answer a list")
    mine = [r for r in rows if isinstance(r, dict) and RETRO_TITLE.match(str(r.get("title") or ""))]
    return max(mine, key=lambda r: str(r.get("createdAt") or "")) if mine else None


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()


def _main_titles(repo, n: int) -> set[str]:
    """The normalised titles of the specs of origin/main (any status) that track issue `n`."""
    try:
        files = dispatch_backlog._git(repo, ["grep", "-l", "-E", "^tracks:", "origin/main", "--", "docs/specs/*/spec.md"]).split()
    except PlatformError:
        return set()   # no spec tracks anything
    out: set[str] = set()
    for f in files:
        path = f.split(":", 1)[-1]
        try:
            text = dispatch_backlog._git(repo, ["show", f"origin/main:{path}"])
        except PlatformError:
            continue
        rec = dispatch_backlog._spec_record(path.split("/")[2], text, None)
        if rec and n in rec["tracks"]:
            out.add(_norm(rec["title"]))
    return out


def _answered(repo, snap: Snapshot, state: dict, n: int, p: Proposal) -> bool:
    if f"retro-{n}-{p.rank}" in (_filler(state).get("drafted") or {}):
        return True
    title = _norm(p.title)
    if any(n in (r.get("tracks") or []) and _norm(r.get("title")) == title for r in [*snap.specs, *snap.drafts]):
        return True
    if any(p.title.lower() in str(pr.get("title") or "").lower() for pr in snap.prs):
        return True
    return title in _main_titles(repo, n)


def _draft(repo, slug: str, snap: Snapshot, state: dict) -> Candidate | None:
    issue = _latest_retro(repo, slug)
    if not issue:
        return None
    n = int(issue["number"])
    for p in retro_proposals(str(issue.get("body") or "")):
        if not _answered(repo, snap, state, n, p):
            return Candidate(key=f"retro-{n}-{p.rank}", item=f"retro#{n}.{p.rank}", kind="draft", title=p.title, labels=[],
                             created=str(issue.get("createdAt") or ""), text=f"/component:spec {p.request} #{n}")
    return None


def extra(repo, slug: str, policy, snap: Snapshot, state: dict, window_id, *, want_drafts: bool) -> list[Candidate]:
    """The filler tasks that did not run in this window, then at most one draft (only with `want_drafts`: window open, slot free)."""
    plan = (policy.values.get("budget") or {}).get("plan") or {}
    f = _filler(state)
    if f.get("window") != window_id:
        f = {"drafted": f.get("drafted") or {}}   # the state is rolled over at the start of the cycle
    out = [Candidate(key=f"task-{specmod.slugify(t['name'])}", item=f"task:{t['name']}", kind="task", title=t["name"], labels=[],
                     created="", text=t["command"])
           for t in plan.get("filler_tasks") or [] if t["name"] not in (f.get("tasks") or {})]
    if not (want_drafts and plan.get("filler_drafts")) or len(f.get("drafts") or []) >= MAX_DRAFTS:
        return out
    if any(u.get("kind") == "draft" and u.get("status") not in dispatch_ready.ENDED for u in dispatch_state.all_units(slug)):
        return out
    if cand := _draft(repo, slug, snap, {**state, "filler": f}):
        out.append(cand)
    return out


__all__ = ["MAX_DRAFTS", "Proposal", "RETRO_TITLE", "extra", "retro_proposals", "split", "window_rollover"]
