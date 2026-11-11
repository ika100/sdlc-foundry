"""Spec 184: repo slots, at most `slots` unattended runs per repo on one machine (design.md "Repo slots").

  total(repo) -> int         the pool size: steering override, else `.platform/dispatch.yml` `slots`, else 1
  holders(slug) -> [Holder]  the live holders (JSON present and its pid running)
  held(repo, command)        context manager that takes a slot (waits, or raises `SlotBusy` with `wait=False`)

A slot is `<state>/locks/<owner>__<name>.slot-<n>.lock`, held by an open, locked file of the process (the kernel frees it when the
process dies), and `.slot-<n>.json` that says who holds it. Every worktree and clone of the repo shares them through the slug.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import core
import dispatch_policy
import dispatch_state
from core import PlatformError

POLL_SECONDS = 15
ENV = "CPLAT_SLOT"


@dataclass(frozen=True)
class Holder:
    slot: int
    command: str
    pid: int
    since: str
    checkout: str
    unit: str | None


class SlotBusy(PlatformError):
    """`--no-wait` and every slot is taken."""


def sleep(seconds: float) -> None:
    """Tests replace this."""
    time.sleep(seconds)


def _lock_path(slug: str, n: int) -> Path:
    return dispatch_state.state_root() / "locks" / f"{dispatch_state.slug_dir(slug)}.slot-{n}.lock"


def _info_path(slug: str, n: int) -> Path:
    return dispatch_state.state_root() / "locks" / f"{dispatch_state.slug_dir(slug)}.slot-{n}.json"


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # PermissionError: the process exists
        return True
    return True


def _read(slug: str, n: int) -> Holder | None:
    doc = dispatch_state.read_json(_info_path(slug, n))
    if doc is None or not isinstance(doc.get("pid"), int):
        return None
    unit = doc.get("unit")
    return Holder(n, str(doc.get("command", "")), doc["pid"], str(doc.get("since", "")), str(doc.get("checkout", "")),
                  unit if isinstance(unit, str) else None)


def total(repo: Path) -> int:
    """Steering override (state.json), else `slots` of `.platform/dispatch.yml`, else 1; a broken file reads as 1."""
    override = dispatch_state.load(dispatch_state.slug_of(repo))["steering"].get("slots")
    if isinstance(override, int) and not isinstance(override, bool) and override >= 1:
        return override
    try:
        return int(dispatch_policy.load(_primary(repo)).values["slots"])
    except PlatformError:
        return 1


def _primary(repo: Path) -> Path:
    """The primary checkout of `repo` (the one the dispatcher reads its policy in), so every worktree sees the same pool size."""
    common = core.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo, check=False).stdout.strip()
    primary = Path(common).parent if common.endswith("/.git") else Path(repo)
    return primary if (primary / dispatch_policy.FILE).is_file() else Path(repo)


def holders(slug: str) -> list[Holder]:
    out = []
    for n in range(1, dispatch_state.MAX_SLOTS + 1):
        h = _read(slug, n)
        if h is not None and _running(h.pid):
            out.append(h)
    return out


def _describe(h: Holder) -> str:
    return f"held by {h.command} (pid {h.pid}, since {h.since}, {h.checkout})"


def _oldest(slug: str, count: int) -> Holder | None:
    live = [h for h in holders(slug) if h.slot <= count]
    return min(live, key=lambda h: (h.since, h.slot)) if live else None


@contextlib.contextmanager
def held(repo: Path, command: str, *, wait: bool = True, say: Callable[[str], object] = print) -> Iterator[int | None]:
    slug = dispatch_state.slug_of(repo)
    if os.environ.get(ENV, "").startswith(f"{slug}#"):
        yield None
        return
    count = total(repo)
    named: tuple[int, int] | None = None
    while True:
        for n in range(1, count + 1):
            path = _lock_path(slug, n)
            path.parent.mkdir(parents=True, exist_ok=True)
            f = open(path, "a+")  # noqa: SIM115  (held for the whole `with`, closed in the finally below)
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                continue
            with contextlib.ExitStack() as stack:
                stack.callback(f.close)
                yield from _own(stack, slug, n, repo, command, say)
            return
        oldest = _oldest(slug, count)
        if oldest is not None:
            if not wait:
                raise SlotBusy(f"slot busy: {_describe(oldest)}")
            if named != (oldest.slot, oldest.pid):
                named = (oldest.slot, oldest.pid)
                say(f"waiting for a slot: {_describe(oldest)}")
        elif not wait:
            raise SlotBusy("slot busy: held by another run")
        sleep(POLL_SECONDS)


def _own(stack: contextlib.ExitStack, slug: str, n: int, repo: Path, command: str, say: Callable[[str], object]) -> Iterator[int]:
    stale = _read(slug, n)
    if stale is not None and stale.pid != os.getpid() and not _running(stale.pid):
        say(f"freed a stale slot of {stale.command} (pid {stale.pid} gone)")
    dispatch_state.write_json(_info_path(slug, n), {
        "command": command, "pid": os.getpid(), "since": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "checkout": str(Path(repo).resolve()), "unit": os.environ.get("CPLAT_DISPATCH_UNIT") or None})
    previous = os.environ.get(ENV)
    os.environ[ENV] = f"{slug}#{n}"

    def restore() -> None:
        if previous is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = previous
        with contextlib.suppress(OSError):
            _info_path(slug, n).unlink()
    stack.callback(restore)
    yield n
