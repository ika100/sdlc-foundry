"""Spec 220 test support: an in-memory GitHub for the merge lock, the fast lane and the kept e2e (not a test file).

Contract: docs/specs/220-a-docs-only-land-does-not-wait-for-a/design.md. Nothing here touches git, GitHub or the network.

`World` fakes `gh` (PR heads, check runs with their workflow, the e2e run, `update-branch`, `merge`, `run cancel`) and the history of
the base (a list of commits with their files; a PR head knows the base commit it contains). Time is the fake clock of
hold_world_198: a check is pending until its duration has passed since its head was born, `sleep` advances the clock.
`e2e_gate.range_scope`, `change_scope`, `workflows` and `local` are replaced (the contract says tests do this); the scope of a
commit is decided here by `IN_SCOPE` (what `scripts/e2e-scope.py` would call in scope).

Other lands run "as another process" inside a hook of the clock (`World.at`), i.e. while the land under test waits for its checks:
the process id is another one while they run, and a land that has to queue stops with `Queued` at its third pause.
"""
import contextlib
import json
import os
import re
import types
from dataclasses import dataclass, field

import dispatch_state
import land_merge
import merge_lock
import pr as prmod
import runs
import ship
from hold_world_198 import SLUG, lock_is_free

OTHER_PROCESS = 5151
E2E_SECONDS = 1500          # the cluster e2e of a head (the median is 25 minutes)
CI_SECONDS = 60
IN_SCOPE = ("scripts/cplat/", "templates/gitops-app/", "tests/e2e/", "shapes.yml")
WORKFLOW_ID = {"ci": 7, "e2e": 8}
CHECK_NAME = {"ci": "ci / test", "e2e": "e2e / cluster"}
DURATION = {"ci": CI_SECONDS, "e2e": E2E_SECONDS}


class Queued(Exception):
    """A land that is not allowed to take the lock paused three times in the queue: the test sees it and goes on."""


def url_of(number: int) -> str:
    return f"https://github.com/{SLUG}/pull/{number}"


def claim_path():
    return dispatch_state.merge_lock_path(SLUG).with_name(f"{dispatch_state.slug_dir(SLUG)}.merge-claim.json")


def read_claim():
    try:
        return json.loads(claim_path().read_text())
    except (OSError, ValueError):
        return None


@dataclass
class Head:
    sha: str
    number: int
    base_idx: int                     # the last base commit this head contains
    born: float
    results: dict                     # workflow -> "pass" | "fail" | "skipping"
    cancelled: set = field(default_factory=set)


@dataclass
class PR:
    number: int
    files: tuple
    head: Head
    results: dict
    state: str = "OPEN"


