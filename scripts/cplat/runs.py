"""Run records (spec 087, ADR-032): every run of the platform ends in one JSON line in a private run store.

Public API for the callers (ship, pr wait, headless, doctor) and for later specs (088-097):

  start(kind, repo=, spec=, mode=, resumes=, parent=) -> run_id     an in-progress record, local only
  phase / ci_round / rerun / event / set_section / add_to / filed    change it in place (never raise, print nothing)
  finish(run_id, outcome, escalation=, fields=)                      redact, buffer, flush; at most one stderr line
  flush(budget=, strict=) -> FlushResult                             buffer (and pending filings) -> store
  store_status() / buffered_count() / pending_count()                for `cplat doctor`
  attach_point(repo) / link_parent(run_id)                           nested runs and headless parents
  init(slug)                                                         create the private store repo

A run is only ever written once, at `finish`; the store is `$CPLAT_RUNS_REPO` (owner/name), reached through
`open_store()` (transport: runs_store). Without a reachable private store the line waits in a local buffer
(1000 records). Recording never raises into a caller and never changes an exit code or stdout.

  mutate(run_id, change) -> "ok"|"none"|"error" / current_run(repo) / mark_incomplete(run_id, section, problem)
                                                                     hooks for agent metrics (spec 089, runs_agents)

  cplat runs init <owner/name> | flush | report [--json] [--since DAYS] [--repo R]
              [--agents [--by-version] [--agent NAME] [--shape SHAPE]]
  cplat runs begin <kind> [--spec S] | phase <name> | end --outcome O [--reason R] [--cause C]
  cplat runs agent <event> ...                                       agent metrics of the current run (spec 089)
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import importlib
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import core
import feedback
import runs_report
import runs_store
from core import PlatformError

SCHEMA = 1
KINDS = ("ship", "build", "headless", "pr-wait", "fleet", "retro", "product-ship")   # documentation; any valid kind works
OUTCOMES = ("done", "escalated", "failed", "abandoned")
CAUSES = ("platform", "code", "decision", "environment", "unknown")
RERUN_REASONS = ("stale", "stuck", "transient")
FILED_RESULTS = ("new", "+1", "suppressed", "pending")
BUFFER_CAP = 1000
BUDGET_SECONDS = 20.0
BATCH = 200
MAX_TEXT = 500
RESERVED = {"schema", "run_id", "kind", "repo", "spec", "platform_version", "mode", "started_at", "ended_at", "phases",
            "ci_rounds", "reruns", "escalation", "filed", "outcome", "resumes", "parent"}
FILERS: dict[str, Callable[[dict, float], tuple[str, str]]] = {}   # name -> retry(entry, timeout) -> (url, result)

_KIND_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_SLUG_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_MODULE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_IDENTIFIERS = {"run_id", "resumes", "parent", "repo", "spec", "platform_version", "started_at", "ended_at"}


def utcnow() -> datetime.datetime:   # tests replace this
    return datetime.datetime.now(datetime.timezone.utc)


def monotonic() -> float:            # tests replace this; shares runs_store's clock so call timeouts and budget agree
    return runs_store.monotonic()


def _iso(when: datetime.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def state_dir() -> Path:
    env = os.environ.get("CPLAT_RUNS_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "sdlc-foundry" / "runs"


def configured_repo() -> str | None:
    slug = os.environ.get("CPLAT_RUNS_REPO", "").strip()
    return slug if _SLUG_RE.match(slug) else None


def open_store(slug: str) -> runs_store.Store:   # tests replace this
    return runs_store.GitHubStore(slug)


def repo_slug(repo_dir: Path) -> str | None:
    """owner/name of origin, else the directory name. Never raises."""
    try:
        url = core.run(["git", "remote", "get-url", "origin"], cwd=repo_dir, check=False).stdout.strip()
        m = re.search(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
        return Path(repo_dir).resolve().name or None
    except Exception:  # noqa: BLE001
        return None


# ---------------- local state ----------------

@contextlib.contextmanager
def _locked() -> Iterator[None]:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _active_path(run_id: str) -> Path:
    return state_dir() / "active" / f"{run_id}.json"


def _read_active(run_id: str | None) -> dict | None:
    if not run_id or not re.fullmatch(r"[\w.-]+", run_id):
        return None
    try:
        return json.loads(_active_path(run_id).read_text())
    except (OSError, ValueError):
        return None


def _write_active(rec: dict) -> None:
    _atomic_write(_active_path(rec["run_id"]), json.dumps(rec, ensure_ascii=False))


def _read_lines(name: str) -> list[dict]:
    try:
        text = (state_dir() / name).read_text()
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _key(item: dict) -> str:
    return item["run_id"] + "/" + item["signature"] if item.get("followup") else item["run_id"]


def _when(item: dict) -> str:
    return str(item.get("at") if item.get("followup") else item.get("ended_at") or "")


def _read_buffer() -> list[dict]:
    return [i for i in _read_lines("buffer.jsonl") if "run_id" in i and (not i.get("followup") or "signature" in i)]


def _write_buffer(items: list[dict]) -> None:
    _atomic_write(state_dir() / "buffer.jsonl", "".join(_dump(i) + "\n" for i in items))


def _buffer_add(item: dict) -> int:
    """Add (or replace by key) under the lock held by the caller; returns how many oldest lines the cap dropped."""
    items = [i for i in _read_buffer() if _key(i) != _key(item)] + [item]
    dropped = 0
    if len(items) > BUFFER_CAP:
        dropped = len(items) - BUFFER_CAP
        victims = {id(i) for i in sorted(items, key=_when)[:dropped]}
        items = [i for i in items if id(i) not in victims]
    _write_buffer(items)
    return dropped


def buffered_count() -> int:
    try:
        return len(_read_buffer())
    except Exception:  # noqa: BLE001
        return 0


def _read_filings() -> list[dict]:
    return [e for e in _read_lines("filings.jsonl") if "run_id" in e and "signature" in e]


def _write_filings(entries: list[dict]) -> None:
    _atomic_write(state_dir() / "filings.jsonl", "".join(_dump(e) + "\n" for e in entries))


def pending_count() -> int:
    try:
        return len(_read_filings())
    except Exception:  # noqa: BLE001
        return 0


# ---------------- lifecycle ----------------

def start(kind: str, *, repo: str | None = None, spec: str | None = None, mode: str | None = None,
          resumes: str | None = None, parent: str | None = None, run_id: str | None = None,
          started_at: str | None = None) -> str | None:
    """Create <dir>/active/<run_id>.json and return the run_id (None only if even that failed).

    mode defaults to "headless" when $CPLAT_HEADLESS is set, else "interactive"; parent defaults to $CPLAT_RUN_PARENT.
    run_id/started_at re-create the active record of a run the caller already knows. Calls link_parent(run_id)."""
    try:
        if not _KIND_RE.match(str(kind)):
            return None
        now = utcnow()
        run_id = run_id or f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
        rec = {
            "schema": SCHEMA, "run_id": run_id, "kind": kind, "repo": repo, "spec": spec,
            "platform_version": core.platform_version(),
            "mode": mode or ("headless" if os.environ.get("CPLAT_HEADLESS") else "interactive"),
            "started_at": started_at or _iso(now), "ended_at": None, "phases": [], "ci_rounds": 0, "reruns": [],
            "escalation": None, "filed": [], "outcome": None, "resumes": resumes,
            "parent": parent or os.environ.get("CPLAT_RUN_PARENT") or None,
        }
        with _locked():
            if _read_active(run_id) is None:
                _write_active(rec)
    except Exception:  # noqa: BLE001  (recording never changes a run)
        return None
    link_parent(run_id)
    return run_id


def link_parent(run_id: str | None) -> None:
    """If $CPLAT_RUN_PARENT is set: set this run's parent, add run_id to the parent's `ships` (once), and if
    $CPLAT_HEADLESS is set, set this run's mode to "headless"."""
    parent = os.environ.get("CPLAT_RUN_PARENT")
    if not parent or not run_id:
        return
    try:
        with _locked():
            rec = _read_active(run_id)
            if rec is not None:
                rec["parent"] = parent
                if os.environ.get("CPLAT_HEADLESS"):
                    rec["mode"] = "headless"
                _write_active(rec)
            par = _read_active(parent)
            if par is not None and parent != run_id:
                ships = par.setdefault("ships", [])
                if run_id not in ships:
                    ships.append(run_id)
                    _write_active(par)
    except Exception:  # noqa: BLE001
        pass


