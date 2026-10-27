"""Shared helpers of the spec 122 acceptance tests (not a test module, never collected).

Contract: docs/specs/122-a-local-console-shows-the-system-and-what/design.md (JSON shapes, HTTP routes, markup contract).

Seams the tests assume beyond the written contract (the coders follow them; they are listed in the tester's report):
  * `console.server.make_server(repo_dir: Path, sources: dict[str, console.sources.Source], *, port: int = 0)` returns a
    `http.server.ThreadingHTTPServer` bound to 127.0.0.1 (read `.server_address[1]`).
  * `console.sources.Source(name, argv)`; `.read()` runs argv and parses stdout as JSON; `.data`, `.read_at`, `.error`,
    `.unavailable_since`. `console.sources.utcnow()` is the clock (tests replace it).
  * Extra markup hooks: `data-need="<id>"` on Inbox rows, `data-column="<stage>"` on Board columns (plus `data-decision` on
    decision columns), `data-card` on Board cards, `data-criterion="<AC id>"` in the spec panel, `data-env="<env>"` on System
    cells.
Everything is served from files written by the test: no network, no real gh, kubectl or claude."""
import contextlib
import http.client
import io
import json
import re
import sys
import threading
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

import pytest

from system_fixtures import ROOT, rich5, write_system

STAGES = ("Issue", "Spec", "Plan", "Build", "Land", "Dev", "Staging", "Prod")
CPLAT = ROOT / "scripts" / "cplat" / "cplat.py"
STATIC = ROOT / "scripts" / "cplat" / "console" / "static"


# ---------------- a tiny HTML tree ----------------

