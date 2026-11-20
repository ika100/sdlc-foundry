"""Milestone comments on linked issues (spec 158): one place renders and posts the spec-written, spec-approved and pr-merged
comments, under a hidden marker, with per-issue and per-step time limits. Every entry point returns output lines and never
raises, so a comment can never change the result of the command that calls it. Texts come from records or fixed templates."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import spec as spec_mod

ISSUE_LIMIT_S = 20.0  # read + post (+ close) of one issue (AC-158.7)
STEP_LIMIT_S = 120.0  # all milestone work of one command process (AC-158.7); only time spent commenting counts, not a CI wait between steps
SKIP_LABELS = {"auto-filed", "notify", "retro"}
STORY_MAX = 400
QUESTIONS_MAX = 5
CLOSING = re.compile(r"(?<![\w/])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)(?!\d)", re.I)
SUMMARY = re.compile(r"<!-- cplat:summary -->(.*?)<!-- /cplat:summary -->", re.S)
STEP_MSG = f"comment step time limit ({STEP_LIMIT_S:g}s) reached"

_spent = 0.0


class _Skip(Exception):
    """Why one issue (or one read) is skipped; the text goes into the `note:` line."""


def gh(args: list[str], *, cwd: Path, timeout: float) -> tuple[int, str, str]:
    """`gh` with a timeout: (rc, stdout, stderr). Never raises and never retries; `core.run` would wait minutes for a dropped
    network and an hour for a rate limit, which breaks the time limits (design Decisions)."""
    try:
        r = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:g}s"
    except FileNotFoundError:
        return 127, "", "gh not installed"
    except OSError as e:
        return 1, "", str(e)
    return r.returncode, r.stdout, r.stderr


def clock() -> float:
    return time.monotonic()


def reset() -> None:
    """Forget the process's step budget (tests)."""
    global _spent
    _spent = 0.0


def remaining() -> float:
    """Seconds left of the step budget (the full budget before the first call)."""
    return STEP_LIMIT_S - _spent


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0][:200]


def _call(args: list[str], cwd: Path, issue_end: float | None = None) -> str:
    """One gh call inside the time limits; returns stdout or raises `_Skip(why)`."""
    global _spent
    now = clock()
    step_left = remaining()
    issue_left = ISSUE_LIMIT_S if issue_end is None else issue_end - now
    if min(step_left, issue_left) <= 0:
        raise _Skip(STEP_MSG if step_left <= 0 else f"timed out after {ISSUE_LIMIT_S:g}s")
    try:
        rc, out, err = gh(args, cwd=cwd, timeout=min(step_left, issue_left))
    finally:
        _spent += max(0.0, clock() - now)
    if rc != 0:
        raise _Skip(_first_line(err) or _first_line(out) or f"gh exited {rc}")
    return out


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _marker(milestone: str, key: str) -> str:
    return f"<!-- cplat:milestone {milestone} {key} -->"


def post(repo: Path, slug: str, issues: list[int], milestone: str, key: str, body: str, *, close: bool = False,
         closed: dict[int, str] | None = None) -> tuple[list[str], dict[int, str]]:
    """Comment on every issue that has not heard this milestone yet. Returns (output lines, issue -> posted|present|skipped|
    ignored). With `close`, an open issue is then closed as completed, also when its comment was already there; `closed`, when
    given, gets issue -> now|before|failed|no."""
    marker = _marker(milestone, key)
    if marker not in body:
        body = body.rstrip("\n") + "\n\n" + marker
    lines: list[str] = []
    how: dict[int, str] = {}
    for n in dict.fromkeys(issues):
        try:
            end = clock() + ISSUE_LIMIT_S
            info = json.loads(_call(["api", f"repos/{slug}/issues/{n}"], repo, end) or "{}")
            if "pull_request" in info or SKIP_LABELS & {x.get("name") for x in info.get("labels") or []}:
                how[n] = "ignored"
                continue
            comments = _call(["api", "--paginate", f"repos/{slug}/issues/{n}/comments", "--jq", ".[].body"], repo, end)
            if marker in comments:
                how[n] = "present"
            else:
                _call(["api", "-X", "POST", f"repos/{slug}/issues/{n}/comments", "-f", f"body={body}"], repo, end)
                how[n] = "posted"
                lines.append(f"issue #{n}: {milestone} comment posted")
        except Exception as e:  # noqa: BLE001 - a comment never fails its command
            how[n] = "skipped"
            lines.append(f"note: issue comment skipped: #{n} {milestone}: {_why(e)}")
            continue
        if close:
            try:
                if info.get("state") == "open":
                    _call(["issue", "close", str(n), "-R", slug, "--reason", "completed"], repo, end)
                    state = "now"
                else:
                    state = "before"
            except Exception as e:  # noqa: BLE001
                state = "failed"
                lines.append(f"note: issue comment skipped: #{n} {milestone}: {_why(e)}")
            if closed is not None:
                closed[n] = state
    if closed is not None:
        for n, status in how.items():
            closed.setdefault(n, "no")
    return lines, how


def _why(e: Exception) -> str:
    return _first_line(str(e)) or type(e).__name__


# ---------------- texts ----------------