def active(run_id: str | None) -> dict | None:
    """A copy of the in-progress record."""
    try:
        return _read_active(run_id)
    except Exception:  # noqa: BLE001
        return None


def _git_common_dir(repo_dir: Path) -> Path | None:
    out = core.run(["git", "rev-parse", "--git-common-dir"], cwd=repo_dir, check=False).stdout.strip()
    if not out:
        return None
    return Path(out) if Path(out).is_absolute() else Path(repo_dir) / out


def attach_point(repo_dir: Path) -> str | None:
    """run_id of the repo's ship run when it is unfinished (phase != done, not escalated) and has a run_id."""
    try:
        common = _git_common_dir(Path(repo_dir))
        if common is None:
            return None
        st = json.loads((common / "cplat-ship.json").read_text())
        if st.get("phase") == "done" or st.get("escalated") or not st.get("run_id"):
            return None
        return st["run_id"]
    except Exception:  # noqa: BLE001
        return None


def mutate(run_id: str | None, change: Callable[[dict], None]) -> str:
    """Apply `change` to the active record under the lock: "ok" | "none" (no run_id, unknown or finished: no-op) |
    "error" (change or write raised; nothing written). Never raises."""
    if not run_id:
        return "none"
    try:
        with _locked():
            rec = _read_active(run_id)
            if rec is None:
                return "none"
            change(rec)
            _write_active(rec)
        return "ok"
    except Exception:  # noqa: BLE001
        return "error"


