"""Spec 176 support (not a test module): a fake GitHub for `cplat issue triage`, a working tree with specs, and row builders.

The new modules (`triage_facts`, `triage_batch`, `triage_view`, `triage_act`, `triage_task`) are imported lazily through `load`, so
a missing module fails the test that needs it and not the collection of every file. Times are relative to the real clock
(`ago`), because the commands read the clock themselves.
"""
import contextlib
import importlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import claim
import triage

SLUG = "acme/shop"
REPO_LABELS = ["triage", "needs-info", "tracked", "bug", "enhancement", "question", "duplicate", "wontfix", "auto-filed", "signal",
               "triaged", "needs-decision", "stale-premise", "in-progress", "p0", "p1", "p2"]
FORBIDDEN = ("claim", "held", "dispatcher", "slot", "unit", "escalat")   # spec 192 words, design "Groups and wording"
SIG = "Signature: signal:0123456789abcdef"


def engine_body(route="fix", confidence=0.9, files=("scripts/cplat/x.py",), key="k1"):
    """The body an autonomy engine files, with its `## Triage` section."""
    import engine_issue
    return engine_issue.body({
        "component": "api", "environment": "prod", "category": "errors", "criticality": "high", "dedupe_key": key, "seen": 1,
        "first_seen": "2026-11-01", "last_seen": "2026-11-02", "engine": "monitor", "evidence": [],
        "triage": {"route": route, "confidence": confidence, "suspected_files": list(files)}, "policy": None})


def load(name):
    return importlib.import_module(name)


def iso(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(**kw):
    return iso(datetime.now(timezone.utc) - timedelta(**kw))


def comment(author, body, assoc="NONE", created=None):
    return {"author": {"login": author}, "authorAssociation": assoc, "body": body, "createdAt": created or ago(hours=1)}


def node(n, title=None, body="body", labels=("triage",), assoc="NONE", author="rep", comments=(), created=None):
    created = created or iso(datetime.now(timezone.utc) - timedelta(days=20) + timedelta(minutes=n))
    return {"number": n, "title": title or f"issue {n}", "body": body, "url": f"https://github.com/{SLUG}/issues/{n}", "createdAt": created,
            "updatedAt": created, "authorAssociation": assoc, "author": {"login": author} if author else None,
            "labels": {"nodes": [{"name": x} for x in labels]}, "comments": {"nodes": list(comments)}}


def row(n, **kw):
    base = {"number": n, "summary": f"Summary of issue {n}", "class": "bug", "priority": "P1", "priority_reason": "P1: normal bug or feature",
            "mark": "sure", "question": None, "answers": [], "expected": f"Issue {n} works", "comment": None, "spec": None,
            "duplicate_of": None}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}     # a key set to None is left out of the row


class Out:
    def __init__(self, rc, out, err):
        self.rc, self.out, self.err = rc, out, err

    @property
    def lines(self):
        return self.out.splitlines()

    def json(self):
        return json.loads(self.out)


