"""Spec 096 test support: a fake GitHub for `cplat fleet update`.

Repos are real git repos: a local bare repo per slug is what `fleet.clone` clones and what the update pushes back into.
`fleet.gh` is replaced by `World.gh`, which answers exactly the argument lists of design.md ("gh calls"); any other call is
recorded in `World.unexpected` and fails with exit 1. `pr.wait` is replaced by `World.wait`. Nothing reaches GitHub.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import core
import pr as prmod
import update

LABEL = "platform-update: needs review"
TARGET = core.platform_version()                    # what `cplat fleet update` brings repos to (the installed version)
OLD = "4.3.0"
URL = "https://github.com/{slug}/pull/{n}"


def git(cwd, *a, check=True):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, text=True, capture_output=True,
                          check=check).stdout.strip()


@pytest.fixture()
def seed(tmp_path_factory, new_service):
    """(repo, baseline): two copies of the shared render of the current service-go template."""
    base = tmp_path_factory.mktemp("fleet-seed")
    for n in ("repo", "base"):
        new_service(["seed", "desc", "--type", "service", "--lang", "go", "--no-github", "--skip-tasks", "--dir", str(base / n), "--org", "acme"])
    return base / "repo" / "seed", base / "base" / "seed"


class World:
    def __init__(self, tmp_path, seed, monkeypatch, capsys):
        self.tmp, self.seed, self.mp, self.capsys = tmp_path, seed, monkeypatch, capsys
        self.repos: dict[str, dict] = {}
        self.login = "acme"
        self.calls: list[list[str]] = []
        self.unexpected: list[list[str]] = []
        self.log: list[tuple[str, str]] = []           # ("clone"|"create"|"wait", slug) in order
        self.inputs: list[tuple[list[str], str | None]] = []
        self.waits: list[tuple] = []
        self.wait_result = lambda slug, url: (True, [f"merged {url}"])
        self.mergeable: dict[str, list[str]] = {}      # slug -> successive answers (the last one repeats)
        self.clone_error: dict[str, str] = {}
        self.read_error: dict[tuple[str, str], str] = {}
        self.list_error: dict[str, str] = {}
        self.sleeps: list[float] = []
        self.mp.setattr(prmod, "wait", self.wait)
        self.mp.setattr(update, "render_baseline", lambda *a, **k: self.seed[1])
        # The README note depends on the platform checkout having the v<old> tag (a shallow CI clone has none),
        # so pin it: the follow-up order must not depend on how the platform was checked out.
        self.mp.setattr(update, "_readme_changed", lambda *a, **k: False)

    # ---- building the fleet ----
    def add(self, slug, version=OLD, *, platform=True, src=None, archived=False, fork=False, mutate=None, stamp=True,
            default="main"):
        bare = self.tmp / "remotes" / (slug.replace("/", "__") + ".git")
        work = self.tmp / "work" / slug.replace("/", "__")
        shutil.copytree(self.seed[0], work, ignore=shutil.ignore_patterns(".git"))
        if not stamp or not platform:
            (work / ".platform-version").unlink(missing_ok=True)
        else:
            (work / ".platform-version").write_text(f"platform: {version}\nshape: service-go\nref: main\n")
        if src:
            ans = work / ".copier-answers.yml"
            lines = [f"_src_path: {src}" if ln.startswith("_src_path:") else ln for ln in ans.read_text().splitlines()]
            ans.write_text("\n".join(lines) + "\n")
        if not platform:
            (work / ".copier-answers.yml").unlink(missing_ok=True)
        if mutate:
            mutate(work)
        subprocess.run(["git", "init", "-q", "--bare", "-b", default, str(bare)], check=True)
        git(work, "init", "-q", "-b", default)
        git(work, "add", "-A")
        git(work, "commit", "-qm", "init")
        git(work, "remote", "add", "origin", str(bare))
        git(work, "push", "-q", "origin", default)
        self.repos[slug] = {"bare": bare, "default": default, "archived": archived, "fork": fork, "prs": [], "n": 0,
                            "comments": {}, "labels": {}, "stamp": version}
        return bare

    def entry(self, slug):
        r = self.repos[slug]
        return {"nameWithOwner": slug, "isArchived": r["archived"], "isFork": r["fork"], "defaultBranchRef": {"name": r["default"]}}

    def branches(self, slug):
        out = git(self.repos[slug]["bare"], "branch", "--format=%(refname:short)")
        return [b for b in out.splitlines() if b]

    def prs(self, slug):
        return self.repos[slug]["prs"]

    def pr_for(self, slug):
        (p,) = self.repos[slug]["prs"]
        return p

    def comments(self, slug, p=None):
        p = p or self.pr_for(slug)
        return self.repos[slug]["comments"].get(p["url"], [])

    def calls_for(self, slug, *prefix):
        return [c for c in self.calls if slug in c and list(c[:len(prefix)]) == list(prefix)]

    def writes(self):
        """gh calls that change something on GitHub, plus every push to a bare repo is checked via branches()."""
        out = []
        for c in self.calls:
            if c[:2] in (["pr", "create"], ["pr", "edit"], ["pr", "comment"], ["pr", "merge"]) or c[:2] == ["label", "create"]:
                out.append(c)
        return out

    # ---- the seams ----
    def slug_of(self, args):
        for i, a in enumerate(args):
            if a == "-R":
                return args[i + 1]
        return None

    def gh(self, args, *, cwd=None, input=None, timeout=60.0):
        args = list(args)
        self.calls.append(args)
        self.inputs.append((args, input))
        a = args
        if a == ["api", "user", "-q", ".login"]:
            return (0, self.login + "\n", "") if self.login else (1, "", "not logged in")
        if a[:2] == ["repo", "list"]:
            assert a[3:] == ["--no-archived", "--source", "--json", "nameWithOwner,isArchived,isFork,defaultBranchRef", "--limit", "1000"], a
            if a[2] in self.list_error:
                return 1, "", self.list_error[a[2]]
            return 0, json.dumps([self.entry(s) for s in self.repos if s.split("/")[0] == a[2]]), ""
        if a[:2] == ["repo", "view"]:
            assert a[3:] == ["--json", "nameWithOwner,isArchived,isFork,defaultBranchRef"], a
            if a[2] not in self.repos:
                return 1, "", "GraphQL: Could not resolve to a Repository with the name '" + a[2] + "'."
            return 0, json.dumps(self.entry(a[2])), ""
        if a[0] == "api" and a[1].startswith("repos/") and "/contents/" in a[1]:
            assert a[2:] == ["-H", "Accept: application/vnd.github.raw"], a
            slug, path = a[1][len("repos/"):].split("/contents/", 1)
            if (slug, path) in self.read_error:
                return 1, "", self.read_error[(slug, path)]
            r = self.repos[slug]
            p = subprocess.run(["git", "show", f"{r['default']}:{path}"], cwd=r["bare"], text=True, capture_output=True)
            if p.returncode:
                return 1, "", "gh: Not Found (HTTP 404)"
            return 0, p.stdout, ""
        slug = self.slug_of(a)
        if a[:2] == ["pr", "list"]:
            assert a == ["pr", "list", "-R", slug, "--state", "open", "--json", "number,url,headRefName,labels", "--limit", "100"], a
            return 0, json.dumps(self.repos[slug]["prs"]), ""
        if a[:2] == ["pr", "create"]:
            assert a[:3] == ["pr", "create", "-R"] and a[4] == "--base" and a[6] == "--head" and a[8] == "--title" \
                and a[10:] == ["--body-file", "-"], a
            r = self.repos[slug]
            assert a[5] == r["default"], a
            r["n"] += 1
            p = {"number": r["n"], "url": URL.format(slug=slug, n=r["n"]), "headRefName": a[7], "labels": [], "title": a[9],
                 "body": input}
            r["prs"].append(p)
            self.log.append(("create", slug))
            return 0, "\n" + p["url"] + "\n", ""
        if a[:2] == ["pr", "edit"]:
            p = self.find(slug, a[2])
            if a[5:] == ["--add-label", LABEL]:
                if not any(lb["name"] == LABEL for lb in p["labels"]):
                    p["labels"].append({"name": LABEL})
                return 0, "", ""
            assert a[5] == "--title" and a[7:] == ["--body-file", "-"] and len(a) == 9, a      # never touches labels
            p["title"], p["body"] = a[6], input
            return 0, "", ""
        if a[:2] == ["pr", "view"]:
            p = self.find(slug, a[2])
            if a[5:] == ["--json", "mergeable"]:
                seq = self.mergeable.get(slug, ["MERGEABLE"])
                v = seq.pop(0) if len(seq) > 1 else seq[0]
                return 0, json.dumps({"mergeable": v}), ""
            if a[5:] == ["--json", "comments"]:
                return 0, json.dumps({"comments": [{"body": b} for b in self.repos[slug]["comments"].get(p["url"], [])]}), ""
        if a[:2] == ["label", "create"]:
            assert a == ["label", "create", LABEL, "-R", slug, "--color", "D93F0B", "--description",
                         "A platform fleet update needs a person (spec 096)"], a
            return 0, "", ""
        if a[:2] == ["pr", "comment"]:
            assert a[5:] == ["--body-file", "-"], a
            p = self.find(slug, a[2])
            self.repos[slug]["comments"].setdefault(p["url"], []).append(input)
            return 0, "", ""
        self.unexpected.append(a)
        return 1, "", "unexpected gh call"

    def find(self, slug, url):
        return next(p for p in self.repos[slug]["prs"] if p["url"] == url)

    def clone(self, slug, dest):
        self.log.append(("clone", slug))
        if slug in self.clone_error:
            raise core.PlatformError(f"clone of {slug} failed: {self.clone_error[slug]}")
        subprocess.run(["git", "clone", "-q", str(self.repos[slug]["bare"]), str(dest)], check=True)

    def wait(self, repo, url, merge, timeout, interval, queue_timeout, slug=None):
        slug = slug or next(s for s in self.repos if f"/{s}/" in url)
        self.log.append(("wait", slug))
        self.waits.append((Path(repo), url, merge, timeout, interval, queue_timeout, slug))
        return self.wait_result(slug, url)

    # ---- running ----
    def run(self, *argv):
        """`cplat fleet update <argv>` -> (exit code, stdout, stderr)."""
        import fleet
        self.mp.setattr(fleet, "gh", self.gh)
        self.mp.setattr(fleet, "clone", self.clone)
        self.mp.setattr(fleet, "sleep", self.sleeps.append)
        self.capsys.readouterr()
        try:
            rc = fleet.main(["update", *argv])
        except core.PlatformError as e:
            rc = 1
            print(f"ERROR: {e}", file=__import__("sys").stderr)
        cap = self.capsys.readouterr()
        assert not self.unexpected, self.unexpected
        return rc, cap.out, cap.err

    def json(self, *argv):
        rc, out, err = self.run("--json", *argv)
        return rc, json.loads(out), err


def row(doc, slug):
    return next(r for r in doc["repos"] if r["repo"] == slug)


@pytest.fixture()
def world(tmp_path, seed, monkeypatch, capsys):
    return World(tmp_path, seed, monkeypatch, capsys)
