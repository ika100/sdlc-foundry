"""Spec 097 acceptance tests: `cplat app-ship` (/app:ship) as design.md "Contract" describes it.

Seams: real git on a local bare "origin" (the GitHub URL is mapped to it with `url.<bare>.insteadOf`), fake `gh`, `kubectl` and
`devbox` executables on PATH (JSON config in the world's directory, every `gh` call logged), `ship.sleep` / `ship.now`,
`ship.argo_health` (the internal-service gate) and `appship_merge.sleep` (the merge slot's wait). The repo ships of the component
repos are simulated by writing their `.git/cplat-ship.json` with `ship.save_state`. The new modules (`appship`, `appship_merge`) are
imported inside the tests: they do not exist yet. `cplat app-ship` is called as `appship.main(["--repo", DIR, <command>, ...])`.
"""
import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import core
import runs
import ship
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_spec import make

SLUG = "acme/shop-gitops"
GITOPS = "shop-gitops"
SPEC = "012-shop"
SHA = "0123456789abcdef0123456789abcdef01234567"
REPO_SPEC = "007-price-alerts"

PRODUCT_SPEC = """---
spec_id: 012-shop
title: Shop
status: {status}
priority: P1
---

# 012 — Shop

## Problem

A shop.

## Acceptance criteria

- **AC-012.1** Given a cart, when checked out, then an order exists.
- **AC-012.2** Given an order, when listed, then the web shows it.
- **AC-012.3** Given a library, when used, then it works.

## Non-goals

- none

## Open questions

None.

## Changelog

- 2026-10-25 created
"""

PLAN_HEAD = """---
plan_id: 012-shop
spec: 012-shop
feature: shop
gitops_app: acme/shop-gitops
status: draft
human_steps:
  - Create the payment provider account
repos:
"""

DEFAULT_REPOS = [
    ("shop-gitops", "gitops-app", [], ["AC-012.1"], False),
    ("shop-lib", "library-python", ["shop-gitops"], ["AC-012.3"], False),
    ("shop-api", "service-python", ["shop-lib"], ["AC-012.1"], False),
    ("shop-worker", "service-python", ["shop-lib"], [], False),
    ("shop-web", "web-nextjs", ["shop-api"], ["AC-012.2"], False),
]

SERVICES = """services:
  - {name: shop-api, repo: acme/shop-api, expose: {port: 8080}}
  - {name: shop-web, repo: acme/shop-web, expose: {port: 3000}}
  - {name: shop-worker, repo: acme/shop-worker}
"""
APP_YAML = "name: shop\nhosts:\n  dev: '{service}.dev.example.test'\n"

FAKE_GH = '''#!%(py)s
import json, os, subprocess, sys
cfg_path = os.environ["FAKE_CFG"]
cfg = json.load(open(cfg_path))
args = sys.argv[1:]
open(cfg["log"], "a").write(json.dumps(args) + "\\n")
def save():
    json.dump(cfg, open(cfg_path, "w"))
def num(ref):
    ref = str(ref)
    if ref.rsplit("/", 1)[-1].isdigit():
        return ref.rsplit("/", 1)[-1]
    for n, p in cfg["prs"].items():
        if p["branch"] == ref:
            return n
    return None
def pr_json(n):
    p = cfg["prs"][n]
    return {"number": int(n), "url": p["url"], "state": p["state"], "headRefName": p["branch"], "isDraft": False,
            "mergeable": p["mergeable"], "mergeCommit": {"oid": "%(sha)s"} if p["state"] == "MERGED" else None}
if args[:2] == ["pr", "create"]:
    branch = args[args.index("--head") + 1] if "--head" in args else subprocess.run(
        ["git", "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    n = str(len(cfg["prs"]) + 1)
    cfg["prs"][n] = {"branch": branch, "state": "OPEN", "mergeable": "MERGEABLE",
                     "url": "https://github.com/acme/shop-gitops/pull/" + n}
    save()
    print(cfg["prs"][n]["url"])
elif args[:2] == ["pr", "list"]:
    want = args[args.index("--head") + 1] if "--head" in args else None
    print(json.dumps([pr_json(n) for n, p in cfg["prs"].items() if p["state"] == "OPEN" and want in (None, p["branch"])]))
elif args[:2] == ["pr", "view"]:
    n = num(args[2])
    if n is None or n not in cfg["prs"]:
        sys.exit("no pull request found")
    print(json.dumps(pr_json(n)))
elif args[:2] == ["pr", "checks"]:
    n = num(args[2])
    if n in cfg.get("red", []) or cfg.get("red_all"):
        print(json.dumps([{"name": "lint", "state": "FAILURE", "bucket": "fail", "link": "https://github.com/acme/shop-gitops/actions/runs/9/job/1"},
                          {"name": "validate", "state": "SUCCESS", "bucket": "pass", "link": "https://github.com/acme/shop-gitops/actions/runs/9/job/2"}]))
    else:
        print(json.dumps([{"name": "validate", "state": "SUCCESS", "bucket": "pass", "link": "https://github.com/acme/shop-gitops/actions/runs/9/job/2"}]))
elif args[:2] == ["pr", "merge"]:
    n = num(args[2])
    cfg["prs"][n]["state"] = "MERGED"
    save()
    ref = subprocess.run(["git", "--git-dir", cfg["origin"], "rev-parse", "refs/heads/" + cfg["prs"][n]["branch"]],
                         capture_output=True, text=True)
    if ref.returncode == 0:
        subprocess.run(["git", "--git-dir", cfg["origin"], "update-ref", "refs/heads/main", ref.stdout.strip()], check=True)
elif args[:2] == ["pr", "ready"]:
    pass
elif args[:2] == ["repo", "clone"]:
    name = args[2].split("/")[-1]
    target = args[3] if len(args) > 3 and not args[3].startswith("-") else name
    subprocess.run(["git", "clone", "-q", os.path.join(cfg["upstream"], name), target], check=True)
elif args[:2] == ["run", "list"] or args[:1] == ["api"] or args[:2] == ["secret", "list"]:
    print("[]")
else:
    sys.exit("fake gh: unexpected " + json.dumps(args))
'''

