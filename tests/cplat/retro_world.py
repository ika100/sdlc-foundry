"""Spec 090: shared data and fakes of the retro tests (not a test module).

The covered week is 2026-W43 (Monday 2026-10-19 to Sunday 2026-10-25); the week before is 2026-W42. The figures the tests rely on:

covered week, 9 records      | shape of repo           | previous week, 4 records
  ship  done 2 escalated 5 abandoned 1 | acme/shop-api: service-python | ship done 2 escalated 1 failed 1
  build failed 1                       | acme/web-ui:   web-nextjs    |
  CI rounds 11, reruns 4               |                               | CI rounds 6, reruns 1
"""
import copy
import importlib
import json

import pytest

import runs_store
from test_runs_report import rec
from test_runs_report_agents import ALL, CODER, ent, fixrounds

WEB = ("web:coder", "web-nextjs", "sonnet")
SHOP, WEBUI, STORE = "acme/shop-api", "acme/web-ui", "acme/runs"
CONSUMER_SPEC = "099-billing-export"
PLATFORM = "ika100/sdlc-foundry"
WEEK, PREV = "2026-W43", "2026-W42"
MONDAY = "2026-10-26T08:00:00Z"            # the clock of the CLI tests: the retro of 2026-W43 is due
GENERATED = "2026-10-26T06:00:12Z"
SECRET = "ghp_abc123abc123abc123abc123abc123"


