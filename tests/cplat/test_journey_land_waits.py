"""#865: the post-merge part of a `system|component ship land` call (Argo CD, operator bootstrap, the dev smokes) is a deploy
wait, and the smoke inside it is smoke; the merge time comes from GitHub for a PR the land's output says it merged."""
import pytest

from journey181_support import Transcript, run_record, split_of, world  # noqa: F401  (fixture)

GITOPS = "https://github.com/ika100-demo/shop-gitops/pull"
API = "https://github.com/ika100-demo/shop-api/pull"
SYSTEM_LAND = "cplat system ship land"  # interface: command line the classifier reads
COMPONENT_LAND = "cplat component ship land"  # interface: command line the classifier reads
SHIP_NEXT = "cplat system ship next shop --wait"
WINDOW = {"start": "2026-11-10T08:00:00Z", "end": "2026-11-10T08:20:00Z"}


def landed(*urls, wait=None):
    """The output of a land call that merged `urls`, ending in the WAIT line of a land that stopped on its budget."""
    lines = ["GREEN: all 7 check(s) passed"] + [f"merged {u}" for u in urls] + ["READY: 3 app(s) in dev"]
    if wait:
        lines.append(f"WAIT: {wait}; run `cplat system ship land` again: it resumes where it stopped")
    return "\n".join(lines)


def waiting(out):
    w = split_of(out["wall"])["waiting"]
    return {k: round(v, 1) for k, v in w.items() if v > 0.05}


def test_the_wait_after_the_merge_of_a_system_land_is_deploy_and_its_smoke_is_smoke(world, capsys):
    world.merged_prs({"url": f"{GITOPS}/9", "createdAt": -30, "mergedAt": 5})
    world.actions_runs((0, 5))                                              # the dev PR's checks
    smoke = run_record("v1", "verify", 18, 18, smoke={"env": "dev", "duration_s": 60.0})   # written after the smoke ran
    world.add_records(smoke)
    t = Transcript().bash(0, 20, SYSTEM_LAND, output=f"dev PR merged: {GITOPS}/9\n" + landed(f"{GITOPS}/9"))
    code, out, _ = world.measure(capsys, world.coordinator(t), **WINDOW)
    assert code == 0
    assert waiting(out) == {"ci": 5.0, "deploy": 14.0, "smoke": 1.0}


def test_the_staging_pr_of_the_same_land_ends_the_dev_deploy_wait_when_it_is_opened(world, capsys):
    world.merged_prs({"url": f"{GITOPS}/9", "createdAt": -30, "mergedAt": 5},
                     {"url": f"{GITOPS}/10", "createdAt": 10, "mergedAt": 14})
    t = Transcript().bash(0, 20, SYSTEM_LAND, output=landed(f"{GITOPS}/9", f"{GITOPS}/10"))
    code, out, _ = world.measure(capsys, world.coordinator(t), **WINDOW)
    assert code == 0
    assert waiting(out) == {"deploy": 11.0, "unattributed": 9.0}           # 5-10 and 14-20; the staging checks have no kind


def test_a_land_that_stopped_after_the_merge_hands_its_deploy_wait_to_the_next_call(world, capsys):
    world.merged_prs({"url": f"{GITOPS}/9", "createdAt": -30, "mergedAt": 4})
    t = (Transcript().bash(0, 10, SYSTEM_LAND, output=landed(f"{GITOPS}/9", wait="Argo CD in dev"))
         .model(11).bash(12, 20, SYSTEM_LAND, output="READY: 3 app(s) in dev"))
    code, out, _ = world.measure(capsys, world.coordinator(t), **WINDOW)
    assert code == 0
    assert waiting(out) == {"deploy": 14.0, "unattributed": 4.0}           # 4-10 and 12-20


def test_a_land_that_stopped_on_the_checks_hands_nothing_on(world, capsys):
    world.merged_prs({"url": f"{GITOPS}/9", "createdAt": -30, "mergedAt": 15})
    wait = "WAIT: the checks of the dev PR; run `cplat system ship land` again: it resumes where it stopped"
    t = (Transcript().bash(0, 10, SYSTEM_LAND, output=wait)
         .model(11).bash(12, 20, SYSTEM_LAND, output=landed(f"{GITOPS}/9")))
    code, out, _ = world.measure(capsys, world.coordinator(t), **WINDOW)
    assert code == 0
    assert waiting(out) == {"deploy": 5.0, "unattributed": 13.0}           # only 15-20, after the merge


def test_a_merge_the_land_did_not_report_gives_no_kind(world, capsys):
    world.merged_prs({"url": f"{API}/4", "createdAt": -30, "mergedAt": 5})   # another session's merge during the wait
    t = Transcript().bash(0, 20, SYSTEM_LAND, output="GREEN: all 7 check(s) passed")
    code, out, _ = world.measure(capsys, world.coordinator(t), **WINDOW)
    assert code == 0
    assert waiting(out) == {"unattributed": 20.0}


def test_the_post_merge_part_of_a_component_land_in_a_repo_session_is_deploy(world, capsys):
    world.merged_prs({"url": f"{API}/4", "createdAt": -30, "mergedAt": 12})
    out_text = [{"type": "text", "text": f"GREEN: all 11 check(s) passed\nmerged {API}/4 (squash)\nmarker pushed"}]
    world.child("child1", Transcript().model(0).bash(2, 15, COMPONENT_LAND, output=out_text).model(16))
    world.add_records(
        run_record("ps1", "product-ship", 0, 20, repo="ika100-demo/shop-gitops", sessions=["coordsess"], ships=["r1"]),
        run_record("r1", "ship", 0, 16, repo="ika100-demo/shop-api", sessions=["child1"], parent="ps1"))
    coord = Transcript().model(0).bash(1, 19, SHIP_NEXT).model(20)
    code, out, _ = world.measure(capsys, world.coordinator(coord), **WINDOW)
    assert code == 0
    assert waiting(out)["deploy"] == pytest.approx(3.0)                    # 12-15: merged, the land still runs


def test_a_smoke_inside_a_ship_deploy_phase_counts_as_smoke(world, capsys):
    world.add_records(run_record("s1", "ship", 5, 15, phases=[("deploy", 5, 15)]),
                      run_record("v1", "verify", 10, 10, smoke={"env": "dev", "duration_s": 120.0}))
    t = Transcript().bash(0, 20, SHIP_NEXT)
    code, out, _ = world.measure(capsys, world.coordinator(t), **WINDOW)
    assert code == 0
    assert waiting(out) == {"deploy": 8.0, "smoke": 2.0, "unattributed": 10.0}
