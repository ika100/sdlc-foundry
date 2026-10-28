"""The source cache of the console (spec 122, AC-122.3, AC-122.42, AC-122.43).

  Source(name, argv)   one `cplat ... --json` call: `read()` runs it with a timeout and keeps `data`, `read_at`, `error`,
                       `unavailable_since`; a failing read never clears the last data
  default_sources()    the sources of design.md, with the paths of the snapshots filled in on every read
  state(...)           the document of `GET /api/state`
  utcnow()             the clock (tests replace it)

Every call runs in its own process, so a hang or crash in `gh` or `kubectl` never blocks the server."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CPLAT = Path(__file__).resolve().parents[1] / "cplat.py"
TIMEOUT = 60.0
STALE_AFTER = timedelta(minutes=2)
REFRESH_EVERY = 30.0
ERROR_CHARS = 300


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


class Source:
    """One cached `cplat ... --json` call. `argv` is a list, or a function returning one (read again on every call)."""

    def __init__(self, name: str, argv: list[str] | Callable[[], list[str]], timeout: float = TIMEOUT):
        self.name = name
        self.argv = argv
        self.timeout = timeout
        self.data: Any = None
        self.read_at: str | None = None
        self.error: str | None = None
        self.unavailable_since: str | None = None
        self.version = 0
        self._read_lock = threading.Lock()

    def _command(self) -> list[str]:
        return list(self.argv() if callable(self.argv) else self.argv)

    def _run(self) -> tuple[Any, str | None]:
        try:
            done = subprocess.run(self._command(), capture_output=True, text=True, timeout=self.timeout,  # noqa: S603
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return None, f"timed out after {self.timeout:g} s"
        except OSError as e:
            return None, f"cannot run: {e}"
        try:
            return json.loads(done.stdout), None   # some commands exit 1 and still print their document (doctor)
        except ValueError:
            pass
        text = (done.stderr or done.stdout or "").strip()
        lines = text.splitlines()
        message = lines[-1] if lines else ""
        if done.returncode:
            return None, (message or f"exit {done.returncode}")[-ERROR_CHARS:]
        return None, f"not JSON: {(message or 'empty output')[:ERROR_CHARS]}"

    def read(self) -> None:
        """Run the call once and update the cache. Reads of one source never overlap."""
        with self._read_lock:
            data, error = self._run()
            now = iso(utcnow())
            changed = False
            if error is None:
                changed = data != self.data or self.error is not None
                self.data, self.read_at, self.error, self.unavailable_since = data, now, None, None
            else:
                changed = error != self.error
                self.error = error
                self.unavailable_since = self.unavailable_since or now
            if changed:
                self.version += 1

    def read_in_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.read, name=f"read-{self.name}", daemon=True)
        thread.start()
        return thread

    def ok(self) -> bool:
        return self.error is None and self.read_at is not None

    def is_stale(self, now: datetime | None = None) -> bool:
        """Never read, or last read more than 2 minutes ago (AC-122.43)."""
        when = parse_iso(self.read_at)
        return when is None or (now or utcnow()) - when > STALE_AFTER

    def info(self) -> dict:
        return {"ok": self.ok(), "read_at": self.read_at, "unavailable_since": self.unavailable_since, "error": self.error}


def cplat_argv(*words: str) -> list[str]:
    return [sys.executable, str(CPLAT), *words]


def default_sources(repo_dir: Path, snapshot: Callable[[str | None], Path]) -> dict[str, Source]:
    """The fixed sources. `snapshot(repo)` is the directory of that repo's `main` (None = the gitops repo itself)."""
    return {
        "model": Source("model", lambda: cplat_argv("model", "show", "--json", "--repo-dir", str(snapshot(None)))),
        "status": Source("status", lambda: cplat_argv("system", "status", "--json", "--repo-dir", str(snapshot(None)))),
        "autonomy": Source("autonomy", lambda: cplat_argv("system", "autonomy", "show", "--json", "--repo-dir", str(snapshot(None))),
                           timeout=60),
        "needs": Source("needs", lambda: cplat_argv("needs", "--json", "--repo-dir", str(repo_dir))),
        "runs": Source("runs", lambda: cplat_argv("runs", "--json", "--since", "90")),
        "doctor": Source("doctor", lambda: cplat_argv("platform", "doctor", "--json", "--repo", str(repo_dir))),
    }


