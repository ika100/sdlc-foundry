"""Spec 129 test world: a platform checkout with a bare local origin (git runs for real), a scripted `gh` behind `ship.gh`,
a scripted release-check/validate behind `platrelease_state.run_check`, a clock behind `ship.now/sleep`.

The seams are the ones of design.md, "Test seams (tests run offline)". The command is driven through `cplat.main`, so
the registration `cplat platform release` is part of what the tests exercise."""
import datetime
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import core  # noqa: F401
import cplat
import pr as prmod
import ship

DAY = datetime.date(2026, 6, 15)
E2E = "e2e upgrade (previous release → candidate)"
SLUG = "acme/shop"
NOTES = "**A feature.** Users notice it (#400).\n\n- a bullet"
HEAD = "# CHANGELOG\n\nAll notable changes.\n\n"
OLD = "## [5.4.0] — 2026-05-01\n\nOld notes of 5.4.0.\n"
CHANGELOG = HEAD + "## [Unreleased]\n\n" + NOTES + "\n\n" + OLD
USER = "Rel Easer"
EMAIL = "rel@example.com"


def moved_changelog(version: str) -> str:
    return HEAD + f"## [Unreleased]\n\n## [{version}] - {DAY.isoformat()}\n\n" + NOTES + "\n\n" + OLD


def chk(name: str, bucket: str, run: int = 42) -> dict:
    state = {"pass": "SUCCESS", "fail": "FAILURE", "pending": "IN_PROGRESS", "cancel": "CANCELLED"}[bucket]
    return {"name": name, "state": state, "bucket": bucket, "link": f"https://github.com/{SLUG}/actions/runs/{run}/job/1"}


def run_entry(rid: int, status: str = "completed", conclusion: str | None = "success", branch: str | None = None) -> dict:
    d = {"databaseId": rid, "status": status, "conclusion": conclusion, "url": f"https://github.com/{SLUG}/actions/runs/{rid}"}
    if branch is not None:
        d["headBranch"] = branch
    return d


@dataclass
class Result:
    rc: int
    out: str
    err: str
    said: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.out + "\n" + self.err + "\n" + "\n".join(self.said)


class Gh:
    def __init__(self, w):
        self.w, self.calls = w, []

    def writes(self) -> list:
        return [c for c in self.calls if c[:2] in (["pr", "create"], ["release", "create"], ["run", "rerun"])]

    def __call__(self, args, *, cwd, check=True):
        w, a = self.w, list(args)
        self.calls.append(a)
        if a[:2] == ["pr", "list"]:
            return json.dumps(w.prs)
        if a[:2] == ["pr", "create"]:
            w.created.append(a)
            branch = a[a.index("--head") + 1]
            w.head = w.git("rev-parse", f"origin/{branch}").strip()
            w.prs.append({"number": 7, "url": w.pr_url, "title": a[a.index("--title") + 1], "headRefName": branch, "headRefOid": w.head})
            return w.pr_url + "\n"
        if a[:2] == ["pr", "view"]:
            if "mergeCommit" in a:
                return (w.merge_sha or "") + "\n"
            if "headRefOid" in a:
                return json.dumps({"headRefOid": w.head})
            if "mergeable" in a:
                return json.dumps({"mergeable": "MERGEABLE"})
            return json.dumps({"state": "OPEN", "url": a[2]})
        if a[:2] == ["pr", "checks"]:
            return json.dumps(w.check_seq.pop(0) if len(w.check_seq) > 1 else w.check_seq[0])
        if a[:2] == ["run", "list"]:
            if "--workflow" in a:
                seq = {"e2e-upgrade.yml": w.e2e_seq, "release-guard.yml": w.guard_seq}[a[a.index("--workflow") + 1]]
                return json.dumps(seq.pop(0) if len(seq) > 1 else seq[0])
            return "[]"
        if a[:2] == ["run", "view"]:
            rid = a[2]
            if "headSha" in a:
                return json.dumps({"headSha": w.head})
            if "workflowDatabaseId" in a:
                return json.dumps({"workflowDatabaseId": int(w.workflow.get(rid, rid))})
            if "status,conclusion" in a:
                return json.dumps(w.view(rid))
            if "--log-failed" in a:
                return ""
            return w.view(rid).get("status", "") + "\n"
        if a[:2] == ["release", "view"]:
            return w.release_url or ""
        if a[:2] == ["release", "create"]:
            w.release_notes = Path(a[a.index("--notes-file") + 1]).read_text()
            w.release_url = f"https://github.com/{SLUG}/releases/tag/{a[2]}"
            return w.release_url + "\n"
        raise AssertionError(f"unscripted gh call: {a}")


