"""The one sanctioned way for a `cplat` test to wait (spec 178).

A test waits for an event or a file with a timeout, never for a fixed time. `TEST_FAKE_DELAY` (seconds, not a `CPLAT_*` name,
because `conftest.py` strips those) slows every fake program that starts with `fake_prelude()`; `budget()` grows the timeouts with it.
This file's own poll is the only sleep `scripts/check-test-sleeps.py` exempts.
"""
import os
import subprocess
import time
from pathlib import Path

DELAY = float(os.environ.get("TEST_FAKE_DELAY", "0"))
POLL = 0.02


def budget(base: float = 30) -> float:
    """Every timeout of a wait: `base` plus 20 times the fake delay."""
    return base + 20 * DELAY


def wait_for(pred, timeout: float | None = None, what: str = ""):
    """The first truthy result of `pred()`; AssertionError when `timeout` (default `budget()`) passes first."""
    limit = budget() if timeout is None else timeout
    end = time.monotonic() + limit
    while True:
        result = pred()
        if result:
            return result
        if time.monotonic() >= end:
            raise AssertionError(f"timed out after {limit}s waiting for {what}")
        time.sleep(POLL)


def wait_file(path, timeout: float | None = None, contains: str | None = None) -> str:
    """The file's text once it exists (and holds `contains`)."""
    p = Path(path)

    def read() -> str | None:
        try:
            text = p.read_text()
        except OSError:
            return None
        return text if contains is None or contains in text else None

    result = wait_for(read, timeout, what=f"{p} to exist" + (f" and hold {contains!r}" if contains is not None else ""))
    return str(result)


def wait_process(proc, timeout: float | None = None) -> int:
    """The exit code of `proc`; AssertionError when it runs past the timeout."""
    limit = budget() if timeout is None else timeout
    try:
        return proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"timed out after {limit}s waiting for process {proc.pid} to end") from None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)  # a child that ended but is not yet collected is gone
    except ChildProcessError:
        return True
    return done == 0


def wait_gone(pid: int, timeout: float | None = None) -> None:
    """Return once no process `pid` exists."""
    wait_for(lambda: not _alive(pid), timeout, what=f"process {pid} to end")


def fake_prelude(kind: str = "python") -> str:
    """Program text, for the start of a fake program, that sleeps `TEST_FAKE_DELAY` seconds ("python" or "sh")."""
    if kind == "python":
        return 'import os, time; time.sleep(float(os.environ.get("TEST_FAKE_DELAY", "0")))  # fake-delay: slows the fake by TEST_FAKE_DELAY'
    if kind == "sh":
        return '/bin/sleep "${TEST_FAKE_DELAY:-0}"  # fake-delay: slows the fake by TEST_FAKE_DELAY'
    raise ValueError(f"unknown kind {kind!r}: python or sh")


def with_prelude(text: str) -> str:
    """`text`, a fake program, with `fake_prelude()` inserted after its shebang line ("sh" unless the shebang names python).

    A text that already holds a prelude is returned as it is, so a helper may apply this to what its callers pass."""
    if fake_prelude("python") in text or fake_prelude("sh") in text:
        return text
    first, newline, rest = text.partition("\n")
    if not first.startswith("#!"):
        return fake_prelude("sh") + "\n" + text
    interpreter = first[2:].split()
    shell = interpreter and interpreter[-1].rsplit("/", 1)[-1] in ("sh", "bash", "zsh", "dash")
    return first + newline + fake_prelude("sh" if shell else "python") + "\n" + rest
