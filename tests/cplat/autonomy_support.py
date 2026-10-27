"""Shared helpers of the spec 124 acceptance tests (not a test module, never collected).

Contract: docs/specs/124-autonomy-is-declared-per-environment-and/design.md and contract.openapi.yaml.

Seams the tests assume beyond the written contract (the coders follow them; the tester's report lists them):
  * `engine._http(method, url, body, token, timeout) -> (status: int, doc: dict)`; it raises `OSError` when the engine cannot be
    reached. `engine.monotonic() -> float` and `engine.sleep(seconds)` are the clock of the 60 s retry loop (tests fake both).
    `engine.send` never sleeps for real. `engine.status(url, system)` returns the parsed status document or None.
  * `engine.confirmed_later(pending, status_doc, events)`: `pending` is `{"signal", "kind", "environment", "level"?}`,
    `status_doc` the whole `GET /v1/status` document, `events` the audit events.
  * `autonomycmd.gh(args) -> str` is the one `gh` of the command (login: `["api", "user", "-q", ".login"]`; the open pause PR:
    `["pr", "list", "--head", <branch>, "--state", "open", "--json", "number,url"]`; `["pr", "close", <n>, "--comment", <text>]`).
    The PRs themselves go through `gitops.open_pr(repo, branch, title, body)`.
  * `autonomy_actions.gh(args) -> str` is the `gh` of undo and approve; `autonomy_actions.pr_wait(number, repo) -> int` runs
    `cplat pr wait <n> -R <repo> --merge`.
  * Store: `runs.open_store(slug)` returns an object with `read(days, deadline=None, prefix="runs")` (see `AutoStore`).
  * `needs.gh(args)` answers `["pr", "view", <n>, "-R", <repo>, "--json", "statusCheckRollup,state"]` (see `FakeNeedsGh`).
Nothing here reaches the network, GitHub, a cluster or claude."""
import datetime as dt
import json
import re
from pathlib import Path

import pytest
import yaml

from system_fixtures import FULL5, PROBES, ROOT, component, git, init_git, rich5, tiny, write_system  # noqa: F401

APP = "applications/shop"
LEVELS = ["observe", "advise", "propose", "act", "improve"]
DEV_URL = "https://ai-ops.dev.example.com"
STG_URL = "https://ai-ops.staging.example.com"
PROD_URL = "https://ai-ops.prod.example.com"
SHA = "1a2b3c4d5e6f" + "0" * 28


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(**kw) -> str:
    return iso(now() - dt.timedelta(**kw))


# ---------------- system documents ----------------

def with_autonomy(doc: dict, **by_env) -> dict:
    """Set `environments.<env>.autonomy` (keyword `dev=` ...); a value of None removes it."""
    for env, block in by_env.items():
        if block is None:
            doc["environments"][env].pop("autonomy", None)
        else:
            doc["environments"][env]["autonomy"] = block
    return doc


def tiny_auto(**by_env) -> dict:
    return with_autonomy(tiny(), **by_env)


def rich_auto(**by_env) -> dict:
    """The rich5 system (dev/staging/prod, shop-api in all three) with autonomy declared."""
    return with_autonomy(rich5(), **by_env)


def declared_system(**by_env) -> dict:
    """A system whose three environments have engines; used by the command tests."""
    base = {"dev": {"level": "act", "engine": DEV_URL}, "staging": {"level": "propose", "engine": STG_URL},
            "prod": {"level": "propose", "engine": PROD_URL}}
    base.update(by_env)
    return with_autonomy(tiny(), **base)


def read_json(path: Path):
    return json.loads(Path(path).read_text())


# ---------------- time, store and engine fakes ----------------

class AutoStore:
    """An in-memory run store holding `runs/...` and `audit/...` files (the `runs_store.Store` protocol with the prefix)."""

    def __init__(self, slug="acme/runs"):
        self.slug, self.files, self.puts = slug, {}, []

    def visibility(self, deadline=None):
        return "private"

    def create_private(self):
        pass

    def put(self, files, message, deadline=None):
        self.puts.append(dict(files))
        self.files.update(files)

    def read_file(self, path, deadline=None):
        return self.files.get(path)

    def read(self, days, deadline=None, prefix="runs"):
        wanted = {d.isoformat() for d in days}
        out = []
        for path, text in sorted(self.files.items()):
            if not path.startswith(prefix + "/"):
                continue
            _, y, m, d, _name = path.split("/", 4)
            if f"{y}-{m}-{d}" in wanted:
                out.append((path, text))
        return out

    def add_run(self, rec: dict):
        day = rec["started_at"][:10].replace("-", "/")
        self.files[f"runs/{day}/{rec['run_id']}.json"] = json.dumps(rec) + "\n"

    def add_event(self, ev: dict):
        day = ev["at"][:10].replace("-", "/")
        self.files[f"audit/{day}/{ev['event_id']}.json"] = json.dumps(ev) + "\n"


