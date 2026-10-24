"""Spec 087, reviewer findings: CI rounds in deploy, one shared clock for the 20 s budget, --no-merge records once."""
import json

import runs
import runs_store
import ship
from test_runs import Clock, buffered_lines, clock, mem, one_run, store, stored, warnings  # noqa: F401  (fixtures)
from test_ship import SHA, check, git, repo, to_land  # noqa: F401  (fixtures)
from test_ship_checks import GITOPS, gh, to_deploy  # noqa: F401  (fixtures)


def test_deploy_counts_main_ci_and_pin_dev_conclusions_as_ci_rounds(repo, gh, store):
    """AC-087.4: in deploy, a red main CI and a red pin-dev run each count a CI round, and so does the green main CI."""
    to_deploy(repo)
    gh.main_runs = [{"databaseId": 5, "status": "completed", "conclusion": "failure"}]
    assert not ship.deploy(repo, timeout=1800, interval=20, context=None)[0]
    gh.main_runs = []
    gh.pin_prs[GITOPS] = [{"number": 9, "state": "OPEN", "url": f"https://github.com/{GITOPS}/pull/9"}]
    gh.pin_runs[GITOPS] = [{"databaseId": 78, "displayTitle": f"pin-dev shop-api sha-{SHA}"}]
    gh.run_views["78"] = [{"status": "in_progress"}, {"status": "completed", "conclusion": "failure"}]
    assert not ship.deploy(repo, timeout=1800, interval=20, context=None)[0]
    gh.main_runs = [{"databaseId": 5, "status": "completed", "conclusion": "success"}]
    gh.pin_prs[GITOPS] = [{"number": 9, "state": "MERGED", "url": f"https://github.com/{GITOPS}/pull/9"}]
    assert ship.deploy(repo, timeout=1800, interval=20, context=None)[0]
    (r,) = stored(store)
    assert r["outcome"] == "done" and r["ci_rounds"] == 3


def test_a_pin_dev_run_is_counted_once_however_often_it_is_polled(repo, gh, store):
    """AC-087.4: a concluded pin-dev run that is polled again while its PR is still open is one CI round."""
    to_deploy(repo)
    st = ship.require_state(repo)
    gh.run_views["78"] = [{"status": "completed", "conclusion": "success"}]
    w = ship.RunWatch(repo, GITOPS, "78", 300, st["run_id"])
    assert [w.poll(), w.poll(), w.poll()] == ["green"] * 3
    assert runs.active(st["run_id"])["ci_rounds"] == 1


def test_a_no_merge_ship_is_recorded_once_when_it_ends(repo, gh, store):
    """AC-087.1: --no-merge ends the run at the green PR (phase done, nothing resumes it): one `done` record, and a
    later `ship start` of the same spec adds no second record."""
    to_land(repo, gh, merge=False)
    gh.checks = [[check("test", "pass")]]
    assert ship.land(repo, timeout=60, interval=10)[0]
    assert ship.load_state(repo)["phase"] == "done"
    ship.start(repo, "7", False)
    ship.deploy(repo, timeout=60, interval=10, context=None)
    (r,) = stored(store)
    assert r["outcome"] == "done" and r["ci_rounds"] == 1 and runs.buffered_count() == 0


def test_a_take_over_refused_by_a_claim_leaves_the_old_run_unfinished(repo, gh, store, monkeypatch):
    """AC-087.3: the old run is only recorded `abandoned` once nothing can refuse the take-over any more."""
    import claim
    import core
    st = ship.start(repo, "7", True)
    monkeypatch.setattr(ship.specmod, "find", lambda r, ref: type("S", (), {
        "id": "099-other", "number": 99, "status": "approved", "meta": {"tracks": ["acme/shop-api#1"]}, "plan": None})())

    def refuse(*a, **kw):
        raise core.PlatformError("claimed by another branch")
    monkeypatch.setattr(claim, "claim", refuse)
    try:
        ship.start(repo, "99", True, take_over=True)
        raise AssertionError("expected a refusal")
    except core.PlatformError:
        pass
    assert runs.active(st["run_id"]) is not None and stored(store) == [] and runs.buffered_count() == 0


def test_the_store_clock_and_the_budget_clock_are_one(monkeypatch, tmp_path):
    """AC-087.7: with every gh call taking several fake seconds, each call gets min(10, remaining) as its timeout, none
    starts with less than 1 s left, and the record is buffered within 20 s of fake time."""
    t = {"now": 0.0}
    monkeypatch.setattr(runs_store, "monotonic", lambda: t["now"])
    timeouts: list[float] = []

    def fake_gh(args, *, input=None, timeout=10.0):
        timeouts.append(timeout)
        t["now"] += min(6.0, timeout)
        path = args[1]
        if path.endswith("/git/ref/heads/main"):
            return 0, json.dumps({"object": {"sha": "h"}}), ""
        if "/git/commits/" in path:
            return 0, json.dumps({"tree": {"sha": "t"}}), ""
        if path.endswith("/git/trees"):
            return 0, json.dumps({"sha": "tr"}), ""
        return 0, json.dumps({"private": True, "default_branch": "main"}), ""

    monkeypatch.setattr(runs_store, "gh", fake_gh)
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")
    monkeypatch.setenv("CPLAT_RUNS_DIR", str(tmp_path / "state"))
    rid = runs.start("ship", repo="acme/shop-api")
    started = t["now"]
    runs.finish(rid, "done")
    assert timeouts and all(1.0 <= x <= 10.0 for x in timeouts)
    assert timeouts[:3] == [10.0, 10.0, 8.0]
    assert t["now"] - started <= 20.0
    assert runs.buffered_count() == 1