def _mutate(run_id: str | None, change: Callable[[dict], None]) -> None:
    mutate(run_id, change)


def current_run(repo_dir: Path) -> str | None:
    """run_id of the pointer `<git common dir>/cplat-run.json` when that run is still active, else attach_point."""
    try:
        rid = (_read_pointer(_pointer(Path(repo_dir))) or {}).get("run_id")
        if rid and _read_active(rid) is not None:
            return rid
        return attach_point(Path(repo_dir))
    except Exception:  # noqa: BLE001
        return None


MAX_PROBLEMS = 10


def _add_problem(rec: dict, section: str, problem: str) -> None:
    sec = rec.get(section)
    if not isinstance(sec, dict):
        sec = rec[section] = {"schema": 1, "complete": False, "measured": [], "problems": []}
    sec["complete"] = False
    problems = sec.setdefault("problems", [])
    if problem not in problems and len(problems) < MAX_PROBLEMS:
        problems.append(problem)


def _incomplete_path(run_id: str) -> Path:
    return state_dir() / "active" / f"{run_id}.incomplete.jsonl"


def mark_incomplete(run_id: str | None, section: str, problem: str) -> None:
    """Note on the side file (plain append) and in the active record that `section` is incomplete. Never raises."""
    try:
        if not run_id or not re.fullmatch(r"[\w.-]+", run_id):
            return
        path = _incomplete_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps({"section": section, "problem": problem}) + "\n")
        mutate(run_id, lambda rec: _add_problem(rec, section, problem))
    except Exception:  # noqa: BLE001
        pass


def _merge_incomplete(rec: dict) -> None:
    try:
        lines = _incomplete_path(rec["run_id"]).read_text().splitlines()
    except OSError:
        return
    for line in lines:
        try:
            obj = json.loads(line)
            _add_problem(rec, str(obj["section"]), str(obj["problem"]))
        except Exception:  # noqa: BLE001
            continue


def phase(run_id: str | None, name: str) -> None:
    """Open phase `name`. No-op when the open phase of the same level already has that name. Level = name.count(":").
    Opening a phase closes the open phase of its level and every deeper one."""
    def change(rec: dict) -> None:
        level, now = str(name).count(":"), _iso(utcnow())
        open_ones = [p for p in rec["phases"] if p.get("ended_at") is None]
        if any(p["name"] == name and p["name"].count(":") == level for p in open_ones):
            return
        for p in open_ones:
            if p["name"].count(":") >= level:
                p["ended_at"] = now
        rec["phases"].append({"name": str(name), "started_at": now, "ended_at": None})
    _mutate(run_id, change)


def ci_round(run_id: str | None) -> None:
    _mutate(run_id, lambda rec: rec.__setitem__("ci_rounds", int(rec.get("ci_rounds") or 0) + 1))


