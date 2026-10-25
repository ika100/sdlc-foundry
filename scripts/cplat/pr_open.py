"""`pr open`: commit (signed off), push and open the pull request in one command (spec 100, ADR-037).

  cplat pr open --title "<type>(<scope>): <subject>" [--body-file .pr-body.md] [--message <commit subject>]
                [--base main] [--issues "#12 #7"] [--spec <id>] [--no-pr] [--json]

Fixed operations only: `git add -A`, `git commit -s`, `git push -u origin <branch>` (never forced, never amended) and
`gh pr create` when the repo's `.claude/settings*.json` allows it, else a ready PR (spec 051). Safe to run again after
a failure: a clean tree is not committed twice and an open PR is not opened twice.
Exit 0: PR opened or ready; 1: a part failed; 2: refused before starting (nothing changed).
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

import core
import spec as specmod
from core import PlatformError, run

BRANCH = re.compile(r"^(feature|fix|chore|docs|refactor|perf|test|release)/[A-Za-z0-9._/-]+$")
TITLE = re.compile(r"^(feat|fix|refactor|perf|test|docs|chore|ci|build|revert|style)(\([^)]+\))?!?: \S.*$")
WIP_NOTE = "Contains WIP commits from an interrupted build: squash-merge."
PR_RULES = ("Bash(gh pr create *)", "Bash(gh pr create:*)", "Bash(gh pr *)", "Bash(gh pr:*)", "Bash(gh *)", "Bash(gh:*)")


class Refused(PlatformError):
    """Exit 2: nothing was changed."""


@dataclass
class Opts:
    title: str
    body_file: str = core.PR_BODY
    message: str | None = None
    base: str = "main"
    issues: str = ""
    spec: str | None = None
    no_pr: bool = False


@dataclass
class Result:
    commit: tuple[str, str | None, str] = ("not run", None, "")
    push: tuple[str, str] = ("not run", "")
    pr: tuple[str, str | None, str | None, str] = ("not run", None, None, "")
    closes: list[int] = field(default_factory=list)

    @property
    def exit(self) -> int:
        failed = "failed" in (self.commit[0], self.push[0], self.pr[0])
        return 1 if failed else 0

    def lines(self) -> list[str]:
        def one(status: str, detail: str) -> str:
            return f"{status}: {detail}" if status == "failed" or (status == "ready") else (detail or status)
        c, p, r = self.commit, self.push, self.pr
        commit = f"commit: {c[0]} {c[1]}" if c[0] == "done" else f"commit: {c[2] if c[0] == 'skipped' else one(c[0], c[2])}"
        push = "push: done" if p[0] == "done" else f"push: {one(*p)}"
        if r[0] == "opened":
            pr = f"pr: opened {r[1]}"
        elif r[0] == "ready":
            pr = f"pr: ready: {r[2]}"
        else:
            pr = f"pr: {one(r[0], r[3])}"
        return [commit, push, pr]

    def as_json(self) -> dict:
        return {"commit": {"status": self.commit[0], "sha": self.commit[1], "detail": self.commit[2]},
                "push": {"status": self.push[0], "detail": self.push[1]},
                "pr": {"status": self.pr[0], "url": self.pr[1], "command": self.pr[2], "detail": self.pr[3]},
                "closes": self.closes, "exit": self.exit}


def _ok(cmd: list[str], repo: Path) -> bool:
    try:
        return run(cmd, cwd=repo, check=False).returncode == 0
    except PlatformError:
        return False


def _out(cmd: list[str], repo: Path) -> str:
    return (run(cmd, cwd=repo, check=False).stdout or "").strip()


def _last(res) -> str:
    return ((res.stderr or res.stdout or "").strip().splitlines() or ["unknown error"])[-1]


def pr_allowed(repo: Path) -> bool:
    """ADR-037: `gh pr create` needs an allow rule and no deny or ask rule among the listed ones."""
    rules: dict[str, set[str]] = {"allow": set(), "deny": set(), "ask": set()}
    for name in ("settings.json", "settings.local.json"):
        f = repo / ".claude" / name
        try:
            perms = json.loads(f.read_text()).get("permissions", {})
        except (OSError, ValueError):
            continue
        for key in rules:
            rules[key] |= {r for r in perms.get(key, []) if isinstance(r, str)}
    listed = set(PR_RULES)
    return bool(rules["allow"] & listed) and not (rules["deny"] & listed) and not (rules["ask"] & listed)


def _closes(repo: Path, o: Opts, base_ref: str, have_gh: bool, body_path: Path) -> list[int]:
    cands: set[int] = {int(n) for n in re.findall(r"#(\d+)", o.issues)}
    if o.spec:
        try:
            cands |= {int(t) for t in specmod.find(repo, o.spec).meta.get("tracks") or []}
        except PlatformError:
            pass
    cands |= {int(n) for n in re.findall(r"#(\d+)", _out(["git", "log", f"{base_ref}..HEAD", "--format=%B"], repo))}
    cands |= {int(n) for n in re.findall(r"#(\d+)", o.message or "")}
    kept = sorted(n for n in cands if have_gh and
                  _out(["gh", "issue", "view", str(n), "--json", "state", "-q", ".state"], repo) == "OPEN")
    text = body_path.read_text()
    if "{{CLOSES}}" in text:
        body_path.write_text(text.replace("{{CLOSES}}", "\n".join(f"Closes #{n}" for n in kept) or "N/A"))
    return kept


def open_pr(repo: Path, o: Opts) -> Result:
    if not _ok(["git", "rev-parse", "--is-inside-work-tree"], repo):
        raise Refused("not a git repository")
    body_path = core.stage_pr_body(repo, o.body_file)
    o.body_file = str(body_path.relative_to(repo)) if repo in body_path.parents else str(body_path)
    if not body_path.is_file():
        raise Refused(f"the PR body file {o.body_file} does not exist", hint="write the PR body there first")
    branch = _out(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    if branch == o.base or not BRANCH.match(branch):
        raise Refused(f"branch '{branch}' cannot be pushed from here",
                      hint=f"work on feature/*, fix/*, chore/*, docs/*, refactor/*, perf/*, test/* or release/*, not {o.base}")
    if not TITLE.match(o.title):
        raise Refused(f"title '{o.title}' is not a Conventional Commits title", hint="<type>(<scope>): <subject>")

    base_ref = f"origin/{o.base}" if _ok(["git", "rev-parse", "--verify", "--quiet", f"origin/{o.base}"], repo) else o.base
    have_gh = _ok(["gh", "auth", "status"], repo)
    res = Result()
    res.closes = _closes(repo, o, base_ref, have_gh, body_path)

    subjects = _out(["git", "log", f"{base_ref}..HEAD", "--format=%s"], repo).splitlines()
    text = body_path.read_text()
    if any(s.startswith("wip(") for s in subjects) and WIP_NOTE not in text:
        body_path.write_text(text.rstrip("\n") + f"\n\n{WIP_NOTE}\n")

    if _out(["git", "status", "--porcelain"], repo):
        add = run(["git", "add", "-A"], cwd=repo, check=False)
        com = run(["git", *core.git_identity(repo), "commit", "-q", "-s", "-m", o.message or o.title], cwd=repo, check=False) \
            if add.returncode == 0 else add
        if com.returncode == 0:
            sha = _out(["git", "rev-parse", "--short=7", "HEAD"], repo)
            res.commit = ("done", sha, f"done {sha}")
        else:
            res.commit = ("failed", None, _last(com))
    else:
        ahead = int(_out(["git", "rev-list", "--count", f"{base_ref}..HEAD"], repo) or 0)
        if ahead:
            res.commit = ("skipped", None, f"skipped (clean tree, {ahead} commits ahead)")
        else:
            res.commit = ("failed", None, "nothing to commit")
    if res.commit[0] == "failed":
        return res

    push = run(["git", "push", "-u", "origin", branch], cwd=repo, check=False)
    if push.returncode != 0:
        res.push = ("failed", _last(push))
        return res
    res.push = ("done", "")

    existing = []
    if have_gh:
        try:
            existing = json.loads(_out(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url"], repo) or "[]")
        except ValueError:
            existing = []
    if existing:
        res.pr = ("failed", existing[0]["url"], None, f"already open {existing[0]['url']}")
        return res
    create = ["gh", "pr", "create", "--base", o.base, "--head", branch, "--title", o.title, "--body-file", o.body_file]
    if o.no_pr or not have_gh or not pr_allowed(repo):
        res.pr = ("ready", None, shlex.join(create), "")
        return res
    made = run(create, cwd=repo, check=False)
    if made.returncode != 0:
        res.pr = ("failed", None, None, _last(made))
    else:
        url = (made.stdout or "").strip().splitlines()[-1:] or [""]
        res.pr = ("opened", url[0], None, "")
    return res
