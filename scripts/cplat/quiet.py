"""`cplat quiet <devbox-script>`: run a devbox script with its output in a log file (spec 100, AC-100.12).

Success prints one line and the last output line; failure prints the last 40 lines and the log path. The exit code
of the script passes through. Only keys of `shell.scripts` in ./devbox.json are accepted, with no extra arguments.
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


def main(argv: list[str]) -> int:
    cwd = Path.cwd()
    raw = bool(argv) and argv[0] == "--raw"
    args = argv[1:] if raw else argv
    if len(args) != 1 or args[0] not in _scripts(cwd):
        print("usage: cplat quiet [--raw] <devbox-script>   (a key of shell.scripts in ./devbox.json; no other arguments)",
              file=sys.stderr)
        return 2
    script = args[0]
    try:
        on, reason = failsum.enabled(cwd)
    except PlatformError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if raw:
        on, reason = False, "--raw"
    log = _log_path(cwd, script)
    with log.open("wb") as fh:
        rc = subprocess.run(["devbox", "run", script], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT).returncode
    lines = log.read_text(errors="replace").splitlines()
    nonempty = [ln for ln in lines if ln.strip()]
    if rc == 0:
        print(f"ok: devbox run {script} ({len(lines)} lines, log: {log})")
        if nonempty:
            print(nonempty[-1])
    else:
        title = f"FAILED (exit {rc}): devbox run {script} (log: {log})"
        if on:
            s = failsum.summarize("\n".join(lines), title=title, check=script, command=f"devbox run {script}",
                                  exit_code=rc, log=log, root=cwd)
            print(s.render())
            failsum.write_sidecar(log, s)
        else:
            print(failsum.raw(title, "\n".join(lines), reason, TAIL))
    return rc
