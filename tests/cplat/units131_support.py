"""Spec 131 acceptance tests: shared world (a real git repo, a fake `claude` that works one unit per session, stubs for `gh`).

Nothing here calls the real `claude`, `gh` or the network. The fake `claude` is a Python script (`CPLAT_CLAUDE`); it reads
`CPLAT_UNIT`, does that unit's work in the repo (commits on the feature branch, plan `done` flags, ship state) and appends one
JSON line per session to `sessions.jsonl` in the world's directory. Per-unit behaviours for the n-th session of a unit
(`ok`, `nothing`, `partial`, `die`, `say-approval`) are set with `World.behave`.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import core
import spec
from test_spec import PLAN, SPEC, make
from waiting import fake_prelude

SPEC_ID = "007-price-alerts"
BRANCH = f"feature/{SPEC_ID}"
SCRIPTS = str(core.PLATFORM_ROOT / "scripts" / "cplat")
SHA = "0123456789abcdef0123456789abcdef01234567"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, name="f.txt", msg="work", branch=BRANCH):
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD") != branch:
        git(repo, "checkout", "-q", "-B", branch)
    (repo / name).write_text(name + msg + str(len(list(repo.iterdir()))))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD")


def head(repo, ref="HEAD"):
    return git(repo, "rev-parse", ref)


def spec_text(acs: int) -> str:
    """The fixture spec of test_spec.py with `acs` active criteria AC-007.1 ... AC-007.<acs>."""
    base = SPEC.format(status="approved", questions="None.")
    rows = "".join(f"- **AC-007.{i}** Given x{i}, when y, then z.\n" for i in range(1, acs + 1))
    start = base.index("- **AC-007.1**")
    end = base.index("- ~~**AC-007.3**~~")
    return base[:start] + rows + base[end:].replace("- ~~**AC-007.3**~~ withdrawn: SMS is out of scope.\n", "")


def plan_for(tasks: int, acs: int, hash_: str) -> str:
    def covers(i: int) -> str:   # every criterion is covered by some task, so the plan passes check_plan
        ids = sorted({(i - 1) % acs + 1} | {j for j in range(1, acs + 1) if (j - 1) % tasks == i - 1})
        return ", ".join(f"AC-007.{j}" for j in ids)
    rows = "".join(f"  - {{id: t{i}, title: task {i}, files: [f{i}.py], covers: [{covers(i)}], "
                   f"parallel_safe: true, depends_on: []}}\n" for i in range(1, tasks + 1))
    return f"---\nspec_id: {SPEC_ID}\nshape: service-python\nspec_hash: {hash_}\ntasks:\n{rows}---\n\n## t1 — task\n"


def sized_plan(root, tasks: int, acs: int) -> str:
    """Write spec.md with `acs` criteria; return the text of a plan.md with `tasks` independent tasks (not written)."""
    d = root / "docs" / "specs" / SPEC_ID
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(spec_text(acs))
    text = plan_for(tasks, acs, spec.read(d).ac_hash())
    return text


def make_repo(tmp_path, *, plan=True, tasks=None, acs=None, name="shop-api"):
    """A git repo `shop-api` with an approved spec 007 and `.claude/settings.json`. plan=False: no plan.md yet (the fake
    claude's `plan` unit writes the one in `<world>/plan.md.txt`). tasks/acs: a bigger plan (independent tasks t1..tN)."""
    r = tmp_path / name
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-go\nproject_name: shop-api\n")
    (r / ".claude").mkdir()
    (r / ".claude" / "settings.json").write_text('{"permissions": {"allow": ["Bash(devbox run *)", "Bash(cplat *)", "Read(~/.claude/plugins/**)"]}}\n')
    if tasks:
        text = sized_plan(r, tasks, acs or 2)
        if plan:
            (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(text)
    else:
        make(r, status="approved", plan=plan)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    git(r, "remote", "add", "origin", "https://github.com/acme/shop-api.git")
    return r


def plan_text(repo, tasks=None, acs=None) -> str:
    d = repo / "docs" / "specs" / SPEC_ID
    if tasks:
        return plan_for(tasks, acs or 2, spec.read(d).ac_hash())
    return PLAN.format(hash=spec.read(d).ac_hash())


FAKE_CLAUDE = r'''#!%(py)s
%(prelude)s
import json, os, pathlib, subprocess, sys
sys.path.insert(0, %(scripts)r)
W = pathlib.Path(%(world)r)
cfg = json.loads((W / "behave.json").read_text())
repo = pathlib.Path.cwd()
unit = os.environ.get("CPLAT_UNIT", "")
counts_f = W / "counts.json"
counts = json.loads(counts_f.read_text()) if counts_f.is_file() else {}
n = counts.get(unit, 0)
counts[unit] = n + 1
counts_f.write_text(json.dumps(counts))
with (W / "sessions.jsonl").open("a") as fh:
    fh.write(json.dumps({"unit": unit, "argv": sys.argv[1:], "allowlist": os.environ.get("CPLAT_RUN_ALLOWLIST"),
                         "n": n + 1}) + "\n")
seq = cfg.get(unit) or cfg.get("*") or []
how = seq[n] if n < len(seq) else cfg.get("after:" + unit, "ok")


def g(*a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit_all(msg):
    if g("rev-parse", "--abbrev-ref", "HEAD") != %(branch)r:
        g("checkout", "-q", "-B", %(branch)r)
    g("add", "-A")
    g("commit", "-q", "--allow-empty", "-m", msg)


if how == "die":
    sys.exit(1)
if how == "nothing":
    sys.exit(0)
if how == "say-approval":
    print("waiting for approval to push the branch")
    sys.exit(0)
if how == "partial":
    commit_all("wip: " + unit)
    sys.exit(0)
if how == "branch-only":
    g("checkout", "-q", "-B", %(branch)r)
    sys.exit(0)

import datetime, runs
if cfg.get("now"):
    runs.utcnow = lambda: datetime.datetime.fromisoformat(cfg["now"])
import ship, spec
if cfg.get("command") == "ship" and unit != "plan" and (repo / "docs" / "specs" / %(spec_id)r / "plan.md").is_file():
    ship.start(repo, "7", True)              # like `cplat component ship start`, step 1 of every /component:ship session (it resumes)
if unit == "plan":
    d = repo / "docs" / "specs" / %(spec_id)r
    if not (d / "plan.md").is_file():
        (d / "plan.md").write_text((W / "plan.md.txt").read_text())
    commit_all("docs(007): plan")
    if cfg.get("command") == "ship":
        ship.start(repo, "7", True)
elif unit == "red-tests":
    t = repo / "tests"
    t.mkdir(exist_ok=True)
    (t / "test_alerts.py").write_text("# " + " ".join(cfg["acs"]) + "\n")
    commit_all("test(007): acceptance tests for " + cfg["acs"][0])
elif unit.startswith("batch:"):              # spec 159: one session runs the batch's tasks ("first-only": just the first)
    ids = unit.split(":", 1)[1].split(",")
    for task in ids[:1] if how == "first-only" else ids:
        if not any(t["id"] == task and t.get("done") for t in spec.find(repo, "7").plan[0]["tasks"]):
            spec.task_done(spec.find(repo, "7"), task)
            (repo / (task + ".py")).write_text("x = 1\n")
    commit_all("feat(007): " + unit)
elif unit.startswith("task:"):
    spec.task_done(spec.find(repo, "7"), unit.split(":", 1)[1])
    (repo / (unit.split(":", 1)[1] + ".py")).write_text("x = 1\n")
    commit_all("feat(007): " + unit)
elif unit == "verification":
    d = repo / "docs" / "specs" / %(spec_id)r
    (d / "verification.md").write_text("**Result:** pass\n")
    (d / "spec.md").write_text((d / "spec.md").read_text().replace("status: approved", "status: done").replace("status: building", "status: done"))
    commit_all("docs(007): verified")
    if cfg.get("command") == "ship":
        ship.set_phase(repo, "pr")
elif unit == "land":
    f = pathlib.Path(g("rev-parse", "--git-common-dir")) / "cplat-ship.json"
    if not f.is_absolute():
        f = repo / f
    st = json.loads(f.read_text())
    st.update(phase="done", merge_sha=%(sha)r)
    f.write_text(json.dumps(st))
'''

GH_STUB = '''#!/bin/sh
# stub gh: FAKE_GH_AUTH=fail -> `auth status` fails (=offline, =flaky as for FAKE_GH_PUSH); FAKE_GH_PUSH=false -> no push permission, =offline -> the network
# is down, =flaky -> down for the first call only; every call is logged.
echo "$@" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "auth status")
    [ "$FAKE_GH_AUTH" = "fail" ] && { echo "You are not logged in" >&2; exit 1; }
    [ "$FAKE_GH_AUTH" = "offline" ] && { echo "error connecting to api.github.com" >&2; exit 1; }
    if [ "$FAKE_GH_AUTH" = "flaky" ] && [ ! -e "$FAKE_GH_LOG.authflaky" ]; then
      touch "$FAKE_GH_LOG.authflaky"; echo "dial tcp: lookup api.github.com: no such host" >&2; exit 1
    fi
    exit 0 ;;
  "pr list") echo "[]"; exit 0 ;;
esac
if [ "$1" = "api" ]; then
  case "$*" in
    *permissions.push*)
      if [ "$FAKE_GH_PUSH" = "offline" ] || { [ "$FAKE_GH_PUSH" = "flaky" ] && [ ! -e "$FAKE_GH_LOG.flaky" ]; }; then
        touch "$FAKE_GH_LOG.flaky"; echo "dial tcp: lookup api.github.com: no such host" >&2; exit 1
      fi
      [ "$FAKE_GH_PUSH" = "false" ] && echo false || echo true ;;
    *) echo tester ;;
  esac
  exit 0
fi
exit 0
'''


class World:
    """A repo plus the fakes. `behave({"task:t2": ["nothing", "ok"]})` sets the n-th session's behaviour per unit."""

    def __init__(self, tmp_path, monkeypatch, *, plan=True, command="ship", tasks=None, acs=None):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.dir = tmp_path / "world"
        self.dir.mkdir()
        self.repo = make_repo(tmp_path, plan=plan, tasks=tasks, acs=acs)
        self.command = command
        n_acs = len(spec.read(self.repo / "docs" / "specs" / SPEC_ID).active_acs())
        self.acs = [f"AC-007.{i}" for i in range(1, n_acs + 1)]
        (self.dir / "plan.md.txt").write_text(plan_text(self.repo, tasks, acs))
        self.cfg = {"command": "ship" if command != "build" else "build", "acs": self.acs}
        self.write_cfg()
        exe = self.dir / "claude"
        exe.write_text(FAKE_CLAUDE % {"py": sys.executable, "scripts": SCRIPTS, "world": str(self.dir), "branch": BRANCH,
                                      "spec_id": SPEC_ID, "sha": SHA, "prelude": fake_prelude()})
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(GH_STUB.replace("\n", "\n" + fake_prelude("sh") + "\n", 1))
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.gh_log = self.dir / "gh.log"
        self.gh_log.write_text("")
        monkeypatch.setenv("CPLAT_CLAUDE", str(exe))
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_GH_LOG", str(self.gh_log))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Tester")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.test")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Tester")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tester@example.test")
        monkeypatch.delenv("FAKE_GH_AUTH", raising=False)
        monkeypatch.delenv("FAKE_GH_PUSH", raising=False)
        self.user_settings = tmp_path / "user-settings.json"
        self.user_settings.write_text("{}")
        import headless
        monkeypatch.setattr(headless, "notify", lambda *a: None)

    # ---- fakes
    def write_cfg(self):
        (self.dir / "behave.json").write_text(json.dumps(self.cfg))

    def behave(self, mapping, **extra):
        self.cfg.update(mapping)
        self.cfg.update(extra)
        self.write_cfg()

    def patch_layers(self):
        """Only the four layers of this world are read (the developer's own settings never matter)."""
        import preflight
        repo, user = self.repo, self.user_settings
        self.mp.setattr(preflight, "layers", lambda r=None: [
            ("managed", self.dir / "no-managed.json"), ("user", user),
            ("project", Path(r or repo) / ".claude" / "settings.json"),
            ("local", Path(r or repo) / ".claude" / "settings.local.json")])

    # ---- reading what happened
    def sessions(self):
        f = self.dir / "sessions.jsonl"
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def units_run(self):
        return [s["unit"] for s in self.sessions()]

    def summary(self):
        f = self.tmp / "cache" / "sdlc-foundry" / "headless" / "shop-api" / "summary.log"
        return f.read_text().splitlines() if f.is_file() else []

    def gh_calls(self):
        return self.gh_log.read_text().splitlines()

    def units_file(self):
        f = self.repo / ".git" / "cplat-units.json"
        return json.loads(f.read_text()) if f.is_file() else None

    def ledgers(self):
        import runs
        d = runs.state_dir() / "budgets"
        return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.is_dir() else []

    def run(self, *args, prompt=None):
        import headless
        self.patch_layers()                  # imports preflight: a missing module fails the test, not its fixture
        import runs
        self.cfg["now"] = runs.utcnow().isoformat()   # the fake sessions run on the test's clock, not the wall clock
        self.write_cfg()
        return headless.main([prompt or f"/component:{self.command} 7", "--repo", str(self.repo), *args])


def snapshot_settings(*paths):
    return {str(p): (Path(p).read_bytes() if Path(p).is_file() else None) for p in paths}
