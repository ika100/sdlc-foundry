"""Spec 167: the backlog snapshot of the dispatcher and the candidates it yields (design.md "Data", "Words and item references").

  snapshot(repo, slug, max_age=300, fetch=True) -> Snapshot   everything readiness needs, read at most every `max_age` seconds
  worktrees(repo) -> [{"path", "branch"}]                      `git worktree list --porcelain` (read fresh, never cached)
  candidates(snap, policy) -> [Candidate]                      issues by label, specs by status, drafts from PRs

The snapshot holds the open issues (raw `gh` shape; `comments` only for issues with `in-progress` or `stale-premise`), the open PRs,
the specs of `origin/main` (status draft, approved or building, with their spec.md and plan.md text), the spec drafts of open PRs
marked `<!-- cplat:spec <id> -->`, the active run records of the repo and the worktrees. A source that cannot be read lands in
`unavailable` (source -> message) and keeps the value of the cached snapshot, if any. This module only reads: no label, comment,
claim, branch or worktree is written. `fetch=False` (`plan`) runs no `git fetch` and does not persist what it read.
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import core
import dispatch_state
import spec as specmod
import yaml
from core import PlatformError

MAX_AGE = 300
ISSUE_FIELDS = "number,title,body,labels,assignees,createdAt,updatedAt"
PR_FIELDS = "number,url,headRefName,body,isDraft,closingIssuesReferences"
COMMENT_LABELS = ("in-progress", "stale-premise")   # an issue the dispatcher or a manual session works on: its comments matter
SPEC_MARK = re.compile(r"<!--\s*cplat:spec\s+(\S+)\s*-->")
SPEC_FILE = re.compile(r"^docs/specs/([^/]+)/(spec|plan)\.md$")
CREATED = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s+created\b", re.M)
CANDIDATE_STATUSES = ("approved", "building")
SNAPSHOT_STATUSES = ("draft", *CANDIDATE_STATUSES)
HELD_LABELS = ("needs-decision", "wontfix")
SOURCES = ("issues", "specs", "drafts", "runs")


@dataclass
class Snapshot:
    read_at: str
    main_sha: str | None = None
    issues: list[dict] = field(default_factory=list)   # raw `gh issue list` rows; `comments` set when fetched
    prs: list[dict] = field(default_factory=list)      # raw `gh pr list` rows
    specs: list[dict] = field(default_factory=list)    # spec records of origin/main (see `_spec_record`), `plan` = plan.md text
    drafts: list[dict] = field(default_factory=list)   # spec records of open draft spec PRs, `pr` = {number, url, head}
    runs: list[dict] = field(default_factory=list)     # active run records of the repo: {run_id, kind, spec, issue, repo, parent}
    unavailable: dict[str, str] = field(default_factory=dict)
    worktrees: list[dict] = field(default_factory=list)   # {path, branch}; read fresh on every call, not stored

    def to_dict(self) -> dict:
        doc = asdict(self)
        doc.pop("worktrees")
        return doc

    @classmethod
    def from_dict(cls, doc: dict) -> Snapshot:
        keys = ("read_at", "main_sha", "issues", "prs", "specs", "drafts", "runs", "unavailable")
        return cls(**{k: doc[k] for k in keys if k in doc})

    def age(self) -> float:
        """Seconds since the snapshot was read (infinite for an unreadable stamp)."""
        try:
            return (dispatch_state.now() - dt.datetime.fromisoformat(self.read_at)).total_seconds()
        except (TypeError, ValueError):
            return float("inf")


@dataclass
class Candidate:
    key: str                       # `issue-<N>` or `spec-<NNN>`
    item: str                      # `#<N>` or `spec-<NNN>`
    kind: str                      # `fix` (issue) or `ship` (spec)
    title: str
    labels: list[str]              # issue labels; for a spec the labels of its own PR, none otherwise
    created: str                   # ISO time (issue `createdAt`, spec `created` changelog date at 00:00:00Z)
    text: str                      # issue body or spec.md: the text `blocked by #N` is read from
    spec: dict | None = None       # the spec record (meta fields, `text`, `plan`, `pr`) of a ship candidate
    tracks: list[int] = field(default_factory=list)   # issues a spec tracks
    status: str = "open"           # `open` (issue) or the spec status
    number: int | None = None      # issue number
    spec_id: str | None = None     # spec id
    pr: dict | None = None         # the draft PR of a draft spec


# ---------------- reading ----------------

def gh(args: list[str], *, cwd: Path) -> str:   # tests replace this
    return core.run(["gh", *args], cwd=cwd).stdout


def _git(repo: Path, args: list[str], *, stdin: str | None = None) -> str:
    p = subprocess.run(["git", *args], cwd=repo, input=stdin, capture_output=True, text=True, check=False)
    if p.returncode:
        raise PlatformError(f"git {' '.join(args[:2])} failed: {(p.stderr or p.stdout).strip()[:200]}")
    return p.stdout


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _repo_args(slug: str) -> list[str]:
    return ["-R", slug] if "/" in slug else []


def _label_names(row: dict) -> list[str]:
    return [lb.get("name") if isinstance(lb, dict) else str(lb) for lb in row.get("labels") or []]


def _read_issues(repo: Path, slug: str) -> list[dict]:
    rows = _json(gh(["issue", "list", *_repo_args(slug), "--state", "open", "--limit", "500", "--json", ISSUE_FIELDS], cwd=repo))
    if not isinstance(rows, list):
        raise PlatformError("gh issue list did not answer a list")
    for row in rows:
        if any(n in COMMENT_LABELS for n in _label_names(row)):
            out = _json(gh(["issue", "view", str(row["number"]), *_repo_args(slug), "--json", "comments"], cwd=repo))
            row["comments"] = out.get("comments") or [] if isinstance(out, dict) else []
    return rows


def _read_prs(repo: Path, slug: str) -> list[dict]:
    rows = _json(gh(["pr", "list", *_repo_args(slug), "--state", "open", "--limit", "200", "--json", PR_FIELDS], cwd=repo))
    if not isinstance(rows, list):
        raise PlatformError("gh pr list did not answer a list")
    return rows


def _created(text: str) -> str:
    m = CREATED.search(text)
    return f"{m.group(1)}T00:00:00Z" if m else ""


def _spec_record(sid: str, text: str, plan: str | None) -> dict | None:
    """The record of one spec from its spec.md text; None for text that has no readable front matter."""
    m = specmod.FRONT.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    tracks = [int(t) for t in meta.get("tracks") or [] if str(t).isdigit()]
    try:
        key = dispatch_state.parse_item(sid)
    except PlatformError:
        return None
    return {"id": sid, "key": key, "title": str(meta.get("title") or sid), "status": str(meta.get("status") or ""),
            "priority": str(meta.get("priority") or ""), "shape": meta.get("shape"), "tracks": tracks,
            "created": _created(m.group(2)), "text": text, "plan": plan}


def as_spec(rec: dict) -> specmod.Spec:
    """A `spec.Spec` (meta, body, plan) rebuilt from a spec record of the snapshot, for `open_questions()`, `acs()` and `check_plan`."""
    meta, body = _split(rec["text"])
    plan = _split(rec["plan"]) if rec.get("plan") else None
    return specmod.Spec(Path("docs") / "specs" / rec["id"], meta, body, plan)


def _split(text: str) -> tuple[dict, str]:
    m = specmod.FRONT.match(text)
    meta = yaml.safe_load(m.group(1)) if m else {}
    return (meta if isinstance(meta, dict) else {}), (m.group(2) if m else text)


def _read_specs(repo: Path) -> list[dict]:
    """The specs of `origin/main` with status draft, approved or building (one `git ls-tree`, one `git cat-file --batch`)."""
    tree = _git(repo, ["ls-tree", "-r", "origin/main", "--", "docs/specs"])
    files: dict[str, dict[str, str]] = {}
    for line in tree.splitlines():
        meta, _, path = line.partition("\t")
        if (m := SPEC_FILE.match(path)) and len(parts := meta.split()) == 3:
            files.setdefault(m.group(1), {})[m.group(2)] = parts[2]
    if not files:
        return []
    wanted = [oid for f in files.values() for oid in f.values()]
    blobs = _blobs(repo, wanted)
    out = []
    for sid in sorted(files):
        if "spec" not in files[sid]:
            continue
        rec = _spec_record(sid, blobs.get(files[sid]["spec"], ""), blobs.get(files[sid].get("plan", ""), None))
        if rec and rec["status"] in SNAPSHOT_STATUSES:
            if rec["status"] == "draft":
                rec["plan"] = None
            out.append(rec)
    return out


def _blobs(repo: Path, oids: list[str]) -> dict[str, str]:
    """oid -> text, from one `git cat-file --batch` process."""
    p = subprocess.run(["git", "cat-file", "--batch"], cwd=repo, input="".join(f"{o}\n" for o in oids).encode(), capture_output=True,
                       check=False)
    if p.returncode:
        raise PlatformError(f"git cat-file failed: {p.stderr.decode(errors='replace').strip()[:200]}")
    data, i, out = p.stdout, 0, {}
    while i < len(data):
        eol = data.index(b"\n", i)
        head = data[i:eol].split()
        if len(head) != 3 or head[1] != b"blob":
            i = eol + 1
            continue
        size = int(head[2])
        out[head[0].decode()] = data[eol + 1:eol + 1 + size].decode(errors="replace")
        i = eol + 1 + size + 1
    return out


def _read_drafts(repo: Path, slug: str, prs: list[dict], on_main: set[str]) -> list[dict]:
    """The draft specs of open PRs marked `<!-- cplat:spec <id> -->`, read at the PR head (`gh api .../contents/...?ref=<head>`)."""
    out = []
    for pr in prs:
        m = SPEC_MARK.search(pr.get("body") or "")
        if not m or m.group(1) in on_main:
            continue
        sid, head = m.group(1), pr.get("headRefName") or ""
        text = _contents(repo, slug, f"docs/specs/{sid}/spec.md", head)
        rec = _spec_record(sid, text, None) if text else None
        if rec and rec["status"] == "draft":
            rec["pr"] = {"number": pr.get("number"), "url": pr.get("url"), "head": head}
            out.append(rec)
    return out


def _contents(repo: Path, slug: str, path: str, ref: str) -> str:
    """A file at `ref` through the contents API (raw text, or the base64 `content` of a JSON answer); "" when it is not there."""
    try:
        text = gh(["api", "-H", "Accept: application/vnd.github.raw", f"repos/{slug}/contents/{path}?ref={ref}"], cwd=repo)
    except PlatformError:
        return ""
    doc = _json(text)
    if isinstance(doc, dict):
        raw = doc.get("content")
        if isinstance(raw, str) and doc.get("encoding") == "base64":
            with contextlib.suppress(ValueError):
                return base64.b64decode(raw).decode(errors="replace")
        return ""
    return text


def _read_runs(slug: str) -> list[dict]:
    import runlist
    rows = runlist.collect(2)["runs"]
    out = []
    for r in rows:
        if not r.get("active") or r.get("repo") != slug:
            continue
        issue = r.get("issue") if isinstance(r.get("issue"), dict) else None
        out.append({"run_id": r.get("run_id"), "kind": r.get("kind"), "spec": r.get("spec"), "repo": r.get("repo"),
                    "issue": issue.get("number") if issue else None, "parent": r.get("parent")})
    return out


def worktrees(repo: Path | str) -> list[dict]:
    """`git worktree list --porcelain` as `[{"path", "branch"}]` (the branch without `refs/heads/`, None for a detached HEAD)."""
    try:
        text = _git(Path(repo), ["worktree", "list", "--porcelain"])
    except PlatformError:
        return []
    out: list[dict] = []
    for block in text.split("\n\n"):
        path, branch = None, None
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):]
            elif line.startswith("branch "):
                branch = line[len("branch "):].removeprefix("refs/heads/")
        if path:
            out.append({"path": path, "branch": branch})
    return out


# ---------------- the snapshot ----------------

def snapshot(repo: Path | str, slug: str, *, max_age: int = MAX_AGE, fetch: bool = True) -> Snapshot:
    """The backlog snapshot: the cached one when it is younger than `max_age` seconds, else a fresh read.

    `fetch=True` (the loop) runs `git fetch -q origin main` and stores the new snapshot in the state; `fetch=False` (`plan`) reads
    GitHub and the local `origin/main` only and stores nothing. A source that fails is named in `unavailable` and keeps the value
    of the cached snapshot.
    """
    repo = Path(repo)
    cached_doc = dispatch_state.load(slug).get("snapshot") or {}
    cached = Snapshot.from_dict(cached_doc) if cached_doc.get("read_at") else None
    if cached is not None and cached.age() < max_age:
        cached.worktrees = worktrees(repo)
        return cached
    snap = Snapshot(read_at=dispatch_state.stamp())
    old = cached or Snapshot(read_at="")
    unavailable: dict[str, str] = {}

    def read(source: str, fn, fallback):
        try:
            return fn()
        except (PlatformError, OSError, ValueError, KeyError) as e:
            unavailable[source] = str(e).splitlines()[0] if str(e) else type(e).__name__
            return fallback

    if fetch:
        read("git", lambda: _git(repo, ["fetch", "-q", "origin", "main"]), None)
    snap.issues = read("issues", lambda: _read_issues(repo, slug), old.issues)
    snap.prs = read("prs", lambda: _read_prs(repo, slug), old.prs)
    snap.main_sha = read("main", lambda: _git(repo, ["rev-parse", "origin/main"]).strip(), old.main_sha)
    snap.specs = read("specs", lambda: _read_specs(repo), old.specs)
    snap.drafts = read("drafts", lambda: _read_drafts(repo, slug, snap.prs, {s["id"] for s in snap.specs}), old.drafts)
    snap.runs = read("runs", lambda: _read_runs(slug), old.runs)
    snap.unavailable = unavailable
    if fetch:
        dispatch_state.update(slug, lambda st: st.__setitem__("snapshot", snap.to_dict()))
    snap.worktrees = worktrees(repo)
    return snap


# ---------------- candidates ----------------

def _issue_candidate(row: dict) -> Candidate:
    n = int(row["number"])
    return Candidate(key=f"issue-{n}", item=f"#{n}", kind="fix", title=str(row.get("title") or ""), labels=_label_names(row),
                     created=str(row.get("createdAt") or ""), text=str(row.get("body") or ""), number=n)


def _spec_candidate(rec: dict) -> Candidate:
    meta = {k: rec.get(k) for k in ("id", "key", "title", "status", "priority", "shape", "tracks", "created", "plan", "pr")}
    return Candidate(key=rec["key"], item=dispatch_state.item_of(rec["key"]), kind="ship", title=rec["title"], labels=[],
                     created=rec.get("created") or "", text=rec["text"], spec={**meta, "text": rec["text"]},
                     tracks=list(rec.get("tracks") or []), status=rec["status"], spec_id=rec["id"], pr=rec.get("pr"))


def candidates(snap: Snapshot, policy) -> list[Candidate]:
    """The candidates of the policy's sources (design.md "Words and item references"), each item once.

    Issues: open, labelled `triaged`, without `needs-decision`, `wontfix` or a `ready.exclude_labels` label and with every
    `ready.labels` label. Specs: `approved` or `building` on `origin/main`, and every `draft` on `origin/main` or in an open draft
    spec PR. A spec carries the issues it `tracks` in `tracks` (and is the candidate that runs: readiness holds those issues as
    `duplicate`); the issues stay in the list so `plan` shows each with its verdict. Issues first (by number), then specs (by id).
    """
    values = policy.values
    sources, ready = values["sources"], values["ready"]
    out: list[Candidate] = []
    if "issues" in sources:
        skip = {*HELD_LABELS, *ready["exclude_labels"]}
        for row in sorted(snap.issues, key=lambda r: int(r["number"])):
            names = set(_label_names(row))
            if "triaged" in names and not names & skip and set(ready["labels"]) <= names:
                out.append(_issue_candidate(row))
    if "specs" in sources:
        recs = [r for r in snap.specs if r["status"] in SNAPSHOT_STATUSES]
        recs += [r for r in snap.drafts if r["id"] not in {s["id"] for s in snap.specs}]
        seen: set[str] = set()
        for rec in sorted(recs, key=lambda r: r["id"]):
            if rec["key"] in seen:
                continue
            seen.add(rec["key"])
            cand = _spec_candidate(rec)
            if cand.status == "draft" and cand.pr is None:
                cand.pr = next(({"number": p.get("number"), "url": p.get("url"), "head": p.get("headRefName")} for p in snap.prs
                                if (m := SPEC_MARK.search(p.get("body") or "")) and m.group(1) == rec["id"]), None)
            out.append(cand)
    return out
