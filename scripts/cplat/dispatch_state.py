"""`cplat dispatch` local state (spec 167): the state file, steering, unit files, events, history and the loop lock.

Everything the dispatcher keeps lives under `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/dispatch/<owner>__<name>/` (state.json,
state.lock, loop.lock, needs.json, logs/, worktrees/) and, per unit, in the unit worktree's git dir (`cplat-dispatch-unit.json`,
`cplat-dispatch-result.json`, `cplat-dispatch-stop`). Nothing lives only in memory, so a killed dispatcher is rebuilt from these files.
Every function that touches `state.json` takes the repo slug (`owner/name`) first; writes are atomic and made under `state.lock`.
Items are kept by key (`issue-<N>`, `spec-<NNN>`), see `parse_item`.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import core
from core import PlatformError

SCHEMA = 1
KEEP_DAYS = 90
KEEP_EVENTS = 500
UNIT_FILE = "cplat-dispatch-unit.json"
RESULT_FILE = "cplat-dispatch-result.json"
STOP_FILE = "cplat-dispatch-stop"
MAX_SLOTS = 10


class Busy(PlatformError):
    """Another dispatcher loop holds the loop lock of this repo."""

    def __init__(self, slug: str, pid: int | None):
        super().__init__(f"a dispatcher already runs for {slug} (pid {pid or '?'})",
                         "use `cplat dispatch status`, or stop that dispatcher first")
        self.pid = pid


def now() -> dt.datetime:
    """Local time; every dispatcher module reads the clock here (tests replace it)."""
    return dt.datetime.now()


def today() -> str:
    return now().strftime("%Y-%m-%d")


def stamp() -> str:
    return now().isoformat(timespec="seconds")


# ---------------- paths ----------------

def state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")) / "sdlc-foundry"


def slug_dir(slug: str) -> str:
    return slug.replace("/", "__")


def slug_of(repo: Path | str) -> str:
    """owner/name from the configured origin URL (a `insteadOf` rewrite does not apply), else the directory name."""
    url = core.run(["git", "config", "--get", "remote.origin.url"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else (Path(repo).resolve().name or "unknown")


def base(slug: str) -> Path:
    return state_root() / "dispatch" / slug_dir(slug)


def worktrees_dir(slug: str) -> Path:
    return base(slug) / "worktrees"


def worktree_path(slug: str, key: str) -> Path:
    """`<base>/worktrees/<repo name>-<key>`."""
    return worktrees_dir(slug) / f"{slug.rsplit('/', 1)[-1]}-{key}"


def log_path(slug: str, unit: str) -> Path:
    return base(slug) / "logs" / f"{unit}.log"


def needs_path(slug: str) -> Path:
    return base(slug) / "needs.json"


def needs_files() -> list[Path]:
    """The `needs.json` of every repo that has a dispatcher state (for `cplat needs`)."""
    return sorted((state_root() / "dispatch").glob("*/needs.json"))


def merge_lock_path(slug: str) -> Path:
    return state_root() / "locks" / f"{slug_dir(slug)}.merge.lock"


def merge_info_path(slug: str) -> Path:
    return state_root() / "locks" / f"{slug_dir(slug)}.merge.json"


# ---------------- atomic files ----------------

def write_json(path: Path, doc: object) -> None:
    """Write `doc` as JSON through a temp file and a rename, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=False)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------- the state file ----------------

def empty() -> dict:
    return {"schema": SCHEMA,
            "steering": {"paused": None, "slots": None, "pinned": [], "skipped": {}, "holds": {}},
            "ledger": {}, "counted": {}, "checks": {}, "snapshot": {}, "last_cycle": {},
            "events": [], "history": [], "days": {}, "seq": {}}


def _complete(doc: dict) -> dict:
    """Fill what a state file lacks (an older or partial file) with the empty values."""
    full = empty()
    steering = doc.get("steering") if isinstance(doc.get("steering"), dict) else {}
    full["steering"].update(steering)
    full.update({k: v for k, v in doc.items() if k != "steering"})
    return full


def state_file(slug: str) -> Path:
    return base(slug) / "state.json"


def load(slug: str) -> dict:
    """The state; the empty one for a missing or unreadable file. Reads without the lock (writes are atomic)."""
    doc = read_json(state_file(slug))
    return _complete(doc) if doc is not None else empty()


