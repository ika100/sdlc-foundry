"""Journey timeline (spec 181): transcript threads, the wait-call table and the exact split of one span.

  command_wait(cmd) -> kind | "wait" | None      is this Bash command a wait call, and of which kind
  read_thread(path, role=, main=) -> Thread      one transcript: span, waits, agent calls, other tool calls, person intervals
  land_evidence(threads, prs) -> [(a, b, kind)]  the deploy wait after each merge of a land call (#865)
  split(threads, evidence, a, b) -> dict         person, agents (coordinator, children) and waiting per kind, each minute once

Every minute of [a, b) is counted once, in this order: person, agents working, no-transcript repo session, a kind from
evidence (smoke first, as a smoke runs inside a deploy wait, then KINDS in order), a GitHub Actions run (CI), unattributed.
All times are epoch seconds; the split object is in minutes.
"""

import bisect
import dataclasses
import datetime as dt
import json
import re

KINDS = ("ci", "deploy", "promotion", "restore", "cluster", "smoke")
WAITING = KINDS + ("unattributed", "no_transcript")
PRIORITY = ("smoke",) + tuple(k for k in KINDS if k != "smoke")   # #865: the smoke of a land or a ship deploy is smoke

Interval = tuple[float, float]

# (regex on the command, kind or None for a wait without a kind), first row wins
_WAIT_ROWS: list[tuple[str, str | None]] = [
    (r"\bcplat\s+pr\s+wait\b", "ci"),
    (r"\bcplat\s+system\s+wait\b|\bcplat\s+component\s+ship\s+deploy\b", "deploy"),
    (r"\bcplat\s+instance\s+promote\b", "promotion"),
    (r"\bcplat\s+resource\s+(restore|backup)\b|\bcplat\s+system\s+restore\b", "restore"),
    (r"\bcplat\s+cluster\s+(wait|new|add)\b|\bdevbox\s+run\s+cluster-up\b", "cluster"),
    (r"\bcplat\s+instance\s+verify\b", "smoke"),
    (r"\bcplat\s+system\s+ship\s+next\b.*--wait\b|\bcplat\s+system\s+ship\s+land\b|\bcplat\s+component\s+ship\s+(wait|land)\b"
     r"|\bcplat\s+component\s+release\s+wait\b|\bcplat\s+spec\s+land\b|\bcplat\s+dispatch\s+wait\b|\bgh\s+run\s+watch\b"
     r"|\bgh\s+pr\s+checks\b.*--watch\b", None),
]
_LAND = re.compile(r"\bcplat\s+(system|component)\s+ship\s+land\b")
_MERGED = re.compile(r"\bmerged:?\s+(https://github\.com/[\w.-]+/[\w.-]+/pull/\d+)")
_RESUMES = re.compile(r"WAIT: (?!the checks)|resumes after the merge")   # stopped after a merge; the next call goes on
_LOOP = re.compile(r"\bsleep \d|\buntil |\bwhile true")
_LOOP_AROUND = re.compile(r"\bgh |\bcplat ")


def command_wait(cmd: str) -> str | None:
    """The kind of a wait call, "wait" for a wait without a kind, None for any other command."""
    for rx, kind in _WAIT_ROWS:
        if re.search(rx, cmd, re.S):
            return kind or "wait"
    if _LOOP.search(cmd) and _LOOP_AROUND.search(cmd):
        return "wait"
    return None


@dataclasses.dataclass
class Thread:
    role: str  # "coordinator" | "child"
    span: Interval
    waits: list[tuple[float, float, str | None]] = dataclasses.field(default_factory=list)
    agents: list[Interval] = dataclasses.field(default_factory=list)
    tools: list[Interval] = dataclasses.field(default_factory=list)
    person: list[Interval] = dataclasses.field(default_factory=list)
    lands: list["Land"] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Land:
    """One `system|component ship land` call: its span, the PRs its output says it merged, and whether it says to run again."""
    a: float
    b: float
    merged: tuple[str, ...] = ()
    resumes: bool = False


@dataclasses.dataclass
class Evidence:
    no_transcript: list[Interval] = dataclasses.field(default_factory=list)
    kinds: list[tuple[float, float, str]] = dataclasses.field(default_factory=list)
    actions: list[Interval] = dataclasses.field(default_factory=list)


def ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def read_thread(path, *, role: str, main: bool) -> Thread:
    events = []
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("timestamp"):
                    events.append(e)
    if not events:
        return Thread(role, (0.0, 0.0))
    uses: dict[str, tuple[float, str, dict]] = {}
    thread = Thread(role, (ts(events[0]["timestamp"]), ts(events[-1]["timestamp"])))
    last = None
    for e in events:
        t, content = ts(e["timestamp"]), (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if c.get("type") == "tool_use":
                    uses[c["id"]] = (t, c.get("name") or "", c.get("input") or {})
            last = t
        elif e.get("type") == "user":
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "tool_result" and c.get("tool_use_id") in uses:
                        t0, name, inp = uses.pop(c["tool_use_id"])
                        _add_call(thread, t0, t, name, inp, main, _text(c.get("content")))
            elif isinstance(content, str) and main and not e.get("isMeta") and last is not None and not content.startswith("<"):
                if t > last:
                    thread.person.append((last, t))
    return thread


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text") or "" for c in content if isinstance(c, dict))
    return ""


def _add_call(thread: Thread, a: float, b: float, name: str, inp: dict, main: bool, output: str = "") -> None:
    if name in ("Agent", "Task"):
        thread.agents.append((a, b))
    elif name == "AskUserQuestion":
        if main:
            thread.person.append((a, b))
        else:
            thread.tools.append((a, b))
    else:
        kind = command_wait(inp.get("command") or "") if name == "Bash" else None
        if kind is None:
            thread.tools.append((a, b))
        else:
            thread.waits.append((a, b, None if kind == "wait" else kind))
            if _LAND.search(inp.get("command") or ""):
                thread.lands.append(Land(a, b, tuple(dict.fromkeys(_MERGED.findall(output))), bool(_RESUMES.search(output))))


def land_evidence(threads: list[Thread], prs: dict[str, tuple[float | None, float]]) -> list[tuple[float, float, str]]:
    """#865: the post-merge part of a land call (Argo CD, operator bootstrap, the dev smokes) is a deploy wait.

    `prs` maps a PR URL to (created, merged). Each PR a land call merged, at a merge time inside the call, starts a deploy wait
    that lasts until the next PR the call merged was opened (none, if that one was opened before), else to the call's end. A
    call that stopped after a merge (its budget ran out on Argo CD or the smokes, or Argo CD timed out) hands the wait on: the
    next land call of the thread is a deploy wait from its start. The smokes inside come from the verify records and win over
    deploy (PRIORITY)."""
    out: list[tuple[float, float, str]] = []
    for th in threads:
        carry = False
        for land in sorted(th.lands, key=lambda x: x.a):
            found = sorted(((prs[u][1], prs[u][0]) for u in land.merged if u in prs and land.a <= prs[u][1] <= land.b),
                           key=lambda x: x[0])
            starts = ([land.a] if carry else []) + [merged for merged, _ in found]
            ends = [opened if opened is not None else merged for merged, opened in found[len(found) - len(starts) + 1:]]
            out += [(start, min(end, land.b), "deploy") for start, end in zip(starts, [*ends, land.b])]
            carry = land.resumes and (bool(found) or carry)
    return [(a, b, k) for a, b, k in out if b > a]


class _Set:
    """A union of intervals, sorted and merged, for membership by bisect."""

    def __init__(self, ivs):
        merged: list[list[float]] = []
        for a, b in sorted(i for i in ivs if i[1] > i[0]):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.starts = [m[0] for m in merged]
        self.ends = [m[1] for m in merged]

    def has(self, t: float) -> bool:
        i = bisect.bisect_right(self.starts, t) - 1
        return i >= 0 and t < self.ends[i]


class _Prepared:
    def __init__(self, th: Thread):
        self.role = th.role
        self.span = _Set([th.span])
        self.waits = _Set([(a, b) for a, b, _ in th.waits])
        self.agents = _Set(th.agents)
        self.tools = _Set(th.tools)
        self.person = _Set(th.person)
        self.kinds = {k: _Set([(a, b) for a, b, kk in th.waits if kk == k]) for k in KINDS}

    def works(self, t: float) -> bool:
        if not self.span.has(t) or self.waits.has(t):
            return False
        return not (self.agents.has(t) and not self.tools.has(t))


def split(threads: list[Thread], evidence: Evidence, a: float, b: float) -> dict:
    """The split object of [a, b): person, agents (coordinator, children) and waiting per kind, in minutes."""
    prepared = [_Prepared(t) for t in threads]
    person = _Set([iv for t in threads for iv in t.person])
    no_tr = _Set(evidence.no_transcript)
    actions = _Set(evidence.actions)
    kind_sets = {k: [p.kinds[k] for p in prepared] + [_Set([(x, y) for x, y, kk in evidence.kinds if kk == k])] for k in KINDS}

    points = {a, b}
    ivs: list[Interval] = list(evidence.no_transcript) + list(evidence.actions) + [(x, y) for x, y, _ in evidence.kinds]
    for t in threads:
        ivs += [t.span, *t.agents, *t.tools, *t.person, *[(x, y) for x, y, _ in t.waits]]
    for x, y in ivs:
        points.update(p for p in (x, y) if a < p < b)
    pts = sorted(points)

    out = {"person": 0.0, "coordinator": 0.0, "children": 0.0, **{k: 0.0 for k in WAITING}}
    for lo, hi in zip(pts, pts[1:]):
        m = (lo + hi) / 2
        if person.has(m):
            which = "person"
        elif any(p.role == "coordinator" and p.works(m) for p in prepared):
            which = "coordinator"
        elif any(p.works(m) for p in prepared):
            which = "children"
        elif no_tr.has(m):
            which = "no_transcript"
        else:
            which = next((k for k in PRIORITY if any(s.has(m) for s in kind_sets[k])), "ci" if actions.has(m) else "unattributed")
        out[which] += hi - lo
    mins = {k: v / 60 for k, v in out.items()}
    waiting = {k: mins[k] for k in WAITING}
    return {"wall_min": round((b - a) / 60, 2), "person_min": round(mins["person"], 2),
            "agents_min": round(mins["coordinator"] + mins["children"], 2),
            "agents": {"coordinator": round(mins["coordinator"], 2), "children": round(mins["children"], 2)},
            "waiting_min": round(sum(waiting.values()), 2), "waiting": {k: round(v, 2) for k, v in waiting.items()}}
