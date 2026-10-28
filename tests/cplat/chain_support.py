"""Shared helpers of the spec 109 acceptance tests (not a test module, never collected).

Builds a component repo with real git history and tags, an optional gitops-app checkout (system.yaml + overlay pins, through
`model_fixtures.write_app`), and a fake of the `gh` seam of `spec_chain_remote` (design: "Remote module API"). The new modules
(`spec_chain`, `spec_chain_remote`) are imported inside the tests, never at module level, so a missing module fails the test and
collection still succeeds.

The fixture repos use the scratch spec number 901 (and 200+), so no literal criterion id of a real spec of this repo that is not
active appears in these files (the platform's own `spec ci` would call such a file an orphan)."""
import base64
import importlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import cplat
from model_fixtures import git, write_app

SLUG = "acme/shop-api"
APP_SLUG = "acme/shop-gitops"
SPEC_ID = "901-demo-chain"
BRANCH = f"feature/{SPEC_ID}"
LINKS = ["issue", "spec", "criterion", "tests", "verdict", "pr", "release", "env dev", "env staging", "env prod"]
ENVS = ("dev", "staging", "prod")

CRITERIA = """- **AC-901.1** Given a, when b, then c.
- **AC-901.2** Given d, when e, then f.
- **AC-901.3** Given g, when h, then i.
- ~~**AC-901.4**~~ withdrawn: out of scope.
"""

SPEC_TEXT = """---
spec_id: {spec_id}
title: Demo chain
status: {status}
priority: P1
shape: {shape}
{tracks}---

# Demo chain

## Problem

Something.

## Acceptance criteria

{criteria}
## Non-goals

- Nothing

## Open questions

None.

## Changelog

- 2026-10-01 created
{changelog}"""

TEST_DEMO = """def test_first():  # AC-901.1
    ...


def test_second_ac_901_2():  # AC-901.2
    ...
"""


def spec_text(*, spec_id=SPEC_ID, status="done", shape="service-python", tracks=(164,), criteria=CRITERIA, changelog="") -> str:
    t = f"tracks: [{', '.join(str(n) for n in tracks)}]\n" if tracks else ""
    return SPEC_TEXT.format(spec_id=spec_id, status=status, shape=shape, tracks=t, criteria=criteria, changelog=changelog)


def verification_text(rows, *, commit, result="pass", cols=5, header=True) -> str:
    """`rows` is [(criterion cell, verdict cell)]."""
    if cols == 3:
        head = "| Criterion | Verdict | Evidence |\n|---|---|---|\n"
        body = "".join(f"| {c} | {v} | `tests/test_demo.py` |\n" for c, v in rows)
    else:
        head = "| Criterion | Verdict | Tests | Implementation | Notes |\n|---|---|---|---|---|\n"
        body = "".join(f"| {c} | {v} | `tests/test_demo.py` | `src/feature.py` | note |\n" for c, v in rows)
    return f"# Verification — 901\n\n**Result:** {result}\n**Commit:** {commit} · **Base:** 0000000\n\n{head if header else ''}{body}"


@dataclass
class World:
    root: Path
    parent: Path
    shas: dict = field(default_factory=dict)

    @property
    def spec_dir(self) -> Path:
        return self.root / "docs" / "specs" / SPEC_ID

    def git(self, *args: str) -> str:
        return git(self.root, *args)

    def sha(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref).strip()

    def commit(self, msg: str, tag: str | None = None) -> str:
        self.git("add", "-A")
        self.git("commit", "-qm", msg)
        if tag:
            self.git("tag", tag)
        return self.sha()

    def short_of_last_commit_touching(self, rel: str) -> str:
        return self.git("log", "-1", "--format=%h", "--", rel).strip()