FAKE_KUBECTL = '''#!%(py)s
import json, os, sys
cfg = json.load(open(os.environ["FAKE_CFG"]))["kube"]
a = sys.argv[1:]
if a[:2] == ["config", "current-context"]:
    if cfg["current"]:
        print(cfg["current"])
        sys.exit(0)
    sys.exit("error: current-context is not set")
ctx = a[a.index("--context") + 1] if "--context" in a else cfg["current"]
if ctx not in cfg["contexts"]:
    sys.exit('error: context "%%s" does not exist' %% ctx)
if "get" in a and "applications" in a:
    for n in cfg["contexts"][ctx]:
        print("application.argoproj.io/" + n)
    sys.exit(0)
sys.exit("fake kubectl: unexpected " + json.dumps(a))
'''

FAKE_DEVBOX = '''#!%(py)s
import os, sys
a = sys.argv[1:]
for i, x in enumerate(a):
    if x.endswith("plan.py"):
        os.execv(sys.executable, [sys.executable, *a[i:]])
sys.exit(0)
'''


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def plan_text(repos=DEFAULT_REPOS):
    rows = "".join(f"  - {{id: {i}, shape: {s}, summary: {i}, depends_on: {d}, acs: {a}, done: {str(done).lower()}}}\n"
                   for i, s, d, a, done in repos)
    return PLAN_HEAD + rows + "---\n\n## Contract\n"


class Result:
    def __init__(self, rc, out):
        self.rc, self.out = rc, out

    @property
    def json(self):
        return json.loads(self.out)


