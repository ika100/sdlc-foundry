"""Per-test time limit for the generated test runs (spec 197).

scripts/gate.sh loads this plugin (`-p platform_test_limit`) when the file exists.
A test that runs past LIMIT_S seconds in its setup, body or teardown is failed with
its test id and the limit; the run goes on with the next test. Stdlib and pytest only.

It steps aside (arms nothing) when pytest-timeout is active, for a test with a
`timeout` marker, and where SIGALRM is missing, the thread is not the main one or
another tool already owns SIGALRM.
"""

import os
import signal
import threading

import pytest

LIMIT_S = 120


def _pytest_timeout_active(config):
    """True when pytest-timeout is set to a limit above 0 by option, ini value or PYTEST_TIMEOUT."""
    candidates = [os.environ.get("PYTEST_TIMEOUT")]
    try:
        candidates.append(config.getoption("timeout", default=None))
    except ValueError:
        pass
    try:
        candidates.append(config.getini("timeout"))
    except (ValueError, KeyError):
        pass
    for value in candidates:
        try:
            if value not in (None, "") and float(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _can_arm(item):
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        return False
    if threading.current_thread() is not threading.main_thread():
        return False
    if signal.getsignal(signal.SIGALRM) not in (signal.SIG_DFL, None):
        return False
    if item.get_closest_marker("timeout") is not None:
        return False
    return not _pytest_timeout_active(item.config)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if not _can_arm(item):
        yield
        return

    def on_alarm(signum, frame):
        signal.setitimer(signal.ITIMER_REAL, LIMIT_S)  # a teardown that also blocks is stopped too
        message = f"Timeout (>{LIMIT_S}s): {item.nodeid} ran past the per-test limit of {LIMIT_S} s"
        raise pytest.fail.Exception(message, pytrace=False)

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, LIMIT_S)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