def spec_source(repo: str | None, snapshot: Callable[[str | None], Path]) -> Source:
    name = f"specs:{repo}" if repo else "specs:gitops"
    return Source(name, lambda: cplat_argv("spec", "--repo", str(snapshot(repo)), "list", "--all", "--detail", "--json"))


def system_repos(model_data: Any) -> list[str]:
    """The `owner/name` of each component repo in a `cplat model show --json` document."""
    found: list[str] = []
    for comp in (model_data or {}).get("components", []) if isinstance(model_data, Mapping) else []:
        repo = comp.get("repo") if isinstance(comp, Mapping) else None
        if isinstance(repo, str) and "/" in repo and repo not in found:
            found.append(repo)
    return found


def sync_spec_sources(sources: dict[str, Source], snapshot: Callable[[str | None], Path]) -> list[Source]:
    """Add a `specs:<repo>` source for each system repo the model names; returns the new ones."""
    model = sources.get("model")
    added = []
    for repo in system_repos(model.data if model else None):
        if f"specs:{repo}" not in sources:
            sources[f"specs:{repo}"] = src = spec_source(repo, snapshot)
            added.append(src)
    return added


PREREQUISITES = ("claude", "gh")   # exact names; `kube:<env>` is matched by its prefix (not the generic "kube context")


def banner(doctor: Source | None) -> list[dict]:
    """The prerequisites the doctor reports as missing, each with its fix (AC-122.41)."""
    rows = doctor.data if doctor and isinstance(doctor.data, list) else []
    out = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("status") == "ok" or not row.get("fix"):
            continue
        name = str(row.get("name", ""))
        if name in PREREQUISITES or name.startswith("kube:"):
            out.append({"piece": name, "fix": row["fix"]})
    return out


def state(sources: Mapping[str, Source], actions: Mapping[str, int], now: datetime | None = None) -> dict:
    """The document of `GET /api/state` (without the per-start token)."""
    now = now or utcnow()
    current = list(sources.items())
    read_ats = [parse_iso(s.read_at) for _, s in current if s.read_at]
    oldest = min((r for r in read_ats if r), default=None)
    needs = sources.get("needs")
    items = needs.data.get("items") if needs and isinstance(needs.data, Mapping) else None
    return {
        "read_at": iso(oldest) if oldest else None,
        "stale": oldest is None or now - oldest > STALE_AFTER,
        "badge": len(items) if isinstance(items, list) else 0,
        "actions": {"running": int(actions.get("running", 0)), "failed": int(actions.get("failed", 0))},
        "sources": {name: s.info() for name, s in current},
        "banner": banner(sources.get("doctor")),
        "version": sum(s.version for _, s in current),
    }


class Refresher(threading.Thread):
    """Read every source at once and again every 30 s; `refresh(names)` re-reads some at once (AC-122.3, AC-122.42)."""

    def __init__(self, sources: dict[str, Source], snapshot: Callable[[str | None], Path], every: float = REFRESH_EVERY):
        super().__init__(name="refresher", daemon=True)
        self.sources, self.snapshot, self.every = sources, snapshot, every
        self.stop_event = threading.Event()

    def refresh(self, names: list[str] | None = None) -> None:
        threads = []
        for name, source in list(self.sources.items()):
            if names is None or name in names:
                threads.append(source.read_in_background())
        for thread in threads:
            thread.join()
        for added in sync_spec_sources(self.sources, self.snapshot):
            added.read_in_background()

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.refresh()
            self.stop_event.wait(self.every)

    def stop(self) -> None:
        self.stop_event.set()

