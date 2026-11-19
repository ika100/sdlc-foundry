"""The released milestone of spec 158 (AC-158.4 to AC-158.7): the issues a release fixes (closing references of the PRs merged
since the previous tag, and changelog fragments named by an issue number), one `Fixed in vX.Y.Z` comment each, the close of
the open ones, and the `## Phase 7 complete` summary. `released` never raises; a failure becomes a `note:` line."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import milestones as ms

WHAT_MAX = 300
FRAGMENT = re.compile(r"^(\d+)-.*\.md$")
PLATFORM_HOW = "run `/plugin marketplace update`, then `/platform:update`."
SEMVER_TAG = "v[0-9]*.[0-9]*.[0-9]*"
LOCAL_LIMIT_S = 20.0


@dataclass
class Result:
    lines: list[str] = field(default_factory=list)       # `issue …` and `note: …` lines, in issue order
    issues: list[dict] = field(default_factory=list)     # {"number", "comment": posted|present|skipped, "closed": now|before|failed|no}
    summary: str = ""                                    # `## Phase 7 complete — …`
    notes: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    """One local git call inside what is left of the step budget; stdout, or raises `ms._Skip(why)`."""
    left = ms.remaining()
    if left <= 0:
        raise ms._Skip(ms.STEP_MSG)
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=min(left, LOCAL_LIMIT_S))
    except subprocess.TimeoutExpired as e:
        raise ms._Skip(f"git {args[0]} timed out") from e
    except OSError as e:
        raise ms._Skip(str(e)) from e
    if r.returncode != 0:
        raise ms._Skip(ms._first_line(r.stderr) or f"git {args[0]} exited {r.returncode}")
    return r.stdout


def _try_git(repo: Path, *args: str) -> str | None:
    try:
        return _git(repo, *args)
    except ms._Skip:
        return None


def tag_exists(repo: Path, tag: str) -> bool:
    return _try_git(repo, "rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}") is not None


def previous_tag(repo: Path, tag: str) -> str | None:
    out = _try_git(repo, "describe", "--tags", "--abbrev=0", "--match", SEMVER_TAG, f"{tag}^")
    return out.strip() or None if out else None


def _fragments(repo: Path, tag: str) -> dict[int, str]:
    """Fragments `docs/changelog.d/<N>-*.md` at the tag or its parent whose text names `#<N>`: issue -> text."""
    found: dict[int, str] = {}
    for ref in (tag, f"{tag}^"):
        names = _try_git(repo, "ls-tree", "-r", "--name-only", ref, "--", "docs/changelog.d/") or ""
        for path in names.splitlines():
            m = FRAGMENT.match(path.rsplit("/", 1)[-1])
            if not m or int(m.group(1)) in found:
                continue
            n = int(m.group(1))
            text = _try_git(repo, "show", f"{ref}:{path}") or ""
            if re.search(rf"(?<![\w/])#{n}(?!\d)", text):
                found[n] = text
    return found


def _has_fragment_dir(repo: Path, tag: str) -> bool:
    return any(_try_git(repo, "ls-tree", "--name-only", ref, "docs/changelog.d/") for ref in (tag, f"{tag}^"))


def _plain(text: str) -> str:
    text = re.sub(r"\*\*|__|\*|`", "", text)
    return ms._collapse(re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text))


def _sentence(block: str) -> str:
    block = ms._collapse(re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", block))
    bold = re.match(r"\*\*(.+?)\*\*", block)
    return _plain(bold.group(1) if bold else re.split(r"(?<=[.!?])\s", block, 1)[0])


def _cut(text: str) -> str:
    return text if len(text) <= WHAT_MAX else text[:WHAT_MAX - 1] + "…"


def _changelog(repo: Path, version: str) -> str:
    """The section of the release in the changelog at origin/main (fetched first), else at the working tree's HEAD."""
    _try_git(repo, "fetch", "-q", "origin", "main")
    for ref in ("origin/main", "HEAD"):
        for name in ("docs/CHANGELOG.md", "CHANGELOG.md"):
            text = _try_git(repo, "show", f"{ref}:{name}")
            if text is None:
                continue
            section: list[str] | None = None
            for row in text.splitlines():
                if row.startswith("## "):
                    if section is not None:
                        break
                    section = [] if version in row else None
                elif section is not None:
                    section.append(row)
            if section is not None:
                return "\n".join(section)
    return ""