def rerun(run_id: str | None, check: str, reason: str) -> None:
    if reason in RERUN_REASONS:
        _mutate(run_id, lambda rec: rec["reruns"].append({"check": check, "reason": reason}))


def event(run_id: str | None, section: str, key: str, data: dict) -> None:
    """Upsert into list `section` the object with "id" == key (a known key is updated in place)."""
    def change(rec: dict) -> None:
        if section in RESERVED:
            return
        items = rec.setdefault(section, [])
        for item in items:
            if isinstance(item, dict) and item.get("id") == key:
                item.update(data)
                return
        items.append({"id": key, **data})
    _mutate(run_id, change)


def set_section(run_id: str | None, name: str, value) -> None:
    if name not in RESERVED:
        _mutate(run_id, lambda rec: rec.__setitem__(name, value))


def add_to(run_id: str | None, name: str, item, *, unique: bool = False) -> None:
    def change(rec: dict) -> None:
        if name in RESERVED:
            return
        items = rec.setdefault(name, [])
        if not (unique and item in items):
            items.append(item)
    _mutate(run_id, change)


def filed(run_id: str | None, signature: str, url: str | None, result: str, *, filer: str | None = None,
          payload: dict | None = None) -> None:
    """Upsert `filed` by signature. A "pending" result also upserts (run_id, signature) into filings.jsonl."""
    if result not in FILED_RESULTS:
        return

    def change(rec: dict) -> None:
        entry = {"signature": signature, "url": url, "result": result}
        for i, f in enumerate(rec["filed"]):
            if f.get("signature") == signature:
                rec["filed"][i] = entry
                break
        else:
            rec["filed"].append(entry)
        others = [e for e in _read_filings() if (e["run_id"], e["signature"]) != (rec["run_id"], signature)]
        if result == "pending":
            others.append({"run_id": rec["run_id"], "signature": signature, "filer": filer, "payload": payload or {},
                           "since": _iso(utcnow())})
        _write_filings(others)
    _mutate(run_id, change)


# ---------------- finish ----------------

def _scrub(value, chain: tuple[str, ...] = ()):
    if isinstance(value, dict):
        return {k: _scrub(v, chain + (k,) if isinstance(k, str) else chain) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, chain) for v in value]
    if isinstance(value, str):
        if chain and (chain[0] in _IDENTIFIERS or chain == ("ships",) or (chain[0] == "phases" and chain[-1] in ("started_at", "ended_at"))
                      or chain == ("filed", "url")):
            return value
        if chain in (("agents", "events", "spec"), ("replans", "spec")):
            return value
        return feedback.redact(value)[:MAX_TEXT]
    return value


def _warning(why: str, buffered: int, dropped: int) -> str:
    extra = f"; {dropped} oldest dropped (the buffer keeps {BUFFER_CAP})" if dropped else ""
    return f"WARNING: run record buffered locally ({why}); {buffered} record(s) buffered{extra}"


def finish(run_id: str | None, outcome: str, *, escalation: dict | None = None, fields: dict | None = None) -> str | None:
    """End the run: close open phases, set ended_at/outcome/escalation (+ `fields`), redact, buffer, flush.

    Returns and prints (stderr) the one warning line when this record is still in the buffer afterwards or records
    were dropped; otherwise None. Never raises."""
    if not run_id:
        return None
    t0, dropped = monotonic(), 0
    try:
        with _locked():
            rec = _read_active(run_id)
            if rec is None:
                return None
            now = _iso(utcnow())
            for p in rec["phases"]:
                if p.get("ended_at") is None:
                    p["ended_at"] = now
            rec["ended_at"] = now
            rec["outcome"] = outcome if outcome in OUTCOMES else "failed"
            if escalation is not None:
                cause = escalation.get("cause")
                rec["escalation"] = {"reason": str(escalation.get("reason", "")), "cause": cause if cause in CAUSES else "unknown"}
            for k, v in (fields or {}).items():
                if k not in RESERVED:
                    rec[k] = v
            _merge_incomplete(rec)
            rec = _scrub(rec)
            dropped = _buffer_add(rec)
            _active_path(run_id).unlink(missing_ok=True)
            _incomplete_path(run_id).unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        return _emit(_warning(f"recording failed: {type(e).__name__}: {e}", buffered_count(), dropped))
    try:
        res = flush(budget=max(0.0, BUDGET_SECONDS - (monotonic() - t0)))
        why = res.detail
    except Exception as e:  # noqa: BLE001
        why = f"recording failed: {type(e).__name__}: {e}"
    still = any(_key(i) == run_id for i in _safe_buffer())
    if still or dropped:
        return _emit(_warning(why or "recording failed: record not written", buffered_count(), dropped))
    return None


