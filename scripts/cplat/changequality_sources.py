"""Every read `cplat platform change-quality` needs (spec 223): releases and fix entries of the changelog, fragments, a PR's
release from git or GitHub, stopped journeys of docs/PERFORMANCE.md and the fleet's `.platform-version` history.

Each reader takes an injectable runner (`git(args, cwd) -> (rc, out, err)`, `gh(args) -> (rc, out, err)`) so the aggregate
stays pure and tests use a tmp repo and a fake gh. Progress lines go to stderr only."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import core
import fleet
import platrelease_changelog as pc
from core import PlatformError

Runner = Callable[[list[str]], tuple[int, str, str]]
GitRunner = Callable[[list[str], Path], tuple[int, str, str]]

RELEASE_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})\s*$", re.M)
FIXED_HEADING = re.compile(r"^### +Fixed\s*$", re.M)
NEXT_SUBHEAD = re.compile(r"^###", re.M)
SUBJECT_PR = re.compile(r"\(#(\d+)\)\s*$")
TAG = re.compile(r"^v\d+\.\d+\.\d+$")
ISSUE_REF = re.compile(r"#(\d+)")
STAMP = re.compile(r"^platform:\s*(\d+\.\d+\.\d+)", re.M)
UNRELEASED = "Unreleased"
PERFORMANCE = "docs/PERFORMANCE.md"


@dataclass(frozen=True)
class Release:
    version: str
    date: str
    body: str


@dataclass(frozen=True)
class FleetUnknown:
    reason: str


def say(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """subprocess `git <args>` -> (exit code, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    except FileNotFoundError:
        return 127, "", "git is not installed"
    return p.returncode, p.stdout, p.stderr


def releases(repo: Path | str) -> list[Release]:
    """Every `## [X.Y.Z] - YYYY-MM-DD` section of docs/CHANGELOG.md, in file order."""
    f = Path(repo) / pc.CHANGELOG
    if not f.is_file():
        return []
    text = f.read_text()
    out = []
    for m in RELEASE_HEADING.finditer(text):
        out.append(Release(m[1], m[2], pc.section_body(text, m[1]) or ""))
    return out


def fixed_section(body: str) -> str:
    """The text under `### Fixed`, up to the next `###` (empty without one)."""
    m = FIXED_HEADING.search(body)
    if not m:
        return ""
    rest = body[m.end():]
    nxt = NEXT_SUBHEAD.search(rest)
    return (rest[: nxt.start()] if nxt else rest).strip()


def fragment_fixes(repo: Path | str) -> list[tuple[str, str]]:
    """(name, text) of the `*.fixed.md` fragments of the working tree."""
    return [(n, t) for n, t in pc.read_fragments(repo) if n.endswith(".fixed.md")]


_SUBJECTS: dict[tuple[str, str], dict[int, str]] = {}


def _subjects(repo: Path, git: GitRunner) -> dict[int, str]:
    """PR number -> commit sha for subjects ending `(#n)` on HEAD (one log read per HEAD, cached)."""
    rc, head, _ = git(["rev-parse", "HEAD"], repo)
    key = (str(repo.resolve()), head.strip())
    if rc == 0 and key in _SUBJECTS:
        return _SUBJECTS[key]
    rc, out, _ = git(["log", "--format=%H%x00%s"], repo)
    found: dict[int, str] = {}
    for line in out.splitlines() if rc == 0 else []:
        sha, _, subject = line.partition("\0")
        m = SUBJECT_PR.search(subject)
        if m:
            found.setdefault(int(m[1]), sha)
    if rc == 0:
        _SUBJECTS[key] = found
    return found


def _lowest_tag(repo: Path, sha: str, git: GitRunner) -> str:
    rc, out, _ = git(["tag", "--contains", sha, "--list", "v*"], repo)
    tags = [t.strip() for t in out.splitlines() if TAG.match(t.strip())] if rc == 0 else []
    return min(tags, key=lambda t: core.vtuple(t[1:]))[1:] if tags else UNRELEASED


def pr_release(repo: Path | str, n: int, *, slug: str | None = None, gh: Runner | None = None,
               git: GitRunner | None = None) -> str | None:
    """Version (`X.Y.Z`) of the lowest release tag containing PR `n`'s merge commit, `Unreleased` without a tag, None when
    the PR is found neither in git (subject `(#n)`) nor on GitHub (`merge_commit_sha`)."""
    repo = Path(repo)
    git = git or run_git
    gh = gh or fleet.gh
    sha = _subjects(repo, git).get(n)
    if sha is None and slug:
        rc, out, _ = gh(["api", f"repos/{slug}/pulls/{n}"])
        if rc == 0:
            try:
                sha = (json.loads(out or "{}") or {}).get("merge_commit_sha")
            except ValueError:
                sha = None
    if not sha:
        return None
    return _lowest_tag(repo, sha, git)


def stopped_journeys(repo: Path | str) -> list[tuple[int, set[int]]]:
    """(journey number, {#N named in the row}) for each docs/PERFORMANCE.md table row with an integer first cell and a
    `**stopped` mark."""
    f = Path(repo) / PERFORMANCE
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        if not line.lstrip().startswith("|") or "**stopped" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"\d+", cells[0]):
            out.append((int(cells[0]), {int(x) for x in ISSUE_REF.findall(line)}))
    return out


def _gh_login(gh: Runner) -> str:
    rc, out, err = gh(["api", "user", "-q", ".login"])
    if rc != 0 or not out.strip():
        raise PlatformError(f"cannot read the gh login: {fleet._first(err)}")
    return out.strip()


def _file(gh: Runner, slug: str, path: str) -> str | None:
    rc, out, err = gh(["api", f"repos/{slug}/contents/{path}", *fleet.RAW])
    if rc == 0:
        return out
    if "404" in err or "Not Found" in err:
        return None
    raise PlatformError(f"cannot read {path} of {slug}: {fleet._first(err)}")


def _history(gh: Runner, slug: str) -> list[str]:
    rc, out, err = gh(["api", "--paginate", f"repos/{slug}/commits?path=.platform-version", "-q", ".[].sha"])
    if rc != 0:
        raise PlatformError(f"cannot read the .platform-version history of {slug}: {fleet._first(err)}")
    versions = []
    for sha in out.split():
        text = _file(gh, slug, f".platform-version?ref={sha}")
        m = STAMP.search(text or "")
        if m:
            versions.append(m[1])
    return versions


def fleet_stamps(*, gh: Runner | None = None) -> dict[str, list[str]] | FleetUnknown:
    """Per platform repo of the gh login, every version its `.platform-version` held (newest first); FleetUnknown when any
    read fails, never an empty result standing for "could not read"."""
    gh = gh or fleet.gh
    try:
        owner = _gh_login(gh)
        templates = {s["template"] for s in core.registry.load()}
        stamps: dict[str, list[str]] = {}
        for entry in fleet._list_owner(owner):
            slug = entry["nameWithOwner"]
            say(f"reading {slug}")
            if _file(gh, slug, ".platform-version") is None:
                continue
            answers = _file(gh, slug, ".copier-answers.yml")
            if answers is None or not fleet.is_platform(answers, templates):
                continue
            stamps[slug] = _history(gh, slug)
        return stamps
    except PlatformError as e:
        return FleetUnknown(str(e))
