"""Spec 122 acceptance tests: `cplat needs [--json]` lists every open decision point (AC-122.4) with the consequence and the way
back of each (AC-122.34, AC-122.35).

Contract: design.md "cplat needs". The GitHub reads go through the replaceable `needs.gh(args) -> str` (answers: spec folders and
spec.md through the contents API, issue lists, PR lists); `status.collect` and `releases.between` are replaced; the run list is the
real one over records written with the run API."""
import base64
import json
import re
from pathlib import Path

import pytest
import yaml

import cplat
import runs
from system_fixtures import rich5, write_system
from test_spec import SPEC

SPEC_ID = "007-price-alerts"


class FakeGh:
    def __init__(self):
        self.specs: dict[str, dict[str, str]] = {}
        self.issues: dict[str, list] = {}
        self.broken = False

    def __call__(self, args):
        if self.broken:
            raise RuntimeError("gh: network unreachable")
        a = " ".join(args)
        m = re.search(r"repos/([^/\s]+/[^/\s]+)/contents/docs/specs/([^/\s?]+)/spec\.md", a)
        if m:
            text = self.specs.get(m.group(1), {}).get(m.group(2))
            if text is None:
                raise RuntimeError("404")
            return text if "raw" in a else json.dumps({"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"})
        m = re.search(r"repos/([^/\s]+/[^/\s]+)/contents/docs/specs(?:\s|\?|$)", a)
        if m:
            return json.dumps([{"name": k, "type": "dir", "path": f"docs/specs/{k}"} for k in self.specs.get(m.group(1), {})])
        if args[:2] == ["issue", "list"]:
            slug = args[args.index("-R") + 1] if "-R" in args else ""
            return json.dumps(self.issues.get(slug, []))
        if args[:2] == ["pr", "list"]:
            return "[]"
        return ""


def issue(n, labels, created="2026-10-20T08:00:00Z", title="alert"):
    return {"number": n, "title": title, "state": "OPEN", "createdAt": created, "url": f"https://github.com/acme/shop-api/issues/{n}",
            "labels": [{"name": x} for x in labels]}


def status_rows(staging="verified", prod="1.3.0", staging_version="1.4.0"):
    def c(v, s):
        return {"tag": v, "ci": "ok", "argo": "Synced/Healthy", "pin_pr": None, "version": v, "state": s, "digest": "sha256:aaaa", "release": v}
    return ("shop", ["dev", "staging", "prod"], [
        {"component": "shop-api", "platform": "5.0.0",
         "cells": {"dev": c(staging_version, "healthy"), "staging": c(staging_version, staging), "prod": c(prod, "healthy")}}], [])


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import needs
    import releases
    import status
    repo = tmp_path / "shop-gitops"
    write_system(repo, rich5())
    fake = FakeGh()
    monkeypatch.setattr(needs, "gh", fake)
    monkeypatch.setattr(status, "collect", lambda *a, **k: status_rows(staging="pinned"))
    monkeypatch.setattr(releases, "between", lambda *a, **k: {
        "commits": 23, "specs": ["012-checkout"], "fixes": [], "criteria": 7,
        "migrations": [{"file": "migrations/versions/0005.py", "additive": False}]})
    monkeypatch.setattr(releases, "previous_release", lambda *a, **k: "1.3.0", raising=False)
    w = type("W", (), {})()
    w.repo, w.gh, w.monkeypatch, w.status = repo, fake, monkeypatch, status
    return w


def needs_json(world, capsys, *extra):
    rc = cplat.main(["needs", "--json", "--repo-dir", str(world.repo), *extra])
    out = capsys.readouterr()
    assert rc == 0, out.err
    return json.loads(out.out)


def items(doc, kind):
    return [i for i in doc["items"] if i["kind"] == kind]


def test_a_draft_with_open_questions_is_an_answer_item_ac_122_4(world, capsys):  # AC-122.4
    world.gh.specs["acme/shop-api"] = {SPEC_ID: SPEC.format(status="draft", questions="- Which mail provider?\n- Rate limit?")}
    doc = needs_json(world, capsys)
    assert doc["schema"] == 1 and doc["system"] == "shop"
    [i] = items(doc, "answer")
    assert i["stage"] == "Spec" and i["object"]["spec"] == SPEC_ID and i["object"]["repo"] == "acme/shop-api"
    assert i["since"] and i["reason"] and "--amend" in i["command"]
    assert not items(doc, "approve")