def _safe_buffer() -> list[dict]:
    try:
        return _read_buffer()
    except Exception:  # noqa: BLE001
        return []


def _emit(line: str) -> str:
    try:
        print(line, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass
    return line


# ---------------- buffer -> store ----------------

@dataclass
class FlushResult:
    store: str | None          # slug, or None when not configured
    problem: str | None        # None | "unset" | "public" | "unreachable" | "budget"
    detail: str                # human text for the problem ("" when none)
    written: int               # records written by this flush
    followups: int             # follow-up lines written by this flush
    buffered: int              # records + follow-ups left in the buffer
    dropped: int               # dropped by the cap during this call (finish only)
    pending: int               # pending filings left


def _result(slug, problem, detail, written=0, followups=0) -> FlushResult:
    return FlushResult(slug, problem, detail, written, followups, buffered_count(), 0, pending_count())


def _retry_filings(deadline: float, budget: float) -> None:
    for entry in _read_filings():
        remaining = deadline - monotonic()
        if remaining < budget / 2:
            return
        try:
            name = str(entry.get("filer") or "")
            retry = FILERS.get(name)
            if retry is None:
                if not _MODULE_RE.match(name):
                    continue
                retry = importlib.import_module(name).retry_filing
            url, result = retry({"run_id": entry["run_id"], "signature": entry["signature"], "payload": entry.get("payload") or {}},
                                min(10.0, remaining))
            if result not in FILED_RESULTS or result == "pending":
                continue
        except Exception:  # noqa: BLE001  (a failed retry stays pending)
            continue
        with _locked():
            _write_filings([e for e in _read_filings() if (e["run_id"], e["signature"]) != (entry["run_id"], entry["signature"])])
            rec = _read_active(entry["run_id"])
            if rec is not None:
                for f in rec["filed"]:
                    if f.get("signature") == entry["signature"]:
                        f.update({"url": url, "result": result})
                _write_active(rec)
            else:
                follow = _scrub({"schema": SCHEMA, "followup": "filed", "run_id": entry["run_id"], "signature": entry["signature"],
                                 "url": url, "result": result, "at": _iso(utcnow())})
                follow["url"] = url
                _buffer_add(follow)


def flush(*, budget: float = BUDGET_SECONDS, strict: bool = False) -> FlushResult:
    """(1) configured? (2) the store is private? (3) retry each pending filing once while at least half the budget is
    left. (4) write the buffer in ended_at order, 200 per commit, removing each written batch by key.
    strict=True (the CLI) raises PlatformError for unset / public / unreachable instead of returning it."""
    deadline = monotonic() + budget
    slug = configured_repo()
    if slug is None:
        res = _result(None, "unset", "no run store: set CPLAT_RUNS_REPO=<owner/name>, see cplat runs init")
        if strict:
            raise PlatformError("no run store configured (CPLAT_RUNS_REPO is not set)",
                                hint="cplat runs init <owner/name>, then set CPLAT_RUNS_REPO=<owner/name>")
        return res
    store = open_store(slug)

    def unreachable(why: str) -> FlushResult:
        if strict:
            raise PlatformError(f"run store {slug} is unreachable: {why}", hint=f"gh repo view {slug}   (is gh logged in, and may it read the repo?)")
        return _result(slug, "unreachable", f"run store {slug} unreachable: {why}")

    try:
        vis = store.visibility(deadline=deadline)
    except runs_store.StoreError as e:
        return unreachable(str(e))
    if vis != "private":
        if strict:
            raise PlatformError(f"run store {slug} is public; records are only written to a private repo",
                                hint=f"gh repo edit {slug} --visibility private --accept-visibility-change-consequences")
        return _result(slug, "public", f"run store {slug} is public; records are only written to a private repo")
    _retry_filings(deadline, budget)
    items = sorted(_read_buffer(), key=_when)
    written = followups = 0
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        if deadline - monotonic() < 1.0:
            if strict:
                return unreachable("no time left")
            return _result(slug, "budget", f"run store {slug}: no time left within {int(BUDGET_SECONDS)} s", written, followups)
        files = {runs_store.record_path(item): _dump(item) + "\n" for item in batch}
        try:
            store.put(files, f"runs: {len(batch)} record(s)", deadline=deadline)
        except runs_store.StoreError as e:
            res = unreachable(str(e))
            res.written, res.followups = written, followups
            return res
        keys = {_key(item) for item in batch}
        with _locked():
            _write_buffer([x for x in _read_buffer() if _key(x) not in keys])
        followups += sum(1 for item in batch if item.get("followup"))
        written += sum(1 for item in batch if not item.get("followup"))
    return _result(slug, None, "", written, followups)


@dataclass
class StoreStatus:
    slug: str | None
    state: str                 # "unset" | "public" | "unreachable" | "ok"
    detail: str
    buffered: int
    pending: int


def store_status(timeout: float = 10.0) -> StoreStatus:
    """For doctor: one visibility call, never raises."""
    buffered, pending = buffered_count(), pending_count()
    slug = configured_repo()
    if slug is None:
        return StoreStatus(None, "unset", "CPLAT_RUNS_REPO is not set", buffered, pending)
    try:
        vis = open_store(slug).visibility(deadline=monotonic() + timeout)
    except runs_store.StoreMissing:
        return StoreStatus(slug, "unreachable", "repo not found or no access", buffered, pending)
    except Exception as e:  # noqa: BLE001
        return StoreStatus(slug, "unreachable", str(e) or type(e).__name__, buffered, pending)
    if vis != "private":
        return StoreStatus(slug, "public", f"{slug} is {vis}", buffered, pending)
    return StoreStatus(slug, "ok", "", buffered, pending)


def init(slug: str) -> list[str]:
    """Create the private store repo if it is missing; raises PlatformError for a public repo or a gh failure."""
    if not _SLUG_RE.match(slug or ""):
        raise PlatformError(f"`{slug}` is not owner/name", hint="cplat runs init <owner/name>")
    store = open_store(slug)
    lines = []
    try:
        try:
            vis = store.visibility()
        except runs_store.StoreMissing:
            store.create_private()
            lines.append(f"created {slug} (private)")
            vis = "private"
    except runs_store.StoreError as e:
        raise PlatformError(f"run store {slug} is unreachable: {e}", hint=f"gh repo view {slug}   (is gh logged in, and may it read the repo?)") from None
    if vis != "private":
        raise PlatformError(f"{slug} is {vis}: the run store must be private; nothing was changed",
                            hint=f"gh repo edit {slug} --visibility private --accept-visibility-change-consequences, or choose another name")
    lines.append(f"export CPLAT_RUNS_REPO={slug}   # add this to your shell profile")
    return lines


# ---------------- CLI ----------------

def _pointer(repo_dir: Path) -> Path | None:
    common = _git_common_dir(repo_dir)
    return common / "cplat-run.json" if common else None


def _read_pointer(path: Path | None) -> dict | None:
    try:
        return json.loads(path.read_text()) if path else None
    except (OSError, ValueError):
        return None


def _report(ns: argparse.Namespace) -> int:
    if not ns.agents and (ns.by_version or ns.agent or ns.shape):
        raise PlatformError("--by-version, --agent and --shape need --agents", hint="cplat runs report --agents ...")
    slug = configured_repo()
    if slug is None:
        raise PlatformError("no run store configured (CPLAT_RUNS_REPO is not set)",
                            hint="cplat runs init <owner/name>, then set CPLAT_RUNS_REPO=<owner/name>")
    store = open_store(slug)
    now = utcnow()
    days = [now.date() - datetime.timedelta(days=n) for n in range(ns.since, -1, -1)]
    try:
        store.visibility()
        files = store.read(days)
    except runs_store.StoreError as e:
        raise PlatformError(f"run store {slug} is unreachable: {e}", hint=f"gh repo view {slug}   (is gh logged in, and may it read the repo?)") from None
    records, follows, malformed = runs_report.parse([text for _, text in files])
    if ns.agents:
        agg = runs_report.aggregate_agents(records, malformed=malformed, buffered=buffered_count(), since_days=ns.since,
                                           repo=ns.repo, agent=ns.agent, shape=ns.shape, by_version=ns.by_version,
                                           store=slug, now=now)
        print(json.dumps(agg, indent=2) if ns.json else runs_report.render_agents_text(agg))
        return 0
    agg = runs_report.aggregate(records, follows, malformed=malformed, buffered=buffered_count(), since_days=ns.since,
                                repo=ns.repo, store=slug, now=now)
    print(json.dumps(agg, indent=2) if ns.json else runs_report.render_text(agg))
    return 0


def _positive(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat runs", description="Private run records (spec 087, ADR-032).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the private run store repo").add_argument("slug", help="owner/name")
    sub.add_parser("flush", help="write the local buffer to the store")
    r = sub.add_parser("report", help="aggregate the stored runs")
    r.add_argument("--json", action="store_true")
    r.add_argument("--since", type=_positive, default=30, metavar="DAYS")
    r.add_argument("--repo", metavar="OWNER/NAME")
    r.add_argument("--agents", action="store_true", help="per agent, shape and model (spec 089)")
    r.add_argument("--by-version", action="store_true", help="with --agents: one row per platform version")
    r.add_argument("--agent", metavar="NAME", help="with --agents: only this agent (or role)")
    r.add_argument("--shape", metavar="SHAPE", help="with --agents: only this shape")
    b = sub.add_parser("begin", help="start a run record (for markdown commands)")
    b.add_argument("kind")
    b.add_argument("--spec")
    ph = sub.add_parser("phase", help="open a phase of the current run")
    ph.add_argument("name")
    e = sub.add_parser("end", help="end the current run")
    e.add_argument("--outcome", required=True, choices=OUTCOMES)
    e.add_argument("--reason", default="")
    e.add_argument("--cause", default=None)
    for s in (b, ph, e):
        s.add_argument("--dir", default=".")
    return p


def main(argv: list[str]) -> int:
    if argv[:1] == ["agent"]:
        import runs_agents
        return runs_agents.main(argv[1:])
    ns = build_parser().parse_args(argv)
    if ns.cmd == "init":
        for line in init(ns.slug):
            print(line)
        return 0
    if ns.cmd == "flush":
        res = flush(strict=True, budget=120)
        print(f"flushed {res.written} record(s) and {res.followups} follow-up(s) to {res.store}; {res.buffered} left in the buffer; "
              f"{res.pending} pending filing(s)")
        return 0
    if ns.cmd == "report":
        return _report(ns)
    try:
        _recording_command(ns)
    except Exception:  # noqa: BLE001  (begin/phase/end never fail a command)
        pass
    return 0


def _init_agents(kind: str, run_id: str | None) -> None:
    if kind != "build" or not run_id:
        return
    try:
        import runs_agents
        runs_agents.init(run_id)
    except Exception:  # noqa: BLE001
        pass


def _recording_command(ns: argparse.Namespace) -> None:
    repo_dir = Path(ns.dir)
    pointer = _pointer(repo_dir)
    current = _read_pointer(pointer)
    if ns.cmd == "begin":
        rid = attach_point(repo_dir)
        if rid:
            spec = (active(rid) or {}).get("spec") or "run"
            _atomic_write(pointer, json.dumps({"run_id": rid, "kind": ns.kind, "attached": True}))
            _init_agents(ns.kind, rid)
            print(f"run {rid} (attached to ship {spec})")
            return
        if current and not current.get("attached"):
            finish(current.get("run_id"), "abandoned")
        rid = start(ns.kind, repo=repo_slug(repo_dir), spec=ns.spec)
        if rid and pointer:
            _atomic_write(pointer, json.dumps({"run_id": rid, "kind": ns.kind, "attached": False}))
        _init_agents(ns.kind, rid)
        print(f"run {rid}")
    elif ns.cmd == "phase":
        if current:
            phase(current.get("run_id"), ns.name)
    elif ns.cmd == "end":
        if not current:
            return
        if not current.get("attached"):
            esc = {"reason": ns.reason, "cause": ns.cause or "unknown"} if ns.outcome == "escalated" else None
            finish(current.get("run_id"), ns.outcome, escalation=esc)
        if pointer:
            pointer.unlink(missing_ok=True)
