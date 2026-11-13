"""The real-sleep guard of the `cplat` suite (spec 185, AC-185.3).

`install()` replaces `time.sleep` and `asyncio.sleep` before any `cplat` module binds them. While a test is armed (setup, call and
teardown), a sleep called from repository code that would take the test over `LIMIT_S` seconds in total does not sleep: it raises
`pytest.fail.Exception` and is recorded, so a sleep in a thread or one swallowed by `except BaseException` still fails the test.
Sleeps called from the standard library or site-packages, and from `tests/cplat/waiting.py`, are passed through uncounted.
"""
import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import pytest

LIMIT_S = 1.0
ROOT = Path(__file__).resolve().parents[2]
EXEMPT = {ROOT / "tests/cplat/waiting.py"}

_REAL_SLEEP = time.sleep
_REAL_ASYNC_SLEEP = asyncio.sleep
_LOCK = threading.Lock()
_state = {"armed": False, "used": 0.0, "failures": []}
_installed = False
_resolved: dict[str, str | None] = {}


def _rel(filename: str) -> str | None:
    """The POSIX path of `filename` relative to ROOT, or None when it is outside ROOT or exempt."""
    key = f"{filename}\0{ROOT}"
    if key not in _resolved:
        path = Path(os.path.realpath(filename))
        root = Path(os.path.realpath(ROOT))
        exempt = {Path(os.path.realpath(p)) for p in EXEMPT}
        try:
            rel = path.relative_to(root).as_posix() if path not in exempt else None
        except ValueError:
            rel = None
        _resolved[key] = rel
    return _resolved[key]


def _check(seconds, frame) -> None:
    """Count `seconds` against the armed test; raise instead of sleeping when it would cross the limit."""
    if not _state["armed"]:
        return
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return
    rel = _rel(frame.f_code.co_filename)
    if rel is None:
        return
    with _LOCK:
        if _state["used"] + s > LIMIT_S:
            msg = (f"real sleep of {s:g} s at {rel}:{frame.f_lineno} takes this test over 1 s; "
                   "wait for an event or a file, or use the fake clock")
            _state["failures"].append(msg)
            raise pytest.fail.Exception(msg, pytrace=False)
        _state["used"] += s


def _sleep(seconds):
    _check(seconds, sys._getframe(1))
    return _REAL_SLEEP(seconds)


def _async_sleep(delay, result=None):
    # A plain function, not a coroutine: the caller's frame is the one that calls `asyncio.sleep(...)`.
    _check(delay, sys._getframe(1))
    return _REAL_ASYNC_SLEEP(delay, result)


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    time.sleep = _sleep
    asyncio.sleep = _async_sleep


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _state.update(armed=True, used=0.0, failures=[])
    try:
        yield
    finally:
        _state["armed"] = False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if _state["failures"] and report.passed:
        report.outcome = "failed"
        report.longrepr = _state["failures"][0]
        _state["failures"] = []