def test_a_draft_without_open_questions_is_an_approve_item_ac_122_4(world, capsys):  # AC-122.4
    world.gh.specs["acme/shop-api"] = {SPEC_ID: SPEC.format(status="draft", questions="None.")}
    doc = needs_json(world, capsys)
    [i] = items(doc, "approve")
    assert i["id"] == f"approve:acme/shop-api:{SPEC_ID}" and "approve" in i["command"] and i["reason"]
    assert not items(doc, "answer")


def test_an_approved_spec_is_not_a_decision_point_ac_122_4(world, capsys):  # AC-122.4
    world.gh.specs["acme/shop-api"] = {SPEC_ID: SPEC.format(status="approved", questions="None.")}
    assert needs_json(world, capsys)["items"] == []


def test_an_escalated_run_is_an_escalation_item_ac_122_4(world, capsys):  # AC-122.4
    rid = runs.start("ship", repo="acme/shop-api", spec=SPEC_ID)
    runs.phase(rid, "plan")
    runs.phase(rid, "build")
    runs.finish(rid, "escalated", escalation={"reason": "3 CI fix rounds without progress", "cause": "code"})
    [i] = items(needs_json(world, capsys), "escalation")
    assert i["stage"] == "Build" and i["object"]["run_id"] == rid and "3 CI fix rounds" in i["reason"]
    assert "ship" in i["command"]


def test_a_newer_done_run_clears_the_escalation_ac_122_4(world, capsys):  # AC-122.4
    rid = runs.start("ship", repo="acme/shop-api", spec=SPEC_ID)
    runs.phase(rid, "build")
    runs.finish(rid, "escalated", escalation={"reason": "stuck", "cause": "code"})
    ok = runs.start("ship", repo="acme/shop-api", spec=SPEC_ID)
    runs.phase(ok, "build")
    runs.finish(ok, "done")
    assert items(needs_json(world, capsys), "escalation") == []


def test_a_release_verified_in_staging_and_not_in_prod_is_a_promote_item_ac_122_4(world, capsys):  # AC-122.4
    world.monkeypatch.setattr(world.status, "collect", lambda *a, **k: status_rows(staging="verified"))
    [i] = items(needs_json(world, capsys), "promote")
    assert i["stage"] == "Prod" and i["object"]["component"] == "shop-api" and i["object"]["version"] == "1.4.0"
    assert i["command"] == "/instance:promote shop-api --to prod --version 1.4.0"


@pytest.mark.parametrize("staging, prod, staging_version", [("NOT VERIFIED", "1.3.0", "1.4.0"), ("verified", "1.4.0", "1.4.0"), ("pinned", "1.3.0", "1.4.0")])
def test_nothing_to_promote_when_not_verified_or_already_in_prod_ac_122_4(world, capsys, staging, prod, staging_version):  # AC-122.4
    world.monkeypatch.setattr(world.status, "collect", lambda *a, **k: status_rows(staging=staging, prod=prod, staging_version=staging_version))
    assert items(needs_json(world, capsys), "promote") == []


@pytest.mark.parametrize("label", ["alert", "smoke-failure"])
def test_an_unrouted_alert_or_smoke_issue_is_a_triage_item_ac_122_4(world, capsys, label):  # AC-122.4
    world.gh.issues["acme/shop-api"] = [issue(57, ["triage", label])]
    [i] = items(needs_json(world, capsys), "triage")
    assert i["stage"] == "Issue" and i["object"]["issue"] == 57 and i["command"] == "/issue:triage 57"


def test_a_routed_or_ordinary_issue_leaves_the_triage_list_ac_122_4(world, capsys):  # AC-122.4
    world.gh.issues["acme/shop-api"] = [issue(57, ["alert", "bug"]), issue(58, ["triage", "enhancement"])]
    assert items(needs_json(world, capsys), "triage") == []


