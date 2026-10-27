"""Spec 122 verification round A: `cplat runs` fills the run-row contract from the records the commands really write."""
import runlist
import runs


def smoke_section(outcome="passed", image="sha-abc1234", **kw):
    return {"env": "dev", "outcome": outcome, "base_url": "http://x", "passed": 3, "failed": 0, "skipped": 0, "image": image,
            "digest": "sha256:aa", "at": "2026-10-20T10:00:00Z", **kw}


def started(phases, **kw):
    rid = runs.start("ship", repo="acme/shop-api", spec="011-cart")
    for p in phases:
        runs.phase(rid, p)
    return rid


def row(rid):
    return next(r for r in runlist.collect(30)["runs"] if r["run_id"] == rid)


def test_smoke_pr_image_and_ci_come_from_the_real_sections(monkeypatch):
    monkeypatch.setattr(runlist, "lookup_pr", lambda repo, branch: {"number": 41, "url": "https://github.com/acme/shop-api/pull/41"})
    rid = started(["plan", "build", "pr", "land", "deploy"])
    runs.set_section(rid, "smoke", {**smoke_section(), "staging": smoke_section("failed", env="staging")})
    r = row(rid)
    assert r["smoke"] == {"dev": {"result": "passed", "instance": "shop-api/dev"},
                          "staging": {"result": "failed", "instance": "shop-api/staging"}}
    assert r["image"] == "sha-abc1234"
    assert r["pr"] == {"number": 41, "url": "https://github.com/acme/shop-api/pull/41"}
    assert r["ci_url"] == "https://github.com/acme/shop-api/pull/41/checks"


def test_a_run_without_smoke_has_no_smoke_cells(monkeypatch):
    monkeypatch.setattr(runlist, "lookup_pr", lambda repo, branch: None)
    r = row(started(["plan"]))
    assert r["smoke"] == {"dev": None, "staging": None} and r["pr"] is None and r["image"] is None


def test_a_promoted_pin_without_staging_smoke_is_the_staging_phase(monkeypatch):
    monkeypatch.setattr(runlist, "lookup_pr", lambda repo, branch: None)
    rid = started(["plan", "build", "pr", "land", "deploy"])
    runs.set_section(rid, "smoke", smoke_section())
    runs.set_section(rid, "promotion", {"staging": {"result": "promoted", "tag": "sha-abc1234"}})
    r = row(rid)
    assert (r["phase"], r["stage"]) == ("staging", "Staging")


def test_a_done_run_has_the_stage_of_its_last_phase():
    rid = started(["plan", "build", "pr", "land", "deploy", "done"])
    runs.finish(rid, "done")
    r = row(rid)
    assert r["phase"] == "done" and r["stage"] == "Dev"
