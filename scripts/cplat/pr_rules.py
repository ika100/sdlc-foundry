"""The PR title rule and the spec rule, shared by CI and the local checks (spec 126, AC-126.11/13/14).

Standard library only: `scripts/check-pr-title.py` and `scripts/check-spec-required.py` load this file by path in CI,
where nothing else of the platform is installed.
"""
from __future__ import annotations

import re
import subprocess

TITLE_PATTERN = r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)(\(.+\))?!?: .{1,72}$"   # the pr-title job's pattern
MAX_SUBJECT = 72
NO_SPEC = "no-spec"
CLOSES = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#\d+", re.I)
CODE = ("scripts/", "plugins/", "templates/")

_TYPES = "feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert"
_SPLIT = re.compile(rf"^({_TYPES})(?:\(([^()]+)\))?(!)?: (.*)$", re.S)
_TRAIL = re.compile(r"\s+[-—–:;,.]+$")   # a separator left standing alone at the cut


def title_error(title: str) -> str | None:
    """None when the title passes the pr-title job, else the message CI prints after `ERROR: `."""
    if re.match(TITLE_PATTERN, title):
        return None
    return f"PR title does not follow Conventional Commits.\n  Got:     {title}\n  Pattern: type(scope): description (≤72 chars)"


def _fits(subject: str) -> bool:
    return 1 <= len(subject) <= MAX_SUBJECT and len(subject.encode()) <= MAX_SUBJECT


def fit(title: str) -> str:
    """A title the platform builds, shortened to 72 characters and 72 UTF-8 bytes of subject. ValueError when it has no type."""
    m = _SPLIT.match(title)
    if not m:
        raise ValueError(f"not a Conventional Commits title: {title!r}")
    kind, scope, bang, subject = m.groups()
    subject = " ".join(subject.split())
    if not subject:
        raise ValueError(f"title without a subject: {title!r}")
    if not _fits(subject):
        for k in range(len(subject), -1, -1):
            cut = _TRAIL.sub("", subject[:k].rstrip()).rstrip() + "..."
            if _fits(cut):
                subject = cut
                break
    return f"{kind}{f'({scope})' if scope else ''}{bang or ''}: {subject}"


def spec_error(body: str, labels: list[str], files: list[str]) -> str | None:
    """None when the PR is fine, else the error message."""
    if NO_SPEC in labels or not CLOSES.search(body or ""):
        return None
    code = [f for f in files if f.startswith(CODE)]
    if not code or any(f.startswith("docs/specs/") for f in files):
        return None
    return (f"this PR closes an issue and changes {len(code)} platform file(s) ({', '.join(code[:3])}{' …' if len(code) > 3 else ''}) "
            "but no spec under docs/specs/. Write one with /component:spec (CLAUDE.md: platform changes start with a spec), "
            "or add the label `no-spec` for a one-line fix or docs.")


def changed_files(repo, base: str, head: str = "HEAD") -> list[str]:
    """The files `git diff --name-only <base>...<head>` lists in `repo`."""
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()