def test_items_are_sorted_oldest_first_ac_122_4(world, capsys):  # AC-122.4
    world.gh.issues["acme/shop-api"] = [issue(60, ["triage", "alert"], created="2026-10-25T08:00:00Z"),
                                        issue(57, ["triage", "alert"], created="2026-10-20T08:00:00Z")]
    world.gh.specs["acme/shop-api"] = {SPEC_ID: SPEC.format(status="draft", questions="None.")}
    since = [i["since"] for i in needs_json(world, capsys)["items"]]
    assert len(since) == 3 and since == sorted(since)


def test_a_failing_source_is_reported_and_exit_is_still_zero_ac_122_4(world, capsys):  # AC-122.4
    world.gh.broken = True
    doc = needs_json(world, capsys)
    assert doc["items"] == [] or isinstance(doc["items"], list)
    assert doc["unavailable"] and {"source", "error", "kinds"} <= set(doc["unavailable"][0])


def test_without_a_system_yaml_it_fails_naming_it_and_the_directory_ac_122_4(tmp_path, capsys):  # AC-122.4
    rc = cplat.main(["needs", "--json", "--repo-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 1 and "system.yaml" in err and str(tmp_path) in err


def test_without_json_there_is_one_line_per_item_ac_122_4(world, capsys):  # AC-122.4
    world.gh.issues["acme/shop-api"] = [issue(57, ["triage", "alert"])]
    assert cplat.main(["needs", "--repo-dir", str(world.repo)]) == 0
    assert "57" in capsys.readouterr().out


# ---------------- consequence and way back (AC-122.34, AC-122.35) ----------------

def test_an_approval_names_repos_unattended_stages_and_no_estimate_yet_ac_122_34(world, capsys):  # AC-122.34
    world.gh.specs["acme/shop-api"] = {SPEC_ID: SPEC.format(status="draft", questions="None.")}
    [i] = items(needs_json(world, capsys), "approve")
    c = i["consequence"]
    assert "acme/shop-api" in c["repos"] and "Plan" in c["unattended"] and "Staging" in c["unattended"] and "Prod" not in c["unattended"]
    assert c["estimate"] is None


def test_a_promotion_shows_what_lies_between_the_versions_and_the_verified_digest_ac_122_34(world, capsys):  # AC-122.34
    world.monkeypatch.setattr(world.status, "collect", lambda *a, **k: status_rows(staging="verified"))
    [i] = items(needs_json(world, capsys), "promote")
    c = i["consequence"]
    assert (c["from"], c["to"]) == ("1.3.0", "1.4.0") and c["commits"] == 23 and c["criteria"] == 7 and "012-checkout" in c["specs"]
    assert c["digest_matches"] is True and c["verified_digest"] == c["digest"]
    assert c["migrations"] == [{"file": "migrations/versions/0005.py", "additive": False}]


def test_the_way_back_of_a_promotion_is_promoting_the_previous_version_ac_122_35(world, capsys):  # AC-122.35
    world.monkeypatch.setattr(world.status, "collect", lambda *a, **k: status_rows(staging="verified"))
    [i] = items(needs_json(world, capsys), "promote")
    assert i["way_back"]["command"] == "/instance:promote shop-api --to prod --version 1.3.0"
    assert "0005" in i["way_back"]["warning"]


def test_the_way_back_of_an_approval_says_the_run_can_be_paused_ac_122_35(world, capsys):  # AC-122.35
    world.gh.specs["acme/shop-api"] = {SPEC_ID: SPEC.format(status="draft", questions="None.")}
    [i] = items(needs_json(world, capsys), "approve")
    assert "paused" in i["way_back"]["text"] and "prod" in i["way_back"]["text"]


def test_stopping_a_run_keeps_branch_and_pull_request_ac_122_35(world, capsys):  # AC-122.35
    rid = runs.start("ship", repo="acme/shop-api", spec=SPEC_ID)
    runs.phase(rid, "build")
    runs.finish(rid, "escalated", escalation={"reason": "stuck", "cause": "code"})
    [i] = items(needs_json(world, capsys), "escalation")
    assert i["consequence"]["deployed"] is False
    assert "nothing was deployed" in i["way_back"]["text"] and "branch" in i["way_back"]["text"]