@contextlib.contextmanager
def _flock(path: Path, *, wait: bool = True) -> Iterator[int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        try:
            yield f.fileno()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def update(slug: str, fn: Callable[[dict], dict | None]) -> dict:
    """Read-modify-write of state.json under state.lock. `fn` changes the state in place (or returns the new one)."""
    with _flock(base(slug) / "state.lock"):
        st = load(slug)
        out = fn(st)
        if isinstance(out, dict):
            st = out
        st["schema"] = SCHEMA
        _prune(st)
        write_json(state_file(slug), st)
        return st


def _prune(st: dict) -> None:
    """Ledger, history and days are kept 90 days; events the last 500."""
    cutoff = (now() - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    for part in ("ledger", "days"):
        st[part] = {d: v for d, v in st.get(part, {}).items() if d >= cutoff}
    st["history"] = [h for h in st.get("history", []) if str(h.get("ended_at") or h.get("started_at") or "9999")[:10] >= cutoff]
    st["events"] = st.get("events", [])[-KEEP_EVENTS:]


# ---------------- items ----------------

def parse_item(text: str) -> str:
    """The key of an item named on the command line: `#123` or a plain `123` is an issue (`issue-123`); `spec-123`, `007` (a
    number with a leading zero) or a spec id such as `167-a-dispatcher-runs-the-backlog-in` is a spec (`spec-167`)."""
    s = text.strip()
    if m := re.fullmatch(r"#(\d+)", s):
        return f"issue-{int(m.group(1))}"
    if m := re.fullmatch(r"issue-(\d+)", s):
        return f"issue-{int(m.group(1))}"
    if m := re.fullmatch(r"(?:spec-)?(\d+)(?:-.*)?", s):
        digits = m.group(1)
        if s == digits and not digits.startswith("0"):
            return f"issue-{int(digits)}"
        return f"spec-{int(digits):03d}"
    raise PlatformError(f"{text!r} is not an item", "name an issue as #<N> and a spec as <NNN>, spec-<NNN> or its id")


def item_of(key: str) -> str:
    """The item as shown: `#123` for `issue-123`, `spec-123` for a spec."""
    return f"#{key[6:]}" if key.startswith("issue-") else key


def unit_key(unit: str) -> str:
    """`issue-123.1` -> `issue-123`."""
    return unit.rsplit(".", 1)[0]


def next_unit(slug: str, key: str) -> str:
    """The id of the item's next unit (`<key>.<seq>`); `seq` counts the item's units."""
    seq = {}

    def go(st: dict) -> None:
        st["seq"][key] = int(st["seq"].get(key, 0)) + 1
        seq["n"] = st["seq"][key]
    update(slug, go)
    return f"{key}.{seq['n']}"


# ---------------- steering ----------------

def pause(slug: str, drain: bool = False) -> str:
    mode = "drain" if drain else "pause"
    update(slug, lambda st: st["steering"].update(paused=mode))
    return mode


def resume(slug: str) -> None:
    update(slug, lambda st: st["steering"].update(paused=None))


def resume_item(slug: str, key: str) -> None:
    """Drop the item's skip and its needs-decision / stuck hold."""
    def go(st: dict) -> None:
        st["steering"]["skipped"].pop(key, None)
        st["steering"]["holds"].pop(key, None)
    update(slug, go)


def set_slots(slug: str, n: int) -> None:
    if not 1 <= n <= MAX_SLOTS:
        raise PlatformError(f"slots {n} is not allowed (allowed: 1..{MAX_SLOTS})")
    update(slug, lambda st: st["steering"].update(slots=n))


def pin(slug: str, key: str) -> None:
    """The item comes first until its unit starts; the most recent pin is first."""
    def go(st: dict) -> None:
        pinned = [k for k in st["steering"]["pinned"] if k != key]
        st["steering"]["pinned"] = [key, *pinned]
    update(slug, go)


def unpin(slug: str, key: str) -> None:
    update(slug, lambda st: st["steering"].update(pinned=[k for k in st["steering"]["pinned"] if k != key]))


def skip(slug: str, key: str, reason: str) -> None:
    update(slug, lambda st: st["steering"]["skipped"].__setitem__(key, {"reason": reason, "at": stamp()}))


def hold(slug: str, key: str, reason: str, unit: str | None) -> None:
    """Hold an item in the state (`needs-decision` of a spec without issue, `stuck`) until `resume <item>`."""
    update(slug, lambda st: st["steering"]["holds"].__setitem__(key, {"reason": reason, "unit": unit, "at": stamp()}))


# ---------------- unit files (in the unit worktree's git dir) ----------------

def unit_git_dir(worktree: Path | str) -> Path:
    gd = core.git_dir(worktree)
    if gd is None:
        raise PlatformError(f"{worktree} is not a git worktree")
    return gd


def unit_path(worktree: Path | str) -> Path:
    return unit_git_dir(worktree) / UNIT_FILE


def result_path(worktree: Path | str) -> Path:
    return unit_git_dir(worktree) / RESULT_FILE


def stop_path(worktree: Path | str) -> Path:
    return unit_git_dir(worktree) / STOP_FILE


def write_unit(worktree: Path | str, data: dict) -> None:
    write_json(unit_path(worktree), {"schema": SCHEMA, **data})


def read_unit(worktree: Path | str) -> dict | None:
    """The unit file of a worktree; None when there is none (or the worktree is gone)."""
    try:
        return read_json(unit_path(worktree))
    except PlatformError:
        return None


def read_result(worktree: Path | str) -> dict | None:
    try:
        return read_json(result_path(worktree))
    except PlatformError:
        return None


def set_stop(worktree: Path | str) -> None:
    stop_path(worktree).write_text(stamp() + "\n")


def clear_stop(worktree: Path | str) -> None:
    with contextlib.suppress(OSError, PlatformError):
        stop_path(worktree).unlink()


def unit_worktrees(slug: str) -> list[Path]:
    """The worktrees under `dispatch/<owner>__<name>/worktrees/` (existing directories)."""
    d = worktrees_dir(slug)
    return sorted(p for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def all_units(slug: str) -> list[dict]:
    """The unit files of every dispatcher worktree: the dispatcher finds its units again from here (AC-167.9)."""
    out = []
    for wt in unit_worktrees(slug):
        if (unit := read_unit(wt)) is not None:
            out.append(unit)
    return out


# ---------------- events, history, days ----------------

def events_add(slug: str, kind: str, unit: str | None, item: str | None, reason: str | None = None, pr: str | None = None) -> int:
    """Append an event (`started|done|escalated|red|stuck|stale`); returns its seq."""
    made: dict = {}

    def go(st: dict) -> None:
        seq = max([int(e.get("seq", 0)) for e in st["events"]] + [int(st.get("event_seq", 0))]) + 1
        st["event_seq"] = seq
        st["events"].append({"seq": seq, "at": stamp(), "kind": kind, "unit": unit, "item": item, "reason": reason, "pr": pr,
                             "seen": False})
        made["seq"] = seq
    update(slug, go)
    return made["seq"]


def events_unseen(slug: str, kinds: tuple[str, ...] | list[str] | None = None) -> list[dict]:
    return [e for e in load(slug)["events"] if not e.get("seen") and (not kinds or e.get("kind") in kinds)]


def mark_seen(slug: str, seq: int) -> None:
    def go(st: dict) -> None:
        for e in st["events"]:
            if e.get("seq") == seq:
                e["seen"] = True
    update(slug, go)


def history_add(slug: str, entry: dict) -> None:
    """`{unit, item, kind, outcome, pr, tokens, reason, started_at, ended_at}`."""
    update(slug, lambda st: st["history"].append(entry))


def days_held(slug: str, day: str, item: str, reason: str) -> None:
    """Record that `item` was held for `reason` on `day` (for `report`)."""
    def go(st: dict) -> None:
        st["days"].setdefault(day, {"held": {}}).setdefault("held", {})[item] = reason
    update(slug, go)


# ---------------- the loop lock ----------------

def loop_lock_path(slug: str) -> Path:
    return base(slug) / "loop.lock"


def loop_pid(slug: str) -> int | None:
    try:
        return int(loop_lock_path(slug).read_text().strip().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None


@contextlib.contextmanager
def loop_lock(slug: str) -> Iterator[None]:
    """Hold the loop lock (one dispatcher loop per repo). Raises `Busy` with the holder's pid when it is held."""
    path = loop_lock_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Busy(slug, loop_pid(slug)) from None
        try:
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()}\n")
            f.flush()
            yield
        finally:
            with contextlib.suppress(OSError):
                f.seek(0)
                f.truncate()
            fcntl.flock(f, fcntl.LOCK_UN)


def loop_alive(slug: str) -> bool:
    """True while another process holds the loop lock."""
    path = loop_lock_path(slug)
    if not path.exists():
        return False
    with open(path, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False