class World:
    """The fake `gh` (installed as `triage.gh`), the working tree and the state directory of one test."""

    def __init__(self, tmp, monkeypatch):
        self.tmp, self.open, self.closed, self.merged = tmp, [], [], []
        self.total, self.errors = None, None
        self.repo_labels = list(REPO_LABELS)
        self.listing, self.view = [], None
        self.calls = []
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp / "state"))
        monkeypatch.chdir(tmp)
        monkeypatch.setattr(triage, "gh", self)
        (tmp / "docs" / "specs").mkdir(parents=True)

    # ---- the fake gh ----

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["api", "graphql"]:
            if self.errors:
                return json.dumps({"errors": [{"message": self.errors}]})
            repo = {"labels": {"nodes": [{"name": x} for x in self.repo_labels]},
                    "open": {"totalCount": self.total if self.total is not None else len(self.open), "nodes": self.open},
                    "closed": {"nodes": self.closed}, "merged": {"nodes": self.merged}}
            return json.dumps({"data": {"repository": repo}})
        if args[:2] == ["issue", "list"]:
            return json.dumps(self.listing)
        if args[:2] == ["issue", "view"]:
            if args[-1] == "labels":
                found = next((i for i in self.open if str(i["number"]) == args[2]), None)
                return json.dumps({"labels": found["labels"]["nodes"] if found else []})
            return json.dumps(self.view)
        if args[:2] == ["label", "list"]:
            return json.dumps([{"name": x} for x in self.repo_labels])
        return ""

    def writes(self):
        return [c for c in self.calls if c[:2] in (["issue", "edit"], ["issue", "comment"])]

    def edits(self):
        """{issue number: (labels added, labels removed)} of every `gh issue edit` call."""
        out = {}
        for c in self.calls:
            if c[:2] == ["issue", "edit"]:
                add = {c[i + 1] for i, x in enumerate(c) if x == "--add-label"}
                rem = {c[i + 1] for i, x in enumerate(c) if x == "--remove-label"}
                out[int(c[2])] = (add, rem)
        return out

    def comments(self):
        """{issue number: comment text} of every `gh issue comment` call."""
        return {int(c[2]): c[c.index("--body") + 1] for c in self.calls if c[:2] == ["issue", "comment"]}

    # ---- the world ----

    def issue(self, n, **kw):
        self.open.append(node(n, **kw))
        return n

    def spec(self, sid, tracks=(), status="approved", title="A spec"):
        d = self.tmp / "docs" / "specs" / sid
        d.mkdir(parents=True, exist_ok=True)
        tr = f"tracks: [{', '.join(str(t) for t in tracks)}]\n" if tracks else ""
        (d / "spec.md").write_text(f"---\nspec_id: {sid}\ntitle: {title}\nstatus: {status}\npriority: P1\nshape: platform\n{tr}---\n\n# {sid}\n")

    def proposals(self, rows, name="proposals.json"):
        path = self.tmp / name
        path.write_text(json.dumps({"rows": rows}))
        return str(path)

    # ---- the commands ----

    def run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = triage.main(["-R", SLUG, *argv])
        return Out(rc, out.getvalue(), err.getvalue())

    def batch(self, *extra):
        res = self.run("batch", "--json", *extra)
        self.data = res.json()
        return self.data

    def by_number(self, data=None):
        return {i["number"]: i for i in (data or self.data)["issues"]}

    def batch_path(self):
        return Path(self.data["batch_file"])

    def set_specs_pr(self, number=640, branch="docs/triage-2026-11-13", specs=("201-new-thing",)):
        path = self.batch_path()
        data = json.loads(path.read_text())
        data["specs_pr"] = {"number": number, "url": f"https://github.com/{SLUG}/pull/{number}", "branch": branch, "specs": list(specs)}
        path.write_text(json.dumps(data))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def overview_world(w):
    """Seven queued issues and one skipped: two to decide, three clear, two handled. Returns the rows (no row for handled issues)."""
    w.spec("176-triage-x", tracks=[548], status="approved")
    w.issue(548, title="Price alert emails are late", assoc="OWNER")
    w.issue(551, title="Export crashes", labels=("triage", "in-progress"), assoc="OWNER",
            comments=[comment("me", f"{claim.MARK}\nClaimed for branch `fix/issue-551` (cplat dispatch).", "OWNER")])
    w.issue(560, title="Login fails", assoc="CONTRIBUTOR", author="outsider")
    w.issue(562, title="Crash on empty config", assoc="OWNER")
    w.issue(563, title="Dark mode", assoc="NONE")
    w.issue(564, title="How do I rotate the token", assoc="MEMBER")
    w.issue(571, title="CSV export", assoc="COLLABORATOR")
    w.issue(12, title="Old question", labels=("needs-info",), created=ago(days=5), comments=[comment("me", "Which version?", "OWNER", ago(days=3, hours=1))])
    return [
        row(560, summary="Login fails after the token refresh on Safari", mark="check",
            question={"text": "Is the refresh failure on every browser?", "options": ["Only Safari", "All browsers"]}),
        row(562, summary="Crash when the config file is empty"),
        row(563, summary="Dark mode for the console", **{"class": "feature", "priority": "P2", "expected": None}),
        row(564, summary="How do I rotate the token", **{"class": "question", "priority": None, "priority_reason": None, "expected": None,
                                                           "comment": "Run cplat rotate."}),
        row(571, summary="Add CSV export to the run list", **{"class": "feature", "expected": None,
                                                               "question": {"text": "Which columns?", "options": ["All", "Only ids"]}}),
    ]
