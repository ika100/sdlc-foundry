"""Spec 144 acceptance tests: a system ship lands dev (and staging) in one gitops PR, as design.md "Contract" describes it.

Seams: the system ship world of spec 097 (`test_appship_097.World`: real git on a local bare origin, fake `gh`, `kubectl`,
`devbox`), here with the template's `pin-dev.yml` and `pin.py` in the gitops-app, a system of two exposed components with dev
and staging overlays, a fake `gh` that also closes PRs and answers `run list` from its config, and a fake `devbox` that runs
`pin.py` and `plan.py`. Argo CD is `envwait.kubectl` (the apps at origin's head, running what that revision pins), the smoke
is `smoke.run_smoke` / `smoke.record` / `smoke.file_issue`, the digests `cluster.running_digest` / `registry.digest`.
"""
import importlib
import itertools
import json
import shutil
import subprocess
import sys

import pytest
import yaml

import autoissue
import cluster
import core
import envwait
import registry
import ship
from waiting import with_prelude
import smoke
import waits
from test_appship_097 import FAKE_GH, GITOPS, REPO_SPEC, SHA, SLUG, SPEC, World, git, plan_text
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

WEB_SHA = "89abcdef0123456789abcdef0123456789abcdef"
OLD = "sha-" + "1" * 40
DIGEST = "sha256:" + "a" * 64

REPOS = [
    (GITOPS, "gitops-app", [], ["AC-012.1"], False),
    ("shop-api", "service-python", [GITOPS], ["AC-012.1"], False),
    ("shop-web", "web-nextjs", ["shop-api"], ["AC-012.2"], False),
]

SYSTEM = """system: shop
owner: acme
environments:
  dev: {host: '{component}.dev.example.test'}
  staging: {host: '{component}.staging.example.test', promote: %(promote)s}
  prod: {}
components:
  shop-api: {type: service, lang: python, repo: acme/shop-api, expose: true, instances: {dev: {}, staging: {}}}
  shop-web: {type: website, lang: typescript, repo: acme/shop-web, expose: true, instances: {dev: {}, staging: {}}}
"""

GH_144 = FAKE_GH.replace(
    'elif args[:2] == ["pr", "ready"]:',
    'elif args[:2] == ["pr", "close"]:\n'
    '    n = num(args[2])\n'
    '    cfg["prs"][n]["state"] = "CLOSED"\n'
    '    save()\n'
    'elif args[:2] == ["pr", "ready"]:',
).replace(
    'elif args[:2] == ["run", "list"] or args[:1] == ["api"]',
    'elif args[:2] == ["run", "list"]:\n'
    '    print(json.dumps(cfg.get("runs", [])))\n'
    'elif args[:1] == ["api"]',
)

DEVBOX_144 = f'''#!{sys.executable}
import os, sys
a = sys.argv[1:]
for i, x in enumerate(a):
    if x.endswith("plan.py") or x.endswith("pin.py"):
        os.execv(sys.executable, [sys.executable, *a[i:]])
sys.exit(0)
'''