@pytest.fixture()
def store(monkeypatch):
    import runs
    s = AutoStore()
    monkeypatch.setenv("CPLAT_RUNS_REPO", s.slug)
    monkeypatch.setattr(runs, "open_store", lambda slug: s)
    return s


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(float(seconds), 0.5)


class FakeEngines:
    """Replaces `engine._http` and the clock: one fake engine per base URL."""

    def __init__(self):
        self.down: set[str] = set()                # URLs that raise OSError
        self.refuse: dict[str, tuple[int, dict]] = {}   # URL -> a fixed answer for POST /v1/signals
        self.heartbeat: dict[str, str] = {}        # URL -> heartbeat_at (default: now)
        self.state: dict[str, dict] = {}           # URL -> {env: status of that env}
        self.posts: list[dict] = []                # every signal received: {"url", "token", "body"}
        self.gets: list[str] = []
        self.clock = FakeClock()

    def __call__(self, method, url, body, token, timeout):
        base = re.sub(r"/v1/.*$", "", url)
        if base in self.down:
            raise OSError("connection refused")
        if method == "POST":
            self.posts.append({"url": base, "token": token, "body": body})
            if base in self.refuse:
                return self.refuse[base]
            sig = body
            env = sig["environment"]
            effective = "observe" if sig["kind"] == "pause" else (sig.get("policy") or {}).get("effective", "observe")
            self.state.setdefault(base, {})[env] = {"paused": sig["kind"] == "pause", "effective": effective, "signal": sig["id"]}
            return 200, {"id": sig["id"], "environment": env, "confirmed": True, "effective": effective, "at": iso(now())}
        self.gets.append(url)
        envs = {}
        for env, st in self.state.get(base, {}).items():
            envs[env] = {"policy_commit": SHA, "applied_at": iso(now()), "declared": st.get("declared", "act"),
                         "effective": st["effective"], "paused": st["paused"], "signals": [{"id": st["signal"], "kind": "pause", "at": iso(now())}] if "signal" in st else []}
        return 200, {"engine": {"name": "ai-ops", "version": "1.0.0"}, "heartbeat_at": self.heartbeat.get(base, iso(now())), "environments": envs}


@pytest.fixture()
def engines(monkeypatch, tmp_path):
    """The fake engines. When `engine.py` does not exist yet the fixture still yields (the test then fails on its own import)."""
    e = FakeEngines()
    monkeypatch.setenv("CPLAT_ENGINE_TOKEN", "tok-123")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    try:
        import engine
    except ImportError:
        return e
    monkeypatch.setattr(engine, "_http", e)
    monkeypatch.setattr(engine, "monotonic", e.clock.monotonic)
    monkeypatch.setattr(engine, "sleep", e.clock.sleep)
    return e


# ---------------- engine documents (the shared examples of the contract) ----------------

def run_record(run_id="20261026T091500Z-1a2b3c4d", started=None, **kw) -> dict:
    started = started or ago(minutes=30)
    rec = {"schema": 1, "run_id": run_id, "kind": "fix", "repo": "acme/shop-api", "spec": None,
           "actor": {"type": "engine", "name": "ai-ops", "id": "ai-ops@shop"},
           "system": "shop", "component": "shop-api", "environment": "prod",
           "issue": {"repo": "acme/shop-api", "number": 57, "url": "https://github.com/acme/shop-api/issues/57"},
           "started_at": started, "ended_at": None, "outcome": None,
           "phases": [{"name": "build", "started_at": started, "ended_at": started}, {"name": "pr", "started_at": started, "ended_at": None}],
           "budget": {"used": {"minutes": 12, "invocations": 6, "reruns": 0, "cost": 0.9},
                      "limits": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}},
           "pr": {"number": 88, "url": "https://github.com/acme/shop-api/pull/88"}, "ci_url": None,
           "route": "fix", "criticality": "low", "change": {"files": 3, "lines": 412},
           "regression": {"test": "tests/test_cart.py::test_total_rounding", "before": "failed", "after": "passed"},
           "second_review": {"result": "passed", "findings": []}, "summary": "Round the cart total once, at the end.",
           "policy": {"level": "act", "commit": SHA}, "decision": {"action": "review", "outside": ["riskGate.maxLines"]},
           "smoke": {"outcome": "not-run"}, "escalation": None}
    rec.update(kw)
    return rec


