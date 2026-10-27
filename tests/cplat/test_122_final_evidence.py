"""Spec 122 final verification: finished runs link their evidence, releases carry dates, ask is read-only, smoke and triage are explained."""
import datetime
import json
import subprocess

import needs
import releases
import runlist
import runs
from console import handoff, palette
from console_support import cell, needs_json, q, run_row, runs_json, status_json

PR = {"number": 41, "url": "https://github.com/acme/shop-api/pull/41"}


def finished(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    rid = runs.start("ship", repo="acme/shop-api", spec="011-cart")
    for p in ("plan", "build", "pr", "land", "deploy", "done"):
        runs.phase(rid, p)
    return rid


def row(rid):
    return next(r for r in runlist.collect(30)["runs"] if r["run_id"] == rid)


def test_a_finished_run_has_its_merged_pr_and_ci_and_asks_gh_once(monkeypatch, tmp_path):  # AC-122.15, 39, 48
    rid = finished(monkeypatch, tmp_path)
    calls = []

    def lookup(repo, branch, state="all"):
        calls.append((repo, branch, state))
        return PR

    monkeypatch.setattr(runlist, "lookup_pr", lookup)
    r = row(rid)
    assert r["pr"] == PR and r["ci_url"] == PR["url"] + "/checks"
    assert calls == [("acme/shop-api", "feature/011-cart", "merged")]
    monkeypatch.setattr(runlist, "lookup_pr", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked again")))
    assert row(rid)["pr"] == PR
    assert (tmp_path / "cache" / "sdlc-foundry" / "console" / "prs.json").is_file()


def test_a_finished_run_gets_a_run_record_link(monkeypatch):  # AC-122.39, 48
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")
    links = handoff.links_for_work({"run_id": "r1", "ended_at": "2026-10-20T10:00:00Z", "pr": PR})
    assert any(x["label"] == "Run record" and x["url"].startswith("https://github.com/acme/runs/blob/main/runs/2026/10/20/") for x in links)


def test_a_failing_gh_does_not_break_a_finished_run(monkeypatch, tmp_path):
    rid = finished(monkeypatch, tmp_path)
    monkeypatch.setattr(runlist, "lookup_pr", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gh down")))
    assert row(rid)["pr"] is None


def test_releases_come_from_gh_with_their_date_within_the_period(monkeypatch):  # AC-122.48
    monkeypatch.setattr(runs, "utcnow", lambda: datetime.datetime(2026, 10, 27, tzinfo=datetime.timezone.utc))
    seen = []

    def gh(args):
        seen.append(args)
        return json.dumps([{"tagName": "v1.4.0", "publishedAt": "2026-10-20T10:00:00Z", "url": "https://github.com/acme/shop-api/releases/tag/v1.4.0"},
                           {"tagName": "v0.1.0", "publishedAt": "2025-01-01T10:00:00Z", "url": "u"}])

    monkeypatch.setattr(needs, "gh", gh)
    out = needs._releases({"shop-api": "acme/shop-api"}, 90)
    assert seen[0][:4] == ["release", "list", "-R", "acme/shop-api"] and "tagName,publishedAt,url" in seen[0]
    assert out == [{"repo": "acme/shop-api", "component": "shop-api", "tag": "v1.4.0", "published_at": "2026-10-20T10:00:00Z",
                    "url": "https://github.com/acme/shop-api/releases/tag/v1.4.0"}]


def test_done_lists_releases_with_their_date_and_filters_by_period(console):  # AC-122.48
    c = console()
    doc = needs_json()
    doc["releases"] = [{"repo": "acme/shop-api", "component": "shop-api", "tag": "v1.4.0", "published_at": "2026-10-20T10:00:00Z", "url": "u"},
                       {"repo": "acme/shop-api", "component": "shop-api", "tag": "v0.9.0", "published_at": "2026-01-01T10:00:00Z", "url": "u"}]
    c.set("needs", doc)
    _, text = c.page("/board?view=done&period=30")
    assert "1.4.0" in text and "2026-10-20" in text and "0.9.0" not in text
    assert "0.9.0" in c.page("/board?view=done&period=all")[1]


def test_ask_runs_in_plan_mode_with_writing_tools_denied(monkeypatch, tmp_path):  # AC-122.21
    got = {}

    def fake(argv, **kw):
        got["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "answer", "")

    class Ctx:
        repo_dir = tmp_path

    monkeypatch.setattr(palette, "_claude", lambda: "claude")
    monkeypatch.setattr(palette.subprocess, "run", fake)
    monkeypatch.setattr(palette, "suggestions_of", lambda ctx, a: [])
    palette.ask(Ctx(), "why?")
    argv = got["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "plan"
    assert set(argv[argv.index("--disallowedTools") + 1].split(",")) >= {"Edit", "Write", "NotebookEdit"}
    assert "--allowedTools" in argv


def test_a_smoke_that_did_not_run_keeps_its_reason():  # AC-122.33
    rec = {"smoke": {"outcome": "not-run", "reason": "no dev instance reachable"}, "repo": "acme/shop-api"}
    assert runlist._smoke(rec)["dev"] == {"result": "not-run", "instance": "shop-api/dev", "reason": "no dev instance reachable"}


def test_a_smoke_that_did_not_run_is_explained_like_a_failure(console):  # AC-122.33
    c = console()
    doc = runs_json()
    doc["runs"].append(run_row(spec="020-smoke", run_id="20261026T071500Z-bbbb2222", phase="staging", stage="Staging",
                               smoke={"dev": {"result": "not-run", "instance": "shop-api/dev", "reason": "no dev instance reachable"},
                                      "staging": None}))
    c.set("runs", doc)
    root, text = c.panel("run", "20261026T071500Z-bbbb2222")
    assert "no dev instance reachable" in text and "did not run" in text and "Criteria left unchecked" in text
    assert "/component:ship 020" in [n.text() for n in q(root, "code", data_command=True)]


SMOKE_BODY = """## Reason
Smoke red in staging: tests/smoke/test_cart.py::test_total_AC-011.3

## Command and phase
- command: `cplat component ship deploy`
- phase: `deploy`

## Evidence
```text
GET /cart 200
AssertionError: 41 != 42
```

## Smoke
- spec: 011-cart
- image: sha-abc
- environment: staging
- base URL: http://x
- failure class: product-bug
- failing tests:
  - tests/smoke/test_cart.py::test_total_AC-011.3

## Run
- run id: r1

Signature: smoke:0123456789abcdef"""

ALERT_BODY = """## Alert
- alert: Checkout5xx
- severity: critical
- environment: prod
- service: shop-api

## Summary
Error ratio above 5 percent

## Query
```promql
x
```
_Filed automatically by the alert poll (spec 092). Secrets were removed. Route it with /issue:triage._

Signature: alert:0123456789abcdef"""


def test_triage_detail_of_a_smoke_failure_and_an_alert():  # AC-122.33
    smoke = needs.triage_detail({"triage", "smoke-failure"}, SMOKE_BODY)
    assert smoke["test"] == "tests/smoke/test_cart.py::test_total_AC-011.3" and smoke["criterion"] == "AC-011.3"
    assert smoke["error"] == "AssertionError: 41 != 42" and "product-bug" in smoke["diagnosis"]
    alert = needs.triage_detail({"triage", "alert"}, ALERT_BODY)
    assert alert["check"] == "Checkout5xx" and alert["error"] == "Error ratio above 5 percent" and "critical" in alert["diagnosis"]
    assert needs.triage_detail({"triage"}, "whatever") == {}


def test_triage_items_carry_the_detail(monkeypatch):  # AC-122.33
    issue = {"number": 57, "title": "Smoke red", "createdAt": "2026-10-20T08:00:00Z", "url": "u", "labels": [{"name": "triage"}, {"name": "smoke-failure"}],
             "body": SMOKE_BODY}
    monkeypatch.setattr(needs, "gh", lambda args: json.dumps([issue]))
    [item] = needs._triage("acme/shop-api")
    assert item["object"]["detail"]["criterion"] == "AC-011.3"


def test_the_triage_panel_shows_the_detail_above_the_ways_forward(console):  # AC-122.33
    c = console()
    doc = needs_json()
    for i in doc["items"]:
        if i["kind"] == "triage":
            i["object"]["detail"] = {"test": "tests/smoke/test_cart.py::t", "criterion": "AC-011.3", "error": "AssertionError: 41 != 42",
                                     "diagnosis": "failure class product-bug"}
    c.set("needs", doc)
    _, text = c.panel("need", next(i["id"] for i in doc["items"] if i["kind"] == "triage"))
    assert text.index("AC-011.3") < text.index("Fix now")
    assert "AssertionError: 41 != 42" in text and "product-bug" in text


def promote_status():
    doc = status_json()
    doc["environment_rules"][1]["promote"] = "manual"
    doc["rows"][0]["cells"] = {"dev": cell("1.5.0", "verified", tag="sha-new", digest="sha256:dddd"),
                               "staging": cell("1.4.0", "healthy", tag="sha-old"), "prod": cell("1.3.0", "healthy")}
    return doc


def test_dev_to_staging_promotion_shows_consequence_and_way_back(console, monkeypatch):  # AC-122.8, 34, 35
    seen = []

    def between(repo, base, head):
        seen.append((repo, base, head))
        return {"commits": 5, "specs": ["012-checkout"], "criteria": 3,
                "migrations": [{"file": "migrations/versions/0007.py", "additive": False}]}

    monkeypatch.setattr(releases, "between", between)
    c = console()
    c.set("status", promote_status())
    root, _ = c.page("/system")
    td = next(t for t in q(root, "td", data_env="dev") if q(t, "button", data_action="promote"))
    [btn] = q(td, "button", data_action="promote")
    assert btn.attrs["data-open"] == "/panel/promote/shop-api%3Adev%3Astaging" and "data-confirm" not in btn.attrs
    root, text = c.panel("promote", "shop-api:dev:staging")
    assert seen == [("acme/shop-api", "sha-old", "sha-new")]
    cmds = [n.text() for n in q(root, "code", data_command=True)]
    assert "/instance:promote shop-api --to staging --version 1.5.0" in cmds
    assert "/instance:promote shop-api --to staging --version 1.4.0" in cmds
    assert "012-checkout" in text and "0007.py" in text and "not additive" in text.lower() and "sha256:dddd" in text
    [p] = q(root, "button", data_action="promote")
    assert p.attrs.get("data-key", "p") == "p" and "disabled" not in p.attrs


def test_promote_panel_with_status_down_keeps_the_button_disabled_with_a_reason(console):  # AC-122.8
    c = console()
    c.fail("status")
    root, text = c.panel("promote", "shop-api:dev:staging")
    [p] = q(root, "button", data_action="promote")
    assert "disabled" in p.attrs
    assert "cannot be read" in text