VOID = {"meta", "link", "input", "br", "hr", "img", "col", "area", "base", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.kids = tag, dict(attrs), parent, []

    def text(self) -> str:
        return " ".join(" ".join(k.text() if isinstance(k, Node) else k for k in self.kids).split())

    def walk(self):
        yield self
        for k in self.kids:
            if isinstance(k, Node):
                yield from k.walk()

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def q(self, tag=None, **attrs):
        return q(self, tag, **attrs)


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def parse(html: str) -> Node:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def q(root: Node, tag=None, **attrs) -> list[Node]:
    """Elements by tag and attributes (`data_place="inbox"` matches data-place="inbox"; True means present)."""
    want = {k.replace("_", "-"): v for k, v in attrs.items()}
    out = []
    for n in root.walk():
        if n.tag == "#root" or (tag and n.tag != tag):
            continue
        if all((k in n.attrs) if v is True else (n.attrs.get(k) == v) for k, v in want.items()):
            out.append(n)
    return out


def row_of(root: Node, needle: str) -> Node | None:
    """The innermost <tr> whose text contains `needle`."""
    best = None
    for tr in q(root, "tr"):
        if needle in tr.text():
            best = tr
    return best


def disabled(n: Node) -> bool:
    return "disabled" in n.attrs or n.attrs.get("aria-disabled") == "true"


# ---------------- fixture documents (the JSON of the contract) ----------------

def model_json(tmp_path: Path) -> dict:
    """A real `cplat model show --json` (schema 2) of the rich5 system."""
    import cplat
    d = tmp_path / "model-src"
    write_system(d, rich5())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cplat.main(["model", "show", "--json", "--repo-dir", str(d)]) == 0
    return json.loads(buf.getvalue())


def cell(version, state, **kw):
    return {"tag": version, "ci": "ok", "argo": "Synced/Healthy", "pin_pr": None, "version": version, "state": state,
            "digest": "sha256:" + "a" * 8, "release": version, **kw}


def status_json() -> dict:
    return {
        "system": "shop", "environments": ["dev", "staging", "prod"],
        "environment_rules": [{"name": "dev", "promote": None, "policy": "audit"},
                              {"name": "staging", "promote": "after-dev-smoke", "policy": "audit"},
                              {"name": "prod", "promote": "manual", "policy": "enforce"}],
        "rows": [
            {"component": "shop-api", "type": "service", "platform": "5.0.0", "release_candidate": None,
             "cells": {"dev": cell("1.4.0", "healthy"), "staging": cell("1.4.0", "verified"), "prod": cell("1.3.0", "healthy")}},
            {"component": "shop-web", "type": "website", "platform": "5.0.0", "release_candidate": None,
             "cells": {"dev": cell("1.0.0", "healthy"), "staging": cell("1.0.0", "NOT VERIFIED"), "prod": None}},
        ],
        "libraries": [{"component": "shop-lib", "used_by": ["shop-api"]}],
        "resources": [{"resource": "postgres", "cells": {"dev": {"argo": "Synced/Healthy", "state": "healthy"}, "staging": None, "prod": None}}],
        "unavailable": [],
    }


def need(kind, spec="012-checkout", repo="acme/shop-api", since="2026-10-25T08:00:00Z", reason="r", **kw):
    stage = {"answer": "Spec", "approve": "Spec", "escalation": "Build", "promote": "Prod", "triage": "Issue"}[kind]
    obj = {"type": "spec", "repo": repo, "spec": spec, "run_id": None, "issue": None, "component": None, "version": None, "pr": 41,
           "url": f"https://github.com/{repo}/pull/41"}
    obj.update(kw.pop("object", {}))
    item = {"id": f"{kind}:{repo}:{spec}", "kind": kind, "stage": stage, "object": obj, "since": since, "reason": reason,
            "command": f"/component:spec approve {spec[:3]}", "cwd_repo": repo, "consequence": {}, "way_back": {}}
    item.update(kw)
    return item


def needs_json() -> dict:
    return {"schema": 1, "system": "shop", "read_at": "2026-10-26T08:00:00Z", "unavailable": [], "items": [
        need("triage", spec="57", since="2026-10-20T08:00:00Z", reason="alert: checkout 5xx", object={"type": "issue", "issue": 57, "spec": None},
             command="/issue:triage 57"),
        need("escalation", spec="011-cart", since="2026-10-22T08:00:00Z", reason="3 CI fix rounds without progress",
             object={"type": "run", "run_id": "20261022T070000Z-1a2b3c4d", "spec": "011-cart"}, command="/component:ship 011",
             consequence={"branch": "feature/011-cart", "pr": 41, "deployed": False},
             way_back={"text": "Stopping keeps the branch and pull request #41; nothing was deployed."}),
        need("answer", spec="012-checkout", since="2026-10-23T08:00:00Z", reason="draft with 2 open questions",
             command="/component:spec --amend 012 <answers>", consequence={"questions": 2}, way_back=None),
        need("approve", spec="013-search", since="2026-10-24T08:00:00Z", reason="draft without open questions; spec check passes",
             command="/component:spec approve 013",
             consequence={"repos": ["acme/shop-api"], "unattended": ["Plan", "Build", "Land", "Dev", "Staging"],
                          "estimate": {"cost_usd": 4.2, "minutes": 55, "runs": 5}},
             way_back={"text": "The run can be paused at any stage; nothing reaches prod without you."}),
        need("promote", spec="shop-api-1.4.0", since="2026-10-25T09:00:00Z", reason="1.4.0 verified in staging; prod runs 1.3.0",
             object={"type": "release", "spec": None, "component": "shop-api", "version": "1.4.0"},
             command="/instance:promote shop-api --to prod --version 1.4.0",
             consequence={"from": "1.3.0", "to": "1.4.0", "specs": ["012-checkout"], "criteria": 7, "commits": 23,
                          "migrations": [{"file": "migrations/versions/0005.py", "additive": False}],
                          "digest": "sha256:aaaa", "verified_digest": "sha256:aaaa", "digest_matches": True},
             way_back={"command": "/instance:promote shop-api --to prod --version 1.3.0", "warning": "migration 0005.py is not additive"}),
    ]}


def run_row(spec="011-cart", repo="acme/shop-api", phase="build", **kw):
    row = {"run_id": "20261022T070000Z-1a2b3c4d", "kind": "ship", "level": "component", "spec": spec, "repo": repo, "parent": None,
           "children": [], "phase": phase, "stopped_in": None, "stage": "Build", "stopped": False, "active": True,
           "started_at": "2026-10-22T07:00:00Z", "ended_at": None, "outcome": None, "escalation": None, "failure": None,
           "budget": {"used": {"minutes": 42, "invocations": 17, "reruns": 1, "cost": 3.1},
                      "limit": {"minutes": 180, "invocations": 60, "reruns": 6, "cost": 15}, "exhausted": None},
           "activity": [{"at": "2026-10-22T07:30:00Z", "agent": "svc:coder", "text": "merged t3"}],
           "session_id": "sess-1", "repo_dir": "/tmp/clone", "pr": {"number": 41, "url": f"https://github.com/{repo}/pull/41"},
           "ci_url": "https://github.com/acme/shop-api/actions/runs/9", "image": None, "smoke": {"dev": None, "staging": None}}
    row.update(kw)
    return row


def runs_json() -> dict:
    stopped = run_row(phase="escalated", stopped_in="build", stage="Build", stopped=True, active=False, outcome="escalated",
                      ended_at="2026-10-22T09:00:00Z",
                      escalation={"reason": "3 CI fix rounds without progress", "cause": "code", "summary": "CI stayed red after three fix rounds."},
                      failure={"check": "tests", "test": "tests/test_cart.py::test_total", "criterion": "AC-011.3",
                               "error": "AssertionError: 41 != 42", "excerpt": ["E   AssertionError"], "log": "/tmp/log", "diagnosis": "rounding in total()"})
    going = run_row(spec="014-wishlist", phase="pr", stage="Land", run_id="20261026T070000Z-aaaa1111")
    return {"schema": 1, "read_at": "2026-10-26T08:00:00Z", "store": {"state": "ok", "detail": "acme/runs"}, "runs": [going, stopped]}


def spec_row(sid="012-checkout", status="draft", **kw):
    row = {"id": sid, "title": "Checkout", "status": status, "priority": "P2", "acs": 2, "open_questions": 0, "level": "component",
           "path": f"docs/specs/{sid}/spec.md", "tracks": [57], "parent": None,
           "criteria": [{"id": "AC-012.1", "text": "Given a cart, when paid, then a receipt is sent.", "smoke": False,
                         "tests": ["tests/test_cart.py"], "verdict": "met"},
                        {"id": "AC-012.2", "text": "Given a cart, when listed, then the total shows.", "smoke": True,
                         "tests": [], "verdict": "not judged"}],
           "questions": [], "check": {"ok": True, "errors": []}, "slices": [], "contract_change": "POST /cart", "draft_pr": None}
    row.update(kw)
    return row


def specs_json() -> list:
    q2 = [{"text": "Should a user be limited?", "options": ["50 per user", "no limit"], "answered": False},
          {"text": "Which currency?", "options": ["EUR", "USD"], "answered": False}]
    return [spec_row("012-checkout", "draft", open_questions=2, questions=q2, check={"ok": True, "errors": []}),
            spec_row("013-search", "draft", title="Search", criteria=[]),
            spec_row("014-wishlist", "building", title="Wishlist"),
            spec_row("015-export", "approved", title="Export"),
            spec_row("016-bad", "draft", title="Broken", check={"ok": False, "errors": ["AC-016.1 has no test"]})]


def doctor_json(missing=()) -> list:
    rows = [{"status": "ok", "name": "git", "detail": "/usr/bin/git", "fix": None}]
    fixes = {"claude": "install Claude Code: https://docs.anthropic.com/claude-code", "gh": "run: gh auth login",
             "kube:prod": "kubectl config use-context <prod-context>"}
    for m in missing:
        rows.append({"status": "warn", "name": m, "detail": "not available", "fix": fixes[m]})
    return rows


def default_sources(tmp_path: Path) -> dict:
    return {"model": model_json(tmp_path), "status": status_json(), "needs": needs_json(), "runs": runs_json(),
            "specs:acme/shop-api": specs_json(), "doctor": doctor_json()}


# ---------------- a running console over file-backed sources ----------------

READER = ("import os, sys\np = sys.argv[1]\n"
          "if not os.path.exists(p):\n    sys.stderr.write('unreachable: connection refused\\n'); sys.exit(1)\n"
          "sys.stdout.write(open(p).read())\n")


class Console:
    def __init__(self, tmp_path, monkeypatch, data, repo_dir=None):
        from console import server, sources
        for k, sub in (("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config")):
            monkeypatch.setenv(k, str(tmp_path / sub))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        self.dir = tmp_path / "srcjson"
        self.dir.mkdir(exist_ok=True)
        self.sources = {}
        for name, obj in data.items():
            self.sources[name] = sources.Source(name, [sys.executable, "-c", READER, str(self._path(name))])
            self.set(name, obj)
        if repo_dir is None:
            repo_dir = tmp_path / "gitops"
            write_system(repo_dir, rich5())
        self.repo_dir = repo_dir
        self.httpd = server.make_server(repo_dir, self.sources, port=0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self._token = None

    def _path(self, name):
        return self.dir / (re.sub(r"[^a-z0-9]+", "_", name) + ".json")

    def set(self, name, obj, read=True):
        self._path(name).write_text(json.dumps(obj))
        if read:
            self.sources[name].read()

    def fail(self, name, read=True):
        self._path(name).unlink(missing_ok=True)
        if read:
            self.sources[name].read()

    def stop(self):
        with contextlib.suppress(Exception):
            self.httpd.shutdown()
            self.httpd.server_close()

    def request(self, method, path, body=None, headers=None, token=True, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body)
            h["Content-Type"] = "application/json"
        if method == "POST" and token is True:
            h["X-Console-Token"] = self.token()
        elif isinstance(token, str):
            h["X-Console-Token"] = token
        conn.request(method, path, data, h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), raw

    def token(self):
        if self._token is None:
            _, _, raw = self.request("GET", "/inbox")
            m = re.search(r'<meta[^>]*name="console-token"[^>]*content="([^"]+)"', raw.decode())
            assert m, "no <meta name=\"console-token\"> on the page"
            self._token = m.group(1)
        return self._token

    def get(self, path):
        st, _, raw = self.request("GET", path)
        return st, raw.decode()

    def page(self, path):
        st, text = self.get(path)
        assert st == 200, (path, st, text[:300])
        return parse(text), text

    def json(self, method, path, body=None, **kw):
        st, _, raw = self.request(method, path, body, **kw)
        try:
            return st, json.loads(raw or b"null")
        except ValueError:
            return st, raw.decode()

    def panel(self, kind, ident):
        return self.page(f"/panel/{kind}/{urllib.parse.quote(ident, safe='')}")

    def wait_action(self, aid, states=("done", "failed", "stopped"), timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            st, a = self.json("GET", f"/api/actions/{aid}")
            if st == 200 and a["state"] in states:
                return a
            time.sleep(0.1)
        raise AssertionError(f"action {aid} did not reach {states}")


@pytest.fixture()
def console(tmp_path, monkeypatch):
    made = []

    def make(data=None, **kw):
        c = Console(tmp_path, monkeypatch, default_sources(tmp_path) if data is None else data, **kw)
        made.append(c)
        return c

    yield make
    for c in made:
        c.stop()