def kustomization(comp, tag):
    return yaml.safe_dump({"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                           "resources": ["../../../base"], "images": [{"name": f"ghcr.io/acme/{comp}", "newTag": tag}]},
                          sort_keys=False)


class JointWorld(World):
    """Spec 097's world with a gitops-app of this spec's template (or, `legacy`, one rendered before it)."""

    def __init__(self, tmp_path, monkeypatch, capsys, legacy=False, promote="after-dev-smoke"):
        self.legacy, self.promote = legacy, promote
        super().__init__(tmp_path, monkeypatch, capsys)
        (self.bin / "gh").write_text(with_prelude(GH_144 % {"py": sys.executable, "sha": SHA}))
        (self.bin / "devbox").write_text(with_prelude(DEVBOX_144))
        cfg = self.cfg()
        cfg["kube"]["contexts"]["kind-shop"] = ["shop-api-dev", "shop-web-dev"]
        self.cfg(kube=cfg["kube"], runs=[{"databaseId": 1, "status": "completed", "conclusion": "success"}])
        monkeypatch.setattr(importlib.import_module("preflight"), "check_repo", lambda *a, **k: None)
        self.argo = {"degraded": [], "stale": False}
        self.smoked, self.recorded, self.filed, self.red = [], [], [], set()
        monkeypatch.setattr(envwait, "kubectl", self.kubectl)
        monkeypatch.setattr(waits, "sleep", lambda s: None)
        monkeypatch.setattr(smoke, "run_smoke", self.run_smoke)
        monkeypatch.setattr(smoke, "record", lambda repo, res, image, spec_id: self.recorded.append((repo.name, res.env, image, spec_id)) or "rid")
        monkeypatch.setattr(smoke, "file_issue", self.file_issue)
        monkeypatch.setattr(cluster, "running_digest", lambda *a, **k: DIGEST)
        monkeypatch.setattr(registry, "digest", lambda image, tag: DIGEST)

    def make_gitops(self, status="approved"):
        super().make_gitops(status)
        g = self.gitops
        if not self.legacy:
            (g / ".github" / "workflows").mkdir(parents=True)
            shutil.copy(core.PLATFORM_ROOT / "templates" / "gitops-app" / ".github" / "workflows" / "pin-dev.yml",
                        g / ".github" / "workflows" / "pin-dev.yml")
        else:
            (g / ".github" / "workflows").mkdir(parents=True)
            (g / ".github" / "workflows" / "pin-dev.yml").write_text("name: pin-dev\n# rendered before spec 144\n")
        shutil.copy(core.PLATFORM_ROOT / "templates" / "gitops-app" / "scripts" / "pin.py", g / "scripts" / "pin.py")
        (g / "applications" / "shop" / "system.yaml").write_text(SYSTEM % {"promote": self.promote})
        for env in ("dev", "staging"):
            for comp in ("shop-api", "shop-web"):
                d = g / "applications" / "shop" / "overlays" / env / comp
                d.mkdir(parents=True)
                (d / "kustomization.yaml").write_text(kustomization(comp, OLD))
        (g / "docs" / "plan" / f"{SPEC}.md").write_text(plan_text(REPOS))
        git(g, "add", "-A")
        git(g, "commit", "-qm", "system of spec 144")
        git(g, "push", "-q", "origin", "main")
        git(g, "fetch", "-q", "origin")

    # ---- Argo CD: every app at origin's head, running what that revision pins
    def origin_head(self, back=0):
        return subprocess.run(["git", "--git-dir", str(self.origin), "rev-parse", f"main~{back}"], capture_output=True,
                              text=True).stdout.strip()

    def dev_merges(self):
        return [c for c in self.made("pr", "merge") if c[2] == self.state()["joint_pr"]]

    def pin(self, env, comp, ref="main"):
        text = subprocess.run(["git", "--git-dir", str(self.origin), "show", f"{ref}:applications/shop/overlays/{env}/{comp}/kustomization.yaml"],
                              capture_output=True, text=True).stdout
        return (yaml.safe_load(text) or {}).get("images", [{}])[0].get("newTag")

    def kubectl(self, args, context=None, check=False):
        if args[:3] == ["-n", "argocd", "get"]:
            rev = self.origin_head(1) if self.argo["stale"] else self.origin_head()
            items = []
            for env in ("dev", "staging"):
                for comp in ("shop-api", "shop-web"):
                    app = f"{comp}-{env}"
                    health = "Degraded" if app in self.argo["degraded"] else "Healthy"
                    items.append({"metadata": {"name": app}, "status": {
                        "sync": {"status": "Synced", "revision": rev}, "health": {"status": health},
                        "summary": {"images": [f"ghcr.io/acme/{comp}:{self.pin(env, comp)}"]}}})
            return subprocess.CompletedProcess(args, 0, json.dumps({"items": items}), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def run_smoke(self, repo, base_url, *, env="dev", spec=None, **kw):
        self.smoked.append((repo.name, env, base_url))
        if (repo.name, env) in self.red:
            return smoke.SmokeResult(env=env, outcome="red", base_url=base_url, passed=1, failed=1, failing=["test_list"],
                                     failure_class="application", tail="AssertionError")
        return smoke.SmokeResult(env=env, outcome="passed", base_url=base_url, passed=3)

    def file_issue(self, result, **kw):
        self.filed.append((kw.get("service_slug"), result.env))
        return autoissue.Outcome("filed", "sig", f"https://github.com/{kw.get('service_slug')}/issues/9", 9, ["issue filed"])

    # ---- steps of a run
    def entry(self):
        r = self.app("repo", "start", GITOPS)
        assert r.rc == 0, r.out
        wt = self.common / "cplat-app-ship" / f"{SPEC}-entry"
        (wt / "applications" / "shop" / "entry.yaml").write_text("postgres: true\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "feat(compose): 012-shop — postgres")
        body = self.root / "body.md"
        body.write_text("## Summary\n")
        assert self.app("entry", "pr", GITOPS, "--title", "feat(compose): 012-shop — postgres", "--body-file", str(body)).rc == 0
        r = self.app("entry", "land", GITOPS)
        assert r.rc == 0, r.out
        return wt, r

    def joint_ship(self, rid, sha=SHA, **over):
        """The clone's ship state as a component ship inside a joint system ship leaves it."""
        st = {"product": {"dir": str(self.gitops), "run_id": self.state()["run_id"], "context": "kind-shop", "joint": True, "spec": SPEC},
              "merge_sha": sha, "deployed": None, "joint": {"tag": f"sha-{sha}"},
              "smoke": {"outcome": "deferred", "row": "with the system ship"}}
        st.update(over)
        return self.ship_state(rid, **st)

    def deliver(self, rid, sha=SHA):
        assert self.app("repo", "start", rid).rc == 0
        self.joint_ship(rid, sha)
        r = self.app("repo", "result", rid)
        assert r.rc == 0, r.out
        return r

    def to_land(self):
        self.started()
        self.entry()
        self.deliver("shop-api")
        self.deliver("shop-web", WEB_SHA)

    def dev_prs(self):
        return [c for c in self.made("pr", "create") if any(str(x).startswith(("compose/", "pin/dev-")) for x in c)]

    def heads(self):
        return git(self.gitops, "ls-remote", "--heads", "origin")


@pytest.fixture()
def j(tmp_path, monkeypatch, capsys):
    return JointWorld(tmp_path, monkeypatch, capsys)


@pytest.fixture()
def manual(tmp_path, monkeypatch, capsys):
    return JointWorld(tmp_path, monkeypatch, capsys, promote="manual")


@pytest.fixture()
def legacy(tmp_path, monkeypatch, capsys):
    return JointWorld(tmp_path, monkeypatch, capsys, legacy=True)


# ---------------- AC-144.1: one dev PR, no pin-dev PR of its own ----------------

def test_a_gitops_app_with_the_new_pin_dev_runs_joint_ac_144_1(j):  # AC-144.1
    r = j.app("start", SPEC, "--context", "kind-shop")
    assert r.rc == 0, r.out
    assert j.state()["joint"] is True
    assert "one dev PR per component" not in r.out  # interface: cplat output line the joint run must not print


def test_an_older_gitops_app_keeps_one_pr_per_component_with_one_line_ac_144_1(legacy):  # AC-144.1
    r = legacy.app("start", SPEC, "--context", "kind-shop")
    assert r.rc == 0, r.out
    assert legacy.state()["joint"] is False
    assert "one dev PR per component: this gitops-app's pin-dev.yml predates spec 144; run /platform:update" in r.out
    legacy.app("repo", "start", GITOPS)
    wt = legacy.common / "cplat-app-ship" / f"{SPEC}-entry"
    (wt / "x.yaml").write_text("x: 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "feat(compose): x")
    body = legacy.root / "b.md"
    body.write_text("b\n")
    legacy.app("entry", "pr", GITOPS, "--title", "feat(compose): x", "--body-file", str(body))
    assert legacy.app("entry", "land", GITOPS).rc == 0
    assert len(legacy.made("pr", "merge")) == 1               # as before spec 144: the entry merges first


def test_the_component_ship_inside_a_joint_run_knows_it_ac_144_1(j):  # AC-144.1
    st = j.started()
    clone = j.clone("shop-api")
    from test_spec import make
    make(clone, status="approved")
    assert ship.main(["--repo", str(clone), "start", REPO_SPEC, "--system-dir", str(j.gitops)]) == 0
    assert ship.load_state(clone)["product"] == {"dir": str(j.gitops), "run_id": st["run_id"], "context": "kind-shop",
                                                 "joint": True, "spec": SPEC}


def test_the_merge_of_a_joint_component_ship_pushes_its_marker_ac_144_1(j):  # AC-144.1
    j.started()
    j.add_pr(7, "feature/x")
    cfg = j.cfg()
    cfg["prs"]["7"].update(state="MERGED", url="https://github.com/acme/shop-api/pull/7")
    j.cfg(prs=cfg["prs"])
    j.joint_ship("shop-api", phase="land", pr="https://github.com/acme/shop-api/pull/7", merge_sha=None)
    assert ship.main(["--repo", str(j.clone("shop-api")), "land"]) == 0
    assert f"refs/heads/ship/{SPEC}/shop-api-{SHA[:7]}" in j.heads()
    assert ship.load_state(j.clone("shop-api"))["phase"] == "deploy"


def test_result_pins_the_build_on_the_compose_branch_and_closes_a_stray_pin_pr_ac_144_1(j):  # AC-144.1
    j.started()
    j.entry()
    stray = j.add_pr(30, f"pin/dev-shop-api-{SHA[:7]}")
    j.deliver("shop-api")
    assert j.pin("dev", "shop-api", f"compose/{SPEC}") == f"sha-{SHA}"
    assert j.pin("dev", "shop-api") == OLD                    # main (dev) is not changed yet
    assert j.cfg()["prs"]["30"]["state"] == "CLOSED"
    assert [c[2] for c in j.made("pr", "close")] == [stray]
    assert len(j.dev_prs()) == 1                             # the entry's PR: no PR of its own for the pin
    log = git(j.gitops, "log", "--format=%s", f"origin/compose/{SPEC}", "-1")
    assert log == f"chore(dev): pin shop-api to sha-{SHA} ({SPEC})"


def test_without_a_gitops_entry_the_first_pin_opens_the_joint_pr_ac_144_1(j):  # AC-144.1
    j.set_plan([("shop-api", "service-python", [], ["AC-012.1"], False), ("shop-web", "web-nextjs", [], ["AC-012.2"], False)])
    j.started()
    j.deliver("shop-api")
    j.deliver("shop-web", WEB_SHA)
    assert len(j.dev_prs()) == 1
    assert j.state()["joint_pr"]
    assert j.pin("dev", "shop-web", f"compose/{SPEC}") == f"sha-{WEB_SHA}"
    assert j.app("next", "--json").json["action"] == "land"


# ---------------- AC-144.2: merged once, after the last component; one sync ----------------

def test_the_entry_pr_waits_for_green_checks_but_stays_open_ac_144_2(j):  # AC-144.2
    j.started()
    wt, r = j.entry()
    assert j.made("pr", "merge") == []
    assert j.state()["repos"][GITOPS]["state"] == "passed"
    assert j.state()["joint_pr"] == j.state()["repos"][GITOPS]["pr"]
    assert wt.is_dir()
    assert "stays open" in r.out
    assert [s["id"] for s in j.app("next", "--json").json["start"]] == ["shop-api"]


def test_a_red_entry_pr_still_escalates_ac_144_2(j):  # AC-144.2
    j.started()
    j.app("repo", "start", GITOPS)
    wt = j.common / "cplat-app-ship" / f"{SPEC}-entry"
    (wt / "x.yaml").write_text("x: 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "feat(compose): x")
    body = j.root / "b.md"
    body.write_text("b\n")
    j.app("entry", "pr", GITOPS, "--title", "feat(compose): x", "--body-file", str(body))
    j.cfg(red_all=True)
    r = j.app("entry", "land", GITOPS)
    assert r.rc == 1 and "lint" in r.out
    assert j.state()["repos"][GITOPS]["state"] == "escalated"


def test_land_is_not_offered_or_run_before_the_last_component_ac_144_2(j):  # AC-144.2
    j.started()
    j.entry()
    j.deliver("shop-api")
    assert j.app("next", "--json").json["action"] == "start"         # shop-web still to build
    r = j.app("land")
    assert r.rc == 1 and "shop-web" in r.out
    assert j.made("pr", "merge") == []
    r = j.app("complete")
    assert r.rc == 1


def test_land_merges_the_one_pr_once_and_dev_syncs_once_ac_144_2(j):  # AC-144.2
    j.to_land()
    assert j.app("next", "--json").json["action"] == "land"
    r = j.app("land")
    assert r.rc == 0, r.out
    assert len(j.dev_merges()) == 1
    assert j.pin("dev", "shop-api") == f"sha-{SHA}" and j.pin("dev", "shop-web") == f"sha-{WEB_SHA}"
    assert "READY:" in r.out
    assert f"refs/heads/ship/{SPEC}/" not in j.heads()      # the markers are deleted after the merge
    st = j.state()
    assert st["dev_landed"] and all(st["repos"][i]["state"] == "passed" for i in ("shop-api", "shop-web"))
    assert j.app("next", "--json").json["action"] == "complete"
    merges = len(j.made("pr", "merge"))
    r = j.app("land")                                        # landing again changes nothing
    assert r.rc == 0 and len(j.made("pr", "merge")) == merges


def test_an_argo_timeout_exits_2_and_land_resumes_after_the_merge_ac_144_2(j):  # AC-144.2
    j.to_land()
    j.argo["stale"] = True
    r = j.app("land", "--wait-timeout", "0")
    assert r.rc == 2, r.out
    assert "TIMEOUT:" in r.out and not j.state().get("escalated")
    assert len(j.dev_merges()) == 1
    j.argo["stale"] = False
    r = j.app("land")
    assert r.rc == 0, r.out
    assert len(j.dev_merges()) == 1


def test_a_red_dev_app_escalates_with_cause_environment_ac_144_2(j):  # AC-144.2
    j.to_land()
    j.argo["degraded"] = ["shop-web-dev"]
    r = j.app("land")
    assert r.rc == 1 and "shop-web-dev" in r.out
    assert j.state()["escalated"] and j.state()["cause"] == "environment"


# ---------------- AC-144.3: the component ship ends at "pinned in the system ship's dev PR" ----------------

def joint_deploy(j, runs=None):
    if runs is not None:
        j.cfg(runs=runs)
    clone = j.clone("shop-api")
    (clone / ".platform-app.yml").write_text(f"apps:\n  - {SLUG}\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "link")
    j.joint_ship("shop-api", phase="deploy", smoke=None, joint=None)
    j.mp.setattr(ship, "now", lambda c=itertools.count(0, 100): next(c))     # a clock that moves: no wait runs forever
    return ship.deploy(clone, 60, 0, None)


def test_a_joint_component_deploy_ends_pinned_in_the_system_ships_pr_ac_144_3(j):  # AC-144.3
    j.started()
    ok, lines = joint_deploy(j)
    assert ok, lines
    text = "\n".join(lines)
    assert f"pinned in the system ship's dev PR (compose/{SPEC})" in text
    assert "Smoke (dev): with the system ship" in text
    sh = ship.load_state(j.clone("shop-api"))
    assert sh["phase"] == "done" and sh["smoke"]["outcome"] == "deferred" and sh["joint"]["tag"] == f"sha-{SHA}"
    assert not any("pin-dev" in c for c in j.made("run", "list"))           # no wait for a pin-dev run
    assert f"refs/heads/ship/{SPEC}/shop-api-{SHA[:7]}" in j.heads()         # the marker is there (pushed again if missing)


def test_a_joint_component_deploy_with_red_main_ci_fails_as_today_ac_144_3(j):  # AC-144.3
    j.started()
    ok, lines = joint_deploy(j, runs=[{"databaseId": 5, "status": "completed", "conclusion": "failure"}])
    assert not ok
    assert any("CI on main is red" in ln for ln in lines)


def test_a_pinned_component_counts_as_delivered_for_the_scheduler_ac_144_3(j):  # AC-144.3
    j.started()
    j.entry()
    r = j.deliver("shop-api")
    assert "pinned" in r.out
    assert j.state()["repos"]["shop-api"]["state"] == "pinned"
    nxt = j.app("next", "--json").json
    assert [s["id"] for s in nxt["start"]] == ["shop-web"] and nxt["action"] == "start"
    assert "pinned" in j.app("status").out


# ---------------- AC-144.4: the system ship runs every dev smoke ----------------

def test_land_runs_the_dev_smoke_of_every_component_and_records_it_ac_144_4(j):  # AC-144.4
    j.to_land()
    r = j.app("land")
    assert r.rc == 0, r.out
    dev = [(n, url) for n, env, url in j.smoked if env == "dev"]
    assert dev == [("shop-api", "https://shop-api.dev.example.test"), ("shop-web", "https://shop-web.dev.example.test")]
    assert ("shop-api", "dev", f"sha-{SHA}", REPO_SPEC) in j.recorded and ("shop-web", "dev", f"sha-{WEB_SHA}", REPO_SPEC) in j.recorded
    assert "Smoke (dev) shop-api: 3/3 passed" in r.out and "Smoke (dev) shop-web: 3/3 passed" in r.out
    assert j.state()["repos"]["shop-web"]["smoke_row"] == "3/3 passed"


def test_a_red_dev_smoke_escalates_naming_the_component_ac_144_4(j):  # AC-144.4
    j.to_land()
    j.red.add(("shop-web", "dev"))
    r = j.app("land")
    assert r.rc == 1
    assert ("shop-api", "dev", "https://shop-api.dev.example.test") in j.smoked       # every component is smoked and reported
    st = j.state()
    # interface: reason text recorded in the run state
    assert st["repos"]["shop-web"]["state"] == "escalated" and "smoke red in dev" in st["repos"]["shop-web"]["reason"]
    assert st["escalated"].startswith("shop-web") and st["cause"] == "code"
    assert ("acme/shop-web", "dev") in j.filed
    assert not [c for c in j.made("pr", "create") if any(str(x).startswith("promote/staging-") for x in c)]


# ---------------- AC-144.5: a failed component holds the dev PR ----------------

def test_a_failed_component_keeps_the_joint_pr_open_and_escalates_ac_144_5(j):  # AC-144.5
    j.started()
    j.entry()
    j.deliver("shop-api")
    assert j.app("repo", "start", "shop-web").rc == 0
    j.ship_state("shop-web", phase="build", merge_sha=None, deployed=None, smoke=None, escalated="CI red after 3 rounds", cause="code")
    assert j.app("repo", "result", "shop-web").rc == 1
    assert j.app("repo", "hold", "shop-web").rc == 0      # spec 186: an escalated repo is first offered as `answer`
    nxt = j.app("next", "--json").json
    assert nxt["action"] == "escalate" and nxt["escalated"] == ["shop-web"]
    r = j.app("escalate", "CI red after 3 rounds")
    assert "shop-web" in j.state()["escalated"]
    assert j.app("land").rc == 1
    assert j.made("pr", "merge") == []
    assert j.pin("dev", "shop-api") == OLD                   # dev keeps the builds it ran before the ship
    assert j.cfg()["prs"][j.state()["joint_pr"].rsplit("/", 1)[-1]]["state"] == "OPEN"


# ---------------- AC-144.7: staging in one PR ----------------

def test_staging_after_dev_smoke_is_promoted_in_one_pr_for_the_spec_ac_144_7(j):  # AC-144.7
    j.to_land()
    r = j.app("land")
    assert r.rc == 0, r.out
    staging = [c for c in j.made("pr", "create") if any(str(x).startswith("promote/staging-") for x in c)]
    assert len(staging) == 1
    assert j.pin("staging", "shop-api") == f"sha-{SHA}" and j.pin("staging", "shop-web") == f"sha-{WEB_SHA}"
    assert len(j.made("pr", "merge")) == 2                   # the dev PR and the staging PR
    assert not [c for c in j.calls() if c[:1] == ["api"] and any("pin-staging" in str(x) for x in c)]
    assert [(n, env) for n, env, _ in j.smoked if env == "staging"] == [("shop-api", "staging"), ("shop-web", "staging")]
    assert "Promotion (staging) shop-api:" in r.out
    report = j.app("complete").out
    assert "Promotion (staging)" in report


def test_manual_staging_is_not_promoted_ac_144_7(manual):  # AC-144.7
    manual.to_land()
    r = manual.app("land")
    assert r.rc == 0, r.out
    assert not [c for c in manual.made("pr", "create") if any(str(x).startswith("promote/staging-") for x in c)]
    assert "Promotion (staging) shop-api: not promoted: automatic promotion to staging is off for shop-api" in r.out
    assert manual.pin("staging", "shop-api") == OLD


# ---------------- AC-144.8: the journey's dev PR count ----------------

def test_a_system_spec_across_the_gitops_repo_and_two_components_gives_one_dev_pr_ac_144_8(j):  # AC-144.8
    j.to_land()
    assert j.app("land").rc == 0
    r = j.app("complete")
    assert r.rc == 0, r.out
    created = [next(str(x) for x in c if str(x).startswith(("compose/", "pin/", "docs/", "promote/"))) for c in j.made("pr", "create")
               if any(str(x).startswith(("compose/", "pin/", "docs/", "promote/")) for x in c)]
    assert [b for b in created if b.startswith(("compose/", "pin/dev-"))] == [f"compose/{SPEC}"]
    assert f"docs/done-{SPEC}" in created
    assert f"| shop-api | {REPO_SPEC} |" in r.out and f"shop-api:sha-{SHA}" in r.out


def test_a_test_only_fix_after_a_red_dev_smoke_reruns_the_smoke_without_a_new_pr_521(j):
    """#521: the fix changed only a test, so the image is the one dev already runs; the resumed ship pins nothing,
    opens no empty compose PR and reruns the dev smoke on the landed revision."""
    j.to_land()
    j.red.add(("shop-api", "dev"))
    assert j.app("land").rc == 1
    prs = len(j.made("pr", "create"))
    j.red.clear()
    assert j.app("start", SPEC, "--context", "kind-shop").rc == 0
    git(j.clone("shop-api"), "add", "-A")
    git(j.clone("shop-api"), "commit", "-qm", "the first ship's spec")
    r = j.app("repo", "start", "shop-api")
    assert r.rc == 0, r.out
    j.joint_ship("shop-api", "f" * 40, joint={"tag": f"sha-{SHA}"})      # a new merge, the same image
    r = j.app("repo", "result", "shop-api")
    assert r.rc == 0, r.out
    assert "dev already runs" in r.out
    assert len(j.made("pr", "create")) == prs
    r = j.app("land")
    assert r.rc == 0, r.out
    assert [n for n, env, _ in j.smoked if env == "dev"].count("shop-api") == 2
    assert j.state()["repos"]["shop-api"]["state"] == "passed"