class World:
    def __init__(self, tmp: Path, capsys):
        self.tmp, self.capsys = tmp, capsys
        self.origin, self.repo, self.other = tmp / "origin.git", tmp / "shop", tmp / "other"
        self.pr_url = f"https://github.com/{SLUG}/pull/7"
        self.prs, self.created, self.merges, self.said = [], [], [], []
        self.head, self.merge_sha = "a" * 40, None
        self.check_seq = [[chk("quality", "pass"), chk(E2E, "pass", 43)]]
        self.e2e_seq = [[run_entry(100)]]
        self.guard_seq = [[run_entry(200, branch="v5.5.0")]]
        self.views, self.workflow = {}, {}
        self.release_url, self.release_notes = None, None
        self.results = {}
        self.check_calls = []
        self.clock = {"t": 0.0}
        self.gh = Gh(self)
        self._build()

    # ---- git ----
    def git(self, *a, cwd=None, check=True) -> str:
        p = subprocess.run(["git", *a], cwd=cwd or self.repo, capture_output=True, text=True)
        if check and p.returncode != 0:
            raise AssertionError(f"git {' '.join(a)}: {p.stderr}")
        return p.stdout

    def _identity(self, d: Path) -> None:
        for k, v in (("user.name", USER), ("user.email", EMAIL), ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
            self.git("config", k, v, cwd=d)

    def _build(self) -> None:
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.tmp)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.tmp)
        self._identity(self.repo)
        files = {
            "docs/CHANGELOG.md": CHANGELOG,
            "README.md": "readme\n",
            ".claude-plugin/marketplace.json": json.dumps({"plugins": [{"name": "alpha", "version": "1.0.0"}]}, indent=2) + "\n",
            "plugins/alpha/.claude-plugin/plugin.json": json.dumps({"name": "alpha", "version": "1.0.0"}, indent=2) + "\n",
        }
        for name, text in files.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "chore: init")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("tag", "-a", "v5.4.0", "-m", "v5.4.0")
        self.git("push", "-q", "origin", "main")
        self.git("push", "-q", "origin", "refs/tags/v5.4.0")
        self.git("fetch", "-q", "origin")
        self.git("branch", "-q", "--set-upstream-to=origin/main", "main")
        self.t540 = self.git("rev-parse", "v5.4.0^{commit}").strip()
        self.git("clone", "-q", str(self.origin), str(self.other), cwd=self.tmp)
        self._identity(self.other)

    # ---- states of a release in flight ----
    def prepare_branch(self, version="5.5.0") -> str:
        self.git("switch", "-q", "-c", f"release/{version}", "main")
        (self.repo / "docs/CHANGELOG.md").write_text(moved_changelog(version))
        self.git("add", "docs/CHANGELOG.md")
        self.git("commit", "-q", "-s", "-m", f"chore: release {version}")
        self.git("push", "-q", "-u", "origin", f"release/{version}")
        sha = self.git("rev-parse", "HEAD").strip()
        self.git("switch", "-q", "main")
        return sha

    def open_pr(self, version="5.5.0") -> None:
        self.head = self.git("rev-parse", f"origin/release/{version}").strip()
        self.prs.append({"number": 7, "url": self.pr_url, "title": f"chore: release {version}",
                         "headRefName": f"release/{version}", "headRefOid": self.head})

    def squash(self, version="5.5.0", number=7) -> str:
        o = self.other
        self.git("fetch", "-q", "origin", cwd=o)
        self.git("checkout", "-q", "main", cwd=o)
        self.git("merge", "-q", "--ff-only", "origin/main", cwd=o)
        self.git("merge", "-q", "--squash", f"origin/release/{version}", cwd=o)
        self.git("commit", "-q", "-s", "-m", f"chore: release {version} (#{number})", cwd=o)
        self.git("push", "-q", "origin", "main", cwd=o)
        self.git("push", "-q", "origin", "--delete", f"release/{version}", cwd=o)
        self.merge_sha = self.git("rev-parse", "HEAD", cwd=o).strip()
        self.git("fetch", "-q", "origin")
        self.prs = []
        return self.merge_sha

    def tag(self, version="5.5.0", sha=None, push=True, local=True) -> str:
        sha = sha or self.merge_sha
        self.git("tag", "-a", f"v{version}", "-m", f"v{version}", sha)
        if push:
            self.git("push", "-q", "origin", f"refs/tags/v{version}")
        if not local:
            self.git("tag", "-d", f"v{version}")
        return sha

    def in_state(self, name: str, version="5.5.0") -> None:
        self._in_state(name, version)
        self.git("fetch", "-q", "origin", "--tags")

    def _in_state(self, name: str, version) -> None:
        if name == "idle":
            return
        self.prepare_branch(version)
        if name == "branch":
            return
        if name == "pr-open":
            self.open_pr(version)
            return
        self.squash(version)
        self.git("branch", "-q", "-D", f"release/{version}")
        if name == "merged":
            return
        self.tag(version)
        if name == "tagged":
            return
        assert name == "released", name
        self.release_url = f"https://github.com/{SLUG}/releases/tag/v{version}"

    # ---- observation ----
    def snapshot(self) -> dict:
        return {
            "refs": self.git("for-each-ref"), "status": self.git("status", "--porcelain"), "head": self.git("rev-parse", "HEAD"),
            "remote": self.git("ls-remote", "origin"), "changelog": (self.repo / "docs/CHANGELOG.md").read_text(),
            "gh_writes": len(self.gh.writes()), "merges": len(self.merges),
        }

    def origin_tags(self) -> dict:
        direct, peeled = {}, {}
        for ln in self.git("ls-remote", "--tags", "origin").splitlines():
            sha, ref = ln.split("\t")
            name = ref.removeprefix("refs/tags/")
            if name.endswith("^{}"):
                peeled[name[:-3]] = sha
            else:
                direct[name] = sha
        return {n: peeled.get(n, s) for n, s in direct.items()}

    def ahead(self, ref: str) -> int:
        return int(self.git("rev-list", "--count", f"origin/main..{ref}").strip())

    def view(self, rid: str) -> dict:
        if rid in self.views:
            seq = self.views[rid]
            return seq.pop(0) if len(seq) > 1 else seq[0]
        for seq in (self.e2e_seq, self.guard_seq):
            for entries in reversed(seq):
                for r in entries:
                    if str(r["databaseId"]) == rid:
                        return {"status": r["status"], "conclusion": r["conclusion"]}
        return {"status": "completed", "conclusion": "success"}

    def check_cmd(self, key: str) -> list:
        return [c for _, c in self.check_calls if key in c]

    # ---- the seams ----
    def run_check(self, repo, cmd):
        self.check_calls.append((Path(repo), list(cmd)))
        for key in ("needs-major", "rows", "gate", "validate"):
            if key in cmd:
                return self.results.get(key, (0, "OK" if key != "needs-major" else ""))
        raise AssertionError(f"unscripted check: {cmd}")

    def fake_pr_run(self, cmd, **kw):
        if cmd[:3] == ["gh", "pr", "merge"]:
            self.merges.append(list(cmd))
            self.squash()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    def run(self, *argv) -> Result:
        self.said.clear()
        try:
            rc = cplat.main(["platform", "release", "--repo", str(self.repo), "--interval", "20", *argv])
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
        cap = self.capsys.readouterr()
        return Result(rc, cap.out, cap.err, list(self.said))


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    import platrelease  # noqa: F401  (the command under test: missing until built)
    import platrelease_publish  # noqa: F401
    import platrelease_state
    world = World(tmp_path, capsys)
    monkeypatch.setattr(ship, "gh", world.gh)
    monkeypatch.setattr(ship, "now", lambda: world.clock["t"])
    monkeypatch.setattr(ship, "sleep", lambda s: world.clock.__setitem__("t", world.clock["t"] + s))
    monkeypatch.setattr(ship, "say", world.said.append)
    monkeypatch.setattr(ship, "service_slug", lambda repo: SLUG)
    monkeypatch.setattr(platrelease_state, "run_check", world.run_check)
    monkeypatch.setattr(platrelease_state, "today", lambda: DAY)
    monkeypatch.setattr(prmod, "run", world.fake_pr_run)
    return world