class World:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.root = tmp_path / "w"
        self.mp, self.capsys = monkeypatch, capsys
        self.root.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.origin = self.root / "origin.git"
        self.cfg_path = self.root / "fake.json"
        self.log = self.root / "gh.log"
        self.log.write_text("")
        self.gitops = self.root / GITOPS
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        cfg = {"log": str(self.log), "origin": str(self.origin), "upstream": str(self.upstream), "prs": {}, "red": [], "red_all": False,
               "kube": {"current": None, "contexts": {"kind-shop": ["shop-api-dev", "shop-worker-dev"], "kind-other": ["x-dev"]}}}
        self.cfg_path.write_text(json.dumps(cfg))
        for name, body in (("gh", FAKE_GH % {"py": sys.executable, "sha": SHA}), ("kubectl", FAKE_KUBECTL % {"py": sys.executable}),
                           ("devbox", FAKE_DEVBOX % {"py": sys.executable})):
            f = self.bin / name
            f.write_text(body)
            f.chmod(f.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_CFG", str(self.cfg_path))
        monkeypatch.setattr(ship, "sleep", lambda s: None)
        monkeypatch.setattr(ship, "now", lambda: 0.0)
        self.make_gitops()
        for rid in ("shop-lib", "shop-api", "shop-worker", "shop-web"):
            self.make_clone(rid)

    # ---- fixtures of the world
    def cfg(self, **changes):
        cfg = json.loads(self.cfg_path.read_text())
        cfg.update(changes)
        self.cfg_path.write_text(json.dumps(cfg))
        return cfg

    def kube(self, current=None, contexts=None):
        cfg = self.cfg()
        cfg["kube"]["current"] = current
        if contexts is not None:
            cfg["kube"]["contexts"] = contexts
        self.cfg(kube=cfg["kube"])

    def calls(self):
        return [json.loads(ln) for ln in self.log.read_text().splitlines() if ln.strip()]

    def made(self, *prefix):
        return [c for c in self.calls() if c[:len(prefix)] == list(prefix)]

    def add_pr(self, number, branch="feature/x", mergeable="MERGEABLE"):
        cfg = self.cfg()
        cfg["prs"][str(number)] = {"branch": branch, "state": "OPEN", "mergeable": mergeable,
                                   "url": f"https://github.com/{SLUG}/pull/{number}"}
        self.cfg(prs=cfg["prs"])
        return f"https://github.com/{SLUG}/pull/{number}"

    def make_gitops(self, status="approved"):
        g = self.gitops
        g.mkdir()
        git(g, "init", "-q", "-b", "main")
        (g / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/gitops-app\nproject_name: shop-gitops\n")
        sd = g / "docs" / "specs" / SPEC
        sd.mkdir(parents=True)
        (sd / "spec.md").write_text(PRODUCT_SPEC.format(status=status))
        (g / "docs" / "plan").mkdir(parents=True)
        (g / "docs" / "plan" / f"{SPEC}.md").write_text(plan_text())
        (g / "applications" / "shop").mkdir(parents=True)
        (g / "applications" / "shop" / "services.yaml").write_text(SERVICES)
        (g / "applications" / "shop" / "app.yaml").write_text(APP_YAML)
        (g / "scripts").mkdir()
        shutil.copy(core.PLATFORM_ROOT / "templates" / "gitops-app" / "scripts" / "plan.py", g / "scripts" / "plan.py")
        git(g, "add", "-A")
        git(g, "commit", "-qm", "init")
        git(g, "remote", "add", "origin", f"https://github.com/{SLUG}.git")
        git(g, "config", f"url.{self.origin}.insteadOf", f"https://github.com/{SLUG}.git")
        git(g, "push", "-q", "origin", "main")
        git(g, "fetch", "-q", "origin")

    def make_clone(self, rid):
        shape = {"shop-lib": "library-python", "shop-web": "web-nextjs"}.get(rid, "service-python")
        c = self.root / rid
        c.mkdir()
        git(c, "init", "-q", "-b", "main")
        (c / ".copier-answers.yml").write_text(f"_src_path: gh:ika100/sdlc-foundry/templates/{shape}\nproject_name: {rid}\n")
        git(c, "add", "-A")
        git(c, "commit", "-qm", "init")
        git(c, "remote", "add", "origin", f"https://github.com/acme/{rid}.git")
        return c

    def clone(self, rid):
        return self.root / rid

    def set_plan(self, repos):
        p = self.gitops / "docs" / "plan" / f"{SPEC}.md"
        p.write_text(plan_text(repos))
        git(self.gitops, "add", "-A")
        git(self.gitops, "commit", "-qm", "plan")
        git(self.gitops, "push", "-q", "origin", "main")
        git(self.gitops, "fetch", "-q", "origin")

    def origin_file(self, path):
        return subprocess.run(["git", "--git-dir", str(self.origin), "show", f"main:{path}"], capture_output=True, text=True).stdout

    # ---- the CLI
    def app(self, *args, repo=None, stdin=None):
        appship = importlib.import_module("appship")
        if stdin is not None:
            import io
            self.mp.setattr(sys, "stdin", io.StringIO(stdin))
        self.capsys.readouterr()
        try:
            rc = appship.main(["--repo", str(repo or self.gitops), *args])
        except core.PlatformError as e:
            rc = 1
            print(f"{e}\n{e.hint or ''}")
        cap = self.capsys.readouterr()
        return Result(rc, cap.out + cap.err)

    @property
    def common(self):
        return self.gitops / ".git"

    @property
    def state_file(self):
        return self.common / "cplat-app-ship.json"

    def state(self):
        return json.loads(self.state_file.read_text())

    def edit(self, change):
        st = self.state()
        change(st)
        self.state_file.write_text(json.dumps(st, indent=2))

    def started(self, repos=None, context="kind-shop", states=None, **top):
        if repos:
            self.set_plan(repos)
        r = self.app("start", SPEC, "--context", context)
        assert r.rc == 0, r.out
        if states or top:
            def change(st):
                for rid, s in (states or {}).items():
                    st["repos"][rid].update(s if isinstance(s, dict) else {"state": s})
                st.update(top)
            self.edit(change)
        return self.state()

    def ship_state(self, rid, **over):
        """The clone's `cplat-ship.json`, as a finished /svc:ship leaves it, and its repo spec (child of the product spec)."""
        c = self.clone(rid)
        d = make(c, status="approved")
        text = (d.dir / "spec.md").read_text().replace("priority: P1\n", f"priority: P1\nparent: {SLUG}:{SPEC}\n")
        (d.dir / "spec.md").write_text(text)
        st = {"spec": REPO_SPEC, "phase": "done", "merge": True, "branch": f"feature/{REPO_SPEC}", "blocks": 0, "fix_rounds": 1,
              "started": "2026-10-25T08:00:00", "recorded": True, "run_id": f"20261025T080000Z-{rid[-4:].ljust(4, '0')}",
              "pr": f"https://github.com/acme/{rid}/pull/7", "merge_sha": SHA, "deployed": f"sha-{SHA}",
              "smoke": {"outcome": "passed", "row": "passed (3 tests)", "url": "https://x.dev.example.test"}}
        st.update(over)
        for k in [k for k, v in st.items() if v is None]:
            del st[k]
        ship.save_state(c, st)
        return st


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    return World(tmp_path, monkeypatch, capsys)


def table_of(out):
    return out


# ---------------- AC-097.1 / AC-097.18: refusals change nothing ----------------

def test_refuses_a_component_repo_with_a_hint_and_changes_nothing(w):  # AC-097.1
    r = w.app("start", REPO_SPEC, "--context", "kind-shop", repo=w.clone("shop-api"))
    assert r.rc == 1
    assert "this is a service-python repo: a component spec ships with /svc:ship" in r.out
    assert not (w.clone("shop-api") / ".git" / "cplat-app-ship.json").exists()
    assert not w.state_file.exists()


def test_refuses_a_product_spec_that_is_not_approved(w):  # AC-097.1
    sp = w.gitops / "docs" / "specs" / SPEC / "spec.md"
    sp.write_text(sp.read_text().replace("status: approved", "status: draft"))
    r = w.app("start", SPEC, "--context", "kind-shop")
    assert r.rc == 1
    assert f"{SPEC} is 'draft'; only an approved product spec is shipped" in r.out
    assert "/app:spec approve" in r.out
    assert not w.state_file.exists()


def test_a_building_spec_may_be_started_and_prints_the_next_line(w):  # AC-097.1
    sp = w.gitops / "docs" / "specs" / SPEC / "spec.md"
    sp.write_text(sp.read_text().replace("status: approved", "status: building"))
    r = w.app("start", SPEC, "--context", "kind-shop")
    assert r.rc == 0 and "next:" in r.out
    assert w.state()["phase"] == "publish" and w.state()["context"] == "kind-shop"


def test_refuses_a_second_unfinished_run_for_another_spec(w):  # AC-097.1
    w.started()
    other = w.gitops / "docs" / "specs" / "013-other"
    other.mkdir()
    (other / "spec.md").write_text(PRODUCT_SPEC.format(status="approved").replace("012-shop", "013-other").replace("AC-012", "AC-013"))
    r = w.app("start", "013-other", "--context", "kind-shop")
    assert r.rc == 1 and "cplat app-ship finish" in r.out
    assert w.state()["spec"] == SPEC


def test_refuses_without_a_kube_context_and_changes_nothing(w):  # AC-097.18
    w.kube(current=None)
    r = w.app("start", SPEC)
    assert r.rc == 1
    assert "no kube context for the product's cluster" in r.out
    assert "pass --context <name> or select it: kubectl config use-context <name>" in r.out
    assert not w.state_file.exists()


def test_refuses_a_context_without_the_products_argo_apps(w):  # AC-097.18
    r = w.app("start", SPEC, "--context", "kind-other")
    assert r.rc == 1 and "no kube context for the product's cluster" in r.out
    r = w.app("start", SPEC, "--context", "missing")
    assert r.rc == 1 and "no kube context for the product's cluster" in r.out
    assert not w.state_file.exists()


def test_the_current_context_is_used_when_none_is_named(w):  # AC-097.18
    w.kube(current="kind-shop")
    assert w.app("start", SPEC).rc == 0
    assert w.state()["context"] == "kind-shop"


# ---------------- AC-097.2: plan unattended ----------------

def test_a_product_spec_without_a_plan_starts_in_the_plan_phase(w):  # AC-097.2
    (w.gitops / "docs" / "plan" / f"{SPEC}.md").unlink()
    w.started()
    assert w.state()["phase"] == "plan"
    assert json.loads(w.app("gate", stdin="{}").out)["decision"] == "block"      # the session cannot end while planning


def test_blocked_planning_ends_the_run_escalated_with_the_reason(w):  # AC-097.2
    (w.gitops / "docs" / "plan" / f"{SPEC}.md").unlink()
    w.started()
    r = w.app("escalate", "architect blockers: no payment provider chosen", "--cause", "decision")
    assert r.rc == 0
    st = w.state()
    assert st["escalated"] == "architect blockers: no payment provider chosen" and st["cause"] == "decision"
    assert w.app("gate", stdin="{}").out.strip() == ""                            # escalated: the session may end
    nxt = w.app("next", "--json").json
    assert nxt["start"] == []


# ---------------- AC-097.3: publish spec and plan ----------------

def test_publish_does_nothing_when_spec_and_plan_are_on_main(w):  # AC-097.3
    w.started()
    r = w.app("publish")
    assert r.rc == 0 and "spec and plan are on main" in r.out
    assert w.state()["phase"] == "repos"
    assert w.made("pr", "create") == []


def test_publish_opens_a_pr_and_merges_it_only_after_green_checks(w):  # AC-097.3
    w.started()
    plan = w.gitops / "docs" / "plan" / f"{SPEC}.md"
    plan.write_text(plan.read_text() + "\nA new paragraph.\n")
    r = w.app("publish")
    assert r.rc == 0, r.out
    calls = w.calls()
    assert w.made("pr", "create")
    merge = w.made("pr", "merge")
    assert len(merge) == 1 and "--squash" in merge[0] and "--admin" not in merge[0]
    last_checks = max(i for i, c in enumerate(calls) if c[:2] == ["pr", "checks"])
    assert last_checks < calls.index(merge[0])
    assert "A new paragraph." in w.origin_file(f"docs/plan/{SPEC}.md")
    assert git(w.gitops, "log", "-1", "--format=%s", "origin/main").startswith("docs(spec): 012-shop") or \
        "docs(spec): 012-shop — product spec and plan" in git(w.gitops, "log", "--format=%s", "origin/main")
    assert subprocess.run(["git", "--git-dir", str(w.origin), "rev-parse", "docs/spec-012-shop"], capture_output=True).returncode == 0
    assert git(w.gitops, "branch", "--show-current") == "main"
    assert git(w.gitops, "status", "--porcelain") == ""
    assert w.state()["phase"] == "repos"


def test_publish_with_a_red_check_starts_no_repo_and_escalates(w):  # AC-097.3
    w.started()
    plan = w.gitops / "docs" / "plan" / f"{SPEC}.md"
    plan.write_text(plan.read_text() + "\nA new paragraph.\n")
    w.cfg(red_all=True)
    r = w.app("publish")
    assert r.rc == 1
    assert "is red" in r.out and "lint" in r.out
    assert w.made("pr", "merge") == []
    st = w.state()
    assert st["phase"] != "repos" and "is red" in st["escalated"] and st["cause"] == "code"
    assert w.app("next", "--json").json["start"] == []
    assert "A new paragraph." not in w.origin_file(f"docs/plan/{SPEC}.md")


# ---------------- AC-097.4: resume, state never committed, Stop hook ----------------

def test_the_state_lives_in_the_git_dir_and_is_never_committed(w):  # AC-097.4
    w.started()
    assert w.state_file.parent == w.common
    assert git(w.gitops, "status", "--porcelain") == ""
    assert "cplat-app-ship" not in git(w.gitops, "ls-files")


def test_resume_keeps_passed_repos_and_restarts_the_escalated_one(w):  # AC-097.4
    st0 = w.started(states={"shop-gitops": "passed", "shop-lib": "passed",
                            "shop-api": {"state": "escalated", "reason": "smoke red", "cause": "code"},
                            "shop-worker": "running"},
                    escalated="shop-api: smoke red", cause="code", blocks=5)
    r = w.app("start", SPEC, "--context", "kind-shop")
    assert r.rc == 0 and "next:" in r.out
    st = w.state()
    assert st["escalated"] is None and st["cause"] is None and st["blocks"] == 0
    assert st["run_id"] != st0["run_id"]
    assert [st["repos"][i]["state"] for i in ("shop-gitops", "shop-lib", "shop-api", "shop-worker")] == \
        ["passed", "passed", "ready", "running"]
    nxt = w.app("next", "--json").json
    assert [s["id"] for s in nxt["start"]] == ["shop-api"] and nxt["running"] == ["shop-worker"]


def test_a_plan_repo_done_by_an_earlier_build_counts_as_past_its_gate(w):  # AC-097.4
    repos = [(i, s, d, a, i == "shop-gitops") for i, s, d, a, _ in DEFAULT_REPOS]
    st = w.started(repos=repos)
    assert st["repos"]["shop-gitops"]["state"] == "done-before"
    assert [s["id"] for s in w.app("next", "--json").json["start"]] == ["shop-lib"]


def test_the_stop_hook_blocks_until_the_run_is_done_or_escalated(w):  # AC-097.4
    w.started()
    ans = w.app("gate", stdin="{}").json
    assert ans["decision"] == "block"
    assert f"The product ship of {SPEC} is not finished (phase publish, stop attempt 1/8)" in ans["reason"]
    assert "Next:" in ans["reason"]
    w.edit(lambda st: st.update(escalated="x", cause="code"))
    assert w.app("gate", stdin="{}").out.strip() == ""
    w.edit(lambda st: st.update(escalated=None, cause=None, phase="done"))
    assert w.app("gate", stdin="{}").out.strip() == ""


def test_the_stop_hook_gives_up_after_max_blocks(w):  # AC-097.4
    w.started()
    for _ in range(3):
        assert w.app("gate", "--max-blocks", "3", stdin="{}").json["decision"] == "block"
    assert w.app("gate", "--max-blocks", "3", stdin="{}").out.strip() == ""
    assert "gave up after 3 attempts to stop" in w.state()["escalated"]


def test_the_stop_hook_is_registered_for_the_product_state_file(w):  # AC-097.4
    hooks = json.loads((core.PLATFORM_ROOT / "plugins" / "shared" / "hooks" / "hooks.json").read_text())
    cmds = [h["command"] for e in hooks["hooks"]["Stop"] for h in e["hooks"]]
    assert any("cplat-app-ship.json" in c and "app-ship gate" in c and "|| exit 0" in c for c in cmds)


# ---------------- AC-097.6: questions escalate verbatim ----------------

def test_a_repo_with_open_questions_escalates_with_them_verbatim(w):  # AC-097.6
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    reason = "open questions: 1. Which payment provider? 2. Refunds allowed?"
    assert w.app("repo", "escalate", "shop-api", reason, "--cause", "decision").rc == 0
    repo = w.state()["repos"]["shop-api"]
    assert repo["state"] == "escalated" and repo["reason"] == reason and repo["cause"] == "decision"
    nxt = w.app("next", "--json").json
    assert "shop-api" in nxt["escalated"]
    assert {"id": "shop-web", "waits_for": ["shop-api"]} in nxt["blocked"]
    assert "shop-web" not in [s["id"] for s in nxt["start"]]


# ---------------- AC-097.7: the repo ship in its own clone ----------------

def test_a_dirty_clone_is_refused_with_its_path(w):  # AC-097.7
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    (w.clone("shop-api") / "scratch.txt").write_text("wip")
    r = w.app("repo", "start", "shop-api")
    assert r.rc == 1
    assert f"{w.clone('shop-api')} has uncommitted changes; commit or stash them, then resume" in r.out
    assert w.state()["repos"]["shop-api"]["state"] == "ready"


def test_repo_start_marks_the_repo_running_and_prints_the_clone(w):  # AC-097.7
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    r = w.app("repo", "start", "shop-api")
    assert r.rc == 0 and str(w.clone("shop-api")) in r.out
    assert w.state()["repos"]["shop-api"]["state"] == "running"


def test_a_missing_clone_is_cloned_next_to_the_gitops_app(w):  # AC-097.7
    shutil.move(str(w.clone("shop-api")), str(w.upstream / "shop-api"))
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    assert w.app("repo", "start", "shop-api").rc == 0
    assert (w.clone("shop-api") / ".git").exists()
    assert w.made("repo", "clone")


def test_nothing_is_ever_pushed_to_the_default_branch_directly(w):  # AC-097.7
    before = git(w.gitops, "ls-remote", "origin", "refs/heads/main")
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    w.app("repo", "start", "shop-api")
    w.app("next", "--json")
    assert git(w.gitops, "ls-remote", "origin", "refs/heads/main") == before
    assert all("--admin" not in c and "--force" not in c for c in w.calls())


def test_ship_start_with_product_links_the_repo_run_to_the_product_run(w):  # AC-097.7
    st = w.started()
    clone = w.clone("shop-api")
    make(clone, status="approved")
    assert ship.main(["--repo", str(clone), "start", REPO_SPEC, "--product", str(w.gitops)]) == 0
    linked = ship.load_state(clone)
    assert linked["product"] == {"dir": str(w.gitops), "run_id": st["run_id"], "context": "kind-shop"}
    assert runs._read_active(linked["run_id"])["parent"] == st["run_id"]


# ---------------- AC-097.8: the gitops-app's own entry ----------------

def entry_pr(w):
    r = w.app("repo", "start", GITOPS)
    assert r.rc == 0, r.out
    wt = Path(r.out.strip().splitlines()[-1].split()[-1])
    (wt / "applications" / "shop" / "entry.yaml").write_text("entry: true\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "feat(shop): gitops entry")
    body = w.root / "body.md"
    body.write_text("## Summary\n")
    r = w.app("entry", "pr", GITOPS, "--title", "feat(shop): gitops entry", "--body-file", str(body))
    assert r.rc == 0, r.out
    return wt


def test_the_entry_is_built_in_a_worktree_and_blocks_its_dependents(w):  # AC-097.8
    w.started()
    nxt = w.app("next", "--json").json
    assert nxt["start"] == [{"id": GITOPS, "shape": "gitops-app", "entry": True,
                             "clone": str(w.common / "cplat-app-ship" / f"{SPEC}-entry")}]
    r = w.app("repo", "start", GITOPS)
    assert r.rc == 0 and str(w.common / "cplat-app-ship" / f"{SPEC}-entry") in r.out
    assert git(w.common / "cplat-app-ship" / f"{SPEC}-entry", "branch", "--show-current") == f"compose/{SPEC}"
    nxt = w.app("next", "--json").json
    assert nxt["start"] == [] and nxt["running"] == [GITOPS] and nxt["action"] == "wait"
    assert {"id": "shop-lib", "waits_for": [GITOPS]} in nxt["blocked"]


def test_entry_land_merges_after_green_and_releases_the_dependents(w):  # AC-097.8
    w.started()
    entry_pr(w)
    assert w.made("pr", "create")
    r = w.app("entry", "land", GITOPS)
    assert r.rc == 0, r.out
    assert len(w.made("pr", "merge")) == 1
    assert w.state()["repos"][GITOPS]["state"] == "passed"
    assert [s["id"] for s in w.app("next", "--json").json["start"]] == ["shop-lib"]


def test_a_red_entry_escalates_with_the_failed_checks_and_merges_nothing(w):  # AC-097.8
    w.started()
    entry_pr(w)
    w.cfg(red_all=True)
    r = w.app("entry", "land", GITOPS)
    assert r.rc == 1 and "lint" in r.out
    assert w.made("pr", "merge") == []
    assert w.state()["repos"][GITOPS]["state"] == "escalated"
    nxt = w.app("next", "--json").json
    assert nxt["start"] == [] and nxt["escalated"] == [GITOPS]


# ---------------- AC-097.9: the merge slot ----------------

def merge_mod(w, monkeypatch):
    mod = importlib.import_module("appship_merge")
    monkeypatch.setattr(mod, "sleep", lambda s: time.sleep(0.01), raising=False)
    return mod


def test_gitops_prs_merge_one_at_a_time_and_are_logged(w, monkeypatch):  # AC-097.9
    mod = merge_mod(w, monkeypatch)
    w.started()
    pr1 = w.add_pr(4, "feature/a")
    pr2 = w.add_pr(5, "feature/b")
    with mod.slot(w.gitops, "shop-api", 2, 5):
        with pytest.raises(BlockingIOError):                 # the lock is held for the whole slot
            import fcntl
            with open(w.common / "cplat-app-ship.lock", "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mod.merge(w.gitops, pr1, "shop-api", cwd=w.gitops)
    with mod.slot(w.gitops, "shop-web", 4, 5):
        mod.merge(w.gitops, pr2, "shop-web", cwd=w.gitops)
    log = w.state()["gitops_merged"]
    assert [(m["pr"], m["repo"]) for m in log] == [(pr1, "shop-api"), (pr2, "shop-web")]
    assert w.state()["waiting"] == []
    assert all("--admin" not in c and "--force" not in c for c in w.calls())


def test_a_waiter_is_served_in_plan_order(w, monkeypatch):  # AC-097.9
    mod = merge_mod(w, monkeypatch)
    w.started(waiting=[{"repo": "shop-lib", "plan_index": 1}])
    with pytest.raises(Exception):                            # a lower plan index is waiting: this one does not get the slot
        with mod.slot(w.gitops, "shop-web", 4, 0.3):
            pytest.fail("the slot was granted out of plan order")
    assert w.state()["waiting"] == [{"repo": "shop-lib", "plan_index": 1}]
    with mod.slot(w.gitops, "shop-lib", 1, 0.3):
        pass
    assert w.state()["waiting"] == []


def test_a_pr_that_no_longer_merges_cleanly_names_both_prs(w, monkeypatch):  # AC-097.9
    mod = merge_mod(w, monkeypatch)
    w.started()
    first = w.add_pr(4, "feature/a")
    second = w.add_pr(5, "feature/b")
    with mod.slot(w.gitops, "shop-api", 2, 5):
        mod.merge(w.gitops, first, "shop-api", cwd=w.gitops)
    cfg = w.cfg()
    cfg["prs"]["5"]["mergeable"] = "CONFLICTING"
    w.cfg(prs=cfg["prs"])
    with mod.slot(w.gitops, "shop-web", 4, 5):
        with pytest.raises(mod.Conflict) as e:
            mod.merge(w.gitops, second, "shop-web", cwd=w.gitops)
    assert e.value.pr == second and e.value.after == first
    assert f"gitops PR {second} no longer merges cleanly after {first} merged" in str(e.value)
    assert len(w.made("pr", "merge")) == 1                    # only the first one; nothing rebased or forced
    assert all(c[:2] != ["pr", "update-branch"] and "--force" not in c and "--admin" not in c for c in w.calls())


def test_a_conflicting_pr_without_an_earlier_merge_has_no_after(w, monkeypatch):  # AC-097.9
    mod = merge_mod(w, monkeypatch)
    w.started()
    pr = w.add_pr(5, "feature/b", mergeable="CONFLICTING")
    with mod.slot(w.gitops, "shop-web", 4, 5):
        with pytest.raises(mod.Conflict) as e:
            mod.merge(w.gitops, pr, "shop-web", cwd=w.gitops)
    assert e.value.after is None and str(e.value) == f"gitops PR {pr} no longer merges cleanly"


# ---------------- AC-097.10: an escalated repo stops its dependents only ----------------

def test_an_escalated_repo_stops_dependents_while_running_repos_finish(w):  # AC-097.10
    w.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "running"})
    w.ship_state("shop-api", phase="build", merge_sha=None, deployed=None, smoke=None, escalated="CI red after 3 rounds", cause="code")
    assert w.app("repo", "result", "shop-api").rc == 1
    st = w.state()["repos"]["shop-api"]
    assert st["state"] == "escalated" and "CI red after 3 rounds" in st["reason"] and st["cause"] == "code"
    nxt = w.app("next", "--json").json
    assert nxt["start"] == [] and nxt["running"] == ["shop-worker"] and nxt["action"] == "wait"
    assert {"id": "shop-web", "waits_for": ["shop-api"]} in nxt["blocked"]
    w.ship_state("shop-worker")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
        assert w.app("repo", "result", "shop-worker").rc == 0
    nxt = w.app("next", "--json").json
    assert nxt["running"] == [] and nxt["action"] == "escalate" and nxt["start"] == []


def test_status_shows_every_repo_and_its_state_on_escalation(w):  # AC-097.10
    w.started(states={GITOPS: "passed", "shop-lib": "passed",
                      "shop-api": {"state": "escalated", "reason": "smoke red in dev: 1 failing", "cause": "code"},
                      "shop-worker": "running"})
    out = w.app("status").out
    for rid in ("shop-gitops", "shop-lib", "shop-api", "shop-worker", "shop-web"):
        assert rid in out
    assert "passed" in out and "running" in out and "blocked" in out
    assert "escalated: smoke red in dev: 1 failing" in out


# ---------------- AC-097.12: one run record at the run end ----------------

def test_no_record_at_start_and_one_escalated_record_with_the_repos_cause(w, store):  # AC-097.12
    w.started(states={"shop-api": {"state": "escalated", "reason": "smoke not run", "cause": "environment"}},
              ships=["20261025T080000Z-aaaa", "20261025T081000Z-bbbb"])
    assert stored(store) == []
    assert w.app("escalate", "shop-api: smoke not run", "--cause", "code").rc == 0
    [rec] = stored(store)
    assert rec["kind"] == "product-ship" and rec["repo"] == SLUG and rec["spec"] == SPEC and rec["outcome"] == "escalated"
    assert rec["escalation"] == {"reason": "shop-api: smoke not run", "cause": "environment"}
    assert rec["ships"] == ["20261025T080000Z-aaaa", "20261025T081000Z-bbbb"]
    assert rec["repos"]["shop-api"] == "escalated" and rec["resumes"] is None


def test_a_resumed_product_ship_is_a_new_run_that_names_the_escalated_one(w, store):  # AC-097.12
    first = w.started()["run_id"]
    w.app("escalate", "plan-check failed", "--cause", "decision")
    w.app("start", SPEC, "--context", "kind-shop")
    second = w.state()["run_id"]
    w.edit(lambda st: st.update(phase="complete"))
    w.app("phase", "done")
    records = {r["run_id"]: r for r in stored(store)}
    assert records[first]["outcome"] == "escalated" and records[first]["resumes"] is None
    assert records[second]["outcome"] == "done" and records[second]["resumes"] == first and records[second]["kind"] == "product-ship"
    assert len(records) == 2


def test_finish_archives_an_unrecorded_run_as_abandoned(w, store):  # AC-097.12
    w.started()
    assert w.app("finish").rc == 0
    [rec] = stored(store)
    assert rec["outcome"] == "abandoned" and rec["kind"] == "product-ship"
    assert not w.state_file.exists()
    assert list(w.common.glob(f"cplat-app-ship-{SPEC}-*.json"))


# ---------------- AC-097.19: scheduling and gates ----------------

def test_repos_start_only_when_all_their_dependencies_passed(w):  # AC-097.19
    w.started(states={GITOPS: "passed"})
    nxt = w.app("next", "--json").json
    assert [s["id"] for s in nxt["start"]] == ["shop-lib"] and nxt["action"] == "start"
    assert {"id": "shop-api", "waits_for": ["shop-lib"]} in nxt["blocked"]
    assert {"id": "shop-web", "waits_for": ["shop-api"]} in nxt["blocked"]
    w.edit(lambda st: st["repos"]["shop-lib"].update(state="passed"))
    nxt = w.app("next", "--json").json
    assert sorted(s["id"] for s in nxt["start"]) == ["shop-api", "shop-worker"]
    assert {"id": "shop-web", "waits_for": ["shop-api"]} in nxt["blocked"]


FLAT = [("shop-gitops", "gitops-app", [], ["AC-012.1"], True)] + \
       [(f"lib-{n}", "library-python", [], ["AC-012.2"] if n == 1 else (["AC-012.3"] if n == 2 else []), False) for n in range(1, 6)]


def test_at_most_max_repos_run_at_once_default_three(w):  # AC-097.19
    w.started(repos=FLAT)
    nxt = w.app("next", "--json").json
    assert len(nxt["start"]) == 3
    w.edit(lambda st: st["repos"][nxt["start"][0]["id"]].update(state="running"))
    nxt = w.app("next", "--json").json
    assert len(nxt["start"]) == 2 and len(nxt["running"]) == 1


def test_max_option_sets_the_parallelism(w):  # AC-097.19
    assert w.app("start", SPEC, "--context", "kind-shop", "--max", "1").rc == 0
    w.set_plan(FLAT)
    w.edit(lambda st: st.update(repos={r[0]: {"state": "done-before" if r[4] else "ready", "gate": "library", "clone": str(w.root / r[0])}
                                       for r in FLAT}))
    assert len(w.app("next", "--json").json["start"]) == 1


@pytest.mark.parametrize("outcome", ["passed", "passed-on-retry"])
def test_an_exposed_service_passes_with_green_smoke(w, outcome):  # AC-097.19
    w.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running"})
    w.ship_state("shop-api", smoke={"outcome": outcome, "row": "passed (3 tests)"})
    r = w.app("repo", "result", "shop-api")
    assert r.rc == 0, r.out
    repo = w.state()["repos"]["shop-api"]
    assert repo["state"] == "passed" and repo["gate"] == "exposed"
    assert repo["spec"] == REPO_SPEC and repo["pr"].endswith("/pull/7") and repo["fix_rounds"] == 1
    assert repo["deployed"] == f"sha-{SHA}" and repo["smoke_row"] == "passed (3 tests)" and repo["run_id"]
    assert not ship.state_path(w.clone("shop-api")).exists()          # the clone's ship state is archived


def test_smoke_not_run_never_passes_an_exposed_service(w):  # AC-097.19
    w.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running"})
    w.ship_state("shop-api", smoke={"outcome": "not-run", "row": "not run: no smoke tests", "reason": "no smoke tests"})
    assert w.app("repo", "result", "shop-api").rc == 1
    repo = w.state()["repos"]["shop-api"]
    assert repo["state"] == "escalated" and repo["cause"] == "environment"
    assert "smoke not run in dev for shop-api" in repo["reason"] and "no smoke tests" in repo["reason"]


def test_a_repo_ship_that_is_not_done_stays_running(w):  # AC-097.19
    w.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running"})
    w.ship_state("shop-api", phase="land", merge_sha=None, deployed=None, smoke=None)
    r = w.app("repo", "result", "shop-api")
    assert r.rc == 1 and "ship of shop-api is in phase land; resume it" in r.out
    assert w.state()["repos"]["shop-api"]["state"] == "running"


def test_an_internal_service_gates_on_argo_for_the_merged_build(w, monkeypatch):  # AC-097.19
    w.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-worker": "running"})
    asked = []

    def argo(context, app, timeout, interval, images=None, **kw):
        asked.append((context, app, images))
        return "Synced/Healthy"
    monkeypatch.setattr(ship, "argo_health", argo)
    w.ship_state("shop-worker", smoke={"outcome": "not-run", "row": "not run: shop-worker has no dev URL (not exposed in dev)"})
    assert w.app("repo", "result", "shop-worker").rc == 0
    repo = w.state()["repos"]["shop-worker"]
    assert repo["state"] == "passed" and repo["gate"] == "internal" and repo["argo"] == "Synced/Healthy"
    assert asked and asked[0][:2] == ("kind-shop", "shop-worker-dev") and f"sha-{SHA}" in (asked[0][2] or set())


def test_an_internal_service_that_is_not_healthy_escalates(w, monkeypatch):  # AC-097.19
    w.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-worker": "running"})
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "OutOfSync/Progressing")
    w.ship_state("shop-worker", smoke={"outcome": "not-run", "row": "not run: x"})
    assert w.app("repo", "result", "shop-worker").rc == 1
    repo = w.state()["repos"]["shop-worker"]
    assert repo["state"] == "escalated" and repo["cause"] == "environment"
    assert f"shop-worker-dev is not Synced/Healthy on sha-{SHA}" in repo["reason"]


def test_a_library_passes_when_its_pr_is_merged(w):  # AC-097.19
    w.started(states={GITOPS: "passed", "shop-lib": "running"})
    w.ship_state("shop-lib", deployed=None, smoke=None)
    assert w.app("repo", "result", "shop-lib").rc == 0
    repo = w.state()["repos"]["shop-lib"]
    assert repo["state"] == "passed" and repo["gate"] == "library"
    assert w.app("repo", "result", "shop-lib").rc in (0, 1)           # idempotent enough not to crash


def test_a_repo_spec_without_the_product_parent_is_an_error(w):  # AC-097.19
    w.started(states={GITOPS: "passed", "shop-lib": "running"})
    w.ship_state("shop-lib", deployed=None, smoke=None)
    sp = w.clone("shop-lib") / "docs" / "specs" / REPO_SPEC / "spec.md"
    sp.write_text(sp.read_text().replace(f"parent: {SLUG}:{SPEC}\n", ""))
    r = w.app("repo", "result", "shop-lib")
    assert r.rc == 1 and "parent" in r.out
    assert w.state()["repos"]["shop-lib"]["state"] == "running"


# ---------------- AC-097.20: completion and report ----------------

def all_passed(w):
    w.started(states={
        GITOPS: {"state": "passed", "gate": "entry", "pr": f"https://github.com/{SLUG}/pull/3", "fix_rounds": 0, "human_steps": []},
        "shop-lib": {"state": "passed", "gate": "library", "spec": "001-lib", "pr": "https://github.com/acme/shop-lib/pull/2",
                     "fix_rounds": 0, "human_steps": ["Publish the lib to the registry"]},
        "shop-api": {"state": "passed", "gate": "exposed", "spec": "002-api", "pr": "https://github.com/acme/shop-api/pull/7",
                     "fix_rounds": 2, "deployed": f"sha-{SHA}", "argo": "Synced/Healthy", "smoke_row": "passed (3 tests)",
                     "human_steps": []},
        "shop-worker": {"state": "passed", "gate": "internal", "spec": "003-worker", "pr": "https://github.com/acme/shop-worker/pull/1",
                        "fix_rounds": 1, "deployed": f"sha-{SHA}", "argo": "Synced/Healthy", "human_steps": ["Set the queue URL"]},
        "shop-web": {"state": "passed", "gate": "exposed", "spec": "004-web", "pr": "https://github.com/acme/shop-web/pull/4",
                     "fix_rounds": 0, "deployed": f"sha-{SHA}", "argo": "Synced/Healthy", "smoke_row": "passed on retry (5 tests)",
                     "human_steps": []}}, phase="complete")


def test_complete_marks_spec_and_plan_done_through_a_pr_merged_on_green(w):  # AC-097.20
    all_passed(w)
    r = w.app("complete")
    assert r.rc == 0, r.out
    assert "status: done" in w.origin_file(f"docs/specs/{SPEC}/spec.md")
    assert "status: completed" in w.origin_file(f"docs/plan/{SPEC}.md")
    merge = w.made("pr", "merge")
    assert len(merge) == 1 and "--admin" not in merge[0]
    assert w.state()["phase"] == "done"


def test_complete_report_has_a_row_per_repo_the_checklist_and_promote_commands(w):  # AC-097.20
    all_passed(w)
    out = w.app("complete").out
    assert f"## Shipped: {SPEC} — Shop" in out
    assert "| Repo | Repo spec | PR | CI rounds | dev | Argo | Smoke (dev) |" in out
    assert f"| shop-api | 002-api | https://github.com/acme/shop-api/pull/7 | 3 | shop-api:sha-{SHA} | Synced/Healthy | passed (3 tests) |" in out
    assert "| shop-lib | 001-lib | https://github.com/acme/shop-lib/pull/2 | 1 | - | - | not run: not deployable (library) |" in out
    assert "shop-worker has no dev URL (not exposed in dev)" in out and "| shop-worker | 003-worker |" in out
    assert "passed on retry (5 tests)" in out
    assert "(entry)" in out
    for step in ("Create the payment provider account", "Publish the lib to the registry", "Set the queue URL"):
        assert f"- [ ] {step}" in out
    assert "/gitops:promote shop-api dev staging" in out and "/gitops:promote shop-web dev staging" in out
    assert "/gitops:promote shop-lib" not in out


def test_complete_with_a_red_pr_escalates_and_merges_nothing(w):  # AC-097.20
    all_passed(w)
    w.cfg(red_all=True)
    r = w.app("complete")
    assert r.rc == 1
    assert w.made("pr", "merge") == []
    st = w.state()
    assert st["phase"] != "done" and st["escalated"] and st["cause"] == "code"
    assert "status: done" not in w.origin_file(f"docs/specs/{SPEC}/spec.md")


def test_done_before_repos_show_dashes_and_done_before_this_run(w):  # AC-097.20
    all_passed(w)
    w.edit(lambda st: st["repos"]["shop-lib"].update(state="done-before"))
    out = w.app("complete").out
    assert "| shop-lib | - | - | - | - | - | done before this run |" in out
