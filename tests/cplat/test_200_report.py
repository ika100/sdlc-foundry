"""Spec 200 acceptance tests: the final report of a handed-off run is built from `cplat component ship status` (AC-200.6).

A finished run is a fake: the ship state of a clone as `deploy` leaves it (phase `done`, the PR, the merge commit, the deploy
lines, smoke rows), a `verification.md` that passes, the deps state with two patched bumps and a plan with human steps. The two
paths of the report (the in-session ship and the hand-off) read the same state; `ship_report.data(repo, st)` and `ship status
--json` must give the same data (design.md, "`ship status` report").
"""
import json

import pytest

import deps
import ship
import spec as specmod
from ship200_support import BRANCH, SPEC, cli
from test_ship import repo  # noqa: F401  (fixture)

SHA = "0123456789abcdef0123456789abcdef01234567"
PR = "https://github.com/acme/shop-api/pull/7"
PIN = "https://github.com/acme/shop-gitops/pull/3"
STAGING_PIN = "https://github.com/acme/shop-gitops/pull/4"
DEPLOY = [f"dev: shop-api:sha-{SHA} (pin PR {PIN}) · Argo Synced/Healthy", "Smoke (dev): 2/2 passed"]
HANDOFF = {"headless": {"pid": 4242, "log": "/logs/x-ship.log", "started": "2026-11-15T10:15:00", "starts": 1,
                        "run_id": "r1", "flags": []}}


def report_module():
    try:
        import ship_report
    except ModuleNotFoundError:
        pytest.fail("scripts/cplat/ship_report.py does not exist yet (plan task t3: data(repo, st) and lines(data))")
    return ship_report


def finished(repo, merge=True, handed_off=False):
    d = repo / "docs" / "specs" / SPEC
    (d / "verification.md").write_text("# Verification\n\n**Result:** pass\n")
    sp = specmod.find(repo, "7")
    meta, body = sp.plan
    meta["human_steps"] = ["set the API key in the dev secret"]
    specmod.save(sp.dir / "plan.md", meta, body)
    deps._save_state(repo, {"run": "r1", "rounds": 1, "bumps": [
        {"package": "requests", "from": "2.31.0", "to": "2.32.0", "advisories": ["CVE-2024-0001"], "severity": "high",
         "major": False, "outcome": "patched", "round": 1},
        {"package": "urllib3", "from": "1.26.0", "to": "2.0.0", "advisories": ["CVE-2024-0002"], "severity": "high",
         "major": True, "outcome": "patched", "round": 1},
        {"package": "flask", "from": "1.0", "to": "2.0", "advisories": ["CVE-2024-0003"], "severity": "high",
         "major": True, "outcome": "reverted", "round": 1}]})
    st = {"spec": SPEC, "phase": "done", "merge": merge, "branch": BRANCH, "started": "2026-11-15T10:00:00", "recorded": True,
          "run_id": "r1", "fix_rounds": 1, "pr": PR, "deploy_lines": DEPLOY,
          "smoke": {"row": "2/2 passed"},
          "staging": {"row": f"Promotion (staging): sha-{SHA} ({STAGING_PIN})", "smoke": {"row": "1/1 passed"}}}
    if merge:
        st.update(merge_sha=SHA, deployed=f"shop-api:sha-{SHA}")
    if handed_off:
        st.update(HANDOFF)
    ship.save_state(repo, st)
    return st


def block(out):
    lines = out.splitlines()
    assert "report:" in lines, out
    return lines[lines.index("report:"):]


