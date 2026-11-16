"""Spec 190, AC-190.4: automatic staging (`promote: after-dev-smoke`, spec 093) skips on an environment limit in the system spec.

Seams: the staging deploy world of test_staging_093_ship (component ship, `staging.decide` over `gh api`) and the joint system ship of
test_144_joint_pr (local gitops clone). The limit is read from `docs/specs/<dir>/spec.md` of the gitops-app; nothing here imports
`envlimit`, so only the missing behaviour fails these tests."""
import re

import pytest

import staging
from test_144_joint_pr import JointWorld
from test_appship_097 import git
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship_checks import argo, gh  # noqa: F401  (gh is a fixture)
from test_smoke_091_ship import PASS_ALL, lines_of, repo, world  # noqa: F401  (fixtures)
from test_staging_093_ship import Api, SWorld, shop_api, system_top

SPEC_ID = "042-anonymous-use"

SPEC = """---
spec_id: {spec_id}
title: Anonymous use
status: {status}
priority: P1
{field}---

# {num}

## Problem

Anonymous use of the app.

## Acceptance criteria

- **AC-{num}.1** Given a visitor, when they open the app, then they see the list.

## Non-goals

- None

## Open questions

None.

## Changelog

- 2026-11-01 created
"""


def spec_text(**kw):
    kw.setdefault("spec_id", SPEC_ID)
    kw.setdefault("status", "building")
    kw.setdefault("field", "environments: [dev]\n")
    return SPEC.format(num=kw["spec_id"][:3], **kw)


class LimitApi(Api):
    """The gitops-app's docs/specs for `staging.decide`: a listing of the spec folders and each spec.md (raw)."""

    def __init__(self, components, top, specs: dict):
        super().__init__(components, top)
        self.specs = specs
        for d, text in specs.items():
            if text is not None:
                self.files[f"docs/specs/{d}/spec.md"] = text

    def __call__(self, args, **kw):
        joined = " ".join(args)
        if args[:1] == ["api"] and re.search(r"contents/docs/specs/?(\s|\?|$)", joined):
            return self._out([{"name": d, "type": "dir"} for d in self.specs], args)
        return super().__call__(args, **kw)


@pytest.fixture()
def sw(repo, gh, store, tr, tmp_path, monkeypatch):  # noqa: F811
    from test_smoke_091_run import FakeDevbox
    return SWorld(repo, gh, store, tr, FakeDevbox(tmp_path, monkeypatch), monkeypatch)


def limit_world(sw, specs):
    return sw.stage(api=LimitApi(shop_api(staging_promote="after-dev-smoke"), system_top(), specs))


def test_a_limiting_spec_stops_the_staging_pin_and_is_not_red(sw, capsys):  # AC-190.4
    limit_world(sw, {SPEC_ID: spec_text()})
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert any(f"not promoted: environment limit {SPEC_ID} allows dev" in line for line in lines_of(capsys))
    assert sw.dispatches() == [] and sw.staging_state()["state"] == "skipped"
    assert sw.state()["phase"] == "done" and not sw.state().get("escalated")


def test_a_spec_allowing_staging_does_not_stop_the_pin(sw, capsys):  # AC-190.4
    limit_world(sw, {SPEC_ID: spec_text(field="environments: [dev, staging]\n")})
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert len(sw.dispatches()) == 1 and "environment limit" not in lines_of(capsys)


def test_a_draft_spec_does_not_stop_the_pin(sw, capsys):  # AC-190.4
    limit_world(sw, {SPEC_ID: spec_text(status="draft")})
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0 and len(sw.dispatches()) == 1


def test_an_unreadable_listed_spec_stops_the_pin_failing_closed(sw, capsys):  # AC-190.4
    limit_world(sw, {SPEC_ID: None})
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert any(f"environment limit of {SPEC_ID} not readable" in line for line in lines_of(capsys)) and sw.dispatches() == []


def test_the_staging_decision_names_the_limit(sw):  # AC-190.4
    limit_world(sw, {SPEC_ID: spec_text()})
    dev = type("Dev", (), {"outcome": "passed", "reason": None})()
    d = staging.decide(sw.repo, {"deployed": "sha-" + "a" * 40}, ["acme/shop-gitops"], "shop-api", dev)
    assert d.action == "skip" and f"environment limit {SPEC_ID} allows dev" in d.reason


@pytest.fixture()
def joint(tmp_path, monkeypatch, capsys):
    return JointWorld(tmp_path, monkeypatch, capsys)


def limit_gitops(w, envs="[dev]"):
    sp = w.gitops / "docs" / "specs" / "012-shop" / "spec.md"
    text = re.sub(r"status: \w+", "status: building", sp.read_text())
    sp.write_text(text.replace("priority: P1\n", f"priority: P1\nenvironments: {envs}\n", 1))
    git(w.gitops, "add", "-A")
    git(w.gitops, "commit", "-qm", "limit")
    git(w.gitops, "push", "-q", "origin", "main")
    git(w.gitops, "fetch", "-q", "origin")


def staging_prs(w):
    return [c for c in w.made("pr", "create") if any(str(x).startswith("promote/staging-") for x in c)]


def test_the_system_ship_promotes_no_component_to_a_limited_staging(joint):  # AC-190.4
    joint.to_land()
    limit_gitops(joint)
    old = joint.pin("staging", "shop-api")
    r = joint.app("land")
    assert r.rc == 0, r.out
    assert "Promotion (staging) shop-api: not promoted: environment limit 012-shop allows dev" in r.out
    assert "Promotion (staging) shop-web: not promoted: environment limit 012-shop allows dev" in r.out
    assert staging_prs(joint) == [] and joint.pin("staging", "shop-api") == old


def test_the_system_ship_still_promotes_when_the_spec_allows_staging(joint):  # AC-190.4
    joint.to_land()
    limit_gitops(joint, "[dev, staging]")
    r = joint.app("land")
    assert r.rc == 0, r.out
    assert len(staging_prs(joint)) == 1 and "environment limit" not in r.out
