"""Spec 185 (AC-185.4, AC-185.5): `cplat quiet test-fast` gives up after 9 minutes, stops the run with every process it
started and names the tests that still run, learned from an injected pytest plugin (`test_progress/`)."""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

GIVE_UP_SECONDS = 540             # seam: tests lower it
GIVE_UP_LABEL = "9 min"
MAX_LISTED = 20
STOP_GRACE_SECONDS = 5
PROGRESS_ENV = "PYTEST_PROGRESS_FILE"
PLUGIN_DIR = Path(__file__).resolve().parent / "test_progress"
NOT_REPORTED = "not reported by this test runner"


def progress_env(log: Path) -> tuple[dict[str, str], Path]:
    """Environment additions that load the progress plugin into a pytest run, and the progress file it writes."""
    progress = Path(f"{log}.progress")
    old_path = os.environ.get("PYTHONPATH", "")
    old_opts = os.environ.get("PYTEST_ADDOPTS", "")
    return {
        "PYTHONPATH": f"{PLUGIN_DIR}{os.pathsep}{old_path}" if old_path else str(PLUGIN_DIR),
        "PYTEST_ADDOPTS": f"{old_opts} -p cplat_test_progress".strip(),
        PROGRESS_ENV: str(progress),
    }, progress


def with_env(cmd: list[str], add: dict[str, str]) -> list[str]:
    """`devbox run <script> …` as `devbox run -e KEY=VALUE … <script> …`: devbox resets PYTHONPATH in its own environment."""
    return cmd[:2] + [a for k, v in add.items() for a in ("-e", f"{k}={v}")] + cmd[2:]


def start(cmd: list[str], *, cwd: Path, out, env: dict[str, str]) -> subprocess.Popen:
    """Start `cmd` in its own session, so `stop` reaches every process it starts."""
    return subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True)


def wait_until(proc: subprocess.Popen, deadline: float) -> int | None:
    """Exit code of `proc`, or None when the monotonic `deadline` passes first."""
    import time
    left = deadline - time.monotonic()
    try:
        return proc.wait(timeout=max(left, 0))
    except subprocess.TimeoutExpired:
        return None


def _killpg(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def stop(proc: subprocess.Popen) -> None:
    """SIGTERM the process group, SIGKILL it after the grace period, and reap."""
    _killpg(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    _killpg(proc, signal.SIGKILL)   # also members that outlived the leader
    proc.wait()


def still_running(progress: Path) -> list[str] | None:
    """Tests started and not ended, in start order; None when the file does not exist (not pytest)."""
    try:
        text = progress.read_text(errors="replace")
    except OSError:
        return None
    running: dict[str, None] = {}
    for ln in text.splitlines():
        kind, _, node = ln.partition(" ")
        if kind == "start" and node:
            running[node] = None
        elif kind == "end":
            running.pop(node, None)
    return list(running)


def gave_up_lines(script: str, log: Path, progress: Path) -> list[str]:
    lines = [f"FAILED (gave up after {GIVE_UP_LABEL}): devbox run {script} (log: {log})"]
    tests = still_running(progress)
    if tests is None:
        return lines + [f"still running: {NOT_REPORTED}"]
    lines += [f"still running: {t}" for t in tests[:MAX_LISTED]]
    if len(tests) > MAX_LISTED:
        lines.append(f"... and {len(tests) - MAX_LISTED} more")
    return lines
