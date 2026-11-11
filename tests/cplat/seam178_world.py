"""Spec 178: the world of the seam test (not a test file).

A temporary clone `shop-api` with a bare `origin.git`, a fake `claude` that follows a script, a fake `gh` backed by that origin, a fake
`devbox` that records how it was started, and no network. `cplat headless "/component:ship 007-price-alerts"` runs as a process on it.

The fake `claude` (`CPLAT_CLAUDE`) does what a coordinator session does for the unit it is given (`CPLAT_UNIT`): it issues the unit's
real `cplat` and git commands, and it calls the configured hooks of plugins/shared/hooks/hooks.json (`SessionStart` before its work,
`Stop` after it) the way Claude Code does: the hook command through `sh -c`, `CLAUDE_PLUGIN_ROOT` set, the hook input as JSON on stdin.
`behave` sets what the sessions of a unit do (`land`: one entry per session).

The fake `gh` is the `gh` stub of the 171 land world (land171_world.py) with the extensions of land178_world.py, and: `pr create` and
`pr list` that know the pull request, `auth status`, `api repos/<slug> --jq .permissions.push`, a held check (`hold_file`: the checks
stay pending until the file exists, and a `handshake` FIFO tells the waiting session that the first pending poll happened) and a
red first head (`first_red`).

Nothing here waits by a fixed sleep: the only blocking points are processes, a FIFO and a file the world creates.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import land171_world
import land178_world
import spec as specmod
from waiting import fake_prelude, with_prelude

SPEC_ID = "007-price-alerts"
BRANCH = f"feature/{SPEC_ID}"
SLUG = "acme/shop-api"
PR_URL = f"https://github.com/{SLUG}/pull/7"
ROOT = Path(__file__).resolve().parents[2]
CPLAT_PY = ROOT / "scripts" / "cplat" / "cplat.py"
HOOKS = ROOT / "plugins" / "shared" / "hooks" / "hooks.json"
ALLOW = ["Bash(devbox run *)", "Bash(cplat *)", "Read(~/.claude/plugins/**)"]
TIMEOUT = 240

SPEC_TEXT = """---
spec_id: 007-price-alerts
title: Price alerts
status: approved
priority: P1
shape: library-python
---

# 007 — Price alerts

## Problem

Traders miss moves.

## Acceptance criteria

- **AC-007.1** Given a rule, when the price crosses it, then an email is sent.

## Non-goals

- SMS

## Open questions

None.

## Changelog

- 2026-10-01 created
"""

PLAN_TEXT = """---
spec_id: 007-price-alerts
shape: library-python
spec_hash: {hash}
tasks:
  - {{id: t1, title: model, files: [a.py], covers: [AC-007.1], parallel_safe: false, depends_on: []}}
---

