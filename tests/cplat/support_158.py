"""Spec 158 test world (not a test module): a scripted `gh` behind `milestones.gh`, a scripted clock behind `milestones.clock`,
spec and PR-body builders, and a real git repository with a bare origin for the release tests.

The seams are the ones of design.md, "Python interface" and "gh calls per issue". The new modules are imported inside the
functions, so a missing module fails the one test that needs it and never the collection."""
import importlib
import json
import re
import subprocess
from pathlib import Path

import spec

SLUG = "acme/shop"
SID = "007-price-alerts"
SPEC_PR = "https://github.com/acme/shop/pull/41"
SPEC_AT_BRANCH = f"https://github.com/{SLUG}/blob/feature/{SID}/docs/specs/{SID}/spec.md"
SPEC_AT_MAIN = f"https://github.com/{SLUG}/blob/main/docs/specs/{SID}/spec.md"
MARKER_RE = r"<!-- cplat:milestone {} {} -->"
SPEC_TEXT = """---
spec_id: 007-price-alerts
title: Price alerts
status: {status}
priority: P1
shape: platform
tracks: {tracks}
---

# 007 — Price alerts

## Problem

Traders miss moves.

## Stories

{story}
**Repos:** the platform.

As an operator, I want a second story that must never be quoted.

## Acceptance criteria

- **AC-007.1** Given a rule, when the price crosses it, then an email is sent.
- **AC-007.2** Given a rule, when a webhook is set, then it is called.
- ~~**AC-007.3**~~ withdrawn: SMS is out of scope.

## Open questions

{questions}

## Changelog

- 2026-10-01 created
- 2026-10-02 approved
"""
STORY = "As a trader, I want an email when a price crosses my rule, so that I never miss a move."


def make_spec(root: Path, *, status="draft", tracks="[42]", story=STORY, questions="None.") -> spec.Spec:
    d = root / "docs" / "specs" / SID
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(SPEC_TEXT.format(status=status, tracks=tracks, story=story, questions=questions))
    return spec.read(d)


def pr_body(closes=(), *, changed="Alerts are emailed", why="Traders missed moves", extra="", block=True) -> str:
    refs = "\n".join(f"Closes #{n}" for n in closes)
    summary = (f"<!-- cplat:summary -->\n- **Changed:** {changed}\n- **Why:** {why}\n<!-- /cplat:summary -->\n" if block else "")
    return f"{summary}\n{refs}\n{extra}\n"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeGh:
    """`milestones.gh(args, *, cwd, timeout) -> (rc, out, err)` over in-memory issues, comments and PRs."""

    def __init__(self, slug=SLUG):
        self.slug = slug
        self.issues: dict[int, dict] = {}
        self.prs: dict[str, dict] = {}
        self.pr_list: list[dict] = []
        self.calls: list[tuple[list[str], float]] = []
        self.clock = Clock()
        self.hang: set[int] = set()        # issues whose every gh call runs into its timeout
        self.offline = False
        self.raises = False
        self.default = "main"

    def issue(self, n, *, state="open", labels=(), pull_request=False, locked=False, comments=(), post_error=None):
        self.issues[n] = {"state": state, "locked": locked, "labels": [{"name": x} for x in labels], "comments": list(comments),
                          "post_error": post_error, **({"pull_request": {"url": "x"}} if pull_request else {})}
        return self

    def pr(self, number, *, body, title="A change", url=None):
        url = url or f"https://github.com/{self.slug}/pull/{number}"
        self.prs[str(number)] = self.prs[url] = {"number": number, "url": url, "title": title, "body": body}
        return url

    # ---- reading what happened
    def posts(self, n=None) -> list[str]:
        return [b for (k, b) in self.posted if n is None or k == n]

    @property
    def posted(self) -> list[tuple[int, str]]:
        out = []
        for args, _ in self.calls:
            if args[:3] == ["api", "-X", "POST"]:
                m = re.search(r"issues/(\d+)/comments", " ".join(args))
                body = next(a for a in args if a.startswith("body="))[len("body="):]
                out.append((int(m.group(1)), body))
        return out

    def closes(self) -> list[int]:
        return [int(a[2]) for a, _ in self.calls if a[:2] == ["issue", "close"]]

    def issue_calls(self, n) -> list[tuple[list[str], float]]:
        return [(a, t) for a, t in self.calls if re.search(rf"issues/{n}\b", " ".join(a)) or (a[:2] == ["issue", "close"] and a[2] == str(n))]

    # ---- the seam
    def __call__(self, args, *, cwd=None, timeout=20.0):
        args = [str(a) for a in args]
        self.calls.append((args, timeout))
        if self.raises:
            raise RuntimeError("gh exploded")
        if self.offline:
            return 1, "", "error connecting to api.github.com"
        text = " ".join(args)
        m = re.search(r"issues/(\d+)", text)
        n = int(m.group(1)) if m else (int(args[2]) if args[:2] == ["issue", "close"] else None)
        if n in self.hang:
            self.clock.now += timeout
            return 124, "", f"timed out after {timeout:g}s"
        if args[:2] == ["repo", "view"]:
            return 0, json.dumps({"nameWithOwner": self.slug, "defaultBranchRef": {"name": self.default}}), ""
        if args[:2] == ["pr", "view"]:
            row = self.prs.get(args[2])
            return (0, json.dumps(row), "") if row else (1, "", "no pull requests found")
        if args[:2] == ["pr", "list"]:
            return 0, json.dumps(self.pr_list), ""
        if args[:2] == ["issue", "close"]:
            self.issues[n]["state"] = "closed"
            return 0, "", ""
        if n is None:
            return 0, "", ""
        issue = self.issues.get(n)
        if issue is None:
            return 1, "", "Not Found (HTTP 404)"
        if text.endswith(f"issues/{n}"):
            return 0, json.dumps({k: issue[k] for k in ("state", "locked", "labels", "pull_request") if k in issue}), ""
        if args[:3] == ["api", "-X", "POST"]:
            if issue["post_error"]:
                return 1, "", issue["post_error"]
            issue["comments"].append(next(a for a in args if a.startswith("body="))[len("body="):])
            return 0, "{}", ""
        if "--paginate" in args:
            return 0, "\n".join(issue["comments"]), ""
        return 0, "", ""


