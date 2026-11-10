"""Spec 171: a shared world for the land tests (not a test file).

A bare `origin.git` stands for GitHub's repository, `shop-api` is the clone a ship run works in, `other` is a person's clone that
moves `main`. The clone's `origin` URL reads `https://github.com/acme/shop-api.git` (so `cplat` finds its slug) and a git
`insteadOf` rule sends the traffic to the bare repository. `gh` is an executable stub on PATH (a Python script) that answers
like GitHub from the real state of the bare repository: the PR head is the tip of the PR branch, `mergeable` comes from a real
`git merge-tree`, and `gh pr merge` squashes into the bare `main`. With `--delete-branch` it does gh's local half too (switch to
the base branch, delete the branch), so a worktree that holds `main` fails it exactly as #371 and #622 describe.

Nothing here touches GitHub or the network. `World.calls()` and `World.events()` read what the stub saw.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import ship
import spec
from test_spec import SPEC, make

BRANCH = "feature/007-price-alerts"
SLUG = "acme/shop-api"
PR_URL = f"https://github.com/{SLUG}/pull/7"
HEAD_TEXT = "# Backlog\n\nhand written head line one\nhand written head line two\n\n"
TAIL_TEXT = "\n## Not built\n\n- a hand written tail line\n"

STUB = r'''#!%(py)s
import json, os, subprocess, sys

W = os.environ["FAKE171"]
S = os.path.join(W, "state.json")
st = json.load(open(S))
args = sys.argv[1:]
BARE = st["bare"]
ENV = {**os.environ, "GIT_AUTHOR_NAME": "gh", "GIT_AUTHOR_EMAIL": "gh@example.test",
       "GIT_COMMITTER_NAME": "gh", "GIT_COMMITTER_EMAIL": "gh@example.test"}


def save():
    json.dump(st, open(S, "w"))


def log(**kw):
    with open(os.path.join(W, "calls.log"), "a") as f:
        f.write(json.dumps(kw) + "\n")


def bgit(*a):
    r = subprocess.run(["git", "--git-dir", BARE, *a], capture_output=True, text=True, env=ENV)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def opt(name):
    return args[args.index(name) + 1] if name in args else None


def fail(msg, code=1):
    sys.stderr.write(msg + "\n")
    sys.exit(code)


pr = st["pr"]


def head():
    return bgit("rev-parse", "refs/heads/" + pr["headRefName"])[1]


def base_tip():
    return bgit("rev-parse", "refs/heads/" + pr["baseRefName"])[1]


def mergeable():
    if pr["state"] != "OPEN":
        return "UNKNOWN"
    rc, _, _ = bgit("merge-tree", "--write-tree", base_tip(), head())
    return "CONFLICTING" if rc == 1 else "MERGEABLE"


def out(value):
    print(json.dumps(value))
    sys.exit(0)


def bucket_of(sha):
    seq = st["checks"].get(sha) or st["checks"]["default"]
    n = st["polls"].get(sha, 0)
    st["polls"][sha] = n + 1
    return seq[min(n, len(seq) - 1)]


cmd = args[:2]
if cmd == ["pr", "view"]:
    fields = (opt("--json") or "").split(",")
    h = head()
    asked = "headRefOid" in fields
    reads = st.get("head_reads", 0)
    if asked:
        st["head_reads"] = reads + 1
        save()
    blind = asked and reads >= st.get("blind_skip", 0) and st.get("blind_until_checks", 0) > st["checks_calls"]
    values = {"number": 7, "url": pr["url"], "state": pr["state"], "mergeable": mergeable(), "headRefOid": None if blind else h,
              "headRefName": pr["headRefName"], "baseRefName": pr["baseRefName"], "isDraft": pr["isDraft"],
              "title": pr["title"], "body": pr["body"], "labels": pr["labels"], "mergeCommit": pr["mergeCommit"],
              "isCrossRepository": False, "mergeStateStatus": "CLEAN"}
    log(args=args)
    out({f: values.get(f) for f in fields if not (f == "headRefOid" and blind)})
if cmd == ["pr", "checks"]:
    st["checks_calls"] += 1
    h = head()
    b = bucket_of(h)
    rid = int(h[:7], 16)
    st["rids"][str(rid)] = h
    st["last_bucket"][h] = b
    save()
    log(args=args, kind="checks", sha=h, bucket=b)
    state = {"pass": "SUCCESS", "fail": "FAILURE", "pending": "IN_PROGRESS"}[b]
    out([{"name": "test", "state": state, "bucket": b, "link": "https://github.com/%%s/actions/runs/%%d/job/1" %% (st["slug"], rid)}])
if cmd == ["run", "view"]:
    rid = args[2]
    if "--log-failed" in args:
        print("FAIL TestSomething\nexit status 1")
        sys.exit(0)
    if "headSha" in args:
        out({"headSha": st["rids"].get(rid)})
    if "workflowDatabaseId" in args:
        out({"workflowDatabaseId": 7})
    if "status" in args:
        print("completed")
        sys.exit(0)
    out({})
if cmd == ["run", "list"]:
    sha = opt("--commit")
    b = st["last_bucket"].get(sha, "pass")
    rid = int(sha[:7], 16) if sha else 0
    done = b != "pending"
    out([{"status": "completed" if done else "in_progress", "conclusion": ("success" if b == "pass" else "failure") if done else "",
          "databaseId": rid, "workflowDatabaseId": 7}])
if cmd == ["pr", "ready"]:
    pr["isDraft"] = False
    save()
    sys.exit(0)
if cmd == ["pr", "edit"] or cmd == ["pr", "comment"]:
    sys.exit(0)
if cmd == ["pr", "list"]:
    out([])
if cmd == ["pr", "update-branch"]:
    h, b = head(), base_tip()
    rc, tree, err = bgit("merge-tree", "--write-tree", b, h)
    if rc != 0:
        fail("Cannot update PR branch due to conflicts")
    rc, commit, err = bgit("commit-tree", tree.splitlines()[0], "-p", h, "-p", b, "-m", "Merge main into the branch")
    bgit("update-ref", "refs/heads/" + pr["headRefName"], commit)
    log(args=args, kind="update-branch")
    sys.exit(0)
if args[:1] == ["api"]:
    path = next((a for a in args[1:] if a.startswith("repos/")), "")
    if "-X" in args or "--method" in args:
        method = opt("-X") or opt("--method")
        branch = path.split("/git/refs/heads/", 1)[-1]
        log(args=args, kind="api-" + method.lower(), path=path)
        if method.upper() == "DELETE":
            if st.get("delete_fail"):
                fail(st["delete_fail"])
            if bgit("rev-parse", "--verify", "-q", "refs/heads/" + branch)[0] != 0:
                fail("Reference does not exist (HTTP 422)")
            bgit("update-ref", "-d", "refs/heads/" + branch)
            sys.exit(0)
    if "/compare/" in path:
        base, _, tip = path.split("/compare/", 1)[1].partition("...")
        rc, n, _ = bgit("rev-list", "--count", tip + ".." + base)
        if rc != 0:
            fail("Not Found (HTTP 404)")
        log(args=args, kind="compare")
        print(n)
        sys.exit(0)
    print("tester")
    sys.exit(0)
if cmd == ["pr", "merge"]:
    h = head()
    match = opt("--match-head-commit")
    log(args=args, kind="merge-attempt", head=h, match=match, delete_branch="--delete-branch" in args)
    if st.get("merge_fail"):
        fail(st["merge_fail"])
    if pr["state"] != "OPEN":
        fail("Pull request is not open")
    if pr["isDraft"]:
        fail("Pull request is still a draft")
    if match and match != h:
        fail("Head branch was modified. Review and try the merge again.")
    if mergeable() == "CONFLICTING":
        fail("Pull request is not mergeable: the merge commit cannot be cleanly created")
    b = base_tip()
    rc, tree, err = bgit("merge-tree", "--write-tree", b, h)
    rc, commit, err = bgit("commit-tree", tree.splitlines()[0], "-p", b, "-m", "squash of the PR (#7)")
    bgit("update-ref", "refs/heads/" + pr["baseRefName"], commit)
    pr["state"] = "MERGED"
    pr["mergeCommit"] = {"oid": commit}
    save()
    log(args=args, kind="merged", head=h, sha=commit)
    if "--delete-branch" in args:
        bgit("update-ref", "-d", "refs/heads/" + pr["headRefName"])
        r = subprocess.run(["git", "switch", "-q", pr["baseRefName"]], capture_output=True, text=True)
        if r.returncode != 0:
            fail("failed to run git: " + r.stderr.strip())
        subprocess.run(["git", "branch", "-D", "-q", pr["headRefName"]], capture_output=True, text=True)
    sys.exit(0)
log(args=args, kind="unexpected")
fail("the gh stub does not know: " + " ".join(args))
'''

DEVBOX = """#!/bin/sh
echo "$* title=$PR_TITLE" >> "$DEVBOX_LOG"
exit ${DEVBOX_RC:-0}
"""


def git(repo, *args, check=True):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout.strip()


def spec_md(number: int) -> str:
    """The fixture spec of test_spec.py as spec <number> (any number of 3 digits), for rows of the backlog index."""
    text = SPEC.format(status="approved", questions="None.")
    return (text.replace("007-price-alerts", f"{number}-more-{number}").replace("AC-007", f"AC-{number}")
            .replace("# 007", f"# {number}").replace("Price alerts", f"Spec {number}"))


def add_spec(root: Path, number: int) -> None:
    d = root / "docs" / "specs" / f"{number}-more-{number}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(spec_md(number))


class World:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.dir = tmp_path / "gh-world"
        self.dir.mkdir()
        self.bare = tmp_path / "origin.git"
        self.repo = tmp_path / "shop-api"
        self.other = tmp_path / "other"
        for var, value in (("GIT_AUTHOR_NAME", "Tester"), ("GIT_AUTHOR_EMAIL", "tester@example.test"),
                           ("GIT_COMMITTER_NAME", "Tester"), ("GIT_COMMITTER_EMAIL", "tester@example.test")):
            monkeypatch.setenv(var, value)
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        (tmp_path / "gitconfig").write_text("")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        self._build_repo()
        git(self.repo, "checkout", "-q", "-b", BRANCH)
        (self.repo / "work.txt").write_text("the feature\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "feat(alerts): the feature")
        git(self.repo, "push", "-q", "-u", "origin", BRANCH)
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.other)], check=True)
        self.pre = git(self.repo, "rev-parse", "HEAD")
        self.start_head = self.pre
        self.state = {"bare": str(self.bare), "slug": SLUG, "checks_calls": 0, "polls": {}, "rids": {}, "last_bucket": {},
                      "checks": {"default": ["pass"]}, "blind_until_checks": 0, "blind_skip": 0, "head_reads": 0, "merge_fail": None, "delete_fail": None,
                      "pr": {"url": PR_URL, "state": "OPEN", "headRefName": BRANCH, "baseRefName": "main", "isDraft": False,
                             "title": "feat(alerts): price alerts", "body": "## Summary\n", "labels": [], "mergeCommit": None}}
        self.save()
        self.hooks: list = []
        self.main_moves = 0
        self._install()
        st = ship.start(self.repo, "7", True)
        st["pr"], st["phase"] = PR_URL, "land"
        ship.save_state(self.repo, st)

    # ---- the repository
    def _build_repo(self) -> None:
        r = self.repo
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        git(r, "config", "user.name", "Tester")
        git(r, "config", "user.email", "tester@example.test")
        (r / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-go\nproject_name: shop-api\n")
        make(r, status="approved")
        (r / "f.txt").write_text("one\ntwo\nthree\n")
        (r / "docs").mkdir(exist_ok=True)
        (r / "docs" / "backlog.md").write_text(f"{HEAD_TEXT}{spec.START}\n{spec.END}\n{TAIL_TEXT}")
        spec.write_index(r)
        git(r, "add", "-A")
        git(r, "commit", "-qm", "init")
        git(r, "remote", "add", "origin", "https://github.com/acme/shop-api.git")
        git(r, "config", f"url.{self.bare}.insteadOf", "https://github.com/acme/shop-api.git")
        git(r, "push", "-q", "-u", "origin", "main")

    def local_commit(self, name="local.txt", text="local\n", msg="wip: local work") -> str:
        (self.repo / name).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", msg)
        return git(self.repo, "rev-parse", "HEAD")

    def bare_git(self, *args) -> str:
        return git(self.bare, *args)

    def pr_head(self) -> str:
        return self.bare_git("rev-parse", f"refs/heads/{BRANCH}")

    def main_tip(self) -> str:
        return self.bare_git("rev-parse", "refs/heads/main")

    def push_pr_commit(self) -> str:
        """Someone pushes one more commit to the PR branch (the head moves)."""
        head = self.pr_head()
        tree = self.bare_git("rev-parse", f"{head}^{{tree}}")
        commit = self.bare_git("commit-tree", tree, "-p", head, "-m", "a push while the land runs")
        self.bare_git("update-ref", f"refs/heads/{BRANCH}", commit)
        return commit

    def other_commit(self, files: dict[str, str], msg="a change on main") -> None:
        git(self.other, "config", "user.name", "Other")
        git(self.other, "config", "user.email", "other@example.test")
        git(self.other, "checkout", "-q", "main")
        git(self.other, "pull", "-q", "--ff-only", "origin", "main")
        for name, text in files.items():
            p = self.other / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git(self.other, "add", "-A")
        git(self.other, "commit", "-qm", msg)
        git(self.other, "push", "-q", "origin", "main")

    def other_adds_spec(self, number: int) -> None:
        """A person merges a PR that adds spec <number> and its row of the backlog index to main."""
        git(self.other, "pull", "-q", "--ff-only", "origin", "main")
        add_spec(self.other, number)
        spec.write_index(self.other)
        self.other_commit({}, f"docs: spec {number}")

    def feature_adds_spec(self, number: int) -> None:
        """The feature branch adds spec <number> and regenerates the index (committed, pushed: the PR head)."""
        add_spec(self.repo, number)
        spec.write_index(self.repo)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", f"docs: spec {number}")
        git(self.repo, "push", "-q", "origin", BRANCH)

    # ---- the gh stub
    def save(self) -> None:
        (self.dir / "state.json").write_text(json.dumps(self.state))

    def configure(self, **changes) -> None:
        cur = json.loads((self.dir / "state.json").read_text())
        for key, value in changes.items():
            if key == "pr":
                cur["pr"].update(value)
            else:
                cur[key] = value
        self.state = cur
        self.save()

    def _install(self) -> None:
        stub = self.dir / "bin" / "gh"
        stub.parent.mkdir()
        stub.write_text(STUB % {"py": sys.executable})
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        devbox = stub.parent / "devbox"
        devbox.write_text(DEVBOX)
        devbox.chmod(devbox.stat().st_mode | stat.S_IEXEC)
        self.devbox_log = self.dir / "devbox.log"
        self.mp.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ['PATH']}")
        self.mp.setenv("FAKE171", str(self.dir))
        self.mp.setenv("DEVBOX_LOG", str(self.devbox_log))
        self.mp.delenv("DEVBOX_RC", raising=False)
        self.mp.setenv("XDG_CACHE_HOME", str(self.tmp / "cache"))
        clock = {"t": 1000.0}
        self.clock = clock
        for mod in (ship,):
            self.mp.setattr(mod, "now", lambda: clock["t"])
            self.mp.setattr(mod, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
        import merge_lock
        self.mp.setattr(merge_lock, "sleep", lambda s: None)
        real = ship.gh

        def wrapped(args, *, cwd, check=True):
            answer = real(args, cwd=cwd, check=check)
            for hook in list(self.hooks):
                if hook["match"](args):
                    hook["seen"] += 1
                    if hook["seen"] == hook["nth"] or (hook["repeat"] and hook["seen"] > hook["nth"]):
                        hook["fn"]()
            return answer
        self.mp.setattr(ship, "gh", wrapped)

    def hook(self, match, fn, nth=1, repeat=False) -> None:
        """Run `fn()` right after the `nth` call of `ship.gh` for which `match(args)` is true (and each later one with `repeat`)."""
        self.hooks.append({"match": match, "fn": fn, "nth": nth, "seen": 0, "repeat": repeat})

    def on_new_head_checks(self, fn, times) -> None:
        """Run `fn()` after the first `gh pr checks` answer for each PR head that is not the first one seen, `times` times at most:
        a person merges into main while the checks of a pushed head run."""
        state = {"last": None, "n": 0}

        def match(args):
            if args[:2] != ["pr", "checks"] or state["n"] >= times:
                return False
            sha = self.events("checks")[-1]["sha"]
            if sha == state["last"]:
                return False
            first = state["last"] is None
            state["last"] = sha
            if first:
                return False
            state["n"] += 1
            return True
        self.hook(match, fn, repeat=True)

    def after_checks(self, fn, nth=1) -> None:
        self.hook(lambda a: a[:2] == ["pr", "checks"], fn, nth)

    def after_compare(self, fn, nth=1) -> None:
        self.hook(lambda a: a[:1] == ["api"] and "/compare/" in " ".join(a), fn, nth)

    def calls(self) -> list[dict]:
        f = self.dir / "calls.log"
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def events(self, kind: str) -> list[dict]:
        return [c for c in self.calls() if c.get("kind") == kind]

    def devbox_runs(self) -> list[str]:
        return self.devbox_log.read_text().splitlines() if self.devbox_log.is_file() else []

    def add_ci_script(self) -> None:
        """devbox.json with a `ci` script, so `ship.run_ci` runs the fake `devbox` (it logs and exits $DEVBOX_RC)."""
        (self.repo / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "true"}}}))

    # ---- one land, by either entry
    def land_argv(self, entry: str) -> list[str]:
        if entry == "ship":
            return ["component", "ship", "--repo", str(self.repo), "land", "--timeout", "900", "--interval", "1"]
        return ["pr", "wait", PR_URL, "--merge", "--repo", str(self.repo), "--timeout", "900", "--interval", "1"]

    def land(self, entry: str) -> int:
        import cplat
        return cplat.main(self.land_argv(entry))


def make_world(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


__all__ = ["World", "make_world", "git", "BRANCH", "PR_URL"]