## t1 — model
"""

# ---------------- the gh stub: the 171 stub, 178 extensions, and what a whole ship needs ----------------

PR_LIST_OLD = 'if cmd == ["pr", "list"]:\n    out([])\n'
PR_LIST_NEW = '''if cmd == ["auth", "status"]:
    sys.exit(0)
if cmd == ["pr", "create"]:
    pr.update(state="OPEN", headRefName=opt("--head"), title=opt("--title"), baseRefName=opt("--base") or "main")
    st["first_head"] = head()
    save()
    log(args=args, kind="created")
    print(pr["url"])
    sys.exit(0)
if cmd == ["pr", "list"]:
    log(args=args, kind="list")
    want = opt("--head")
    if pr["state"] == "NONE" or (want and want != pr["headRefName"]) or (opt("--state") == "open" and pr["state"] != "OPEN"):
        out([])
    out([{"number": 7, "url": pr["url"], "title": pr["title"], "labels": [], "isDraft": pr["isDraft"], "state": pr["state"]}])
'''
API_OLD = '    if "/compare/" in path:\n'
API_NEW = '''    if ".permissions.push" in " ".join(args):
        print("true")
        sys.exit(0)
    if "/compare/" in path:
'''
CHECKS_OLD = '    rid = int(h[:7], 16)\n    st["rids"][str(rid)] = h\n    st.setdefault("reported", {})[h] = poll\n'
CHECKS_NEW = '''    if st.get("first_red") and h == st.get("first_head"):
        poll = {n: "fail" for n in poll}
    hold = st.get("hold_file")
    if hold and not os.path.exists(hold):
        if st.get("handshake"):
            fifo, st["handshake"] = st["handshake"], None
            save()
            with open(fifo, "w") as f:
                f.write("polling\\n")
        poll = {n: "pending" for n in poll}
''' + CHECKS_OLD

DEVBOX = '''#!%(py)s
import json, os, sys
with open(os.path.join(os.environ["FAKE178"], "devbox.jsonl"), "a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "cplat": sorted(k for k in os.environ if k.startswith("CPLAT_")), "cwd": os.getcwd()}) + "\\n")
'''

CPLAT_SH = '#!/bin/sh\nexec %(py)s %(cplat)s "$@"\n'

CLAUDE = r'''#!@@PY@@
import json, os, pathlib, subprocess, sys

W = pathlib.Path("@@WORLD@@")
PY, CPLAT, PLUGIN, HOOKS = "@@PY@@", "@@CPLAT@@", "@@PLUGIN@@", pathlib.Path("@@HOOKS@@")
SPEC, BRANCH = "@@SPEC@@", "@@BRANCH@@"
cfg = json.loads((W / "behave.json").read_text())
repo = pathlib.Path.cwd()
unit = os.environ.get("CPLAT_UNIT", "")
argv = sys.argv[1:]
sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else "no-session"
counts_f = W / "counts.json"
counts = json.loads(counts_f.read_text()) if counts_f.is_file() else {}
n = counts.get(unit, 0) + 1
counts[unit] = n
counts_f.write_text(json.dumps(counts))


def note(path, **kw):
    with (W / path).open("a") as fh:
        fh.write(json.dumps(kw) + "\n")


note("sessions.jsonl", unit=unit, n=n, sid=sid, argv=argv)
seq = cfg.get(unit) or []
how = seq[n - 1] if n <= len(seq) else cfg.get("after:" + unit, "normal")


def cplat(*a, check=True):
    res = subprocess.run([PY, CPLAT, *a], cwd=repo, capture_output=True, text=True)
    note("commands.jsonl", unit=unit, n=n, argv=list(a), rc=res.returncode, out=res.stdout[-400:], err=res.stderr[-400:])
    if check and res.returncode != 0:
        sys.stderr.write(res.stdout + res.stderr)
        sys.exit(2)
    return res


def git(*a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True)


def hooks(event):
    """Run the configured hooks of `event` the way Claude Code does; the parsed JSON answers."""
    answers = []
    for group in json.loads(HOOKS.read_text())["hooks"].get(event, []):
        for h in group["hooks"]:
            res = subprocess.run(["sh", "-c", h["command"]], cwd=repo, capture_output=True, text=True, timeout=900,
                                 env={**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN},
                                 input=json.dumps({"session_id": sid, "cwd": str(repo), "hook_event_name": event, "stop_hook_active": False}))
            try:
                answer = json.loads(res.stdout) if res.stdout.strip() else None
            except ValueError:
                answer = {"unparsed": res.stdout}
            note("hooks.jsonl", unit=unit, n=n, event=event, rc=res.returncode, answer=answer, err=res.stderr[-300:])
            answers.append(answer or {})
    return answers


def ship_phase():
    return json.loads(cplat("component", "ship", "status", "--json").stdout)["phase"]


def commit(msg):
    git("add", "-A")
    git("commit", "-q", "-s", "-m", msg)


def on_branch():
    if subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True).stdout.strip() != BRANCH:
        git("switch", "-c", BRANCH) if subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/heads/" + BRANCH], cwd=repo).returncode else git("switch", BRANCH)


def lands():
    on_branch()
    if ship_phase() == "pr":
        (repo / ".pr-body.md").write_text("## Summary\n\nPrice alerts.\n")
        cplat("component", "ship", "pr", "--title", "feat(alerts): price alerts", "--body-file", ".pr-body.md")
    if how == "commit-then-die":                       # the session is killed after a local commit, before the land
        (repo / "late.txt").write_text("a late change\n")
        commit("fix: a late change")
        os._exit(1)
    if how == "stop-during-wait":
        fifo = W / "wait.fifo"
        os.mkfifo(fifo)
        proc = subprocess.Popen([PY, CPLAT, "component", "ship", "land", "--interval", "1"], cwd=repo, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        with open(fifo) as f:                          # blocks until the fake gh saw the first pending poll of the wait
            f.readline()
        gd = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, text=True).stdout.strip()
        marks = sorted(p.name for p in (repo / gd / "cplat-waits").glob("*.json")) if (repo / gd / "cplat-waits").is_dir() else []
        note("waits.jsonl", marks=marks)
        for _ in range(2):                             # the session wants to stop while its wait runs
            answers = hooks("Stop")
            note("stops.jsonl", answers=answers)
        (W / "release").write_text("go\n")
        out, _ = proc.communicate(timeout=300)
        note("commands.jsonl", unit=unit, n=n, argv=["component", "ship", "land", "(background)"], rc=proc.returncode, out=out[-400:], err="")
        if proc.returncode != 0:
            sys.exit(2)
    elif ship_phase() == "land":
        cplat("component", "ship", "land", "--interval", "1")
    if ship_phase() == "deploy":
        cplat("component", "ship", "deploy")


hooks("SessionStart")
if unit != "plan":
    cplat("component", "ship", "start", SPEC)
d = repo / "docs" / "specs" / SPEC
if unit == "red-tests":
    on_branch()
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_alerts.py").write_text("def test_email_on_cross():  # AC-007.1\n    assert True\n")
    commit("test(007): acceptance tests for AC-007.1")
    cplat("spec", "trace", SPEC)
elif unit.startswith("task:"):
    on_branch()
    cplat("spec", "task-done", SPEC, unit.split(":", 1)[1])
    (repo / "a.py").write_text("X = 1\n")
    cplat("quiet", "test-fast")
    commit("feat(007): " + unit)
elif unit == "verification":
    on_branch()
    (d / "verification.md").write_text("**Result:** pass\n")
    text = (d / "spec.md").read_text().replace("status: approved", "status: done").replace("status: building", "status: done")
    (d / "spec.md").write_text(text)
    commit("docs(007): verified")
    cplat("component", "ship", "phase", "pr")
elif unit == "land":
    lands()
answers = hooks("Stop")
if any(a.get("decision") == "block" for a in answers):
    note("blocked.jsonl", unit=unit, n=n, answers=answers)
    sys.exit(4)
'''


def executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(with_prelude(text))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def stub_text() -> str:
    text = land178_world.patched_stub()
    for old, new in ((PR_LIST_OLD, PR_LIST_NEW), (API_OLD, API_NEW), (CHECKS_OLD, CHECKS_NEW)):
        assert text.count(old) == 1, f"the gh stub changed: {old[:40]!r}"
        text = text.replace(old, new)
    return text % {"py": sys.executable, "prelude": fake_prelude()}


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {res.stderr}")
    return res.stdout.strip()


class Seam:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.dir = tmp / "world"
        self.dir.mkdir()
        self.bin = self.dir / "bin"
        self.home = tmp / "home"
        self.home.mkdir()
        self.bare = tmp / "origin.git"
        self.repo = tmp / "shop-api"
        self.runs = tmp / "runs"
        self.runs.mkdir()
        self.plugin = self.dir / "plugin"
        self.git_env = {**os.environ, "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "tester@example.test",
                        "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "tester@example.test",
                        "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}
        (tmp / "gitconfig").write_text("")
        executable(self.bin / "gh", stub_text())
        executable(self.bin / "devbox", DEVBOX % {"py": sys.executable})
        wrapper = CPLAT_SH % {"py": sys.executable, "cplat": CPLAT_PY}
        executable(self.bin / "cplat", wrapper)
        executable(self.plugin / "bin" / "cplat", wrapper)
        self.claude = executable(self.dir / "claude", self.claude_text())
        self.behave({})
        self._build()

    def claude_text(self) -> str:
        text = CLAUDE
        for key, value in (("PY", sys.executable), ("WORLD", self.dir), ("CPLAT", CPLAT_PY), ("PLUGIN", self.plugin), ("HOOKS", HOOKS),
                           ("SPEC", SPEC_ID), ("BRANCH", BRANCH)):
            text = text.replace(f"@@{key}@@", str(value))
        return text

    # ---- the repository
    def g(self, *args: str) -> str:
        return git(self.repo, *args, env=self.git_env)

    def _build(self) -> None:
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True, env=self.git_env)
        r = self.repo
        r.mkdir()
        self.g("init", "-q", "-b", "main")
        (r / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/library-python\nproject_name: shop-api\n")
        (r / ".claude").mkdir()
        self.write_settings(ALLOW)
        (r / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "true", "test-fast": "true"}}}))
        d = r / "docs" / "specs" / SPEC_ID
        d.mkdir(parents=True)
        (d / "spec.md").write_text(SPEC_TEXT)
        (d / "plan.md").write_text(PLAN_TEXT.format(hash=specmod.read(d).ac_hash()))
        self.g("add", "-A")
        self.g("commit", "-q", "-m", "init")
        self.g("remote", "add", "origin", f"https://github.com/{SLUG}.git")
        self.g("config", f"url.{self.bare}.insteadOf", f"https://github.com/{SLUG}.git")
        self.g("push", "-q", "-u", "origin", "main")
        self.state = {"bare": str(self.bare), "slug": SLUG, "checks_calls": 0, "polls": {}, "rids": {}, "last_bucket": {},
                      "checks": {"default": ["pass"]}, "blind_until_checks": 0, "blind_skip": 0, "head_reads": 0, "merge_fail": None,
                      "delete_fail": None, "required": ["test"], "strict": True,
                      "pr": {"url": PR_URL, "state": "NONE", "headRefName": BRANCH, "baseRefName": "main", "isDraft": False,
                             "title": "", "body": "## Summary\n", "labels": [], "mergeCommit": None}}
        self.save()

    def write_settings(self, allow: list[str], commit: bool = False) -> None:
        (self.repo / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": allow}}) + "\n")
        if commit:
            self.g("add", "-A")
            self.g("commit", "-q", "-m", "chore: settings")

    # ---- the fakes
    def save(self) -> None:
        (self.dir / "state.json").write_text(json.dumps(self.state))

    def gh(self, **changes) -> None:
        cur = json.loads((self.dir / "state.json").read_text())
        cur.update(changes)
        self.state = cur
        self.save()

    def behave(self, mapping: dict) -> None:
        (self.dir / "behave.json").write_text(json.dumps(mapping))

    def env(self) -> dict[str, str]:
        base = {k: v for k, v in self.git_env.items() if not k.startswith("CPLAT_")}
        return {**base, "HOME": str(self.home), "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "XDG_CACHE_HOME": str(self.tmp / "cache"), "XDG_CONFIG_HOME": str(self.tmp / "config"), "XDG_STATE_HOME": str(self.tmp / "state"),
                "CPLAT_CLAUDE": str(self.claude), "CPLAT_RUNS_DIR": str(self.runs), "FAKE171": str(self.dir), "FAKE178": str(self.dir),
                "CPLAT_OUTER_RUN": "the-outer-run", "PYTHONUNBUFFERED": "1"}

    def headless(self, *extra: str) -> subprocess.CompletedProcess:
        """`cplat headless "/component:ship 007-price-alerts"` in the clone, as a process."""
        return subprocess.run([sys.executable, str(CPLAT_PY), "headless", f"/component:ship {SPEC_ID}", "--repo", str(self.repo), *extra],
                              cwd=self.repo, env=self.env(), capture_output=True, text=True, timeout=TIMEOUT)

    # ---- what happened
    def lines(self, name: str) -> list[dict]:
        f = self.dir / name
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def sessions(self) -> list[dict]:
        return self.lines("sessions.jsonl")

    def calls(self) -> list[dict]:
        return self.lines("calls.log")

    def events(self, kind: str) -> list[dict]:
        return [c for c in self.calls() if c.get("kind") == kind]

    def devbox_runs(self) -> list[dict]:
        return [c for c in self.lines("devbox.jsonl") if c["args"][:1] == ["run"]]

    def records(self) -> list[dict]:
        f = self.runs / "buffer.jsonl"
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def origin(self, *args: str) -> str:
        return git(self.bare, *args, env=self.git_env)


__all__ = ["Seam", "SPEC_ID", "BRANCH", "PR_URL", "TIMEOUT", "land171_world"]
