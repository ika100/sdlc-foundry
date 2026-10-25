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
    if len(argv) != 1 or argv[0] not in _scripts(cwd):
        print("usage: cplat quiet <devbox-script>   (a key of shell.scripts in ./devbox.json; no other arguments)",
              file=sys.stderr)
        return 2
    script = argv[0]
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
        print(f"FAILED (exit {rc}): devbox run {script} (log: {log})")
        print("\n".join(lines[-TAIL:]))
    return rc
