"""The repo merge lock (spec 167, ADR-089): every merge into main, from a dispatcher unit or a manual session, holds one
machine-wide lock per repo slug, and a branch that is behind its base is updated and has its checks run again on top
before it merges.

Inside the lock `held` also checks the release hold of the repo (spec 198): a hold of another process is waited for with the
lock released, that wait does not count against the timeout, and the merge then starts over from the lock. The release sets
its own hold with `set_release_hold`, which waits once for a merge already inside the lock.

  with merge_lock.held(slug, who, timeout):   an exclusive flock on `<state>/locks/<owner>__<name>.merge.lock`
      caught = merge_lock.catch_up(...)       inside the lock: behind check, `gh pr update-branch`, the new head's checks

The callers (`pr wait --merge`, `ship land`) merge through `land_merge` (spec 171), which settles inside this lock: a head
that was not known is read here and guards the merge, a conflict in a generated file is regenerated, the cleanup after the
merge never fails it.
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
import release_hold
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
    """Hold the merge lock of `slug`; `Busy` when it stays taken for `timeout` seconds. A release hold of another process
    (spec 198) is waited for outside the lock and does not count against the timeout."""
    path, info = dispatch_state.merge_lock_path(slug), dispatch_state.merge_info_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    said = begin
    with open(path, "a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                holder = _holder(slug)
                since = holder.get("since") or "an unknown time"
                if time.monotonic() - begin > timeout:
                    raise Busy(slug, holder.get("who") or "another merge", since) from None
                if time.monotonic() - said >= WAIT_LINE_EVERY:
                    said = time.monotonic()
                    ship.say(f"waiting for the merge lock of {slug}: held by {holder.get('who') or 'another merge'} since {since}")
                sleep(interval)
                continue
            hold = release_hold.foreign(slug)       # inside the lock, so no merge starts between the check and the merge
            if hold is None:
                break
            fcntl.flock(lock, fcntl.LOCK_UN)        # wait outside the lock: the release itself must be able to merge
            begin += release_hold.wait_clear(slug, hold)
            said = time.monotonic()
        try:
            dispatch_state.write_json(info, {"who": who, "pid": os.getpid(), "since": dispatch_state.now().strftime("%H:%M:%S")})
            yield
        finally:
            info.unlink(missing_ok=True)
            fcntl.flock(lock, fcntl.LOCK_UN)


def set_release_hold(slug: str, version: str, timeout: float, interval: float = 5) -> release_hold.Hold:
    """Set the release hold of `slug` for `version`, then wait once for a merge already inside the merge lock to end."""
    before = release_hold.read(slug)
    hold, taken = release_hold.claim(slug, version)       # HoldTaken: nothing is written
    path = dispatch_state.merge_lock_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    said: float | None = None
    with open(path, "a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
                break
            except BlockingIOError:
                pass
            who = _holder(slug).get("who") or "another merge"
            if time.monotonic() - begin > timeout:
                release_hold.release(slug)
                raise PlatformError(f"the merge of {who} in {slug} did not end within {int(timeout)}s; the release did not start",
                                    hint="run the release again")
            if said is None or time.monotonic() - said >= WAIT_LINE_EVERY:
                said = time.monotonic()
                ship.say(f"waiting for the merge of {who} to end before the release")
            sleep(interval)
    tail = f" (taken over from the stop at confirm {before.confirm})" if taken and before is not None else ""
    ship.say(f"release hold set on {slug} for {version}{tail}")
    return hold


@dataclass
class CatchUp:
    """The outcome of `catch_up`: `status` is `green` (merge now) or `red` (the new head's checks failed)."""
    updated: bool = False
    status: str = "green"
    cs: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


class Behind(PlatformError):
    """A land that may not change the branch found it behind its base (spec 178, RELEASE)."""

    def __init__(self, base: str, behind: int):
        super().__init__(f"the branch is {behind} commit(s) behind {base}", hint="update the branch, then run the land again")
        self.base, self.behind = base, behind


BEHIND_TRIES = 4             # reads of the compare answer before the merge is refused


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
                if watch.head is None:      # spec 171: the merge carries the head this answer was read for
                    watch.head = head
                return behind, base, head
        if attempt < BEHIND_TRIES - 1:
            ship.say(f"  could not tell whether {url} is behind its base; retrying in {int(backoff)}s")
            ship.sleep(backoff)
            backoff = min(backoff * 2, 60)
    raise Unknown(f"could not tell whether {url} is behind its base, so it is not merged",
                  hint="run the merge again; no pull request merges on a guess")


def await_change(watch: ship.CheckWatch, old: str, timeout: float, interval: float) -> None:
    """Poll until the head of the pull request differs from `old`, bounded by the wait timeout."""
    begin = ship.now()
    while watch.head_sha() in (None, old):
        if ship.now() - begin > timeout:
            raise PlatformError(f"GitHub does not show the updated head of {watch.pr}", hint="run the land again")
        ship.sleep(interval)


def catch_up(repo: Path, url: str, watch: ship.CheckWatch, timeout: float, interval: float, allow: bool = True) -> CatchUp:
    """Inside the lock, before the merge: a branch behind its base is updated (a merge commit on the branch, never a force
    push) and the checks of its new head are waited for; the first red one ends it. A conflict raises `Conflict`.
    A head that is not known yet is read; an unreadable answer raises `Unknown` and nothing merges."""
    behind, base, head = _known(repo, url, watch, interval)
    if behind <= 0:
        return CatchUp()
    if not allow:
        raise Behind(base, behind)
    watch.expect_from_current()
    res = run(["gh", "pr", "update-branch", url], cwd=repo, check=False)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
        raise Conflict(f"{url} conflicts with {base}: a human decision ({detail[0]})",
                       hint="resolve the conflict on the branch, then run the merge again")
    out = CatchUp(updated=True, lines=[f"{url} was behind {base}: updated, waiting for its checks again"])
    await_change(watch, head, timeout, interval)      # the update is visible as a new head commit
    while True:
        out.status, out.cs, out.failed = ship.wait_checks(watch, timeout, interval)
        if out.status == "red" or watch.head_sha() in (None, watch.head):
            break                      # a push during the last poll means the green belongs to an old head: wait again
    if out.status != "red":
        out.lines.append(f"GREEN: all {len(out.cs)} check(s) passed on {url} after the update")
    return out