class World:
    def __init__(self, monkeypatch, tmp_path, clock, said):
        import e2e_gate                                # the module of this spec: a missing module fails the test here
        self.gate = e2e_gate
        self.mp, self.clock, self.said, self.repo = monkeypatch, clock, said, tmp_path
        self.base = [("b0", ("README.md",))]
        self.prs: dict[str, PR] = {}
        self.heads: dict[str, Head] = {}
        self.rids: dict[int, tuple[Head, str]] = {}
        self.counter = 0
        self.after_update: dict[str, dict] = {}        # url -> workflow results of the head `update-branch` makes
        self.undecidable = ""                          # the range scope cannot be decided (the error text)
        self.change_undecidable = ""                   # the scope of a PR's own change cannot be decided
        self.merges: list[dict] = []
        self.updates: list[tuple[float, str, str]] = []
        self.cancels: list[int] = []
        self.events: list[tuple[str, object]] = []     # ("merge", number) / ("cancel", run id) in call order
        self.range_calls: list[tuple] = []
        self.change_calls: list[str] = []
        self.records: list[tuple] = []                 # (run id, name, item) of runs.add_to
        self.gh_calls: list[list[str]] = []
        self.merge_under_lock: list[bool] = []
        self.probing = False
        self.probe_sleeps = 0
        self._install()

    # ---- the history of the base and the PRs
    def head_sha(self) -> str:
        self.counter += 1
        return f"{self.counter:07x}" + "a" * 33

    def new_head(self, number, base_idx, results) -> Head:
        h = Head(self.head_sha(), number, base_idx, self.clock.t, dict(results))
        self.heads[h.sha] = h
        return h

    def add_pr(self, number: int, files, *, e2e="pass", ci="pass") -> str:
        """A PR whose head was judged on the current base; its checks are done (born long ago). `e2e="skipping"`: the docs PR."""
        url = url_of(number)
        results = {"ci": ci, "e2e": e2e}
        head = self.new_head(number, len(self.base) - 1, results)
        head.born = -100000.0
        self.prs[url] = PR(number, tuple(files), head, results)
        return url

    def base_moves(self, *files) -> str:
        sha = f"b{len(self.base)}"
        self.base.append((sha, tuple(files)))
        return sha

    def behind(self, head: Head) -> int:
        return len(self.base) - 1 - head.base_idx

    def head_of(self, url: str) -> Head:
        return self.prs[url].head

    def in_scope(self, files) -> list[str]:
        return [f for f in files if f.startswith(IN_SCOPE)]

    # ---- checks and runs
    def bucket(self, h: Head, wf: str) -> str:
        if wf in h.cancelled:
            return "cancel"
        result = h.results[wf]
        if result == "skipping":
            return "skipping"
        return "pending" if self.clock.t - h.born < DURATION[wf] else result

    def rid(self, h: Head, wf: str) -> int:
        n = int(h.sha[:7], 16) * 10 + (1 if wf == "ci" else 2)
        self.rids[n] = (h, wf)
        return n

    def checks_of(self, h: Head) -> list[dict]:
        rows = []
        for wf in ("ci", "e2e"):
            b = self.bucket(h, wf)
            link = "" if b == "skipping" else f"https://github.com/{SLUG}/actions/runs/{self.rid(h, wf)}/job/1"
            state = {"pass": "SUCCESS", "fail": "FAILURE", "pending": "IN_PROGRESS", "cancel": "CANCELLED", "skipping": "SKIPPED"}[b]
            rows.append({"name": CHECK_NAME[wf], "state": state, "bucket": b, "link": link, "workflow": wf})
        return rows

    def run_rows(self, h: Head) -> list[dict]:
        rows = []
        for wf in ("ci", "e2e"):
            b = self.bucket(h, wf)
            done = b != "pending"
            rows.append({"databaseId": self.rid(h, wf), "workflowDatabaseId": WORKFLOW_ID[wf], "workflowName": wf, "event": "pull_request",
                         "status": "completed" if done else "in_progress",
                         "conclusion": {"pass": "success", "fail": "failure", "cancel": "cancelled", "skipping": "skipped"}.get(b, "")})
        return rows

    # ---- gh
    def _answer(self, args) -> tuple[int, str, str]:
        self.gh_calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            pr = self.prs[args[2]]
            fields = args[args.index("--json") + 1].split(",")
            values = {"headRefOid": pr.head.sha, "baseRefName": "main", "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
                      "state": pr.state, "url": args[2], "headRefName": f"feature/{pr.number}", "isCrossRepository": False,
                      "mergeCommit": {"oid": f"merge{pr.number}"} if pr.state == "MERGED" else None}
            return 0, json.dumps({f: values.get(f) for f in fields}), ""
        if args[:2] == ["pr", "checks"]:
            if "--required" in args:
                return 0, "[]", ""
            return 0, json.dumps(self.checks_of(self.prs[args[2]].head)), ""
        if args[:2] == ["pr", "update-branch"]:
            pr = self.prs[args[2]]
            results = {**pr.results, **self.after_update.get(args[2], {})}
            old = pr.head
            pr.head = self.new_head(pr.number, len(self.base) - 1, results)
            self.updates.append((self.clock.t, args[2], pr.head.sha))
            self.events.append(("update", old.sha))
            return 0, "", ""
        if args[:2] == ["pr", "merge"]:
            pr = self.prs[args[2]]
            match = args[args.index("--match-head-commit") + 1] if "--match-head-commit" in args else None
            if match and match != pr.head.sha:
                return 1, "", "Head branch was modified. Review and try the merge again."
            self.merge_under_lock.append(not lock_is_free())
            self.merges.append({"t": self.clock.t, "pr": pr.number, "head": pr.head.sha, "behind": self.behind(pr.head),
                                "base_idx": pr.head.base_idx, "e2e_pending": self.bucket(pr.head, "e2e") == "pending"})
            self.events.append(("merge", pr.number))
            pr.state = "MERGED"
            self.base_moves(*pr.files)
            return 0, "", ""
        if args[:1] == ["api"]:
            path = next((a for a in args[1:] if a.startswith("repos/")), "")
            if "/compare/" in path:
                head = self.heads[path.split("...", 1)[1]]
                return 0, str(self.behind(head)), ""
            return 0, "", ""
        if args[:2] == ["run", "view"]:
            h, wf = self.rids[int(args[2])]
            if "headSha" in args:
                return 0, json.dumps({"headSha": h.sha}), ""
            if "workflowDatabaseId" in args:
                return 0, json.dumps({"workflowDatabaseId": WORKFLOW_ID[wf]}), ""
            return 0, "{}", ""
        if args[:2] == ["run", "list"]:
            return 0, json.dumps(self.run_rows(self.heads[args[args.index("--commit") + 1]])), ""
        if args[:2] == ["run", "cancel"]:
            h, wf = self.rids[int(args[2])]
            h.cancelled.add(wf)
            self.cancels.append(int(args[2]))
            self.events.append(("cancel", int(args[2])))
            return 0, "", ""
        return 0, "", ""

    def gh(self, args, *, cwd, check=True):
        return self._answer(args)[1]

    def run(self, cmd, cwd=None, check=True, **kw):
        if cmd and cmd[0] == "gh":
            rc, out, err = self._answer(cmd[1:])
        else:
            rc, out, err = 0, "", ""
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    # ---- the scope, as e2e_gate answers it
    def _scope(self, files) -> object:
        hits = self.in_scope(files)
        return self.gate.Scope(bool(hits), hits)

    def range_scope(self, repo, url, base, e2e_head):
        self.range_calls.append((url, base, e2e_head))
        since = self.heads[e2e_head].base_idx
        to = len(self.base) - 1
        if self.undecidable:
            return self.gate.Range(self.gate.Scope(None, [], self.undecidable), "", "", 0)
        files = [f for _, fs in self.base[since + 1:] for f in fs]
        return self.gate.Range(self._scope(files), self.base[since][0], self.base[to][0], to - since)

    def change_scope(self, repo, url, base):
        self.change_calls.append(url)
        if self.change_undecidable:
            return self.gate.Scope(None, [], self.change_undecidable)
        return self._scope(self.prs[url].files)

    # ---- wiring
    def _install(self):
        mp, clock = self.mp, self.clock
        mp.setattr(ship, "gh", self.gh)
        mp.setattr(ship, "run", self.run)
        mp.setattr(merge_lock, "run", self.run)
        mp.setattr(prmod, "run", self.run)
        mp.setattr(ship, "now", clock.monotonic)
        mp.setattr(ship, "sleep", clock.sleep)
        mp.setattr(merge_lock, "sleep", self._pause)
        mp.setattr(runs, "add_to", lambda run_id, name, item, **kw: self.records.append((run_id, name, item)))
        mp.setattr(runs, "ci_round", lambda run_id: None)
        mp.setattr(self.gate, "workflows", lambda repo: frozenset({"e2e"}))
        mp.setattr(self.gate, "local", lambda repo, slug: True)
        mp.setattr(self.gate, "range_scope", self.range_scope)
        mp.setattr(self.gate, "change_scope", self.change_scope)

    def _pause(self, seconds):
        if self.probing:
            self.probe_sleeps += 1
            if self.probe_sleeps >= 3:
                raise Queued()
        self.clock.sleep(seconds)

    # ---- running lands
    def land(self, url, *, mode=None, run_id=None):
        """What `pr wait --merge` does for the PR from its first green on: returns pr._watch's (ok, lines, section)."""
        return prmod._watch(self.repo, url, True, 3600, 10, 300, run_id, (SLUG, merge_lock.who_of(url), False), mode or land_merge.CATCH_UP)

    @contextlib.contextmanager
    def as_process(self, pid=OTHER_PROCESS):
        real = os.getpid
        self.clock.live.add(pid)
        os.getpid = lambda: pid
        try:
            yield
        finally:
            os.getpid = real

    def at(self, seconds, fn, *, queue_probe=False):
        """Run `fn()` as another process, once, in the first pause of the clock that reaches `seconds`. With `queue_probe` a pause of
        a land that queues for the lock ends it with `Queued`; the hook swallows that and keeps `fn`'s outcome in `hook.result`."""
        out = types.SimpleNamespace(result=None, queued=False, claim=None, lock_free=None, at=None)

        def hook():
            out.at = self.clock.t
            out.claim, out.lock_free = read_claim(), lock_is_free()
            self.probing, self.probe_sleeps = queue_probe, 0
            with self.as_process():
                try:
                    out.result = fn()
                except Queued:
                    out.queued = True
                finally:
                    self.probing = False
        self.clock.at(seconds, hook)
        return out

    # ---- reading the outcome
    def lines(self, ok_lines=()):
        return list(self.said) + list(ok_lines)

    def merged(self, number):
        return [m for m in self.merges if m["pr"] == number]

    def order(self):
        return [m["pr"] for m in self.merges]

    def sha7(self, sha: str) -> str:
        return sha[:7]

    def lands_item(self, run_id):
        items = [i for r, n, i in self.records if r == run_id and n == "lands"]
        assert len(items) == 1, f"expected one lands item for {run_id}, got {items}"
        return items[0]


QUEUE_LINE = re.compile(rf"^waiting for the merge lock of {re.escape(SLUG)}: held by (.+) \(waiting on its checks\) since \d\d:\d\d:\d\d$")


def fast_lane_line(a_url: str, b_url: str) -> str:
    return f"fast lane: {a_url} waits on its checks; merging {b_url} outside the e2e scope"


def kept_line(old_head: str, n: int) -> str:
    return f"e2e: kept the green e2e of {old_head[:7]}; {n} commit(s) since are outside the e2e scope"


def waiting_line(new_head: str, reason: str) -> str:
    return f"e2e: waiting for the e2e of {new_head[:7]}: {reason}"
