"""Spec 193 test world: the `cplat next` world of spec 192 plus the dispatcher's local files (policy, state, unit worktrees) and
a replaceable queue (`dispatch_cycle.preview`). New modules and functions are reached lazily, so a missing one fails the test that
needs it and nothing else.

The dispatcher world of spec 167 (`dispatch_world`) is used by the verb tests; this file is for the screens."""
import json
import os
import subprocess
from pathlib import Path

import support_192 as s192
from support_192 import NOW, World, option, question  # noqa: F401  (re-exported)

LOCAL = NOW.replace(tzinfo=None)          # the dispatcher's clock: local, naive
DAY = LOCAL.strftime("%Y-%m-%d")
POLICY_TEXT = """# The run queue's policy (docs/dispatch.md), written by /platform:next.
budget:
  tokens_per_day: {n}
sources: [issues, specs]
gates:
  approve_specs: human
"""


def local_stamp(minutes_ago: float = 0) -> str:
    import datetime
    return (LOCAL - datetime.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def utc_stamp(minutes_ago: float = 0) -> str:
    import datetime
    return (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry(n, ref, *, kind="fix", title=None, spec=None, tracks=(), after=None):
    """One element of `dispatch_cycle.preview` (design.md contract)."""
    key = f"issue-{ref.lstrip('#')}" if ref.startswith("#") else f"spec-{ref.split()[-1]}"
    return {"n": n, "key": key, "item": ref if ref.startswith("#") else key, "ref": ref, "kind": kind,
            "title": title or f"Title of {ref}", "spec": spec, "tracks": list(tracks), "after": after}


class BuildWorld(World):
    def __init__(self, tmp_path, monkeypatch, shape="platform", policy=True):
        super().__init__(tmp_path, monkeypatch, shape=shape)
        import dispatch_state
        self.ds = dispatch_state
        monkeypatch.setattr(dispatch_state, "now", lambda: LOCAL)
        self._git_id = ["-c", "user.name=t", "-c", "user.email=t@t"]
        if policy:
            self.write_policy()

    # ---- the repo ----

    def write_policy(self, tokens=20_000_000):
        (self.repo / ".platform").mkdir(exist_ok=True)
        (self.repo / ".platform" / "dispatch.yml").write_text(POLICY_TEXT.format(n=tokens))

    def queue(self, *entries):
        """Replace the read-only twin of `plan` (`dispatch_cycle.preview`) with these entries."""
        import dispatch_cycle
        rows = list(entries)
        self.mp.setattr(dispatch_cycle, "preview", lambda repo, policy: [dict(r) for r in rows], raising=False)

    def hint(self, *tokens):
        import dispatch_budget
        days = [{"day": f"2026-11-{8 + i:02d}", "tokens": t} for i, t in enumerate(tokens)]
        self.mp.setattr(dispatch_budget, "history_hint", lambda slug, days_=7, **k: days, raising=False)

    def commit(self, name, text, msg):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self._git("add", "-A")
        self._git(*self._git_id, "commit", "-qm", msg)

    def read_head(self) -> str:
        """The head sha; `origin/main` points at it (the world has no real remote)."""
        sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        self._git("update-ref", "refs/remotes/origin/main", sha)
        return sha

    def tag(self, name, when="2026-11-14T09:50:00"):
        env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", str(self.repo), "tag", "-a", name, "-m", name], check=True, capture_output=True, env=env)

    def fragment(self, name, text):
        d = self.repo / "docs" / "changelog.d"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)
        self._git("add", "-A")
        self._git(*self._git_id, "commit", "-qm", f"fragment {name}")

    # ---- the dispatcher state ----

    def state(self, fn):
        self.ds.update(self.slug, fn)

    def read_state(self) -> dict:
        return self.ds.load(self.slug)

    def history(self, kind, minutes, tokens, n=1, outcome="done"):
        def go(st):
            for i in range(n):
                st["history"].append({"unit": f"{kind}-{len(st['history'])}.1", "item": "#1", "kind": kind, "outcome": outcome,
                                      "pr": None, "tokens": tokens, "reason": None,
                                      "started_at": f"2026-11-1{i}T08:00:00", "ended_at": self._plus(f"2026-11-1{i}T08:00:00", minutes)})
        self.state(go)

    @staticmethod
    def _plus(stamp, minutes):
        import datetime
        return (datetime.datetime.fromisoformat(stamp) + datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")

    def used(self, tokens):
        self.state(lambda st: st["ledger"].__setitem__(DAY, {"units": {"x.1": tokens}, "agent": 0}))

    def build(self, started="2026-11-14T09:00:00", slots=2):
        self.state(lambda st: st.__setitem__("build", {"started_at": started, "slots": slots}))
        self.state(lambda st: st["steering"].update(slots=slots))

    def event(self, kind, item, at, *, unit=None, pr=None, reason=None):
        def go(st):
            seq = max([e["seq"] for e in st["events"]] + [0]) + 1
            st["event_seq"] = seq
            st["events"].append({"seq": seq, "at": at, "kind": kind, "unit": unit or f"{item}.1", "item": item, "reason": reason,
                                 "pr": pr, "seen": False})
        self.state(go)

    def counted(self, unit, tokens):
        self.state(lambda st: st["counted"].__setitem__(unit, tokens))

    def skipped(self, key, reason):
        self.state(lambda st: st["steering"]["skipped"].__setitem__(key, {"reason": reason, "at": local_stamp(30)}))

    def unit(self, key, status="running", *, kind=None, starts=1, land_starts=0, cause=None, reason=None, ship=None, pid=None):
        """A unit worktree under the dispatcher's state dir with its unit file (and the ship state of a ship unit)."""
        kind = kind or ("fix" if key.startswith("issue") else "ship")
        wt = self.ds.worktree_path(self.slug, key)
        wt.parent.mkdir(parents=True, exist_ok=True)
        branch = f"feature/{ship['spec']}" if ship else f"dispatch/{key}"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", branch, str(wt)], check=True, capture_output=True)
        log = self.ds.log_path(self.slug, f"{key}.1")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("AGENT-OUTPUT-SENTINEL: the agent thought about the problem\n")
        item = f"#{key.split('-')[1]}" if key.startswith("issue") else key
        unit = {"unit": f"{key}.1", "item": item, "key": key, "kind": kind, "mode": "single", "branch": branch, "worktree": str(wt),
                "slot": 1, "pid": pid or os.getpid(), "land_pid": None, "log": str(log), "starts": starts, "land_starts": land_starts,
                "run_id": f"run-{key}", "status": status, "pr": None, "started_at": local_stamp(90), "ended_at": None,
                "reason": reason, "cause": cause, "tokens": None, "spec": ship.get("spec") if ship else None, "tracks": []}
        self.ds.write_unit(wt, unit)
        if ship is not None:
            import ship as shipmod
            shipmod.state_path(wt).write_text(json.dumps(ship))
        return wt

    def stop_item(self, key, kind="escalation", minutes_ago=125, *, spec_id=None, reason="the run needs a decision"):
        """The needs item the dispatcher wrote for a stop (`<state>/needs.json`)."""
        number = int(key.split("-")[1])
        obj = {"type": "issue" if key.startswith("issue") else "run", "repo": self.slug, "issue": number if key.startswith("issue") else None,
               "spec": spec_id, "run_id": None, "component": None, "version": None, "pr": None, "url": None}
        self.dispatch_item({"id": f"{kind}:{self.slug}:{key}", "kind": kind, "stage": "Build", "since": utc_stamp(minutes_ago),
                            "reason": reason, "command": f"cplat dispatch resume {key}", "object": obj, "cwd_repo": self.slug,
                            "consequence": None, "way_back": None})

    def loop_runs(self):
        """Hold the loop lock the way a running build loop does (a context manager)."""
        return self.ds.loop_lock(self.slug)

    def person(self, *refs, minutes=7.0):
        import runs
        parts = [tuple(r.split(":", 2)) for r in refs]
        calls = max(1, -(-int(minutes) // 10))  # one record carries at most 10 minutes
        for _ in range(calls):
            runs.person_answer(shown_at=utc_stamp(20), answered_at=utc_stamp(10), option="x", refs=parts,
                               minutes_total=minutes / calls)

    def judgement(self, tmp_path, items):
        p = Path(tmp_path) / "judgement.json"
        p.write_text(json.dumps({"items": items}))
        return str(p)

    # ---- the fake gh: closed issues ----

    def closed_issue(self, number, title="done"):
        self.issues.append({"number": number, "title": title, "createdAt": "2026-11-12T08:00:00Z", "state": "CLOSED", "labels": [],
                            "url": f"https://github.com/{self.slug}/issues/{number}", "body": ""})

    def _gh(self, args):
        a = list(args)
        if a[:2] == ["issue", "view"]:
            self.gh_calls.append(a)
            row = next((i for i in self.issues if str(i["number"]) == a[2]), None)
            return json.dumps(row) if row else "null"
        if a[:2] == ["issue", "list"]:
            self.gh_calls.append(a)
            want = a[a.index("--state") + 1] if "--state" in a else "open"
            rows = [i for i in self.issues if want == "all" or (i.get("state", "OPEN").lower() == want)]
            return json.dumps(rows)
        return super()._gh(args)

    def text(self, capsys, *args, **kw) -> str:
        return self.screen(capsys, *args, **kw)


def section(screen: str, title: str) -> str:
    """The lines of `screen` from the line `title` to the next blank line."""
    lines = screen.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == title or ln.startswith(title))
    out = []
    for ln in lines[start:]:
        if not ln.strip():
            break
        out.append(ln)
    return "\n".join(out)


def labels(q):
    return [o["label"] for o in q["options"]]


def by_label(q, label):
    return next(o for o in q["options"] if o["label"].startswith(label))