def install(monkeypatch, fake: FakeGh):
    """Put the fake behind `milestones.gh` and `milestones.clock`; a missing module fails the test here."""
    milestones = importlib.import_module("milestones")
    monkeypatch.setattr(milestones, "gh", fake)
    monkeypatch.setattr(milestones, "clock", fake.clock)
    milestones.reset()
    return milestones


def marker(milestone: str, key: str) -> str:
    return f"<!-- cplat:milestone {milestone} {key} -->"


def lines_of(body: str) -> list[str]:
    return body.rstrip("\n").splitlines()


# ---------------- a real repository for the release tests ----------------

def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args], cwd=repo, capture_output=True, text=True,
                       check=True)
    return r.stdout.strip()


class ReleaseRepo:
    """origin (bare) + clone with `main`: v1.0.0, then merged PRs 10, 11, 13 (closing #5, #6, #7), a PR 12 that only mentions #9 and
    names another repo's #8, a PR 9 merged before v1.0.0 that closed #3, a fragment naming #77, a spec-numbered fragment `88-…`
    that does not name #88, and the changelog of v1.1.0 on `origin/main`."""

    def __init__(self, tmp: Path, fake: FakeGh):
        origin = tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        self.dir = tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(origin), str(self.dir)], check=True, capture_output=True)
        git(self.dir, "checkout", "-q", "-b", "main")
        (self.dir / "docs" / "changelog.d").mkdir(parents=True)
        self.sha = {}
        self.sha[9] = self.commit("old.txt", "pr 9 (#3)")
        git(self.dir, "tag", "v1.0.0")
        self.sha[10] = self.commit("a.txt", "pr 10")
        self.sha[11] = self.commit("b.txt", "pr 11")
        self.sha[12] = self.commit("c.txt", "pr 12")
        self.sha[13] = self.commit("d.txt", "pr 13")
        (self.dir / "docs" / "changelog.d" / "77-widget.added.md").write_text("A widget for everyone (#77).\n")
        (self.dir / "docs" / "changelog.d" / "88-spec.added.md").write_text("A spec-numbered entry without an issue.\n")
        (self.dir / "CHANGELOG.md").write_text(
            "# CHANGELOG\n\n## [1.1.0] - 2026-11-19\n\n- **Fixed the widget.** More words about it (#5).\n- A widget for everyone (#77).\n\n"
            "## [1.0.0] - 2026-10-01\n\n- Old (#3).\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "docs: changelog and fragments")
        git(self.dir, "tag", "v1.1.0")
        git(self.dir, "push", "-q", "origin", "main", "--tags")
        fake.issue(3).issue(5).issue(6, state="closed").issue(7).issue(77).issue(88).issue(9)
        fake.pr(9, body=pr_body([3]))
        fake.pr(10, body=pr_body([5], changed="Widget fix from the PR", why="because"), title="fix widget")
        fake.pr(11, body=pr_body([6], changed="Six is fixed", why="why six"), title="fix six")
        fake.pr(12, body="See #9 and Closes other/repo#8\n", title="mention only")
        fake.pr(13, body="Closes #7\n", title="Title of the PR without a summary block")
        fake.pr_list = [{**fake.prs[str(n)], "mergeCommit": {"oid": self.sha[n]}} for n in (9, 10, 11, 12, 13)]

    def commit(self, name: str, msg: str) -> str:
        (self.dir / name).write_text(msg)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", msg)
        return git(self.dir, "rev-parse", "HEAD")
