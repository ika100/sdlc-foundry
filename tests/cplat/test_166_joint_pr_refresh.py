"""Spec 166: the system ship's dev PR is brought up to main before it lands (#597).

Seams: spec 144's joint world (`test_144_joint_pr.JointWorld`: real git on a local bare origin, fake `gh` whose merge moves
main to the PR branch, fake `devbox` that runs `pin.py`); here main moves on after the builds were pinned on compose/<spec>.
`staging.newer` (GitHub's compare) is replaced to say which build is later.
"""
import subprocess

import pytest

import staging
from test_144_joint_pr import WEB_SHA, JointWorld, kustomization
from test_appship_097 import SHA, SPEC, git
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

LATER_WEB = "f" * 40


@pytest.fixture()
def j(tmp_path, monkeypatch, capsys):
    return JointWorld(tmp_path, monkeypatch, capsys)


def push_main(j, path, text, msg):
    """A gitops PR merged on main while the run's builds wait on compose/<spec>."""
    git(j.gitops, "checkout", "-q", "main")
    git(j.gitops, "pull", "-q", "origin", "main")
    f = j.gitops / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(j.gitops, "add", "-A")
    git(j.gitops, "commit", "-qm", msg)
    git(j.gitops, "push", "-q", "origin", "main")
    return git(j.gitops, "rev-parse", "HEAD")


def on_main(j, sha):
    return subprocess.run(["git", "--git-dir", str(j.origin), "merge-base", "--is-ancestor", sha, "main"]).returncode == 0


def test_main_merged_meanwhile_is_kept_when_the_dev_pr_lands_ac_166_1(j):  # AC-166.1
    j.to_land()
    hosts = push_main(j, "docs/hosts.md", "hosts\n", "feat: hosts")
    r = j.app("land")
    assert r.rc == 0, r.out
    assert on_main(j, hosts), "the gitops PR merged meanwhile is still on main after the dev PR landed"
    assert f"compose/{SPEC}: merged main" in r.out
    assert j.pin("dev", "shop-api") == f"sha-{SHA}" and j.pin("dev", "shop-web") == f"sha-{WEB_SHA}"


def test_a_conflict_in_a_rendered_pin_takes_main_and_pins_the_run_again_ac_166_2(j):  # AC-166.2
    j.to_land()
    older = "sha-" + "2" * 40
    push_main(j, "applications/shop/overlays/dev/shop-web/kustomization.yaml", kustomization("shop-web", older), "chore(dev): pin web")
    r = j.app("land")
    assert r.rc == 0, r.out
    assert "took main's rendered files in 1 conflict(s)" in r.out
    assert f"shop-web: pinned sha-{WEB_SHA} again" in r.out
    assert j.pin("dev", "shop-web") == f"sha-{WEB_SHA}" and j.pin("dev", "shop-api") == f"sha-{SHA}"


def test_a_later_build_on_main_is_kept_and_reported_as_what_dev_runs_ac_166_3(j, monkeypatch):  # AC-166.3
    j.to_land()
    monkeypatch.setattr(staging, "newer", lambda slug, build, have, repo=None: "ahead" if have == LATER_WEB else "behind")
    push_main(j, "applications/shop/overlays/dev/shop-web/kustomization.yaml", kustomization("shop-web", f"sha-{LATER_WEB}"),
              "chore(dev): pin web")
    r = j.app("land")
    assert r.rc == 0, r.out
    assert f"main pins a later build (sha-{LATER_WEB})" in r.out
    assert j.pin("dev", "shop-web") == f"sha-{LATER_WEB}"
    assert j.state()["repos"]["shop-web"]["pinned"] == f"sha-{LATER_WEB}"
    assert j.state()["repos"]["shop-web"]["deployed"] == f"sha-{LATER_WEB}", "the report names the build dev runs"


def test_a_conflict_in_system_yaml_escalates_without_merging_ac_166_4(j):  # AC-166.4
    j.to_land()
    wt = j.common / "cplat-app-ship" / f"{SPEC}-entry"
    sysyaml = "applications/shop/system.yaml"
    text = (wt / sysyaml).read_text()
    (wt / sysyaml).write_text(text.replace("owner: acme", "owner: acme-compose"))
    git(wt, "commit", "-qam", "feat(compose): owner")
    git(wt, "push", "-q", "origin", f"HEAD:compose/{SPEC}")
    push_main(j, sysyaml, text.replace("owner: acme", "owner: acme-main"), "feat: owner on main")
    r = j.app("land")
    assert r.rc == 1, r.out
    assert f"conflicts with main in {sysyaml}" in r.out
    assert j.dev_merges() == []
    assert "conflicts with main" in j.state()["escalated"]
    assert git(wt, "status", "--porcelain") == "", "the merge was aborted"