def audit_event(kind="merge", *, at=None, env="prod", component_="shop-api", name="ai-ops", eid=None, level="act", effective="act",
                undoes=None, obj=None, **kw) -> dict:
    at = at or ago(hours=2)
    eid = eid or at.replace("-", "").replace(":", "") + f"-{name}-3f9c2a71"
    ev = {"schema": 1, "event_id": eid, "at": at,
          "actor": {"type": "engine" if name == "ai-ops" else "person", "name": name, "id": f"{name}@shop"},
          "system": "shop", "environment": env, "component": component_, "kind": kind,
          "object": {"type": "pr", "repo": "acme/shop-api", "number": 88, "url": "https://github.com/acme/shop-api/pull/88",
                     "run_id": None, "version": None, "previous": None, "signal": None},
          "policy": {"level": level, "effective": effective,
                     "guardrails": {"autoMerge": {}, "riskGate": {}, "budget": {}, "window": {}, "undoWindow": "24h"}, "commit": SHA},
          "store_ref": {"store": "ai-ops", "id": "e-1", "hash": "sha256:" + "a" * 8} if name == "ai-ops" else None,
          "detail": {}, "undoes": undoes}
    if obj:
        ev["object"].update(obj)
    ev.update(kw)
    return ev


ENGINE_BODY = """## Signal
- component: shop-api
- environment: prod
- category: error-rate
- criticality: high
- dedupe key: shop-api/prod/error-rate/HTTP 500 on POST /cart
- seen: 3
- first seen: 2026-10-26T07:00:00Z
- last seen: 2026-10-26T09:12:00Z
- engine: ai-ops

## Evidence
- [Grafana: error rate](https://grafana.example.com/d/abc)

## Triage
- route: fix
- confidence: 0.82
- suspected files: src/shop_api/cart.py, src/shop_api/totals.py

## Policy
- level: act
- decision: review: outside riskGate.maxLines
- commit: 1a2b3c4d5e6f

_Filed automatically by ai-ops (spec 124). Secrets were removed. Route it with /issue:triage._

Signature: signal:0123456789abcdef
"""
ENGINE_LABELS = ["triage", "auto-filed", "signal", "engine:ai-ops", "env:prod", "criticality:high"]


def signal_issue(n=57, body=ENGINE_BODY, labels=ENGINE_LABELS, created="2026-10-26T07:00:00Z") -> dict:
    return {"number": n, "title": "[auto] [signal] error-rate: shop-api in prod", "state": "OPEN", "createdAt": created, "body": body,
            "url": f"https://github.com/acme/shop-api/issues/{n}", "labels": [{"name": x} for x in labels]}


# ---------------- the autonomy source of the console (`cplat system autonomy show --json`) ----------------

