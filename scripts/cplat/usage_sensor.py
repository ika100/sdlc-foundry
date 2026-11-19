"""Spec 210: the status line sensor. Stdlib only: `cplat dispatch sensor install` copies this file to `<usage dir>/sensor.py`.

  usage_dir() -> Path                       `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/usage/`
  lock() -> context manager                 the machine-wide `usage.lock` (`fcntl.flock`)
  write_json_atomic(path, doc)              temp file + rename
  record(payload, now) -> None              the readings of a status line input into `readings.json`
  main() -> int                             the status line command: record, chain the earlier command, else print `5h … · 7d …`

A reading always replaces `last`; it joins `history` when `used` or `resets_at` changed or the last entry is 10 minutes old; history
older than 7 days is dropped. A window missing from the input is left alone. `main` swallows every error and exits 0.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WINDOWS = ("five_hour", "seven_day")
HISTORY_GAP = 600.0
HISTORY_KEEP = 7 * 86400.0
CHAIN_TIMEOUT = 10


def usage_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "sdlc-foundry" / "usage"


@contextlib.contextmanager
def lock():
    d = usage_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / "usage.lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def write_json_atomic(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _load(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def record(payload: dict, now: float) -> None:
    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return
    found = {}
    for w in WINDOWS:
        sec = limits.get(w)
        if isinstance(sec, dict) and _num(sec.get("used_percentage")) and _num(sec.get("resets_at")):
            found[w] = {"at": now, "used": sec["used_percentage"], "resets_at": sec["resets_at"]}
    if not found:
        return
    path = usage_dir() / "readings.json"
    with lock():
        doc = _load(path)
        doc["schema"] = 1
        for w in WINDOWS:
            cur = doc.get(w) if isinstance(doc.get(w), dict) else {}
            hist = [h for h in cur.get("history") or [] if isinstance(h, dict)]
            last = cur.get("last") if isinstance(cur.get("last"), dict) else None
            if w in found:
                r = found[w]
                prev = hist[-1] if hist else None
                if (prev is None or prev.get("used") != r["used"] or prev.get("resets_at") != r["resets_at"]
                        or now - float(prev.get("at") or 0) >= HISTORY_GAP):
                    hist.append(r)
                last = r
                hist = [h for h in hist if now - float(h.get("at") or 0) <= HISTORY_KEEP]
            doc[w] = {"last": last, "history": hist}
        write_json_atomic(path, doc)


def _short_line() -> str:
    doc = _load(usage_dir() / "readings.json")

    def used(w: str) -> str:
        last = (doc.get(w) or {}).get("last") if isinstance(doc.get(w), dict) else None
        v = last.get("used") if isinstance(last, dict) else None
        if not _num(v):
            return "?"
        return str(int(v)) if float(v) == int(v) else f"{v:g}"

    return f"5h {used('five_hour')} % · 7d {used('seven_day')} %"


def main() -> int:
    raw = b""
    try:
        raw = sys.stdin.buffer.read()
        now = float(os.environ.get("CPLAT_SENSOR_NOW") or time.time())
        record(json.loads(raw.decode("utf-8")), now)
    except Exception:  # noqa: BLE001  the status line never breaks
        pass
    try:
        previous = (_load(usage_dir() / "sensor.json").get("previous") or {}).get("command")
        if isinstance(previous, str) and previous:
            res = subprocess.run(["sh", "-c", previous], input=raw, capture_output=True, timeout=CHAIN_TIMEOUT, check=False)
            sys.stdout.buffer.write(res.stdout)
        else:
            sys.stdout.write(_short_line() + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
