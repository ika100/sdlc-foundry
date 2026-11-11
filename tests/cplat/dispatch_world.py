"""Spec 167 acceptance tests: the dispatcher world. Nothing here reaches GitHub, `claude` or the network.

`World` builds, under tmp_path: a bare `origin`, a clone `shop-api` whose origin URL is `https://github.com/acme/shop-api.git`
(rewritten to the bare repo with `insteadOf`), a state home, and three executables the dispatcher reaches only through its
documented seams:

- `gh` on PATH (`dispatch_fake_gh`): issues, labels, pull requests and checks in a JSON file;
- `$CPLAT_CLAUDE`: the two short agent calls (premise and mode check). It answers with the JSON `{"verdict", "evidence", "why", "mode"}`
  of `World.answer` (default: `holds`, `single`), reports `usage`, and records every call;
- `$CPLAT_DISPATCH_HEADLESS`: the fake `cplat headless` of design.md "Units": it writes the result file at start and at its end, records
  its arguments and working directory, and (behaviour `wait`) runs until `World.release(unit)`. `World.behave(...)` sets what a unit does.

The dispatcher is driven through `cplat.main(["dispatch", ...])` in the clone (the cwd). The clock is `dispatch_state.now` and
`notify.now` (patched before every command, when the module exists), so a missing module fails the test through the command, not
through the fixture.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import importlib
import io
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

import claim
from waiting import budget, fake_prelude, wait_file, wait_for, with_prelude
from dispatch_fake_gh import script as gh_script
from units131_support import plan_for, spec_text

REAL_CLAIM_GH = claim.gh            # conftest replaces `claim.gh` for every test; the world wants the real one (it reaches the fake gh)
SLUG = "acme/shop-api"
BASE = "dispatch/acme__shop-api"

FAKE_CLAUDE = r'''#!%(py)s
%(pre)s
import json, os, pathlib, sys
W = pathlib.Path(os.environ["FAKE_DISPATCH_DIR"])
args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args and args.index("-p") + 1 < len(args) else sys.stdin.read()
cfg = json.loads((W / "claude.json").read_text())
with (W / "claude-calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"prompt": prompt, "args": args, "cwd": os.getcwd()}) + "\n")
if cfg.get("fail"):
    print("claude: boom", file=sys.stderr)
    sys.exit(1)
answer = dict(cfg.get("default") or {"verdict": "holds", "evidence": "", "why": "still reproducible", "mode": "single"})
for a in cfg.get("answers", []):
    if a["match"] in prompt:
        answer = a["result"]
out = {"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(answer), "session_id": "fake",
       "total_cost_usd": 0.01}
if not cfg.get("no_usage"):
    out["usage"] = cfg.get("usage") or {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 0,
                                        "cache_creation_input_tokens": 0}
print(json.dumps(out))
'''

FAKE_HEADLESS = r'''#!%(py)s
%(pre)s
import datetime, json, os, pathlib, re, subprocess, sys, time
W = pathlib.Path(os.environ["FAKE_DISPATCH_DIR"])
argv = sys.argv[1:]
unit = os.environ.get("CPLAT_DISPATCH_UNIT", "")
res = pathlib.Path(os.environ["CPLAT_DISPATCH_RESULT"]) if os.environ.get("CPLAT_DISPATCH_RESULT") else None
calls = W / "headless-calls.jsonl"
n = 1 + sum(1 for ln in calls.read_text().splitlines() if json.loads(ln)["unit"] == unit) if calls.is_file() else 1
with calls.open("a") as fh:
    fh.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "unit": unit, "pid": os.getpid(), "n": n, "result_file": str(res)}) + "\n")
B = json.loads((W / "behave.json").read_text())
cfg = dict(B.get("default", {}))
u = B.get("units", {}).get(unit, {})
cfg.update({k: v for k, v in u.items() if not k.startswith("start")})
cfg.update(u.get("start%%d" %% n, {}))
now = lambda: datetime.datetime.now().isoformat(timespec="seconds")
rec = {"unit": unit, "run_id": "fake-run-" + unit, "pid": os.getpid(), "started_at": now(), "ended_at": None}
def put(text):
    tmp = res.with_name(res.name + ".%%d.tmp" %% os.getpid())
    tmp.write_text(text)
    os.replace(tmp, res)


if res:
    put(json.dumps(rec))


def end(outcome, result, stop_reason, cause=None, code=0):
    rec.update({"ended_at": now(), "result": result, "stop_reason": stop_reason, "outcome": outcome, "cause": cause, "code": code,
                "tokens": cfg.get("tokens", 1234)})
    if res:
        put(json.dumps(rec))
    sys.exit(code)


if cfg.get("then") == "die":
    time.sleep(cfg.get("die_after", 0.2))  # fake-delay: the unit dies die_after seconds after it started
    os._exit(1)
if cfg.get("mode", "wait") == "wait":
    deadline = time.time() + 90
    stop = res.parent / "cplat-dispatch-stop" if res else None
    while time.time() < deadline:
        if (W / "release" / unit).exists() or (W / "release" / "all").exists():
            break
        if cfg.get("honor_stop") and stop and stop.exists():
            end("abandoned", "paused at a checkpoint by cplat dispatch", "paused", code=1)
        time.sleep(0.05)  # fake-delay: polls for the release or stop file the test writes
then =cfg.get("then", "done")
if then == "die-late":
    os._exit(1)
if then == "escalate":
    end("escalated", cfg.get("reason", "escalated: tests keep failing"), "escalated", cause="decision", code=1)
text = " ".join(argv)
m = re.search(r"/component:fix #(\d+)", text)
if m and cfg.get("pr", True):
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
    subprocess.run(["gh", "pr", "create", "--head", branch, "--title", "fix #" + m.group(1), "--body", "Closes #" + m.group(1)],
                   capture_output=True, text=True)
end("done", "pull request opened", "done")
'''


def git(cwd, *args, check=True):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise AssertionError(f"git {' '.join(args)}: {p.stderr}")
    return p.stdout.strip()


def _atomic_write(path: Path, text: str) -> None:
    """Readers in other processes see the old or the new text, never an empty or half-written file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _exe(path: Path, text: str) -> Path:
    path.write_text(with_prelude(text))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Result:
    def __init__(self, rc, out, err):
        self.rc, self.out, self.err = rc, out, err

    @property
    def lines(self):
        return self.out.splitlines()

    def json(self):
        return json.loads(self.out)

    def __repr__(self):
        return f"rc={self.rc}\n--- stdout\n{self.out}\n--- stderr\n{self.err}"