def build_world(tmp_path: Path, *, status="done", tracks=(164,), shape="service-python", linked=True, verification="pass",
                rows=None, cols=5, changelog="", origin=f"https://github.com/{SLUG}.git", tags=None, orphan_tests=True,
                criteria=CRITERIA, name="shop-api", extra_specs=0) -> World:
    """A component repo: c0 (README, answers, links) -> c1 (spec + tests) -> verification.md -> m (the 'merge') -> later.
    `tags` maps tag name -> one of c0, c1, m, later, later2 (default v1.0.0@c0, v1.1.0@m, v1.2.0@later)."""
    parent = tmp_path / "work"
    root = parent / name
    root.mkdir(parents=True)
    w = World(root, parent)
    git(root, "init", "-q", "-b", "main")
    if origin:
        git(root, "remote", "add", "origin", origin)
    (root / "README.md").write_text("demo\n")
    (root / ".copier-answers.yml").write_text(f"_src_path: templates/{shape}\n")
    if linked:
        (root / ".platform-app.yml").write_text(f"gitops_apps:\n  - {APP_SLUG}\n")
    w.shas["c0"] = w.commit("c0")
    (w.spec_dir).mkdir(parents=True)
    (w.spec_dir / "spec.md").write_text(spec_text(status=status, tracks=tracks, shape=shape, criteria=criteria, changelog=changelog))
    (root / "tests").mkdir()
    (root / "tests" / "test_demo.py").write_text(TEST_DEMO)
    if orphan_tests:
        (root / "tests" / "test_orphans.py").write_text(
            "def test_old():  # AC-901.4\n    ...\n\n\ndef test_typo():  # AC-901.9\n    ...\n\n\ndef test_other_spec():  # AC-777.1\n    ...\n")
    for i in range(extra_specs):
        sid = f"{200 + i}-extra-{i}"
        d = root / "docs" / "specs" / sid
        d.mkdir(parents=True)
        (d / "spec.md").write_text(spec_text(spec_id=sid, status="done", shape=shape, tracks=(),
                                             criteria=f"- **AC-{200 + i}.1** Given a, when b, then c.\n"))
        (root / "tests" / f"test_extra_{i}.py").write_text(f"def test_x():  # AC-{200 + i}.1\n    ...\n")
    w.shas["c1"] = w.commit("c1: spec and tests")
    if verification:
        r = rows if rows is not None else [("AC-901.1", "met"), ("AC-901.2", "met"), ("AC-901.3", "met")]
        (w.spec_dir / "verification.md").write_text(verification_text(r, commit=w.shas["c1"][:7], result=verification, cols=cols))
        w.shas["v"] = w.commit("verification")
    (root / "src").mkdir()
    (root / "src" / "feature.py").write_text("X = 1\n")
    w.shas["m"] = w.commit("feat: demo (#301)")
    (root / "src" / "more.py").write_text("Y = 1\n")
    w.shas["later"] = w.commit("feat: more")
    (root / "src" / "more2.py").write_text("Z = 1\n")
    w.shas["later2"] = w.commit("feat: even more")
    for tag, ref in (tags if tags is not None else {"v1.0.0": "c0", "v1.1.0": "m", "v1.2.0": "later"}).items():
        git(root, "tag", tag, w.shas[ref])
    return w


def build_gitops(w: World, pins: dict, *, environments=ENVS, component="shop-api", repo=SLUG, name="shop-gitops",
                 origin=f"https://github.com/{APP_SLUG}.git") -> Path:
    """A gitops-app checkout beside the component repo (the clone layout the platform uses): applications/shop/system.yaml and
    overlays/<env>/<component>/kustomization.yaml pins. `pins` maps env -> tag."""
    gdir = w.parent / name
    gdir.mkdir(parents=True)
    services = [{"name": component, "repo": repo, "image": f"ghcr.io/acme/{component}", "shape": "service-python", "port": 8080,
                 "environments": list(environments)}]
    write_app(gdir, services, pins={(env, component): tag for env, tag in pins.items()})
    git(gdir, "init", "-q", "-b", "main")
    git(gdir, "remote", "add", "origin", origin)
    git(gdir, "add", "-A")
    git(gdir, "commit", "-qm", "init")
    return gdir


def pr_entry(number: int, merge: str, merged_at="2026-10-30T10:00:00Z") -> dict:
    return {"number": number, "url": f"https://github.com/{SLUG}/pull/{number}", "mergeCommit": {"oid": merge}, "mergedAt": merged_at}


WRITE_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}