class Lazy:
    """A module that is imported on first use, so a missing module fails the test that needs it (not the collection)."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(importlib.import_module(self._name), attr)


def rid(name, ended):
    return ended.replace("-", "").replace(":", "") + "-" + name.rjust(8, "0")


def _shift(ended, hours):
    import datetime as dt
    t = dt.datetime.strptime(ended, "%Y-%m-%dT%H:%M:%SZ") - dt.timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(name, ended, hours=1.0, *, entries=None, kind="ship", outcome="done", **kw):
    if entries is not None:
        kw.update(agents=list(entries), replans=[],
                  agent_metrics={"schema": 1, "complete": True, "measured": list(ALL), "problems": []})
    return rec(rid(name, ended), ended, kind=kind, outcome=outcome, started_at=_shift(ended, hours), **kw)


def esc(reason, cause="platform"):
    return {"reason": reason, "cause": cause}


def ids(*pairs):
    return [rid(n, e) for n, e in pairs]


ENDED = {"c1": "2026-10-20T10:00:00Z", "c2": "2026-10-21T10:00:00Z", "c3": "2026-10-22T12:00:00Z", "c4": "2026-10-23T12:00:00Z",
         "c5": "2026-10-23T13:00:00Z", "c6": "2026-10-25T23:59:59Z", "c7": "2026-10-24T10:00:00Z", "c8": "2026-10-19T00:00:00Z",
         "c9": "2026-10-24T08:00:00Z", "p1": "2026-10-13T10:00:00Z", "p2": "2026-10-14T10:00:00Z", "p4": "2026-10-16T10:00:00Z",
         "p5": "2026-10-18T23:59:59Z"}


def RID(name):
    return rid(name, ENDED[name])


def records():
    """Covered week c1-c9, previous week p1-p5, and two records outside both (the second Monday and the week before the previous)."""
    e = ENDED
    return [
        run("c1", e["c1"], repo=SHOP, spec=CONSUMER_SPEC, ci_rounds=2, entries=[ent(CODER, fixrounds("test", "test"))],
            phases=[("build", "2026-10-20T09:00:00Z", "2026-10-20T09:10:00Z")]),
        run("c2", e["c2"], 2, outcome="escalated", repo=SHOP, ci_rounds=3, escalation=esc("merge failed"),
            reruns=[("ci / test", "stuck")], entries=[ent(CODER)]),
        run("c3", e["c3"], 1, outcome="escalated", repo=WEBUI, ci_rounds=1, escalation=esc("merge failed "),
            reruns=[("ci / test", "transient"), ("lint", "stale")], entries=[ent(WEB)]),
        run("c4", e["c4"], 5, outcome="escalated", repo=WEBUI, ci_rounds=0, escalation=esc("stale base"), entries=[ent(WEB)]),
        run("c5", e["c5"], kind="build", outcome="failed", repo=SHOP, ci_rounds=1, entries=[ent(CODER)],
            phases=[("build", "2026-10-23T12:00:00Z", "2026-10-23T12:05:00Z")]),
        run("c6", e["c6"], outcome="abandoned", repo=SHOP, ci_rounds=1),
        run("c7", e["c7"], outcome="escalated", repo=SHOP, ci_rounds=1, escalation=esc("tests red", "code"),
            reruns=[("lint", "transient")], entries=[ent(CODER)]),
        run("c8", e["c8"], repo=SHOP, ci_rounds=1),
        run("c9", e["c9"], 0.5, outcome="escalated", repo=SHOP, ci_rounds=1, escalation=esc("disk full")),
        run("p1", e["p1"], repo=SHOP, ci_rounds=1, entries=[ent(CODER, fixrounds("ci", "ci", "ci"))]),
        run("p2", e["p2"], repo=SHOP, outcome="escalated", ci_rounds=2, escalation=esc("merge failed"), reruns=[("ci / test", "stuck")]),
        run("p4", e["p4"], repo=SHOP, outcome="failed", ci_rounds=2),
        run("p5", e["p5"], repo=SHOP, ci_rounds=1, entries=[ent(CODER)]),
        run("x1", "2026-10-26T00:00:00Z", repo=SHOP),                      # the next week
        run("w0", "2026-10-11T23:59:59Z", repo=SHOP),                      # before the previous week
    ]


def _issue(number, title, labels, state, created, body_sig, comments=()):
    body = "Something broke.\n\n" + (f"Signature: platform:{body_sig}\n" if body_sig else "")
    return {"number": number, "title": title, "url": f"https://github.com/{PLATFORM}/issues/{number}", "state": state,
            "labels": list(labels), "created_at": created, "body": body,
            "comments": [{"created_at": c, "body": b} for c, b in comments]}


def auto_issues():
    return [
        _issue(101, "[auto] cplat ship: gate check hung", ["auto-filed", "triage"], "open", "2026-10-14T09:00:00Z", "0123456789abcdef",
               [("2026-10-20T09:00:00Z", "**Occurrence 2** seen again"), ("2026-10-21T09:00:00Z", "thanks, looking"),
                ("2026-10-22T09:00:00Z", "**Occurrence 3** seen again")]),
        _issue(102, "[auto] image push refused", ["auto-filed", "tracked"], "closed", "2026-10-21T09:00:00Z", "fedcba9876543210"),
        _issue(103, "[auto] no signature line", ["auto-filed"], "open", "2026-10-21T09:00:00Z", None),
        _issue(104, "[auto] quiet this week", ["auto-filed"], "open", "2026-10-01T09:00:00Z", "00000000000000aa",
               [("2026-10-05T09:00:00Z", "**Occurrence 2** old")]),
        _issue(105, "not auto filed", ["bug"], "open", "2026-10-21T09:00:00Z", "00000000000000bb"),
    ]


def open_issues():
    return [{"number": 101, "title": "[auto] cplat ship: gate check hung", "labels": ["auto-filed", "triage"]}]


def specs(tracks=()):
    return [{"number": "087", "id": "087-run-records", "title": "Run records", "status": "building", "tracks": list(tracks)}]


def build(recs=None, **over):
    import retro_report
    args = dict(auto_issues=auto_issues(), open_issues=open_issues(), specs=specs(), week=WEEK, store=STORE, generated_at=GENERATED)
    args.update(over)
    return retro_report.build(records() if recs is None else recs, **args)


def dumps(report):
    return json.dumps(report, indent=2, ensure_ascii=False)


# ---------------- the GitHub fake of the CLI tests ----------------

WRITES = ("create", "edit_body", "comment", "close")


class FakeRetroTracker:
    """An in-memory platform repo as `retro_github.tracker()` sees it."""

    def __init__(self):
        self.autos = auto_issues()
        self.opens = open_issues()
        self.retros: list[dict] = []
        self.calls: list[tuple] = []
        self.error: Exception | None = None
        self.n = 200

    def _enter(self, what, *args):
        self.calls.append((what, *args))
        if self.error:
            raise self.error

    @property
    def writes(self):
        return [c for c in self.calls if c[0] in WRITES]

    def add_retro(self, number, title, state="open", labels=("retro",)):
        self.retros.append({"number": number, "title": title, "url": f"https://github.com/{PLATFORM}/issues/{number}",
                            "state": state, "labels": list(labels), "body": "old"})

    def get(self, number):
        return next(i for i in self.retros if i["number"] == number)

    def auto_issues(self, repo, since):
        self._enter("auto_issues", repo, since)
        return copy.deepcopy(self.autos)

    def open_issues(self, repo):
        self._enter("open_issues", repo)
        return copy.deepcopy(self.opens)

    def retro_issues(self, repo):
        self._enter("retro_issues", repo)
        return [dict(i) for i in sorted(self.retros, key=lambda i: -i["number"]) if "retro" in i["labels"]]

    def create(self, repo, title, body, labels):
        self._enter("create", repo, title, body, list(labels))
        self.n += 1
        self.add_retro(self.n, title, labels=labels)
        self.get(self.n)["body"] = body
        return self.get(self.n)["url"]

    def edit_body(self, repo, number, body):
        self._enter("edit_body", repo, number, body)
        self.get(number)["body"] = body
        return self.get(number)["url"]

    def comment(self, repo, number, body):
        self._enter("comment", repo, number, body)

    def close(self, repo, number):
        self._enter("close", repo, number)
        self.get(number)["state"] = "closed"


@pytest.fixture()
def tracker(monkeypatch):
    import retro_github
    t = FakeRetroTracker()
    monkeypatch.setattr(retro_github, "tracker", lambda: t)
    return t


def fill(store, recs=None):
    for r in (records() if recs is None else recs):
        store.files[runs_store.record_path(r)] = json.dumps(r) + "\n"