MUTATING = {("issue", "edit"), ("issue", "comment"), ("issue", "close"), ("issue", "reopen"), ("label", "create"), ("pr", "merge"),
            ("pr", "update-branch"), ("pr", "create"), ("pr", "close"), ("pr", "comment"), ("pr", "edit"), ("pr", "ready")}


class World:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.dir = tmp_path / "fake"
        (self.dir / "release").mkdir(parents=True)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.state_home = tmp_path / "state"
        self.state_home.mkdir()
        self.now = dt.datetime(2026, 11, 10, 12, 0, 0)
        self.desktop, self.posts, self.mails, self.notify_gh = [], [], [], []
        self.gh_file = tmp_path / "gh.json"
        _atomic_write(self.gh_file, json.dumps({
            "slug": SLUG, "issues": {}, "prs": {}, "labels": [], "log": [], "events": [], "main": 0, "merge_delay": 0,
            "default_checks": [[{"name": "ci", "bucket": "pass"}]]}))
        self._threads = set(threading.enumerate())      # threads of the test (not ours) are joined on close
        _exe(self.bin / "gh", gh_script())
        _exe(self.bin / "claude", FAKE_CLAUDE % {"py": sys.executable, "pre": fake_prelude()})
        _exe(self.bin / "fake-headless", FAKE_HEADLESS % {"py": sys.executable, "pre": fake_prelude()})
        self.claude_cfg, self.behave_cfg = {}, {"default": {}, "units": {}}
        self._write_cfg()
        gitcfg = tmp_path / "gitconfig"
        gitcfg.write_text("[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        for k, v in {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "XDG_STATE_HOME": str(self.state_home),
                     "XDG_CONFIG_HOME": str(tmp_path / "config"), "HOME": str(tmp_path / "home"), "FAKE_GH_STATE": str(self.gh_file),
                     "FAKE_DISPATCH_DIR": str(self.dir), "CPLAT_CLAUDE": str(self.bin / "claude"),
                     "CPLAT_DISPATCH_HEADLESS": str(self.bin / "fake-headless"), "GIT_CONFIG_GLOBAL": str(gitcfg),
                     "GIT_CONFIG_NOSYSTEM": "1"}.items():
            monkeypatch.setenv(k, v)
        (tmp_path / "home").mkdir()
        monkeypatch.setattr(claim, "gh", REAL_CLAIM_GH)
        import notify
        monkeypatch.setattr(notify, "desktop_send", lambda title, text: self.desktop.append((title, text)) or f"d{len(self.desktop)}")
        monkeypatch.setattr(notify, "desktop_withdraw", lambda ref: None)
        monkeypatch.setattr(notify, "http_post", lambda url, payload: self.posts.append((url, payload)))
        monkeypatch.setattr(notify, "send_mail", lambda cfg, subject, body: self.mails.append((subject, body)))
        monkeypatch.setattr(notify, "gh", lambda args: self.notify_gh.append(list(args)) or "")
        self._repo()
        monkeypatch.chdir(self.repo)

    # ---- git ----

    def _repo(self):
        self.bare = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True, env=os.environ)
        self.repo = self.work / "shop-api"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        url = f"https://github.com/{SLUG}.git"
        git(self.repo, "remote", "add", "origin", url)
        git(self.repo, "config", f"url.{self.bare}.insteadOf", url)
        (self.repo / "README.md").write_text("shop-api\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        git(self.repo, "fetch", "-q", "origin")

    def commit(self, name, text, msg):
        """A commit on main, pushed; returns its sha."""
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", msg)
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "fetch", "-q", "origin")
        return git(self.repo, "rev-parse", "HEAD")

    def policy(self, **kw):
        doc = {"slots": 1, "budget": {"tokens_per_day": 20_000_000}}
        doc.update(kw)
        for k in [k for k, v in doc.items() if v is None]:
            del doc[k]
        (self.repo / ".platform").mkdir(exist_ok=True)
        (self.repo / ".platform" / "dispatch.yml").write_text(yaml.safe_dump(doc))
        return doc

    def policy_text(self, text):
        (self.repo / ".platform").mkdir(exist_ok=True)
        (self.repo / ".platform" / "dispatch.yml").write_text(text)

    def spec(self, number=7, slug="price-alerts", status="approved", plan="single", tracks=(), questions="None.", priority="P1",
             created="2026-10-01"):
        """A spec on main (`docs/specs/<NNN>-<slug>`): plan `team` (two independent tasks: a `batch:` unit), `single` (one task) or None."""
        sid = f"{number:03d}-{slug}"
        text = spec_text(2).replace("007-price-alerts", sid).replace("007", f"{number:03d}")
        text = text.replace("status: approved", f"status: {status}").replace("priority: P1", f"priority: {priority}")
        text = text.replace("tracks: [42]", f"tracks: [{', '.join(str(t) for t in tracks)}]" if tracks else "")
        text = text.replace("## Open questions\n\nNone.\n", f"## Open questions\n\n{questions}\n")
        text = text.replace("- 2026-10-01 created", f"- {created} created")
        d = self.repo / "docs" / "specs" / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.md").write_text(text)
        if plan:
            import spec as specmod
            ptext = plan_for(2 if plan == "team" else 1, 2, specmod.read(d).ac_hash()).replace("007-price-alerts", sid)
            (d / "plan.md").write_text(ptext)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", f"spec {sid}")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "fetch", "-q", "origin")
        return sid

    # ---- the fake gh ----

    def _gh(self):
        return json.loads(self.gh_file.read_text())

    def _put(self, doc):
        _atomic_write(self.gh_file, json.dumps(doc))

    def edit_gh(self, fn):
        """Read-modify-write under the lock the fake gh holds for each call: no update of either side is lost."""
        with open(f"{self.gh_file}.lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            doc = self._gh()
            fn(doc)
            self._put(doc)

    def issue(self, n, title=None, labels=("triaged",), body="", created=None, state="OPEN", comments=()):
        created = created or f"2026-11-0{min(n, 9)}T08:00:00Z"
        row = {"number": n, "title": title or f"issue {n}", "body": body, "state": state, "labels": list(labels), "assignees": [],
               "createdAt": created, "comments": [{"body": c, "createdAt": created} for c in comments]}
        self.edit_gh(lambda d: d["issues"].__setitem__(str(n), row))

    def pr(self, n, head, closes=(), state="OPEN", checks=None, behind=0, after_update=None, body=""):
        row = {"number": n, "url": f"https://github.com/{SLUG}/pull/{n}", "title": f"pr {n}", "body": body, "state": state,
               "isDraft": False, "headRefName": head, "head": f"sha{n}-0", "behind": behind, "closes": list(closes), "labels": [],
               "seqs": {}, "after_update_checks": after_update}
        if checks is not None:
            row["seqs"][row["head"]] = {"seq": checks, "i": 0}
        self.edit_gh(lambda d: d["prs"].__setitem__(str(n), row))
        return row["url"]

    def issue_of(self, n):
        return self._gh()["issues"][str(n)]

    def labels_of(self, n):
        return self.issue_of(n)["labels"]

    def comments_of(self, n):
        return [c["body"] for c in self.issue_of(n)["comments"]]

    def set_default_checks(self, seq):
        self.edit_gh(lambda d: d.__setitem__("default_checks", seq))

    def gh_calls(self):
        return [e["argv"] for e in self._gh()["log"]]

    def gh_writes(self):
        return [a for a in self.gh_calls() if tuple(a[:2]) in MUTATING]

    def events(self):
        return self._gh()["events"]

    def fingerprint(self):
        """GitHub (issues, labels, PRs), branches, worktrees, stashes: what a read-only command must leave as it is."""
        d = self._gh()
        return json.dumps({"gh": [d["issues"], d["labels"], d["prs"]],
                           "git": [git(self.repo, "branch", "-a"), git(self.repo, "worktree", "list"), git(self.repo, "stash", "list")]},
                          sort_keys=True)

    # ---- the fake claude and the fake headless ----

    def _write_cfg(self):
        _atomic_write(self.dir / "claude.json", json.dumps(self.claude_cfg))
        _atomic_write(self.dir / "behave.json", json.dumps(self.behave_cfg))

    def answer(self, match, **result):
        """The premise answer for the issue whose text holds `match` (e.g. its title)."""
        self.claude_cfg.setdefault("answers", []).append({"match": match, "result": result})
        self._write_cfg()

    def claude(self, **kw):
        self.claude_cfg.update(kw)
        self._write_cfg()

    def claude_calls(self):
        f = self.dir / "claude-calls.jsonl"
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def behave(self, unit=None, **kw):
        """What the fake headless does: mode `wait` (until `release`) or `now`; then `done`, `escalate`, `die`; tokens; reason; honor_stop."""
        (self.behave_cfg["units"].setdefault(unit, {}) if unit else self.behave_cfg["default"]).update(kw)
        self._write_cfg()

    def calls(self):
        f = self.dir / "headless-calls.jsonl"
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def calls_of(self, unit):
        return [c for c in self.calls() if c["unit"] == unit]

    def release(self, unit="all"):
        (self.dir / "release" / unit).write_text("")

    def result_of(self, unit):
        c = self.calls_of(unit)[-1]
        return json.loads(Path(c["result_file"]).read_text())

    def wait_ended(self, unit, timeout=20):
        assert self.calls_of(unit), f"the dispatcher never started {unit}"
        def ended():
            try:
                return bool(self.result_of(unit).get("ended_at"))
            except (OSError, ValueError, IndexError):
                return False

        ok = bool(wait_for(ended, budget(timeout), what=f"the fake headless of {unit} to end"))
        # the fake writes `ended_at` and then exits: the dispatcher still sees a live unit until the process is gone
        pid = self.calls_of(unit)[-1]["pid"]
        wait_for(lambda: not self.alive(pid), budget(timeout), what=f"the fake headless of {unit} (pid {pid}) to exit")
        return ok

    def wait_until(self, fn, timeout=30):
        return bool(wait_for(fn, budget(timeout), what="the condition"))

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(out) and not out.startswith("Z")

    def pids(self):
        return [c["pid"] for c in self.calls()]

    # ---- the dispatcher ----

    def dispatch_dir(self):
        return self.state_home / "sdlc-foundry" / BASE

    def state(self):
        f = self.dispatch_dir() / "state.json"
        return json.loads(f.read_text()) if f.is_file() else {}

    def write_state(self, **parts):
        f = self.dispatch_dir() / "state.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        doc = {"schema": 1}
        if f.is_file():
            doc = json.loads(f.read_text())
        doc.update(parts)
        f.write_text(json.dumps(doc))

    def worktree(self, key):
        return self.dispatch_dir() / "worktrees" / f"shop-api-{key}"

    def unit_file(self, key):
        wt = self.worktree(key)
        gd = Path(git(wt, "rev-parse", "--absolute-git-dir"))
        return json.loads((gd / "cplat-dispatch-unit.json").read_text()), gd

    def set_now(self, when):
        self.now = when

    def _patch_clock(self):
        for name in ("dispatch_state", "notify"):
            try:
                mod = importlib.import_module(name)
            except ImportError:
                continue
            self.mp.setattr(mod, "now", lambda: self.now, raising=False)

    def restart(self):
        """A killed dispatcher keeps nothing in memory: every `dispatch*` module is imported afresh by the next command."""
        keep = ("dispatch_world", "dispatch_fake_gh")
        for name in [n for n in sys.modules if (n == "dispatch" or n.startswith("dispatch_")) and n not in keep]:
            del sys.modules[name]

    def run(self, *argv, cwd=None) -> Result:
        import cplat
        self._patch_clock()
        out, err = io.StringIO(), io.StringIO()
        before = len(self.calls())
        if argv and argv[0] in ("start", "resume"):
            self._settle_lands()
        if cwd:
            self.mp.chdir(cwd)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cplat.main(["dispatch", *argv])
        finally:
            self.mp.chdir(self.repo)
        res = Result(rc, out.getvalue(), err.getvalue())
        if argv and argv[0] in ("start", "resume"):
            self._settle(before, res)
        return res

    def _settle_lands(self):
        """A land process writes its verdict into the unit file and then exits: the dispatcher must not look at it in between
        (it would still count as landing and say nothing), so wait until every land process that has given its verdict is gone."""
        listing = git(self.repo, "worktree", "list", "--porcelain")
        for line in listing.splitlines():
            if not line.startswith("worktree "):
                continue
            try:
                gd = Path(git(Path(line[9:]), "rev-parse", "--absolute-git-dir", check=False).strip())
                unit = json.loads((gd / "cplat-dispatch-unit.json").read_text())
            except (OSError, ValueError):
                continue
            pid = unit.get("land_pid")
            if pid and unit.get("landed"):
                wait_for(lambda pid=pid: not self.alive(pid), budget(15), what=f"the land process {pid} to exit")

    def _settle(self, before, res):
        """The fake headless records its call when its interpreter is up: wait for the processes this command started."""
        expected = before + len([ln for ln in res.lines if ln.startswith(("started ", "restarted "))])
        wait_for(lambda: len(self.calls()) >= expected, budget(15), what=f"{expected} headless calls")
        for call in self.calls()[before:expected]:      # the next thing a test reads is the result file the fake writes at start
            if call["result_file"] != "None":
                wait_file(call["result_file"], budget(15))

    def needs(self, *argv) -> Result:
        import cplat
        self._patch_clock()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cplat.main(["needs", *argv])
        return Result(rc, out.getvalue(), err.getvalue())

    def plan(self):
        r = self.run("plan", "--json")
        assert r.rc == 0, r
        return r.json()

    def cand(self, doc, item):
        [c] = [c for c in doc["candidates"] if c["item"] == item]
        return c

    def order(self, doc):
        return [c["item"] for c in doc["candidates"]]

    def _stragglers(self):
        """Pids of every process whose command line names this world (headless units, land processes, anything they started)."""
        out = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, check=False).stdout
        mine = str(self.tmp)
        pids = []
        for ln in out.splitlines():
            pid, _, cmd = ln.strip().partition(" ")
            if pid.isdigit() and int(pid) != os.getpid() and mine in cmd:
                pids.append(int(pid))
        return pids

    def close(self):
        """End the world: release and kill every process it started, close the fake gh to leftover callers, join leftover threads."""
        with contextlib.suppress(OSError):
            (self.dir / "release" / "all").write_text("")
        victims = set(self.pids()) | set(self._stragglers())
        for pid in victims:
            with contextlib.suppress(OSError):
                os.killpg(pid, signal.SIGKILL)      # a detached process leads its own session and group
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        for pid in victims:
            with contextlib.suppress(OSError):
                os.waitpid(pid, os.WNOHANG)
        with contextlib.suppress(OSError, ValueError):
            self.edit_gh(lambda d: d.update(closed=True))
        end = time.time() + 20                      # a thread the test left behind would call gh in the next test's world
        for t in [t for t in threading.enumerate() if t not in self._threads and t is not threading.current_thread()]:
            t.join(max(0.0, end - time.time()))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    yield w
    w.close()