def _entry(section: str, n: int) -> str:
    """The first bullet or paragraph of a changelog section that names `#<n>`, reduced to its sentence."""
    blocks: list[list[str]] = []
    for row in section.splitlines():
        if not row.strip():
            blocks.append([])
        elif re.match(r"\s*(?:[-*+]|\d+\.)\s", row) or not blocks:
            blocks.append([row])
        else:
            blocks[-1].append(row)
    for block in blocks:
        text = " ".join(block)
        if re.search(rf"(?<![\w/])#{n}(?!\d)", text):
            return _sentence(text)
    return ""


def _merged(repo: Path, slug: str, default: str, tag: str, prev: str | None) -> list[dict]:
    """The PRs merged into the release: the merged-PR list filtered to the commits of `prev..tag`."""
    args = ["pr", "list", "-R", slug, "--state", "merged", "--base", default, "--limit", "300"]
    if prev:
        since = (_try_git(repo, "log", "-1", "--format=%cs", prev) or "").strip()
        if since:
            args += ["--search", f"merged:>={since}"]
    rows = json.loads(ms._call([*args, "--json", "number,title,body,url,mergeCommit"], repo) or "[]")
    shas = set(_git(repo, "rev-list", f"{prev}..{tag}" if prev else tag).split())
    return sorted((r for r in rows if (r.get("mergeCommit") or {}).get("oid") in shas), key=lambda r: r["number"])


def _how(repo: Path, slug: str, version: str) -> str:
    try:
        import shapecmd
        if shapecmd.route(repo)["shape"] == "platform":
            return PLATFORM_HOW
    except Exception:  # noqa: BLE001 - an unknown shape is a component
        pass
    return f"https://github.com/{slug}/releases/tag/{version}"


def summary_line(issues: list[dict], notes: list[str]) -> str:
    if not issues:
        return "## Phase 7 complete — no linked issues found"
    now = sum(1 for i in issues if i["closed"] == "now")
    before = sum(1 for i in issues if i["closed"] == "before")
    skipped = f", {len(notes)} skipped" if notes else ""
    names = ", ".join(f"#{i['number']}" for i in issues)
    return f"## Phase 7 complete — issues closed: {names} ({now} closed, {before} already closed{skipped})"


def released(repo: Path, version: str, previous: str | None = None) -> Result:
    """Comment on and close the issues linked to release `version` (`vX.Y.Z`). Never raises."""
    version = "v" + version.lstrip("v")
    res = Result()
    skipped = lambda why, what: res.notes.append(f"note: issue comment skipped: {what}: {why}")  # noqa: E731
    try:
        slug, default = ms._repo(repo)
        prev = "v" + previous.lstrip("v") if previous else previous_tag(repo, version)
        prs: list[dict] = []
        try:
            prs = _merged(repo, slug, default, version, prev)
        except Exception as e:  # noqa: BLE001 - the fragments alone still link issues
            skipped(ms._why(e), f"merged PRs of {version}")
        linked: dict[int, str] = {}       # issue -> the `what` fallback (closing PR's Changed or title, else the fragment)
        for pr in prs:
            for n in ms.closing_issues(pr.get("body") or ""):
                linked.setdefault(n, ms.summary_lines(pr.get("body") or "", pr.get("title") or "")[0])
        if _has_fragment_dir(repo, version):
            for n, text in _fragments(repo, version).items():
                linked.setdefault(n, _sentence(text))
        section = _changelog(repo, version.lstrip("v")) if linked else ""
        how = _how(repo, slug, version)
        closed: dict[int, str] = {}
        how_posted: dict[int, str] = {}
        for n in sorted(linked):
            what = _cut(_entry(section, n) or linked[n])
            body = f"Fixed in {version}.\n\nShipped: {what}\n\nGet it: {how}"
            lines, got = ms.post(repo, slug, [n], "released", version, body, close=True, closed=closed)
            res.lines += lines
            how_posted.update(got)
        res.notes += [x for x in res.lines if x.startswith("note:")]
        res.issues = [{"number": n, "comment": c, "closed": closed.get(n, "no")} for n, c in sorted(how_posted.items())
                      if c != "ignored"]
    except Exception as e:  # noqa: BLE001 - a comment never fails its command
        skipped(ms._why(e), f"linked issues of {version}")
    res.lines += [n for n in res.notes if n not in res.lines]
    res.summary = summary_line(res.issues, res.notes)
    return res
