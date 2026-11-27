"""Spec 210: install and remove the status line sensor (design.md "Sensor").

  install() -> str     copy `usage_sensor.py` to `<usage dir>/sensor.py`, point `statusLine` at it, keep the earlier one; the message
  remove() -> str      restore the earlier `statusLine` (or delete it) when it is still the sensor's; the message

The settings file is `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`; the install record is `<usage dir>/sensor.json`.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import dispatch_state as ds
import usage_sensor as us
from core import PlatformError


def settings_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")) / "settings.json"


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as err:
        raise PlatformError(f"{path} is not valid JSON: {err}", "fix or move the file, then rerun") from err
    if not isinstance(doc, dict):
        raise PlatformError(f"{path} is not a JSON object", "fix or move the file, then rerun")
    return doc


def _write_settings(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def _record() -> dict | None:
    try:
        doc = json.loads((us.usage_dir() / "sensor.json").read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _stable_python() -> str:
    """The first `python3` on PATH outside a temporary environment (uv's cache, this process's own venv)."""
    own = {str(Path(p).resolve()) for p in (sys.prefix, sys.exec_prefix)}
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        cand = Path(entry) / "python3" if entry else None
        if cand is None or not (cand.is_file() and os.access(cand, os.X_OK)):
            continue
        if "uv" in cand.parts and {"builds-v0", "environments-v2", "archive-v0"} & set(cand.parts):
            continue
        if str(Path(entry).resolve().parent) in own:
            continue
        return str(cand)
    return "/usr/bin/python3"


def _command(target: Path) -> str:
    return f"{shlex.quote(_stable_python())} {shlex.quote(str(target))}"


def _check(command: str) -> None:
    hint = f"run `echo '{{}}' | {command}` to see why"
    try:
        r = subprocess.run(command, shell=True, input="{}", capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as err:
        raise PlatformError(f"the status line command does not run: {err}", hint) from err
    if r.returncode != 0:
        raise PlatformError(f"the status line command exits {r.returncode}: {r.stderr.strip()[:200]}", hint)


def install() -> str:
    path = settings_path()
    doc = _read_settings(path)
    d = us.usage_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = d / "sensor.py"
    command = _command(target)
    current = doc.get("statusLine")
    rec = _record()
    if isinstance(current, dict) and current.get("command") == command and rec is not None:
        previous = rec.get("previous")
    else:
        previous = current if isinstance(current, dict) else None
        base = {k: v for k, v in (previous or {}).items() if k not in ("type", "command")}
        doc["statusLine"] = {**base, "type": "command", "command": command}
    shutil.copyfile(Path(__file__).with_name("usage_sensor.py"), target)
    _check(command)
    us.write_json_atomic(d / "sensor.json", {"installed_at": ds.stamp(), "settings": str(path), "previous": previous, "command": command})
    _write_settings(path, doc)
    kept = previous.get("command") if isinstance(previous, dict) else None
    return f"sensor installed: {path} (earlier status line kept: {kept})" if kept else f"sensor installed: {path}"


def remove() -> str:
    rec = _record()
    if rec is None:
        return "no sensor installed"
    path = Path(str(rec.get("settings") or settings_path()))
    message = "sensor removed: the status line was changed since the install; left unchanged"
    try:
        doc = _read_settings(path)
    except PlatformError:
        doc = None
    current = doc.get("statusLine") if doc is not None else None
    if doc is not None and isinstance(current, dict) and current.get("command") == rec.get("command"):
        if rec.get("previous") is None:
            del doc["statusLine"]
        else:
            doc["statusLine"] = rec["previous"]
        _write_settings(path, doc)
        message = f"sensor removed: {path}"
    for name in ("sensor.json", "sensor.py"):
        (us.usage_dir() / name).unlink(missing_ok=True)
    return message
