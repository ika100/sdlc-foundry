"""Spec 198 test support: the release hold file, a fake clock behind the module seams (`release_hold.now/sleep/alive`,
`merge_lock.sleep/time`) and a way to hold the merge lock from the test.

Contract: docs/specs/198-a-platform-release-holds-main-through/design.md. The tests write and read the hold file by its documented
path and JSON shape and never through `release_hold` itself, so the file format is part of what they check."""
import datetime as dt
import fcntl
import json
import os
import types

import pytest

import dispatch_state
import ship

SLUG = "acme/shop"
BASE = dt.datetime(2026, 11, 16, 10, 20, 0)
OTHER_PID = 4242


def hold_path(slug=SLUG):
    return dispatch_state.merge_lock_path(slug).with_name(f"{dispatch_state.slug_dir(slug)}.release-hold.json")


def write_hold(slug=SLUG, **fields):
    doc = {"slug": slug, "version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": OTHER_PID, "state": "running",
           "confirm": None, "expires": None, **fields}
    hold_path(slug).parent.mkdir(parents=True, exist_ok=True)
    hold_path(slug).write_text(json.dumps(doc))
    return doc


def stopped_hold(slug=SLUG, confirm="merge", expires="2026-11-16T12:20:00", **fields):
    return write_hold(slug, state="stopped", confirm=confirm, expires=expires, **fields)


def read_hold(slug=SLUG):
    try:
        return json.loads(hold_path(slug).read_text())
    except (OSError, ValueError):
        return None


def drop_hold(slug=SLUG):
    hold_path(slug).unlink(missing_ok=True)


class Clock:
    """Seconds since BASE. `sleep` advances it and runs the hooks that are due; nothing sleeps for real."""

    def __init__(self):
        self.t = 0.0
        self.live = {os.getpid()}
        self._hooks = []

    def now(self):
        return BASE + dt.timedelta(seconds=self.t)

    def monotonic(self):
        return self.t

    def alive(self, pid):
        return pid in self.live

    def at(self, seconds, fn):
        """Run `fn` once, during the first sleep that brings the clock to `seconds` or past it."""
        self._hooks.append([seconds, fn, False])

    def every(self, fn):
        self._hooks.append([0, fn, True])

    def sleep(self, seconds):
        self.t += seconds
        for hook in list(self._hooks):
            due, fn, repeat = hook
            if self.t >= due:
                if not repeat:
                    self._hooks.remove(hook)
                fn()


@pytest.fixture()
def clock(monkeypatch):
    import merge_lock
    import release_hold
    c = Clock()
    monkeypatch.setattr(release_hold, "now", c.now)
    monkeypatch.setattr(release_hold, "sleep", c.sleep)
    monkeypatch.setattr(release_hold, "alive", c.alive)
    monkeypatch.setattr(dispatch_state, "now", c.now)
    monkeypatch.setattr(merge_lock, "sleep", c.sleep)
    monkeypatch.setattr(merge_lock, "time", types.SimpleNamespace(monotonic=c.monotonic, sleep=c.sleep))
    return c


@pytest.fixture()
def said(monkeypatch):
    lines = []
    monkeypatch.setattr(ship, "say", lines.append)
    return lines


def busy_lock(slug=SLUG, who="pr 10"):
    """Take the merge lock of `slug` from the test (as a merge inside the lock does); returns the function that lets go."""
    path = dispatch_state.merge_lock_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(path, "a")
    fcntl.flock(fd, fcntl.LOCK_EX)
    dispatch_state.write_json(dispatch_state.merge_info_path(slug), {"who": who, "pid": os.getpid(), "since": "10:20:00"})

    def let_go():
        dispatch_state.merge_info_path(slug).unlink(missing_ok=True)
        if not fd.closed:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
    return let_go


def lock_is_free(slug=SLUG):
    """True when the merge lock can be taken right now (a second open file description, so this process is no exception)."""
    path = dispatch_state.merge_lock_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