class FakeGh:
    """Replaces the `gh` and `which` seams of spec_chain_remote. Answers like gh does (state OPEN/CLOSED, contents API of a
    gitops-app checkout) and records every call, so a test can prove which calls were made and that they were all reads."""

    def __init__(self, *, installed=True, authed=True, reachable=True, probe_timeout=False, issues=None, prs=None, repos=None):
        self.installed, self.authed, self.reachable, self.probe_timeout = installed, authed, reachable, probe_timeout
        self.issues = {int(k): v for k, v in (issues or {}).items()}   # number -> "OPEN" / "CLOSED"
        self.prs = prs or {}                                           # head branch -> list of gh pr entries
        self.repos = repos or {}                                       # slug -> checkout dir served by the contents API
        self.calls: list[list[str]] = []

    def install(self, monkeypatch):
        rm = importlib.import_module("spec_chain_remote")
        monkeypatch.setattr(rm, "gh", self.gh)
        monkeypatch.setattr(rm, "which", self.which)
        return self

    def which(self, tool):
        if tool == "gh":
            return "/usr/bin/gh" if self.installed else None
        return shutil.which(tool)

    # -- the seam
    def gh(self, args, *, cwd, timeout=10):
        args = [str(a) for a in args]
        self.calls.append(args)
        if args[:2] == ["auth", "token"]:
            return (0, "ghp_fake\n", "") if self.authed else (1, "", "no oauth token found for github.com")
        if "rate_limit" in args:
            if self.probe_timeout:
                return 124, "", "timed out"
            if not self.reachable:
                return 1, "", "error connecting to api.github.com"
            if not self.authed:
                return 1, "", "gh: Bad credentials (HTTP 401)"
            return 0, '{"resources": {}}', ""
        if not self.reachable:
            return 1, "", "error connecting to api.github.com"
        if args[:2] == ["issue", "view"]:
            n = next(int(a) for a in args[2:] if a.isdigit())
            if n in self.issues:
                return 0, json.dumps({"number": n, "state": self.issues[n]}), ""
            return 1, "", "Could not resolve to an issue"
        if args[:2] == ["pr", "list"]:
            head = args[args.index("--head") + 1] if "--head" in args else None
            return 0, json.dumps(self.prs.get(head, [])), ""
        if args[0] == "api":
            return self._api(args)
        return 1, "", f"fake gh: unsupported call {args}"

    def _api(self, args):
        endpoint = next((a for i, a in enumerate(args[1:], 1) if not a.startswith("-") and args[i - 1] not in {"-H", "--header", "-q", "--jq"}), "")
        endpoint = endpoint.lstrip("/").split("?")[0]
        raw = any("raw" in a for a in args)
        m = re.match(r"repos/([^/]+/[^/]+)(?:/(contents|git/trees)(?:/(.*))?)?$", endpoint)
        if not m or m.group(1) not in self.repos:
            return 1, "", "gh: Not Found (HTTP 404)"
        base = Path(self.repos[m.group(1)])
        if m.group(2) is None:
            return 0, json.dumps({"default_branch": "main", "full_name": m.group(1)}), ""
        if m.group(2) == "git/trees":
            tree = [{"path": str(p.relative_to(base)), "type": "blob" if p.is_file() else "tree"}
                    for p in sorted(base.rglob("*")) if ".git" not in p.relative_to(base).parts]
            return 0, json.dumps({"tree": tree, "truncated": False}), ""
        target = base / (m.group(3) or "")
        if target.is_dir():
            return 0, json.dumps([{"name": p.name, "path": str(p.relative_to(base)), "type": "dir" if p.is_dir() else "file"}
                                  for p in sorted(target.iterdir()) if p.name != ".git"]), ""
        if target.is_file():
            if raw:
                return 0, target.read_text(), ""
            return 0, json.dumps({"type": "file", "encoding": "base64", "content": base64.b64encode(target.read_bytes()).decode()}), ""
        return 1, "", "gh: Not Found (HTTP 404)"

    # -- what the tests assert on
    def network_calls(self) -> list[list[str]]:
        """Every call except the local `gh auth token`."""
        return [c for c in self.calls if c[:2] != ["auth", "token"]]

    def only_reads(self) -> bool:
        for c in self.calls:
            if c[:2] in (["auth", "token"], ["issue", "view"], ["pr", "list"]):
                continue
            if c[0] == "api" and not (set(c) & WRITE_FLAGS):
                methods = [c[i + 1] for i, a in enumerate(c[:-1]) if a in {"-X", "--method"}]
                if all(m.upper() == "GET" for m in methods):
                    continue
            return False
        return True


# ---------------- running the verb ----------------

def run_cplat(capsys, root: Path, *args: str) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = cplat.main(["spec", "--repo", str(root), *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


def chain(capsys, root: Path, ref="901", *extra: str) -> tuple[int, dict]:
    rc, out, err = run_cplat(capsys, root, "trace", ref, "--chain", "--json", *extra)
    assert out.strip(), f"no output (rc {rc}): {err}"
    return rc, json.loads(out)


def chain_text(capsys, root: Path, ref="901") -> tuple[int, str, str]:
    return run_cplat(capsys, root, "trace", ref, "--chain")


def links(doc: dict, ac: str) -> dict:
    block = next(c for c in doc["criteria"] if c["id"] == ac)
    return {link["link"]: link for link in block["links"]}


def rendered(link: dict) -> str:
    return f"{link['state']}: {link['text']}"


def block_ids(doc: dict) -> list[str]:
    return [c["id"] for c in doc["criteria"]]