def env_show(name="prod", declared="act", effective=None, cap="act", **kw) -> dict:
    d = {"name": name, "declared": declared, "effective": effective or declared, "cap": cap,
         "guardrails": {"autoMerge": {"routes": ["fix"], "maxCriticality": "low"},
                        "riskGate": {"maxFiles": 5, "maxLines": 200, "regressionTest": True, "secondReview": True},
                        "budget": {"runsPerDay": 5, "mergesPerDay": 2, "perRun": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}},
                        "window": {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"}},
         "undoWindow": "24h",
         "budget_today": {"runs": 2, "merges": 1, "cost": 3.4, "runsPerDay": 5, "mergesPerDay": 2},
         "engine": {"url": PROD_URL, "state": "ok", "name": "ai-ops", "version": "1.0.0", "heartbeat_at": "2026-10-26T09:19:00Z"},
         "supervised": True, "confirmed": True, "pending": [], "override": None,
         "caps": []}
    d.update(kw)
    return d


def undo_info(allowed=True, reason=None, eid="20261026T091733Z-ai-ops-3f9c2a71"):
    return {"allowed": allowed, "reason": reason, "command": f"/system:autonomy undo {eid}" if allowed else None}


def show_json(envs=None, actions=None, paused=False, **kw) -> dict:
    doc = {"schema": 1, "system": "shop", "read_at": "2026-10-26T09:20:00Z", "paused": paused, "paused_by_signal": False,
           "environments": envs if envs is not None else [env_show("dev", "act", cap="improve"), env_show("staging", "propose", cap="improve"),
                                                          env_show("prod", "act", cap="act")],
           "actions": actions or [], "store": {"state": "ok"}, "unavailable": []}
    doc.update(kw)
    return doc


def done_action(eid="20261026T091733Z-ai-ops-3f9c2a71", kind="merge", allowed=True, reason=None, **kw) -> dict:
    ev = audit_event(kind, at="2026-10-26T09:17:33Z", eid=eid, **kw)
    ev["undo"] = undo_info(allowed, reason, eid)
    return ev


def review_need(pr=88, why=None, level="act", **kw) -> dict:
    why = why or [{"guardrail": "riskGate.maxLines", "text": "412 lines, at most 200"}]
    item = {"id": f"review:acme/shop-api#{pr}", "kind": "review", "stage": "Land",
            "object": {"type": "run", "repo": "acme/shop-api", "spec": None, "run_id": "20261026T091500Z-1a2b3c4d", "issue": 57,
                       "component": "shop-api", "version": None, "pr": pr, "url": f"https://github.com/acme/shop-api/pull/{pr}",
                       "engine": "ai-ops", "environment": "prod"},
            "since": "2026-10-26T09:15:00Z", "reason": "outside riskGate.maxLines (412 lines, at most 200)",
            "command": f"/system:autonomy approve acme/shop-api#{pr}", "cwd_repo": "acme/shop-gitops",
            "consequence": {"why": why, "level": level, "regression": {"test": "tests/test_cart.py::test_total_rounding", "before": "failed", "after": "passed"},
                            "ci": "passed", "second_review": {"result": "passed", "findings": []},
                            "summary": "Round the cart total once, at the end.", "merges_to": "dev"},
            "way_back": {"text": "After the merge, Undo or a revert pull request takes the change back; the issue stays linked."}}
    item.update(kw)
    return item


def signal_triage_need() -> dict:
    return {"id": "triage:acme/shop-api:57", "kind": "triage", "stage": "Issue",
            "object": {"type": "issue", "repo": "acme/shop-api", "spec": None, "run_id": None, "issue": 57, "component": None, "version": None,
                       "pr": None, "url": "https://github.com/acme/shop-api/issues/57", "engine": "ai-ops",
                       "detail": {"signal": {
                           "component": "shop-api", "environment": "prod", "category": "error-rate", "criticality": "high",
                           "dedupe_key": "shop-api/prod/error-rate/HTTP 500 on POST /cart", "seen": 3, "first_seen": "2026-10-26T07:00:00Z",
                           "last_seen": "2026-10-26T09:12:00Z", "engine": "ai-ops",
                           "evidence": [{"text": "Grafana: error rate", "url": "https://grafana.example.com/d/abc"}],
                           "triage": {"route": "fix", "confidence": 0.82, "suspected_files": ["src/shop_api/cart.py", "src/shop_api/totals.py"]},
                           "policy": {"level": "act", "decision": "review: outside riskGate.maxLines", "commit": "1a2b3c4d5e6f"}}}},
            "since": "2026-10-26T07:00:00Z", "reason": "signal: error-rate", "command": "/issue:triage 57", "cwd_repo": "acme/shop-api",
            "consequence": {}, "way_back": {}}


def engine_run_row(**kw) -> dict:
    from console_support import run_row
    row = run_row(spec=None, repo="acme/shop-api", phase="pr", stage="Land", run_id="20261026T091500Z-1a2b3c4d", kind="fix")
    row.update({"actor": {"type": "engine", "name": "ai-ops", "id": "ai-ops@shop"}, "engine": "ai-ops",
                "issue": {"repo": "acme/shop-api", "number": 57, "url": "https://github.com/acme/shop-api/issues/57"},
                "system": "shop", "component": "shop-api", "environment": "prod",
                "fix": {"route": "fix", "criticality": "low", "change": {"files": 3, "lines": 412},
                        "regression": {"test": "tests/test_cart.py::test_total_rounding", "before": "failed", "after": "passed"},
                        "second_review": {"result": "passed", "findings": []}, "summary": "Round the cart total once, at the end.",
                        "policy": {"level": "act", "commit": SHA}, "decision": {"action": "review", "outside": ["riskGate.maxLines"]}}})
    row.update(kw)
    return row


def console_data(tmp_path, **over) -> dict:
    from console_support import default_sources, needs_json, runs_json
    data = default_sources(tmp_path)
    data["autonomy"] = show_json()
    data.update(over)
    return data
