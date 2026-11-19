"""The release hold (spec 198, ADR-089): a platform release holds `main` of its repo against every cplat merge until its tag
is pushed. The hold is a file beside the merge lock, because a release outlives any flock (it exits at its confirmation stops).

  `<state>/locks/<owner>__<name>.release-hold.json`    the hold: version, since, pid, running or stopped (+ expiry)
  `<state>/locks/<owner>__<name>.release-hold.lock`    a short mutex for every read-modify-write of that file

A running hold whose process is gone is dropped, a stopped hold is dropped after its expiry, by whoever checks it; the
readers that only show a hold (`view`) treat such a hold as absent and leave the file alone.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import fcntl
import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import dispatch_state
import ship
from core import PlatformError

HOLD_POLL = 5            # seconds between two checks of a waiting merge
WAIT_LINE_EVERY = 60     # seconds between two "waiting for the release hold" lines
STOP_TTL = 2 * 3600      # a hold at a confirmation stop expires this long after the stop
ISO = "%Y-%m-%dT%H:%M:%S"


def now() -> dt.datetime:   # tests replace this
    return dispatch_state.now()


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


def alive(pid: int) -> bool:   # tests replace this
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class Hold:
    slug: str
    version: str
    since: str
    pid: int
    state: str = "running"
    confirm: str | None = None
    expires: str | None = None


def hhmm(iso: str | None) -> str:
    """`YYYY-MM-DD HH:MM` of a stored time."""
    return (iso or "").replace("T", " ")[:16]


class HoldTaken(PlatformError):
    """A second release met a live running hold."""

    def __init__(self, h: Hold):
        super().__init__(f"release {h.version} holds {h.slug} (process {h.pid}, since {hhmm(h.since)}): one release at a time",
                         hint="wait for it to end, or see it with `cplat platform hold`")


def path(slug: str) -> Path:
    return dispatch_state.merge_lock_path(slug).with_name(f"{dispatch_state.slug_dir(slug)}.release-hold.json")


@contextlib.contextmanager
def _mutex(slug: str) -> Iterator[None]:
    p = path(slug).with_suffix(".lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _load(slug: str) -> tuple[Hold | None, dict | None]:
    try:
        doc = json.loads(path(slug).read_text())
    except (OSError, ValueError):
        return None, None
    if not isinstance(doc, dict):
        return None, None
    try:
        return Hold(slug=str(doc.get("slug") or slug), version=str(doc["version"]), since=str(doc["since"]), pid=int(doc["pid"]),
                    state=str(doc.get("state") or "running"), confirm=doc.get("confirm"), expires=doc.get("expires")), doc
    except (KeyError, TypeError, ValueError):
        return None, None


def read(slug: str) -> Hold | None:
    return _load(slug)[0]


def stale(h: Hold) -> str | None:
    """`expired` (a stopped hold past its expiry), `dropped` (a running hold whose process is gone), else None."""
    if h.state == "stopped":
        try:
            if h.expires and now() >= dt.datetime.strptime(h.expires, ISO):
                return "expired"
        except ValueError:
            return "expired"
        return None
    return None if alive(h.pid) else "dropped"


def _line(slug: str, why: str, h: Hold) -> str:
    return f"release hold of {slug} expired" if why == "expired" else f"release hold of {slug} dropped: process {h.pid} is gone"


def view(slug: str) -> dict | None:
    h = read(slug)
    if h is None or stale(h):
        return None
    state = "running" if h.state == "running" else f"stopped at confirm {h.confirm}"
    return {"version": h.version, "since": h.since, "pid": h.pid, "state": state, "expires": h.expires}


def _resolve(slug: str) -> Hold | None:
    h = read(slug)
    if h is None:
        return None
    why = stale(h)
    if why:
        path(slug).unlink(missing_ok=True)
        ship.say(_line(slug, why, h))
        return None
    return h


def resolve(slug: str) -> Hold | None:
    with _mutex(slug):
        return _resolve(slug)


def _write(slug: str, h: Hold) -> None:
    dispatch_state.write_json(path(slug), dataclasses.asdict(h))


def claim(slug: str, version: str) -> tuple[Hold, bool]:
    with _mutex(slug):
        cur = _resolve(slug)
        if cur is not None and cur.state == "running" and cur.pid != os.getpid():
            raise HoldTaken(cur)
        if cur is not None and cur.state == "stopped":
            h = dataclasses.replace(cur, version=version, pid=os.getpid(), state="running", confirm=None, expires=None)
            _write(slug, h)
            return h, True
        if cur is not None:      # the same process claims again
            return cur, False
        h = Hold(slug=slug, version=version, since=now().strftime(ISO), pid=os.getpid())
        _write(slug, h)
        return h, False


def stop(slug: str, confirm: str) -> Hold | None:
    with _mutex(slug):
        cur = read(slug)
        if cur is None or cur.state != "running" or cur.pid != os.getpid():
            return None
        h = dataclasses.replace(cur, state="stopped", confirm=confirm, expires=(now() + dt.timedelta(seconds=STOP_TTL)).strftime(ISO))
        _write(slug, h)
        return h


def release(slug: str) -> bool:
    with _mutex(slug):
        cur = read(slug)
        if cur is None or cur.state != "running" or cur.pid != os.getpid():
            return False
        path(slug).unlink(missing_ok=True)
        return True


def clear(slug: str) -> Hold | None:
    with _mutex(slug):
        cur = read(slug)
        path(slug).unlink(missing_ok=True)
        return cur


def foreign(slug: str) -> Hold | None:
    h = resolve(slug)
    return None if h is None or h.pid == os.getpid() else h


def describe(h: Hold) -> str:
    return f"release {h.version} since {hhmm(h.since)}"


def _waiting(slug: str, h: Hold) -> str:
    return f"waiting for the release hold of {slug}: {describe(h)}"


def _remove_if_unchanged(slug: str, seen: dict | None) -> None:
    with _mutex(slug):
        if _load(slug)[1] == seen:
            path(slug).unlink(missing_ok=True)


def wait_clear(slug: str, h: Hold) -> float:
    """The wait of a merge for a foreign hold: polls every HOLD_POLL seconds until the hold is gone, expired or dropped.
    Returns the seconds waited (the sum of its sleeps)."""
    ship.say(_waiting(slug, h))
    waited = said = 0.0
    while True:
        sleep(HOLD_POLL)
        waited += HOLD_POLL
        cur, raw = _load(slug)
        if cur is None:
            ship.say(f"release hold of {slug} cleared")
            return waited
        why = stale(cur)
        if why:
            _remove_if_unchanged(slug, raw)
            ship.say(_line(slug, why, cur))
            return waited
        if waited - said >= WAIT_LINE_EVERY:
            said = waited
            ship.say(_waiting(slug, cur))


def text(slug: str, v: dict | None) -> str:
    if v is None:
        return f"no release hold on {slug}"
    tail = "running" if v["state"] == "running" else f"{v['state']}, expires {hhmm(v['expires'])}"
    return f"release hold on {slug}: release {v['version']} since {hhmm(v['since'])}, process {v['pid']}, {tail}"