def tracked(spec: spec_mod.Spec) -> list[int]:
    """The issues of this repository a spec tracks: ints and `#N`; anything naming another repository is dropped."""
    out: set[int] = set()
    for item in spec.meta.get("tracks") or []:
        text = str(item).strip().lstrip("#")
        if text.isdigit():
            out.add(int(text))
    return sorted(out)


def first_story(spec: spec_mod.Spec) -> str:
    text = spec_mod.sections(spec.body).get("stories", "")
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if para.startswith("As "):
            story = _collapse(para.split("**Repos:**")[0])
            return story if len(story) <= STORY_MAX else story[:STORY_MAX - 1] + "…"
    return ""


def _planned(spec: spec_mod.Spec) -> str:
    return f"Planned solution: {first_story(spec)} It has {len(spec.active_acs())} acceptance criteria."


def _repo(root: Path) -> tuple[str, str]:
    info = json.loads(_call(["repo", "view", "--json", "nameWithOwner,defaultBranchRef"], root))
    return info["nameWithOwner"], (info.get("defaultBranchRef") or {}).get("name") or "main"


def _spec_link(spec: spec_mod.Spec, slug: str, ref: str) -> str:
    return f"[{spec.id}](https://github.com/{slug}/blob/{ref}/docs/specs/{spec.id}/spec.md)"


def _tracked_notes(issues: list[int], milestone: str, e: Exception) -> list[str]:
    return [f"note: issue comment skipped: #{n} {milestone}: {_why(e)}" for n in issues]


def spec_written(root: Path, spec: spec_mod.Spec, branch: str, pr_url: str) -> list[str]:
    issues = tracked(spec)
    if not issues:
        return []
    try:
        slug, _ = _repo(root)
        questions = spec.open_questions()
        asked = ["Open questions you can answer here:", *(f"- {q}" for q in questions[:QUESTIONS_MAX])]
        if len(questions) > QUESTIONS_MAX:
            asked.append(f"- … and {len(questions) - QUESTIONS_MAX} more")
        body = "\n".join([
            f"Spec {spec.number} for this issue is written: {_spec_link(spec, slug, branch)}, spec PR {pr_url}.", "",
            _planned(spec), "", *(asked if questions else ["No open questions."]), "", _marker("spec-written", spec.id)])
        return post(root, slug, issues, "spec-written", spec.id, body)[0]
    except Exception as e:  # noqa: BLE001
        return _tracked_notes(issues, "spec-written", e)


def _approved_on(spec: spec_mod.Spec) -> str:
    dates = re.findall(r"^\s*-\s+(\d{4}-\d{2}-\d{2})\s+approved\b", spec_mod.sections(spec.body).get("changelog", ""), re.M)
    return dates[-1] if dates else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spec_approved(root: Path, spec: spec_mod.Spec) -> list[str]:
    issues = tracked(spec)
    if not issues:
        return []
    try:
        slug, default = _repo(root)
        body = "\n".join([
            f"Spec {spec.number} approved on {_approved_on(spec)}: {_spec_link(spec, slug, default)}.", "", _planned(spec), "",
            "Next: the build; you will hear here when its PR merges.", "", _marker("spec-approved", spec.id)])
        return post(root, slug, issues, "spec-approved", spec.id, body)[0]
    except Exception as e:  # noqa: BLE001
        return _tracked_notes(issues, "spec-approved", e)


def closing_issues(body: str) -> list[int]:
    """Issues of this repository a PR body closes by a closing keyword and a bare `#N`."""
    return sorted({int(m.group(1)) for m in CLOSING.finditer(body or "")})


def summary_lines(body: str, title: str) -> tuple[str, str]:
    """`Changed` and `Why` of a PR from its spec 157 summary block; without one the PR title and `not recorded`."""
    block = SUMMARY.search(body or "")
    found = {k: m.group(1) for k in ("Changed", "Why")
             if block and (m := re.search(rf"^\s*-\s+\*\*{k}:\*\*[ \t]*(.*)$", block.group(1), re.M))}
    return _collapse(found.get("Changed") or title), _collapse(found.get("Why") or "not recorded")


def pr_merged(repo: Path, pr: str) -> list[str]:
    number = re.search(r"(\d+)\s*$", str(pr))
    try:
        info = json.loads(_call(["pr", "view", str(pr), "--json", "number,url,title,body"], repo))
        slug = re.search(r"github\.com/([^/]+/[^/]+)/pull/", info["url"]).group(1)
        issues = closing_issues(info.get("body", ""))
        if not issues:
            return []
        changed, why = summary_lines(info.get("body", ""), info.get("title", ""))
        body = "\n".join([f"Merged: {info['url']}", "", f"- **Changed:** {changed}", f"- **Why:** {why}", "",
                          "Ships with the next release; you will hear here when it does.", "",
                          _marker("pr-merged", str(info["number"]))])
        return post(repo, slug, issues, "pr-merged", str(info["number"]), body)[0]
    except Exception as e:  # noqa: BLE001
        # the PR could not be read, so its issues are unknown: the note names the PR
        return [f"note: issue comment skipped: #{number.group(1) if number else pr} pr-merged: {_why(e)}"]
