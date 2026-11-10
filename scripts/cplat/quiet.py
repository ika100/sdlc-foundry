"""`cplat quiet <devbox-script>`: run a devbox script with its output in a log file (spec 100, AC-100.12).

Success prints one line and the last output line; failure prints the last 40 lines and the log path. The exit code
of the script passes through. Only keys of `shell.scripts` in ./devbox.json are accepted, only test-fast takes arguments, after `--` (spec 172).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import failsum
from core import PlatformError

TAIL = 40


def _scripts(cwd: Path) -> dict:
    try:
        return json.loads((cwd / "devbox.json").read_text()).get("shell", {}).get("scripts", {}) or {}
    except (OSError, ValueError):
        return {}


def _log_path(cwd: Path, script: str) -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    d = base / "sdlc-foundry" / "logs" / cwd.name
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{datetime.now():%Y%m%d-%H%M%S}-{script}.log"


def _flaky(cwd: Path, summary) -> bool:
    """Spec 165 (AC-165.7): run the few failed tests of `summary` again alone once; True (printed and recorded as
    flaky) when they all pass. Never raises: any problem keeps the first result."""
    try:
        import flaky
        found = flaky.failed_tests(summary)
        if not found:
            return False
        tool, tests = found
        log = _log_path(cwd, "test-fast-rerun")
        with log.open("wb") as fh:
            rc = subprocess.run(["devbox", "run", "test-fast", "--", *flaky.rerun_args(tool, tests)], cwd=cwd, stdout=fh,
                                stderr=subprocess.STDOUT).returncode
        if rc != 0:
            return False
        print(f"ok: devbox run test-fast (flaky: {len(tests)} test(s) failed, then passed when run again alone; log: {log})")
        for t in tests:
            print(f"  flaky: {t}")
        try:
            import runs
            rid = runs.current_run(cwd)
            for t in tests:
                runs.add_to(rid, "flaky_tests", {"test": t, "script": "test-fast"})
        except Exception:  # noqa: BLE001  (recording never changes the result)
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


USAGE = ("usage: cplat quiet [--raw] <devbox-script> | cplat quiet [--raw] test-fast [--repeat N] -- <test args>   "
         "(a key of shell.scripts in ./devbox.json; only test-fast takes arguments, after --)")


def _parse(args: list[str], scripts: dict) -> tuple[str, int | None, list[str]] | None:
    """`<script> [--repeat N] [-- <args>...]` -> (script, repeat or None, args); None when refused."""
    if not args or args[0] not in scripts:
        return None
    script, rest = args[0], args[1:]
    if not rest:
        return script, None, []
    if script != "test-fast":
        return None
    n = None
    if rest[0] == "--repeat":
        if len(rest) < 2 or not rest[1].isdigit() or not 2 <= int(rest[1]) <= 5:
            return None
        n, rest = int(rest[1]), rest[2:]
    if not rest or rest[0] != "--":
        return None
    targs = rest[1:]
    if n is not None and not targs:
        return None
    return script, n, targs


def main(argv: list[str]) -> int:
    cwd = Path.cwd()
    raw = bool(argv) and argv[0] == "--raw"
    args = argv[1:] if raw else argv
    parsed = _parse(args, _scripts(cwd))
    if parsed is None:
        print(USAGE, file=sys.stderr)
        return 2
    script, repeat, targs = parsed
    try:
        on, reason = failsum.enabled(cwd)
    except PlatformError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if raw:
        on, reason = False, "--raw"
    if repeat is not None:
        import quiet_repeat
        return quiet_repeat.run(cwd, repeat, targs, raw=raw, on=on)
    cmd = ["devbox", "run", script] + (["--", *targs] if targs else [])
    log = _log_path(cwd, script)
    with log.open("wb") as fh:
        rc = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT).returncode
    lines = log.read_text(errors="replace").splitlines()
    nonempty = [ln for ln in lines if ln.strip()]
    if rc == 0:
        print(f"ok: devbox run {script} ({len(lines)} lines, log: {log})")
        if nonempty:
            print(nonempty[-1])
    else:
        title = f"FAILED (exit {rc}): devbox run {script} (log: {log})"
        if on:
            s = failsum.summarize("\n".join(lines), title=title, check=script, command=" ".join(cmd),
                                  exit_code=rc, log=log, root=cwd)
            if script == "test-fast" and _flaky(cwd, s):
                return 0
            print(s.render())
            failsum.write_sidecar(log, s)
        else:
            print(failsum.raw(title, "\n".join(lines), reason, TAIL))
    return rc
