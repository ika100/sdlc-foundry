"""Phase detection, version proposal and the state block of `cplat platform release` (spec 129).

Read-only: it fetches, reads git and GitHub and never writes. The progress of a release is derived from git and GitHub on
every run (release branch, PR, squash commit on origin/main, tag, GitHub release, release-guard run); nothing is stored."""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import core
import ship

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
RELEASE_SUBJECT = re.compile(r"^chore: release (\d+\.\d+\.\d+)(?: \(#\d+\))?$")
GUARD_YOUNG = 600     # seconds a tag may lack a release-guard run before that counts as "not checked"
LOG_WINDOW = 200

IDLE, BRANCH, PR_OPEN, MERGED, TAGGED, GUARDING, GUARD_RED = (
    "idle", "branch", "pr-open", "merged", "tagged", "guarding", "guard-red")

FIRST_STEP = {IDLE: 1, BRANCH: 2, PR_OPEN: 5, MERGED: 7, TAGGED: 11, GUARDING: 12, GUARD_RED: 13}


def run_check(repo: Path, cmd: list[str]) -> tuple[int, str]:
    """Run a repo script (release-check, devbox run validate) in `repo`; (returncode, stdout+stderr). Tests replace this."""
    try:
        p = subprocess.run(cmd, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return 127, f"`{cmd[0]}` is not installed or not on PATH"
    return p.returncode, p.stdout


def today() -> datetime.date:  # tests replace this
    return datetime.date.today()


def vkey(version: str) -> tuple[int, int, int]:
    m = SEMVER.match(version.removeprefix("v"))
    assert m, version
    return int(m[1]), int(m[2]), int(m[3])


@dataclass
class State:
    tag: str = ""                       # newest release tag, "v5.4.0"
    tag_sha: str = ""                   # its commit
    tags: dict[str, str] = field(default_factory=dict)   # every vX.Y.Z on origin -> commit
    merged_version: str | None = None   # M.version
    merged_sha: str | None = None       # M.sha
    merged_subject: str | None = None
    branch: str | None = None           # version of the release branch
    pr: dict | None = None
    release_url: str | None = None      # GitHub release of `version`
    guard: dict | None = None           # newest release-guard run of the tag
    notes: list[str] = field(default_factory=list)
    phase: str = IDLE
    version: str | None = None          # the release in flight (None in idle)


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return core.run(["git", *args], cwd=repo, check=check).stdout


def fetch(repo: Path) -> None:
    _git(repo, "fetch", "origin", "--tags")
    _git(repo, "fetch", "origin", "main")


def _origin_tags(repo: Path) -> dict[str, str]:
    direct: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for ln in _git(repo, "ls-remote", "--tags", "origin").splitlines():
        if "\t" not in ln:
            continue
        sha, ref = ln.split("\t", 1)
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name[:-3]] = sha
        else:
            direct[name] = sha
    return {n: peeled.get(n, s) for n, s in direct.items() if TAG.match(n)}


def _merged(repo: Path) -> tuple[str, str, str] | None:
    out = _git(repo, "log", "-n", str(LOG_WINDOW), "--format=%H%x09%s", "origin/main")
    for ln in out.splitlines():
        sha, _, subject = ln.partition("\t")
        m = RELEASE_SUBJECT.match(subject)
        if m:
            return m[1], sha, subject
    return None


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/release", "refs/remotes/origin/release")
    found = set()
    for ref in out.split():
        m = re.match(r"^refs/(?:heads|remotes/origin)/release/(\d+\.\d+\.\d+)$", ref)
        if m:
            found.add(m[1])
    return found


def _tag_age(repo: Path, tag: str) -> float | None:
    out = _git(repo, "for-each-ref", f"refs/tags/{tag}", "--format=%(taggerdate:unix)", check=False).strip()
    if not out.isdigit():
        return None
    return ship.now() - int(out)


def _guard_run(repo: Path, slug: str, tag: str) -> dict | None:
    out = ship.gh(["run", "list", "-R", slug, "--workflow", "release-guard.yml", "--event", "push", "--limit", "50",
                   "--json", "databaseId,headBranch,status,conclusion,url"], cwd=repo)
    runs = [r for r in json.loads(out or "[]") if r.get("headBranch") == tag]
    return max(runs, key=lambda r: r["databaseId"]) if runs else None