def test_status_of_a_finished_run_prints_the_report_rows_ac_200_6(repo, capsys):  # AC-200.6
    finished(repo, handed_off=True)
    rc, out, err = cli(capsys, repo, "status")
    assert rc == 0, out + err
    rows = block(out)
    for want in ("  plan: 3 tasks", "  build: 2/2 criteria met (verification.md: pass)",
                 f"  pr: {PR}, merged after 2 CI round(s)", f"  merge: {SHA}",
                 f"  deploy: {DEPLOY[0]}", f"  deploy: {DEPLOY[1]}", "  smoke (dev): 2/2 passed",
                 f"  promotion (staging): sha-{SHA} ({STAGING_PIN})", "  smoke (staging): 1/1 passed"):
        assert want in rows, (want, rows)
    assert any("requests 2.31.0 → 2.32.0 (CVE-2024-0001)" in ln for ln in rows)
    assert any("urllib3 1.26.0 → 2.0.0 (CVE-2024-0002), major bump" in ln for ln in rows)
    assert not any("flask" in ln for ln in rows)                                   # a reverted bump is not a patch
    assert any("- [ ] set the API key in the dev secret" in ln for ln in rows)


def test_a_run_that_is_green_but_not_merged_says_so_ac_200_6(repo, capsys):  # AC-200.6
    finished(repo, merge=False)
    rc, out, _ = cli(capsys, repo, "status")
    assert rc == 0 and f"  pr: {PR}, green, not merged (--no-merge)" in block(out)


def test_status_json_carries_the_report_object_ac_200_6(repo, capsys):  # AC-200.6
    finished(repo, handed_off=True)
    rc, out, _ = cli(capsys, repo, "status", "--json")
    assert rc == 0
    r = json.loads(out)["report"]
    assert r["plan_tasks"] == 3 and r["criteria_total"] == 2 and r["verification"] == "pass"
    assert r["pr"] == PR and r["merged"] is True and r["ci_rounds"] == 2 and r["merge_sha"] == SHA
    assert r["deployed"] == f"shop-api:sha-{SHA}" and r["deploy_lines"] == DEPLOY
    assert r["smoke_dev"] == "2/2 passed" and r["smoke_staging"] == "1/1 passed"
    assert r["promotion_staging"] == f"sha-{SHA} ({STAGING_PIN})"
    assert [(b["package"], b["from"], b["to"], b["advisories"], b["major"]) for b in r["dependency_patches"]] == [
        ("requests", "2.31.0", "2.32.0", ["CVE-2024-0001"], False), ("urllib3", "1.26.0", "2.0.0", ["CVE-2024-0002"], True)]
    assert r["human_steps"] == ["set the API key in the dev secret"]


def test_the_in_session_path_and_the_hand_off_path_give_the_report_the_same_data_ac_200_6(repo, capsys):  # AC-200.6
    ship_report = report_module()
    in_session = finished(repo)                                          # the state the in-session ship leaves
    data = ship_report.data(repo, in_session)
    handed = {**in_session, **HANDOFF}                                    # the same run, handed off
    assert ship_report.data(repo, handed) == data
    ship.save_state(repo, handed)
    rc, out, _ = cli(capsys, repo, "status", "--json")
    assert rc == 0 and json.loads(out)["report"] == data                  # what the shipping session reads
    rc, text, _ = cli(capsys, repo, "status")
    rows = text.splitlines()
    want = ship_report.lines(data)
    assert want[0] == "report:" and rows[rows.index("report:"):][:len(want)] == want


@pytest.mark.parametrize("steps", [[], ["set the API key in the dev secret"]])
def test_deploy_keeps_its_result_lines_in_the_state_for_the_report_ac_200_6(repo, steps):  # AC-200.6
    st = {"spec": SPEC, "phase": "deploy", "merge": True, "branch": BRANCH, "started": "2026-11-15T10:00:00", "recorded": True,
          "run_id": "r1", "pr": PR, "merge_sha": SHA}
    ship.save_state(repo, st)
    if steps:
        sp = specmod.find(repo, "7")
        meta, body = sp.plan
        meta["human_steps"] = steps
        specmod.save(sp.dir / "plan.md", meta, body)
    ok, lines = ship._done(repo, st, list(DEPLOY))
    assert ok and ship.load_state(repo)["deploy_lines"] == DEPLOY         # the lines before the human steps
