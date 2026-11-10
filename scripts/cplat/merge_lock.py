"""The repo merge lock (spec 167, ADR-089): every merge into main, from a dispatcher unit or a manual session, holds one
machine-wide lock per repo slug, and a branch that is behind its base is updated and has its checks run again on top
before it merges.

  with merge_lock.held(slug, who, timeout):   an exclusive flock on `<state>/locks/<owner>__<name>.merge.lock`
      caught = merge_lock.catch_up(...)       inside the lock: behind check, `gh pr update-branch`, the new head's checks

The callers (`pr wait --merge`, `ship land`) run `gh pr merge` themselves, so their own error handling stays theirs.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import dispatch_state
import ship
from core import PlatformError, run

WAIT_LINE_EVERY = 60          # seconds between two "waiting for the merge lock" lines
HEAD_POLLS = 5                # polls for the new head after an update


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


class Busy(PlatformError):
    """The merge lock stayed held by someone else past the timeout: no red check, no fix round, no escalation."""

    def __init__(self, slug: str, who: str, since: str):
        super().__init__(f"the merge lock of {slug} is held by {who} since {since}", hint="run it again")


class Conflict(PlatformError):
    """The branch could not be brought up to date with its base: a human decision."""


def slug_of(repo: Path, url: str) -> str:
    """owner/name of the pull request's repo: from its URL, else the repo's origin."""
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/", url or "")
    return m.group(1) if m else dispatch_state.slug_of(repo)


def who_of(url: str) -> str:
    """Who asks for the lock: the pull request, and the dispatcher unit when there is one."""
    who = f"pr {(url or '').rstrip('/').rsplit('/', 1)[-1]}"
    unit = os.environ.get("CPLAT_DISPATCH_UNIT")
    return f"{who} ({unit})" if unit else who


def _holder(slug: str) -> dict:
    try:
        return json.loads(dispatch_state.merge_info_path(slug).read_text())
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def held(slug: str, who: str, timeout: float, interval: float = 5) -> Iterator[None]:
    """Hold the merge lock of `slug`; `Busy` when it stays taken for `timeout` seconds."""
    path, info = dispatch_state.merge_lock_path(slug), dispatch_state.merge_info_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    said = begin
    with open(path, "a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                pass
            holder = _holder(slug)
            since = holder.get("since") or "an unknown time"
            if time.monotonic() - begin > timeout:
                raise Busy(slug, holder.get("who") or "another merge", since)
            if time.monotonic() - said >= WAIT_LINE_EVERY:
                said = time.monotonic()
                ship.say(f"waiting for the merge lock of {slug}: held by {holder.get('who') or 'another merge'} since {since}")
            sleep(interval)
        try:
            dispatch_state.write_json(info, {"who": who, "pid": os.getpid(), "since": dispatch_state.now().strftime("%H:%M:%S")})
            yield
        finally:
            info.unlink(missing_ok=True)
            fcntl.flock(lock, fcntl.LOCK_UN)


@dataclass
class CatchUp:
    """The outcome of `catch_up`: `status` is `green` (merge now) or `red` (the new head's checks failed)."""
    updated: bool = False
    status: str = "green"
    cs: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


BEHIND_TRIES = 4              # reads of the compare answer before the merge is refused


class Unknown(PlatformError):
    """GitHub gave no readable answer on whether the branch is behind its base: a merge on a guess is never done."""


def _behind(repo: Path, slug: str, url: str, head: str) -> tuple[int | None, str]:
    """(commits the head is behind its base, the base branch); None when GitHub gives no readable answer: that is unknown, not 0."""
    base = "main"
    try:
        base = json.loads(ship.gh(["pr", "view", url, "--json", "baseRefName"], cwd=repo, check=False) or "{}").get("baseRefName") or "main"
        out = ship.gh(["api", f"repos/{slug}/compare/{base}...{head}", "--jq", ".behind_by"], cwd=repo, check=False).strip()
    except Exception:  # noqa: BLE001
        return None, base
    return (int(out) if out.isdigit() else None), base


def _known(repo: Path, url: str, watch: ship.CheckWatch, interval: float) -> tuple[int, str, str]:
    """(behind, base, head): the head is read when it is not known yet, an unreadable answer is retried with a growing wait,
    and `Unknown` is raised when it stays unreadable."""
    backoff = max(interval, 1)
    for attempt in range(BEHIND_TRIES):
        head = watch.head or watch.head_sha()
        if head:
            behind, base = _behind(repo, slug_of(repo, url), url, head)
            if behind is not None:
                return behind, base, head
        if attempt < BEHIND_TRIES - 1:
            ship.say(f"  could not tell whether {url} is behind its base; retrying in {int(backoff)}s")
            ship.sleep(backoff)
            backoff = min(backoff * 2, 60)
    raise Unknown(f"could not tell whether {url} is behind its base, so it is not merged",
                  hint="run the merge again; no pull request merges on a guess")


def catch_up(repo: Path, url: str, watch: ship.CheckWatch, timeout: float, interval: float) -> CatchUp:
    """Inside the lock, before the merge: a branch behind its base is updated (a merge commit on the branch, never a force
    push) and the checks of its new head are waited for; the first red one ends it. A conflict raises `Conflict`.
    A head that is not known yet is read; an unreadable answer raises `Unknown` and nothing merges."""
    behind, base, head = _known(repo, url, watch, interval)
    if behind <= 0:
        return CatchUp()
    res = run(["gh", "pr", "update-branch", url], cwd=repo, check=False)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
        raise Conflict(f"{url} conflicts with {base}: a human decision ({detail[0]})",
                       hint="resolve the conflict on the branch, then run the merge again")
    out = CatchUp(updated=True, lines=[f"{url} was behind {base}: updated, waiting for its checks again"])
    for _ in range(HEAD_POLLS):       # the update is visible as a new head commit
        if watch.head_sha() not in (None, head):
            break
        ship.sleep(2)
    while True:
        out.status, out.cs, out.failed = ship.wait_checks(watch, timeout, interval)
        if out.status == "red" or watch.head_sha() in (None, watch.head):
            break                      # a push during the last poll means the green belongs to an old head: wait again
    if out.status != "red":
        out.lines.append(f"GREEN: all {len(out.cs)} check(s) passed on {url} after the update")
    return out