def detect(repo: Path) -> State:
    repo = Path(repo)
    tags = _origin_tags(repo)
    if not tags:
        raise core.PlatformError("no release tag vX.Y.Z on origin")
    newest = max(tags, key=lambda t: vkey(t))
    s = State(tag=newest, tag_sha=tags[newest], tags=tags)
    top = vkey(newest)
    m = _merged(repo)
    if m:
        s.merged_version, s.merged_sha, s.merged_subject = m
    mv = s.merged_version

    versions = sorted((v for v in _branches(repo) if vkey(v) > top and v != mv), key=vkey)
    if len(versions) > 1:
        raise core.PlatformError("several release branches: " + ", ".join(f"release/{v}" for v in versions))
    prs = json.loads(ship.gh(["pr", "list", "--state", "open", "--base", "main", "--json",
                              "number,url,title,headRefName,headRefOid"], cwd=repo) or "[]")
    prs = [p for p in prs if (mm := re.match(r"^release/(\d+\.\d+\.\d+)$", p.get("headRefName", ""))) and vkey(mm[1]) > top]
    if len(prs) > 1:
        raise core.PlatformError("several release PRs: " + ", ".join(p["url"] for p in prs))
    if prs:
        s.pr = prs[0]
    pr_version = prs[0]["headRefName"].removeprefix("release/") if prs else None
    s.branch = versions[0] if versions else None

    merged_open = mv is not None and vkey(mv) > top
    if pr_version and merged_open:
        raise core.PlatformError(f"two releases in flight: PR for {pr_version} and merged release {mv}")
    if pr_version and s.branch and pr_version != s.branch:
        raise core.PlatformError(f"two releases in flight: PR for {pr_version} and branch release/{s.branch}")
    if pr_version and not s.branch:
        s.branch = pr_version

    if pr_version:
        s.phase, s.version = PR_OPEN, pr_version
        return s
    if merged_open:
        s.phase, s.version = MERGED, mv
        return s
    if s.branch:
        s.phase, s.version = BRANCH, s.branch
        return s
    if mv is not None and mv == newest.removeprefix("v"):
        if s.tag_sha != s.merged_sha:
            raise core.PlatformError(
                f"tag {newest} is on {s.tag_sha}, not on the release's merge commit {s.merged_sha}")
        slug = ship.service_slug(repo)
        url = ship.gh(["release", "view", newest, "-R", slug, "--json", "url", "-q", ".url"], cwd=repo, check=False)
        s.release_url = (url or "").strip() or None
        if not s.release_url:
            s.phase, s.version = TAGGED, mv
            return s
        s.guard = _guard_run(repo, slug, newest)
        age = _tag_age(repo, newest)
        young = age is not None and age < GUARD_YOUNG
        if s.guard is None:
            if young:
                s.phase, s.version = GUARDING, mv
                return s
            s.notes.append(f"release-guard: no run on {newest}, not checked")
        elif s.guard.get("status") != "completed":
            s.phase, s.version = GUARDING, mv
            return s
        elif s.guard.get("conclusion") != "success":
            s.phase, s.version = GUARD_RED, mv
            return s
        s.release_url = None
    return s


# ---------------- version ----------------

def needs_major(repo: Path, tag: str) -> list[str]:
    rc, out = run_check(Path(repo), [sys.executable, "scripts/release-check.py", "needs-major", "--base", tag])
    if rc != 0:
        raise core.PlatformError(out.strip() or "release-check needs-major failed")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def proposal(tag: str, changes: list[str]) -> tuple[str, str]:
    major, minor, _ = vkey(tag)
    if changes:
        return f"{major + 1}.0.0", f"major after {tag}: " + "; ".join(changes)
    return f"{major}.{minor + 1}.0", f"minor after {tag}, no change needs a major release"


def propose(repo: Path, tag: str) -> tuple[str, str]:
    return proposal(tag, needs_major(repo, tag))


def check_syntax(requested: str) -> None:
    if not SEMVER.match(requested):
        raise core.PlatformError(f"--version {requested} is not X.Y.Z semver")


def check_in_flight(requested: str, state: State) -> None:
    if state.phase != IDLE and requested != state.version:
        raise core.PlatformError(f"release {state.version} is in flight ({state.phase}): finish it first")


def check_version(requested: str, state: State, changes: list[str]) -> None:
    """The checks of --version against the state (AC-129.3, AC-129.18). `changes` are the lines of needs-major."""
    check_syntax(requested)
    check_in_flight(requested, state)
    if state.phase != IDLE:
        return
    if vkey(requested) <= vkey(state.tag):
        raise core.PlatformError(f"--version {requested} is not newer than {state.tag}")
    if changes and vkey(requested)[0] <= vkey(state.tag)[0]:
        raise core.PlatformError(
            f"--version {requested} is not a major release; needs a major: " + "; ".join(changes))


# ---------------- steps and rendering ----------------

def steps(phase: str, version: str, sha: str | None, date: datetime.date | str) -> list[str]:
    x, d, s = version, str(date), sha or "the merge commit"
    allsteps = [
        "check the working tree, main and docs/CHANGELOG.md",
        f"create release/{x} from main and move [Unreleased] under ## [{x}] - {d}",
        "run release-check rows and devbox run validate",
        f'commit "chore: release {x}" (signed off), push release/{x} and open the PR',
        "wait for CI on the PR (the newest run of each workflow, the upgrade e2e included)",
        "stop for confirmation: squash-merge the PR (cplat platform release --confirm merge)",
        f"wait for the upgrade e2e on {s} (up to 10 minutes for it to start)",
        f"run release-check gate {s}",
        f"stop for confirmation: tag v{x} (cplat platform release --confirm tag)",
        f"tag v{x} on {s} and push it",
        f"create the GitHub release v{x} with the ## [{x}] section as notes",
        f"wait for the release-guard run on v{x}",
    ]
    return allsteps[FIRST_STEP[phase] - 1:]


def render(state: State, version: str, reason: str, step_texts: list[str]) -> list[str]:
    inflight = state.phase != IDLE
    merged = state.phase in (MERGED, TAGGED, GUARDING, GUARD_RED)
    tag_sha = state.tags.get(f"v{version}")
    lines = [
        "state:",
        f"  newest release tag: {state.tag} ({state.tag_sha[:7]})",
        f"  release branch: {'release/' + state.branch if state.branch else 'absent'}",
        f"  release PR: {state.pr['url'] if state.pr else 'absent'}",
        "  merged release commit: " + (f"{state.merged_sha[:7]} {state.merged_subject}" if merged and state.merged_sha else "absent"),
        f"  tag v{version}: " + (f"on {tag_sha[:7]}" if tag_sha else "absent"),
        f"  GitHub release v{version}: " + ((state.release_url or "absent") if inflight else "absent"),
    ]
    lines += [f"  {n}" for n in state.notes]
    lines.append(f"phase: {state.phase}")
    lines.append(f"version: {version} ({reason})")
    if step_texts:
        lines.append("steps:")
        lines += [f"  {i}. {t}" for i, t in enumerate(step_texts, 1)]
    return lines
