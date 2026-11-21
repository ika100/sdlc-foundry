"""#924: `cplat system ship land` never needs a background run and an ad-hoc wait. One call stops its waits after its
budget and exits 3 (`WAIT:`) with the state kept, so the coordinator calls it again in the foreground; a running land is
a cplat wait the Stop hook sees (ADR-093) and a detached wait under `cplat headless` (spec 202).

Seams: the joint system ship world of spec 144 (`test_144_joint_pr.JointWorld`).
"""
import waitdetach
import waits
import ship
import appship_joint
from test_144_joint_pr import JointWorld, j  # noqa: F401  (fixture)


def test_land_stops_at_its_budget_with_wait_and_resumes_after_the_merge(j):  # noqa: F811
    j.to_land()
    j.argo["stale"] = True
    r = j.app("land", "--budget", "0")
    assert r.rc == appship_joint.WAIT == 3, r.out
    assert "WAIT:" in r.out and "TIMEOUT:" not in r.out
    st = j.state()
    assert st.get("dev_merged") and not st.get("dev_landed") and not st.get("escalated")
    assert len(j.dev_merges()) == 1
    j.argo["stale"] = False
    r = j.app("land")
    assert r.rc == 0, r.out
    assert len(j.dev_merges()) == 1


def test_checks_still_running_at_the_budget_wait_and_merge_nothing(j):  # noqa: F811
    j.to_land()

    def pending(*a, **k):
        raise ship.ChecksPending("checks still pending", checks=["validate"])
    j.mp.setattr(ship, "wait_checks", pending)
    r = j.app("land", "--budget", "0")
    assert r.rc == 3, r.out
    assert "WAIT:" in r.out
    st = j.state()
    assert not st.get("dev_merged") and not st.get("escalated") and j.dev_merges() == []
    assert st["land_ci_since"][st["joint_pr"]]                     # the checks' own timeout counts from the first call


def test_the_checks_own_timeout_is_still_an_error_not_a_wait(j):  # noqa: F811
    j.to_land()

    def pending(*a, **k):
        raise ship.ChecksPending("checks still pending", checks=["validate"])
    j.mp.setattr(ship, "wait_checks", pending)
    r = j.app("land", "--timeout", "0", "--budget", "1000")
    assert r.rc == 1 and "WAIT:" not in r.out, r.out


def test_an_argo_timeout_inside_the_budget_stays_a_timeout(j):  # noqa: F811
    j.to_land()
    j.argo["stale"] = True
    r = j.app("land", "--wait-timeout", "0")
    assert r.rc == 2 and "TIMEOUT:" in r.out, r.out


def test_a_running_land_is_a_cplat_wait_the_stop_hook_sees(j):  # noqa: F811
    j.to_land()
    seen = []

    def fake_land(repo, *a, **k):
        seen.extend(waits.live(repo))
        return 0, ["landed"]
    j.mp.setattr(appship_joint, "land", fake_land)
    j.mp.chdir(j.gitops)                                            # the session runs land in the gitops-app checkout
    assert j.app("land").rc == 0
    assert "cplat system ship land" in seen  # interface: the wait's command name the Stop hook reports


def test_land_detaches_under_headless():
    assert waitdetach._matches(["system", "ship", "land"]) is not None
