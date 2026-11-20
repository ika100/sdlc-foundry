"""The release milestone (spec 158): the issues a release fixes get one `Fixed in vX.Y.Z` comment and are closed, and one call
returns the Phase 7 summary. Never raises: a failed read or comment becomes a `note:` line (AC-158.7)."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import milestones as ms

WHAT_MAX = 300
FRAGMENT = re.compile(r"^(\d+)-.*\.md$")


@dataclass
class Result:
    lines: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    summary: str = ""


def git(repo: Path, args: list[str], timeout: float) -> tuple[int, str]:
    """`git` with a timeout; (rc, stdout). Never raises; tests may replace this."""
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return 124, ""
    return r.returncode, r.stdout


def _git(repo: Path, *args: str) -> str:
    """stdout of a git call inside the step budget, or `ms._Skip`."""
    left = min(ms.remaining(), ms.ISSUE_LIMIT_S)
    if left <= 0:
        raise ms._Skip(ms.STEP_MSG)
    rc, out = git(repo, list(args), left)
    if rc != 0:
        raise ms._Skip(f"git {args[0]} failed")
    return out


def tag_exists(repo: Path, tag: str) -> bool:
    rc, _ = git(repo, ["rev-parse", "-q", "--verify", f"refs/tags/{tag}"], ms.ISSUE_LIMIT_S)
    return rc == 0


def _previous(repo: Path, tag: str) -> str | None:
    try:
        return _git(repo, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*.[0-9]*.[0-9]*", f"{tag}^").strip() or None
    except ms._Skip:
        return None


def _fragments(repo: Path, tag: str) -> dict[int, str]:
    """issue -> fragment text, for the `<N>-*.md` fragments at the tag or its parent that name `#<N>`."""
    found: dict[int, str] = {}
    for rev in (tag, f"{tag}^"):
        try:
            names = _git(repo, "ls-tree", "--name-only", rev, "docs/changelog.d/").split()
        except ms._Skip:
            continue
        for path in names:
            m = FRAGMENT.match(path.rsplit("/", 1)[-1])
            if not m or int(m.group(1)) in found:
                continue
            try:
                text = _git(repo, "show", f"{rev}:{path}")
            except ms._Skip:
                continue
            if re.search(rf"#{m.group(1)}(?!\d)", text):
                found[int(m.group(1))] = text
    return found


def _unemph(text: str) -> str:
    text = re.sub(r"(\*\*|__|`)(.+?)\1", r"\2", text)
    return re.sub(r"(?<!\w)(\*|_)(.+?)\1(?!\w)", r"\2", text)


def _entry(section: str, n: int) -> str:
    """The first bullet or paragraph of a changelog section naming `#n`, as one sentence without emphasis."""
    blocks: list[str] = []
    for line in section.splitlines():
        if line.startswith(("- ", "* ")) or not blocks or not line.strip() or not blocks[-1]:
            blocks.append(line[2:] if line.startswith(("- ", "* ")) else line)
        else:
            blocks[-1] += " " + line.strip()
    for block in blocks:
        text = ms._collapse(block)
        if re.search(rf"#{n}(?!\d)", text):
            bold = re.match(r"\*\*(.+?)\*\*", text)
            first = bold.group(1) if bold else re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
            return _unemph(first).strip()
    return ""


def _changelog(repo: Path, version: str) -> str:
    """The section of the changelog at `origin/main` that names this version."""
    try:
        _git(repo, "fetch", "-q", "origin", "main")
    except ms._Skip:
        pass
    for name in ("docs/CHANGELOG.md", "CHANGELOG.md"):
        try:
            text = _git(repo, "show", f"origin/main:{name}")
        except ms._Skip:
            continue
        for part in re.split(r"(?m)^(?=## )", text):
            if part.startswith("## ") and version.lstrip("v") in part.splitlines()[0]:
                return part
        return ""
    return ""


def _cap(text: str) -> str:
    return text if len(text) <= WHAT_MAX else text[:WHAT_MAX - 1] + "…"


def _how(repo: Path, slug: str, version: str) -> str:
    try:
        import shapecmd
        if shapecmd.route(repo)["shape"] == "platform":
            return "run `/plugin marketplace update`, then `/platform:update`."
    except Exception:  # noqa: BLE001 - an unknown shape gets the release page
        pass
    return f"https://github.com/{slug}/releases/tag/{version}"


def _merged(repo: Path, slug: str, default: str, tag: str, previous: str | None) -> list[dict]:
    revs = set(_git(repo, "rev-list", f"{previous}..{tag}" if previous else tag).split())
    args = ["pr", "list", "-R", slug, "--state", "merged", "--base", default, "--limit", "300"]
    if previous:
        date = _git(repo, "log", "-1", "--format=%cs", previous).strip()
        args += ["--search", f"merged:>={date}"]
    prs = json.loads(ms._call([*args, "--json", "number,title,body,url,mergeCommit"], repo))
    return sorted((p for p in prs if (p.get("mergeCommit") or {}).get("oid") in revs), key=lambda p: p["number"])


def released(repo: Path, version: str, previous: str | None = None) -> Result:
    res = Result()
    notes: list[str] = []
    prs: list[dict] = []
    slug, default, why = "", "main", "no repository"
    try:
        slug, default = ms._repo(repo)
        prev = previous or _previous(repo, version)
        prs = _merged(repo, slug, default, version, prev)
    except Exception as e:  # noqa: BLE001
        why = ms._why(e)
        notes.append(f"note: issue comment skipped: merged PRs of {version}: {why}")
    fragments: dict[int, str] = {}
    try:
        fragments = _fragments(repo, version)
    except Exception:  # noqa: BLE001
        pass
    source: dict[int, dict | None] = {}
    for pr in prs:
        for n in ms.closing_issues(pr.get("body", "")):
            source.setdefault(n, pr)
    for n in fragments:
        source.setdefault(n, None)
    res.lines.extend(notes)
    if not slug:
        for n in sorted(source):
            res.lines.append(f"note: issue comment skipped: #{n} released: {why}")
        res.notes = [x for x in res.lines if x.startswith("note:")]
        res.summary = _summary({})
        return res
    try:
        section = _changelog(repo, version)
        how = _how(repo, slug, version)
    except Exception:  # noqa: BLE001
        section, how = "", _how(repo, slug, version)
    status: dict[int, tuple[str, str]] = {}
    for n in sorted(source):
        pr = source[n]
        what = _entry(section, n)
        if not what and pr:
            what = ms.summary_lines(pr.get("body", ""), pr.get("title", ""))[0]
        if not what:
            what = ms._collapse(fragments.get(n, "")) or "see the release notes"
        body = f"Fixed in {version}.\n\nShipped: {_cap(what)}\n\nGet it: {how}"
        closed: dict[int, str] = {}
        lines, posted = ms.post(repo, slug, [n], "released", version, body, close=True, closed=closed)
        res.lines.extend(lines)
        if n in posted and posted[n] != "ignored":
            status[n] = (posted[n], closed.get(n, "no"))
    res.notes = [x for x in res.lines if x.startswith("note:")]
    res.issues = [{"number": n, "comment": c, "closed": k} for n, (c, k) in sorted(status.items())]
    res.summary = _summary(status)
    return res


def _summary(status: dict[int, tuple[str, str]]) -> str:
    head = "## Phase 7 complete — "
    if not status:
        return head + "no linked issues found"
    now = sum(1 for _, k in status.values() if k == "now")
    before = sum(1 for _, k in status.values() if k == "before")
    skipped = len({n for n in status if status[n][0] == "skipped" or status[n][1] == "failed"})
    tail = f", {skipped} skipped" if skipped else ""
    return head + f"issues closed: {', '.join(f'#{n}' for n in sorted(status))} ({now} closed, {before} already closed{tail})"
