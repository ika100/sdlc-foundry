"""Spec 167: the verdict of each dispatcher candidate and the order of the ready ones (design.md "Readiness", "Order").

  judge(cands, snap, state, units, policy) -> [Verdict]   `ready` or `held` with a reason, in the order of `cands`
  order(ready, priority, pins) -> [Verdict]               pins first, then the policy's rules, each only breaking a tie
  text(verdict) -> str                                    `ready`, `held: <reason> (<detail>)`, `held: skipped: <text>`
  hold_ship_busy(verdict, unit) / hold_stale(verdict, evidence) -> Verdict     applied while slots are assigned
  ship_busy_unit(units) -> str | None                     the ship unit that is not ended, if any

Pure functions over the snapshot (`dispatch_backlog.Snapshot`), the state (`dispatch_state.load`) and the unit files
(`dispatch_state.all_units`): nothing is read from GitHub or written anywhere. Reasons are checked in the order of `REASONS`; the
first that applies wins. An item whose unit is not ended is not a candidate (no verdict), nor is one whose last unit ended after the
snapshot was read: it waits for the next snapshot.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import claim
import dispatch_backlog
import dispatch_state
import spec as specmod
from dispatch_backlog import Candidate, Snapshot

REASONS = ("skipped", "needs-decision", "stuck", "claimed", "blocked", "duplicate", "needs-spec", "needs-approval", "ship-busy", "stale")
ENDED = ("done", "escalated", "stuck")
BLOCKED = re.compile(r"(?i)\b(?:blocked by|depends on)\s+#(\d+)")


@dataclass
class Verdict:
    cand: Candidate
    verdict: str                     # `ready` or `held`
    reason: str | None = None        # one of REASONS when held
    detail: str | None = None
    approve: str | None = None       # `self` for a draft the dispatcher approves itself
    labels: list[str] = field(default_factory=list)   # what `label:<name>` matches: own labels, a spec's priority and tracked issues'

    @property
    def ready(self) -> bool:
        return self.verdict == "ready"

    @property
    def key(self) -> str:
        return self.cand.key

    @property
    def item(self) -> str:
        return self.cand.item


def text(v: Verdict) -> str:
    """`ready`, `held: <reason> (<detail>)`, `held: skipped: <text>`."""
    if v.verdict == "ready":
        return "ready"
    if v.reason == "skipped":
        return f"held: skipped: {v.detail}" if v.detail else "held: skipped"
    return f"held: {v.reason} ({v.detail})" if v.detail else f"held: {v.reason}"


def _held(v: Verdict, reason: str, detail: str | None) -> Verdict:
    return replace(v, verdict="held", reason=reason, detail=detail, approve=None)


def hold_ship_busy(v: Verdict, unit: str | None) -> Verdict:
    """The candidate waits for the ship unit that runs, or for an earlier ship candidate that takes the slot in this cycle."""
    return _held(v, "ship-busy", unit)


def hold_stale(v: Verdict, evidence: str | None) -> Verdict:
    """`plan` only: the premise check found the issue resolved on main (`start` closes it instead)."""
    return _held(v, "stale", evidence)


# ---------------- units ----------------

def _seq(unit: dict) -> int:
    try:
        return int(str(unit.get("unit") or "").rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0


def _key_of(unit: dict) -> str:
    return str(unit.get("key") or dispatch_state.unit_key(str(unit.get("unit") or "")))


def _units_of(units: list[dict], key: str) -> list[dict]:
    return sorted((u for u in units if _key_of(u) == key), key=_seq)


def ship_busy_unit(units: list[dict]) -> str | None:
    """The id of a ship unit that is not ended (one ship unit at a time: the `ship-busy` reason), else None."""
    return next((str(u.get("unit")) for u in units if u.get("kind") == "ship" and u.get("status") not in ENDED), None)


def _time(s) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def _skip_item(mine: list[dict], read_at: str) -> bool:
    """True for an item with a unit that is not ended, or whose last unit ended after the snapshot was read."""
    if any(u.get("status") not in ENDED for u in mine):
        return True
    if mine and (ended := _time(mine[-1].get("ended_at"))) and (read := _time(read_at)) and ended > read:
        return True
    return False


# ---------------- the reasons ----------------

def _branch(c: Candidate) -> str:
    return f"fix/{c.key}" if c.kind == "fix" else f"feature/{c.spec_id}"


def _issue_numbers(c: Candidate) -> list[int]:
    """The issues of the candidate: itself, or the issues a spec tracks."""
    return [c.number] if c.number is not None else list(c.tracks)


def _issue_rows(c: Candidate, snap: Snapshot) -> list[dict]:
    """The open issue rows of the candidate (a spec's tracked issues that are still open)."""
    wanted = set(_issue_numbers(c))
    return [r for r in snap.issues if int(r["number"]) in wanted]


def _own_runs(units: list[dict], runs: list[dict]) -> set[str]:
    """The run ids that belong to a unit: the unit's dispatch run and every run below it (`parent` chain)."""
    own = {str(u["run_id"]) for u in units if u.get("run_id")}
    grew = True
    while grew:
        grew = False
        for r in runs:
            if r.get("run_id") not in own and r.get("parent") in own:
                own.add(str(r["run_id"]))
                grew = True
    return own


def _claimed(c: Candidate, snap: Snapshot, units: list[dict], slug: str | None) -> str | None:
    branch = _branch(c)
    for row in _issue_rows(c, snap):
        who, by_dispatch = claim.holder_by(row)
        names = {lb.get("name") if isinstance(lb, dict) else lb for lb in row.get("labels") or []}
        if claim.LABEL not in names:
            continue
        if who is None:
            return f"#{row['number']} is labelled {claim.LABEL} without a claim comment"
        if not (by_dispatch and who == branch):
            return f"#{row['number']} is claimed for {who}" + ("" if by_dispatch else " by a session")
    own = _own_runs(units, snap.runs)
    issues = set(_issue_numbers(c))
    for r in snap.runs:
        if r.get("run_id") in own:
            continue
        if (c.spec_id and r.get("spec") == c.spec_id) or (r.get("issue") is not None and r.get("issue") in issues):
            return f"run {r.get('run_id')} ({r.get('kind')}) is open for it"
    mine = {Path(str(u["worktree"])).resolve() for u in units if u.get("worktree") and _key_of(u) == c.key}
    base = dispatch_state.worktrees_dir(slug).resolve() if slug else None
    for w in snap.worktrees:
        if w.get("branch") != branch:
            continue
        path = Path(str(w["path"])).resolve()
        if path in mine or (base is not None and base in path.parents):
            continue
        return f"{branch} is checked out in {w['path']}"
    return None


def _blocked(c: Candidate, snap: Snapshot) -> str | None:
    open_numbers = {int(r["number"]) for r in snap.issues}
    for m in BLOCKED.finditer(c.text or ""):
        n = int(m.group(1))
        if n in open_numbers and n != c.number:
            return f"#{n} is open"
    return None


def _unit_pr_heads(units: list[dict]) -> set[str]:
    return {str(u["branch"]) for u in units if u.get("branch")}


def _duplicate(c: Candidate, snap: Snapshot, units: list[dict]) -> str | None:
    heads = _unit_pr_heads(units) | {_branch(c)}
    if c.kind == "fix":
        for pr in snap.prs:
            refs = {int(r.get("number")) for r in pr.get("closingIssuesReferences") or [] if str(r.get("number", "")).isdigit()}
            if c.number in refs and pr.get("headRefName") not in heads:
                return f"PR #{pr.get('number')}"
        for rec in snap.specs:
            if rec["status"] in dispatch_backlog.CANDIDATE_STATUSES and c.number in (rec.get("tracks") or []):
                return f"spec {rec['id']}"
        return None
    unit_branches = _unit_pr_heads([u for u in units if _key_of(u) == c.key])
    for pr in snap.prs:
        if pr.get("headRefName") == _branch(c) and _branch(c) not in unit_branches:
            return f"PR #{pr.get('number')}"
    return None


def _needs_spec(c: Candidate) -> bool:
    return c.kind == "fix" and "tracked" in c.labels


def _approval(c: Candidate, policy, shape: str | None) -> tuple[str, str | None, str | None]:
    """(`ready`|`held`, detail, approve) of a draft spec."""
    if policy.values["gates"]["approve_specs"] != "self":
        return "held", "gates.approve_specs: human", None
    rec = c.spec or {}
    sp = dispatch_backlog.as_spec({**rec, "plan": None})
    questions = sp.open_questions()
    if questions:
        return "held", f"open question: {questions[0]}", None
    trial = specmod.Spec(sp.dir, {**sp.meta, "status": "approved"}, sp.body, None)
    errs = specmod.check(trial, shape=shape)
    if errs:
        return "held", f"spec check: {errs[0]}", None
    return "ready", None, "self"


def _spec_hold(c: Candidate, state: dict, snap: Snapshot, units: list[dict]) -> tuple[str, str] | None:
    """`needs-decision` / `stuck` of an item: from the state (a spec without issue) or from the label of its tracked issues."""
    mine = _units_of(units, c.key)
    last = mine[-1] if mine else None
    if c.kind == "fix":
        return None   # an issue with needs-decision is no candidate at all: the label takes it out before readiness
    open_rows = _issue_rows(c, snap)
    if not c.tracks or not open_rows:
        hold = (state.get("steering") or {}).get("holds", {}).get(c.key)
        if not hold:
            return None
        unit = next((u for u in mine if u.get("unit") == hold.get("unit")), last)
        reason = str(hold.get("reason") or "")
        if reason == "stuck":
            return "stuck", str((unit or {}).get("log") or hold.get("unit") or "")
        return "needs-decision", str((unit or {}).get("reason") or reason or "")
    labelled = [r for r in open_rows if "needs-decision" in {lb.get("name") if isinstance(lb, dict) else lb for lb in r.get("labels") or []}]
    if not labelled:
        return None
    if last and last.get("status") == "stuck":
        return "stuck", str(last.get("log") or last.get("unit") or "")
    why = str(last.get("reason") or "") if last else ""
    return "needs-decision", why or f"#{labelled[0]['number']} carries needs-decision"


def _labels(c: Candidate, snap: Snapshot) -> list[str]:
    names = list(c.labels)
    if c.kind == "ship":
        if (c.spec or {}).get("priority"):
            names.append(str(c.spec["priority"]).lower())
        for row in _issue_rows(c, snap):
            names += [lb.get("name") if isinstance(lb, dict) else str(lb) for lb in row.get("labels") or []]
    return list(dict.fromkeys(n for n in names if n))


def judge(cands: list[Candidate], snap: Snapshot, state: dict, units: list[dict], policy, *, slug: str | None = None,
          shape: str | None = None) -> list[Verdict]:
    """The verdict of every candidate, in the order of `cands` (not yet in priority order). `slug` names the dispatcher's own
    worktrees (a unit branch checked out there is no `claimed`); `shape` is the repo shape for the self-approval check."""
    steering = state.get("steering") or {}
    skipped = steering.get("skipped") or {}
    out: list[Verdict] = []
    for c in cands:
        mine = _units_of(units, c.key)
        if _skip_item(mine, snap.read_at):
            continue
        v = Verdict(c, "ready", labels=_labels(c, snap))
        if c.key in skipped:
            out.append(_held(v, "skipped", str((skipped[c.key] or {}).get("reason") or "")))
            continue
        if hold := _spec_hold(c, state, snap, units):
            out.append(_held(v, *hold))
            continue
        if detail := _claimed(c, snap, units, slug):
            out.append(_held(v, "claimed", detail))
            continue
        if detail := _blocked(c, snap):
            out.append(_held(v, "blocked", detail))
            continue
        if detail := _duplicate(c, snap, units):
            out.append(_held(v, "duplicate", detail))
            continue
        if _needs_spec(c):
            out.append(_held(v, "needs-spec", None))
            continue
        if c.kind == "ship" and c.status == "draft":
            verdict, detail, approve = _approval(c, policy, shape)
            if verdict == "held":
                out.append(_held(v, "needs-approval", detail))
                continue
            v = replace(v, approve=approve)
        out.append(v)
    return out


# ---------------- the order ----------------

def _cand(x) -> Candidate:
    return x.cand if isinstance(x, Verdict) else x


def _labels_of(x) -> set[str]:
    if isinstance(x, Verdict) and x.labels:
        return set(x.labels)
    c = _cand(x)
    names = set(c.labels)
    if c.kind == "ship" and (c.spec or {}).get("priority"):
        names.add(str(c.spec["priority"]).lower())
    return names


def _spec_number(c: Candidate) -> int:
    m = re.search(r"\d+", c.key)
    return int(m.group()) if m else 0


def _created(c: Candidate) -> float:
    t = _time(c.created)
    return t.timestamp() if t else float("inf")


def _item_key(c: Candidate) -> tuple[int, int]:
    return (0 if c.kind == "fix" else 1, c.number if c.number is not None else _spec_number(c))


def _sort(items: list, rules: list[str]) -> list:
    """Order `items` by the first rule; the following rules only break the ties of the ones before; the last tie by item key."""
    if len(items) < 2:
        return list(items)
    if not rules:
        return sorted(items, key=lambda x: _item_key(_cand(x)))
    rule, rest = rules[0], rules[1:]
    if rule.startswith("label:"):
        name = rule[len("label:"):].lower()
        has = [x for x in items if name in {n.lower() for n in _labels_of(x)}]
        return _sort(has, rest) + _sort([x for x in items if x not in has], rest)
    if rule == "oldest":
        out: list = []
        for t in sorted({_created(_cand(x)) for x in items}):
            out += _sort([x for x in items if _created(_cand(x)) == t], rest)
        return out
    if rule == "spec-order":
        ordered = _sort(items, rest)
        specs = iter(sorted((x for x in ordered if _cand(x).kind == "ship"), key=lambda x: _spec_number(_cand(x))))
        return [next(specs) if _cand(x).kind == "ship" else x for x in ordered]
    return _sort(items, rest)


def order(ready: list, priority: list[str], pins: list[str] | None = None) -> list:
    """The ready items in the order they take slots: pinned ones first (`pins`, most recent first, item keys), then `priority`'s
    rules (`label:<name>`, `spec-order`, `oldest`), each only breaking a tie of those before it, a last tie by item key."""
    pins = list(pins or [])
    pinned = sorted((x for x in ready if _cand(x).key in pins), key=lambda x: pins.index(_cand(x).key))
    rest = [x for x in ready if _cand(x).key not in pins]
    return pinned + _sort(rest, list(priority))
