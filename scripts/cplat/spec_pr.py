"""Draft spec pull requests (spec 122, AC-122.30): publish a spec as a draft PR, land it after approval, read reviews.

`publish` pushes the spec's own branch (never forced) and opens or updates one draft PR that holds only
`docs/specs/<id>/`, marked `<!-- cplat:spec <id> -->`. The system owner is asked to review it; that review request is
the GitHub notification for approve and answer. When the owner is the author, GitHub refuses a self-review, so the
author is assigned instead. `land` approves the review, marks the PR ready and merges it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pr_rules
import spec as specmod
from core import PlatformError, run

JSON_FIELDS = "number,url,body,isDraft"


def git(args: list[str], *, cwd: Path) -> tuple[int, str]:   # tests replace this
    try:
        p = run(["git", *args], cwd=cwd, check=False)
    except PlatformError:
        return 127, ""
    return p.returncode, p.stdout


def gh(args: list[str], *, cwd: Path) -> tuple[int, str]:   # tests replace this
    try:
        p = run(["gh", *args], cwd=cwd, check=False)
    except PlatformError:
        return 127, ""
    return p.returncode, p.stdout


def marker(spec_id: str) -> str:
    return f"<!-- cplat:spec {spec_id} -->"


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _git_ok(root: Path, *args: str) -> str:
    rc, out = git(list(args), cwd=root)
    if rc != 0:
        raise PlatformError(f"`git {' '.join(args[:2])}` failed (exit {rc})")
    return out


def branch_of(root: Path, spec: specmod.Spec) -> str:
    """The current branch, which must be the spec's own (`feature/<id>` or `docs/spec-<id>`)."""
    name = _git_ok(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if name not in (f"feature/{spec.id}", f"docs/spec-{spec.id}"):
        raise PlatformError(f"on branch {name or '?'}, not the spec's own branch feature/{spec.id} or docs/spec-{spec.id}")
    return name


def find_pr(root: Path, spec: specmod.Spec, branch: str) -> dict | None:
    """The open pull request of the branch that carries the spec's marker."""
    rc, out = gh(["pr", "list", "--head", branch, "--state", "open", "--json", JSON_FIELDS], cwd=root)
    for row in (_json(out) if rc == 0 else None) or []:
        if marker(spec.id) in (row.get("body") or ""):
            return row
    return None


def login(root: Path) -> str | None:
    rc, out = gh(["api", "user"], cwd=root)
    doc = _json(out) if rc == 0 else None
    return doc.get("login") if isinstance(doc, dict) else None


def _owner_from(text: str) -> str | None:
    try:
        import yaml
        doc = yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        return None
    owner = doc.get("owner") if isinstance(doc, dict) else None
    return str(owner) if owner else None


def owner_of(root: Path) -> str | None:
    """`owner:` of the system's system.yaml: this gitops repo's, else the one `.platform-app.yml` names (read through gh)."""
    for f in sorted((root / "applications").glob("*/system.yaml")):
        if (owner := _owner_from(f.read_text())):
            return owner
    link = root / ".platform-app.yml"
    slugs = re.findall(r"^\s*-\s*([^\s#]+/[^\s#]+)", link.read_text(), re.M) if link.is_file() else []
    for slug in slugs[:1]:
        rc, out = gh(["api", f"repos/{slug}/contents/applications"], cwd=root)
        for entry in (_json(out) if rc == 0 else None) or []:
            rc, text = gh(["api", "-H", "Accept: application/vnd.github.raw", f"repos/{slug}/contents/{entry.get('path')}/system.yaml"],
                          cwd=root)
            if rc == 0 and (owner := _owner_from(text)):
                return owner
    return None


def _commit(root: Path, spec: specmod.Spec, message: str) -> None:
    rel = f"docs/specs/{spec.id}"
    _git_ok(root, "add", "--", rel)
    rc, _ = git(["commit", "-s", "-m", message, "--", rel], cwd=root)
    if rc != 0 and git(["diff", "--cached", "--quiet", "--", rel], cwd=root)[0] != 0:
        raise PlatformError(f"`git commit` failed (exit {rc})")   # a clean folder (nothing to commit) is fine


def _ask_review(root: Path, number: int, owner: str | None, author: str | None) -> tuple[str | None, str]:
    """(reviewer, note): request the owner's review, or assign the author when they are the owner."""
    if not owner:
        return None, "no owner in system.yaml: nobody was asked to review"
    if author and owner == author:
        gh(["pr", "edit", str(number), "--add-assignee", author], cwd=root)
        return None, f"{owner} owns the system and wrote the draft: assigned instead of a review request (GitHub refuses a self-review)"
    candidates = [owner]
    if "/" not in owner:
        rc, out = gh(["repo", "view", "--json", "nameWithOwner"], cwd=root)
        doc = _json(out) if rc == 0 else None
        if isinstance(doc, dict) and "/" in str(doc.get("nameWithOwner")):
            candidates.append(f"{str(doc['nameWithOwner']).split('/')[0]}/{owner}")
    for c in candidates:
        if gh(["pr", "edit", str(number), "--add-reviewer", c], cwd=root)[0] == 0:
            return c, ""
    return None, f"review could not be requested from {owner}"


def publish(root: Path, spec: specmod.Spec) -> dict:
    """Push the spec's branch and open or update its draft PR; ask the owner for review."""
    branch = branch_of(root, spec)
    title = pr_rules.fit(f"docs(spec): {spec.id} — {spec.meta.get('title') or spec.id}")
    _commit(root, spec, title)
    _git_ok(root, "push", "-u", "origin", branch)
    row = find_pr(root, spec, branch)
    if row is None:
        body = f"Draft of spec {spec.id}. Holds only docs/specs/{spec.id}/.\n\n{marker(spec.id)}"
        rc, out = gh(["pr", "create", "--draft", "--head", branch, "--title", title, "--body", body], cwd=root)
        url = out.strip().splitlines()[-1] if out.strip() else ""
        m = re.search(r"/pull/(\d+)", url)
        if rc != 0 or not m:
            raise PlatformError(f"opening the draft pull request failed (gh exit {rc})")
        row = {"number": int(m.group(1)), "url": url}
    number = int(row["number"])
    reviewer, note = _ask_review(root, number, owner_of(root), login(root))
    return {"pr": number, "url": row.get("url"), "reviewer": reviewer, "note": note}


def land(root: Path, spec: specmod.Spec) -> tuple[bool, list[str]]:
    """Approve the review, mark the PR ready and merge it once CI is green. The spec must be approved."""
    if spec.status != "approved":
        raise PlatformError(f"{spec.id} is {spec.status}, not approved: run `cplat spec approve {spec.id}` first")
    info = publish(root, spec)
    number = str(info["pr"])
    me, owner = login(root), owner_of(root)
    if me and owner and me == owner:
        gh(["pr", "comment", number, "--body", f"approved by {me} (author is the system owner)"], cwd=root)
    else:
        gh(["pr", "review", number, "--approve"], cwd=root)
    gh(["pr", "ready", number], cwd=root)
    import pr
    import ship
    return pr.wait(root, number, True, 3600, 20, ship.QUEUE_TIMEOUT)


def request_changes(root: Path, spec: specmod.Spec, body_file: Path) -> str:
    row = find_pr(root, spec, branch_of(root, spec))
    if row is None:
        raise PlatformError(f"{spec.id} has no open draft pull request: run `cplat spec publish {spec.id}`")
    rc, _ = gh(["pr", "review", str(row["number"]), "--request-changes", "--body-file", str(body_file)], cwd=root)
    if rc != 0:
        raise PlatformError(f"posting the review failed (gh exit {rc})")
    return str(row["url"])


def comments(root: Path, spec: specmod.Spec) -> list[dict]:
    """The reviews and comments of the draft PR as `[{"author", "body", "at"}]`, oldest first."""
    row = find_pr(root, spec, branch_of(root, spec))
    if row is None:
        return []
    rc, out = gh(["pr", "view", str(row["number"]), "--json", "reviews,comments"], cwd=root)
    doc = (_json(out) if rc == 0 else None) or {}
    rows = []
    for c in [*(doc.get("reviews") or []), *(doc.get("comments") or [])]:
        if (c.get("body") or "").strip():
            rows.append({"author": (c.get("author") or {}).get("login", ""), "body": c["body"],
                         "at": c.get("submittedAt") or c.get("createdAt") or ""})
    return sorted(rows, key=lambda r: r["at"])


def main(ns, root: Path, spec: specmod.Spec) -> int:
    """Run `spec publish|land|review` for a parsed namespace (called by spec.main)."""
    if ns.cmd == "publish":
        info = publish(root, spec)
        print(json.dumps(info, indent=2) if ns.json else f"{spec.id}: {info['url']}" + (f" ({info['note']})" if info["note"] else ""))
        return 0
    if ns.cmd == "land":
        if spec.status != "approved":
            print(f"{spec.id} is {spec.status}, not approved: run `cplat spec approve {spec.id}` first", file=sys.stderr)
            return 1
        res = land(root, spec)
        ok, lines = res if isinstance(res, tuple) else (res == 0, [])
        for line in lines:
            print(line, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if ns.request_changes:
        if not ns.body_file:
            raise PlatformError("--request-changes needs --body-file")
        print(request_changes(root, spec, Path(ns.body_file)))
        return 0
    if not ns.comments:
        raise PlatformError("review needs --request-changes --body-file F, or --comments")
    rows = comments(root, spec)
    if ns.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['at']} {r['author']}: {r['body']}")
    return 0
