"""Spec 102 (ADR-043): one budget per run tree, stops at safe points, no-progress stops, a recovery snapshot, verified stages.

Public API for the callers (headless, ship, pr wait, app-ship, runs) and the hook:

  parse_options(["minutes=45", "cost=off"]) -> dict         `--budget KEY=VALUE`; PlatformError for a bad key or value
  open_root(run_id, key, ships=, options=, repo=)           open or continue the ledger of a root run (a child opens none)
  root_of(run_id) -> run_id                                 follows `parent` through the active records
  check(run_id, point) -> limit name | None                 the exhausted limit at a safe point (a run's cost "unknown" is skipped)
  allow_rerun(run_id) -> bool                               asked before a CI rerun; counts it, False when `reruns` is used up
  count_invocation(run_id) / stop(run_id, limit, point)     one more session / write the `budget` section of a stop
  limits_line(run_id) -> str | None                         the start output ("budget: minutes 180, ...")
  attempt(repo, stage, error, failing, names=) -> reason | None   third equivalent failure without progress stops
  snapshot(repo, stage, excerpt, criteria)                  <git common dir>/cplat-recovery.json (local only)
  record_stage(repo, name, result)                          verified stage result for HEAD + inputs
  on_finish(run_id, usage)                                  called by runs.finish: the record's section, the ledger carry

  cplat budget show [--json] | gate [--invocation] | attempt <stage> --failing N [--names a,b] (--error-file F | --error T)
              | stage <name> passed|failed | resume [--json]

The ledger is `runs.state_dir()/budgets/<sha1 of key>.json`; it outlives the run records (one record per resumed run).
Every function that records or reads for a caller swallows its own failure: a broken ledger never stops a run.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import feedback
import runs
import settings
from core import PlatformError, run

LIMITS = ("minutes", "invocations", "reruns", "cost")
DEFAULTS = {"minutes": 180, "invocations": 60, "reruns": 6, "cost": 15}
STAGES = ("acceptance", "quality", "tests", "security", "verify", "image", "ci")
RECOVERY_FILE = "cplat-recovery.json"
STOP_AFTER = 2                      # equivalent failures without progress
EXCERPT_LINES = 40
REFUSED_RERUN = "budget exhausted: reruns"
UNKNOWN = "unknown"


# ---------------- options and defaults ----------------

def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def parse_options(items: list[str] | dict | None) -> dict:
    """{limit: number | None (off)} from `KEY=VALUE` strings."""
    if isinstance(items, dict):
        return items
    out: dict = {}
    for item in items or []:
        key, sep, value = str(item).partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in LIMITS:
            raise PlatformError(f"--budget expects KEY=VALUE with KEY one of {', '.join(LIMITS)}, got '{item}'",
                                hint="for example --budget minutes=45 --budget cost=off")
        if value.lower() == "off":
            out[key] = None
            continue
        try:
            number = float(value)
        except ValueError:
            number = -1.0
        if number < 0 or number != number or number == float("inf"):
            raise PlatformError(f"--budget {key}: '{value}' is not a number (or `off`)", hint=f"for example --budget {key}=10")
        out[key] = _number(number)
    return out


def defaults(repo: Path | None = None) -> dict:
    """The per-ship limits: the platform defaults, overridden by `budget:` in the settings files (settings.py)."""
    return {**DEFAULTS, **(settings.budget_defaults(repo) if repo else {})}


def repo_key(repo: Path) -> str:
    """The GitHub slug of origin, else the absolute path of the repo."""
    try:
        url = run(["git", "config", "--get", "remote.origin.url"], cwd=repo, check=False).stdout.strip()
        m = re.search(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    except Exception:  # noqa: BLE001
        pass
    return str(Path(repo).resolve())


def work_key(repo: Path, refs: list[str] | str | None, fallback: str) -> str:
    """`<repo key>:<spec id>`; several specs are their full ids sorted and joined with `+`; `fallback` when none resolves."""
    import spec as specmod
    ids = set()
    for ref in ([refs] if isinstance(refs, str) else refs or []):
        try:
            ids.add(specmod.find(Path(repo), ref).id)
        except Exception:  # noqa: BLE001
            pass
    return f"{repo_key(repo)}:{'+'.join(sorted(ids)) if ids else fallback}"


def spec_refs(prompt: str) -> list[str]:
    args = re.sub(r"^\s*/\S+", "", prompt)
    return [t for t in re.split(r"[\s,]+", args) if re.match(r"\d", t)]


def ships_in(prompt: str) -> int:
    """How many ships a headless prompt covers: the spec numbers after the command (`/svc:ship 102 103` -> 2), at least 1."""
    args = re.sub(r"^\s*/\S+", "", prompt)
    return max(1, sum(1 for t in re.split(r"[\s,]+", args) if re.match(r"\d", t)))


# ---------------- the ledger ----------------

def _iso(when: datetime.datetime) -> str:
    return runs._iso(when)


def _when(text) -> datetime.datetime | None:
    try:
        when = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _dir() -> Path:
    return runs.state_dir() / "budgets"


def _path(key: str) -> Path:
    return _dir() / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("limits"), dict) else None


def _write(path: Path, data: dict) -> None:
    runs._atomic_write(path, json.dumps(data, indent=1) + "\n")


def _modify(path: Path, fn) -> dict | None:
    """Apply `fn(data)` to the ledger under the runs lock (never nest: `runs._locked` is not reentrant)."""
    with runs._locked():
        data = _read(path)
        if data is None:
            return None
        fn(data)
        _write(path, data)
        return data


def _all() -> list[tuple[Path, dict]]:
    out = []
    try:
        files = sorted(_dir().glob("*.json"))
    except OSError:
        return []
    for f in files:
        data = _read(f)
        if data is not None:
            out.append((f, data))
    return out


def root_of(run_id: str | None) -> str | None:
    """The run without a (still active) parent that `run_id` belongs to."""
    seen: set[str] = set()
    while run_id and run_id not in seen:
        seen.add(run_id)
        parent = (runs.active(run_id) or {}).get("parent")
        if not parent or runs.active(parent) is None:
            return run_id
        run_id = parent
    return run_id


def find(run_id: str | None) -> tuple[Path, dict] | None:
    """The ledger of the tree `run_id` belongs to."""
    root = root_of(run_id)
    if not root:
        return None
    for path, data in _all():
        if root in (data.get("roots") or []):
            return path, data
    return None


def _fold_previous(data: dict, now: str) -> None:
    """A continued ledger whose last root never closed: its minutes up to the stop (not the idle time since) and counters carry over."""
    prev = data.get("current")
    if not prev:
        return
    start = _when(prev.get("started_at"))
    end = _when((data.get("stop") or {}).get("at")) or _when(now)
    c = data["carried"]
    if start and end:
        c["minutes"] = round(c.get("minutes", 0) + max(0.0, (end - start).total_seconds() / 60), 1)
    for k in ("invocations", "reruns"):
        c[k] = c.get(k, 0) + data["used"].get(k, 0)
    data["used"] = {"invocations": 0, "reruns": 0}
    data["current"] = None


def open_root(run_id: str | None, key: str, *, ships: int = 1, options: list[str] | dict | None = None,
              repo: Path | None = None) -> None:
    """Open the ledger of a root run, or continue the unfinished ledger of the same work (AC-102.6).

    A run with an active parent is a child: it opens nothing (AC-102.2). A root started in an interactive session is one
    invocation. A limit given in `options` replaces the (multiplied) default; on a continued ledger only a limit that
    differs is a change, noted in `changes`. Raises PlatformError for a bad option; nothing else."""
    opts = parse_options(options)
    try:
        rec = runs.active(run_id)
        if rec is None or (rec.get("parent") and runs.active(rec["parent"]) is not None):
            return
        base = defaults(repo)
    except PlatformError:
        raise
    except Exception:  # noqa: BLE001
        return
    try:
        now = _iso(runs.utcnow())
        path = _path(key)
        # a root started by hand inside a Claude Code session is that session's invocation; headless counts its own sessions
        started_in_session = 1 if rec.get("mode") != "headless" and os.environ.get("CLAUDE_CODE_SESSION_ID") else 0
        with runs._locked():
            data = _read(path)
            if data is not None and run_id in (data.get("roots") or []):
                pass
            elif data is not None and data.get("state") != "done":
                _fold_previous(data, now)
                data["roots"].append(run_id)
                data["state"], data["stop"] = "open", None
                data["current"] = {"run_id": run_id, "started_at": now}
                data["used"]["invocations"] = data["used"].get("invocations", 0) + started_in_session
            else:
                limits = {k: (None if v is None else _number(v * max(1, ships))) for k, v in base.items()}
                limits.update({k: v for k, v in opts.items()})
                data = {"key": key, "limits": limits, "carried": {"minutes": 0, "invocations": 0, "reruns": 0, "cost": 0},
                        "used": {"invocations": started_in_session, "reruns": 0}, "roots": [run_id],
                        "current": {"run_id": run_id, "started_at": now}, "started_at": now,
                        "changes": [], "state": "open", "stop": None, "attempts": {}, "stages": {}}
                opts = {}
            for limit, value in opts.items():
                if data["limits"].get(limit) != value:
                    data["changes"].append({"at": now, "limit": limit, "from": data["limits"].get(limit), "to": value})
                    data["limits"][limit] = value
            _write(path, data)
    except Exception:  # noqa: BLE001
        pass


# ---------------- usage ----------------

def _cost_of(rec: dict) -> float | str:
    import runs_usage
    try:
        sec = runs_usage.for_run(rec, ended_at=_iso(runs.utcnow()), budget_s=3.0, peek=True)
    except TypeError:
        return UNKNOWN
    totals = (sec or {}).get("totals")
    if not totals:                       # unreadable usage is unknown, never 0 (AC-102.5)
        return UNKNOWN
    if not totals.get("cost_complete", False) and totals.get("calls"):
        return UNKNOWN
    return float(totals.get("cost_usd") or 0.0)


def _sum_cost(a, b):
    return UNKNOWN if UNKNOWN in (a, b) else a + b


def _tree(root: str) -> list[dict]:
    recs = []
    try:
        files = sorted((runs.state_dir() / "active").glob("*.json"))
    except OSError:
        return []
    for f in files:
        rec = runs.active(f.stem)
        if rec is not None and root_of(rec["run_id"]) == root:
            recs.append(rec)
    return recs


def _live_cost(root: str):
    recs = _tree(root)
    top = next((r for r in recs if r["run_id"] == root), None)
    if top is not None and top.get("kind") == "headless":
        recs = [top]              # the headless session's transcripts already hold every child
    total: float | str = 0.0
    for rec in recs:
        total = _sum_cost(total, _cost_of(rec))
    return total


def used_of(data: dict, *, cost: bool = True) -> dict:
    carried, used, cur = data.get("carried") or {}, data.get("used") or {}, data.get("current") or {}
    minutes = carried.get("minutes", 0)
    started = _when(cur.get("started_at"))
    if started is not None:
        minutes += max(0.0, (runs.utcnow() - started).total_seconds() / 60)
    out = {"minutes": round(minutes, 1), "invocations": carried.get("invocations", 0) + used.get("invocations", 0),
           "reruns": carried.get("reruns", 0) + used.get("reruns", 0), "cost": None}
    if cost:
        out["cost"] = _sum_cost(carried.get("cost", 0), _live_cost(cur["run_id"]) if cur.get("run_id") else 0.0)
        if out["cost"] != UNKNOWN:
            out["cost"] = round(out["cost"], 4)
    return out


def check(run_id: str | None, point: str) -> str | None:
    """The first used-up limit (used >= limit) of the run's budget, else None. An unknown cost is not checked (AC-102.5)."""
    try:
        found = find(run_id)
        if found is None:
            return None
        limits = found[1]["limits"]
        used = used_of(found[1], cost=limits.get("cost") is not None)
        for name in LIMITS:
            limit, value = limits.get(name), used.get(name)
            if limit is not None and value is not None and value != UNKNOWN and value >= limit:
                return name
    except Exception:  # noqa: BLE001
        pass
    return None


def allow_rerun(run_id: str | None) -> bool:
    """Asked before every CI rerun: counts it, False (and nothing counted) when `reruns` is used up."""
    try:
        found = find(run_id)
        if found is None:
            return True
        verdict = [True]

        def count(data: dict) -> None:
            limit = data["limits"].get("reruns")
            total = data["carried"].get("reruns", 0) + data["used"].get("reruns", 0)
            if limit is not None and total >= limit:
                verdict[0] = False
            else:
                data["used"]["reruns"] = data["used"].get("reruns", 0) + 1
        _modify(found[0], count)
        return verdict[0]
    except Exception:  # noqa: BLE001
        return True


def count_invocation(run_id: str | None, n: int = 1) -> None:
    try:
        found = find(run_id)
        if found is not None:
            _modify(found[0], lambda d: d["used"].__setitem__("invocations", d["used"].get("invocations", 0) + n))
    except Exception:  # noqa: BLE001
        pass


def _fmt(value) -> str:
    return "off" if value is None else str(value)


def limits_line(run_id: str | None) -> str | None:
    try:
        found = find(run_id)
        if found is None:
            return None
        lim = found[1]["limits"]
        cost = "off" if lim.get("cost") is None else f"${lim['cost']}"
        return (f"budget: minutes {_fmt(lim.get('minutes'))}, invocations {_fmt(lim.get('invocations'))}, "
                f"reruns {_fmt(lim.get('reruns'))}, cost {cost}  (cplat budget show)")
    except Exception:  # noqa: BLE001
        return None


# ---------------- the stop ----------------

def section(data: dict, limit: str | None, phase: str | None, point: str | None) -> dict:
    return {"limits": dict(data["limits"]), "used": used_of(data), "limit": limit, "phase": phase, "point": point}


def stop(run_id: str | None, limit: str, point: str, phase: str | None = None) -> str:
    """Write the `budget` section into the stopping run's record and the root's; returns `budget exhausted: <limit>`.
    The caller escalates the run (cause decision). Never raises."""
    reason = f"budget exhausted: {limit}"
    try:
        found = find(run_id)
        if found is None:
            return reason
        if phase is None:
            open_ones = [p["name"] for p in (runs.active(run_id) or {}).get("phases") or [] if p.get("ended_at") is None]
            phase = open_ones[-1] if open_ones else point
        info = {"limit": limit, "point": point, "phase": phase, "at": _iso(runs.utcnow())}
        data = _modify(found[0], lambda d: d.update(stop=info, state="stopped")) or found[1]
        value = section(data, limit, phase, point)
        for rid in dict.fromkeys([run_id, root_of(run_id)]):
            runs.set_section(rid, "budget", value)
    except Exception:  # noqa: BLE001
        pass
    return reason


def on_finish(run_id: str | None, usage: dict | None, outcome: str) -> None:
    """Called by runs.finish before the record is closed: the `budget` section, and the ledger carries what this run spent.
    Never raises."""
    try:
        found = find(run_id)
        if found is None or runs.active(run_id) is None:
            return
        path, data = found
        root = root_of(run_id)
        stopped = data.get("stop") or {}
        if run_id == root or stopped:
            runs.set_section(run_id, "budget", section(data, stopped.get("limit"), stopped.get("phase"), stopped.get("point")))
        cost: float | str = UNKNOWN
        totals = (usage or {}).get("totals")
        if totals:
            cost = float(totals.get("cost_usd") or 0.0) if totals.get("cost_complete", True) else UNKNOWN
        is_root = run_id == root
        headless_root = (runs.active(root) or {}).get("kind") == "headless"
        used = used_of(data, cost=False)

        def carry(d: dict) -> None:
            c = d["carried"]
            if is_root:
                c["minutes"] = used["minutes"]
                c["invocations"], c["reruns"] = used["invocations"], used["reruns"]
                d["used"], d["current"] = {"invocations": 0, "reruns": 0}, None
                c["cost"] = _sum_cost(c.get("cost", 0), cost)
                d["state"] = "done" if outcome == "done" else ("stopped" if d.get("stop") else d.get("state", "open"))
            elif not headless_root:
                c["cost"] = _sum_cost(c.get("cost", 0), cost)
        _modify(path, carry)
    except Exception:  # noqa: BLE001
        pass


# ---------------- where a command runs ----------------

def current_run(repo: Path) -> str | None:
    rid = runs.current(Path(repo))
    if rid:
        return rid
    try:
        import appship_state
        st = appship_state.load_state(Path(repo))
        if st and st.get("run_id") and runs.active(st["run_id"]) is not None:
            return st["run_id"]
    except Exception:  # noqa: BLE001
        pass
    return None


def _holder(repo: Path):
    """(read, update) of the dict that keeps `attempts` and `stages`: the ship state, else the run's ledger, else None."""
    import ship
    try:
        f = ship.state_path(repo)
    except PlatformError:
        f = None
    if f is not None and f.is_file():
        def read() -> dict:
            try:
                return json.loads(f.read_text())
            except (OSError, ValueError):
                return {}

        def update(fn) -> None:
            with runs._locked():
                data = read()
                fn(data)
                f.write_text(json.dumps(data, indent=2) + "\n")
        return read, update
    found = find(current_run(repo))
    if found is None:
        return None
    return (lambda: (_read(found[0]) or {})), (lambda fn: _modify(found[0], fn))


# ---------------- no progress ----------------

_NORMALISE = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), ""),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), ""),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|m)\b"), ""),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"(?:\.{0,2}/)?(?:[\w.~@+-]+/)+[\w.~@+-]+"), "<path>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,}\b"), "<id>"),
    (re.compile(r"(?i)\bline \d+"), "line"),
    (re.compile(r"(?<=[\w>]):\d+(?::\d+)?\b"), ""),
]


def normalise(text: str) -> str:
    """The error without what changes between equivalent runs: times, paths, ids, line numbers, whitespace."""
    for pattern, repl in _NORMALISE:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


def _progress(prev: dict, cur: dict) -> bool:
    if cur["failing"] < prev["failing"]:
        return True
    return bool(prev["names"]) and bool(set(prev["names"]) - set(cur["names"]))


def attempt(repo: Path, stage: str, error: str, failing: int, names: list[str] | None = None) -> str | None:
    """Record a failed attempt of `stage`; the reason when the last 3 are equivalent without progress between them, else None.
    The attempts are kept in the ship state (or the ledger without a ship)."""
    try:
        text = normalise("\n".join(str(error).strip().splitlines()[-EXCERPT_LINES:]))
        entry = {"at": _iso(runs.utcnow()), "failing": int(failing), "names": sorted(names or []),
                 "sig": hashlib.sha1(text.encode()).hexdigest()[:12], "error": feedback.redact(text)[:400]}
        holder = _holder(Path(repo))
        if holder is None:
            return None
        verdict: list[str | None] = [None]

        def add(data: dict) -> None:
            hist = data.setdefault("attempts", {}).setdefault(stage, [])
            hist.append(entry)
            del hist[:-10]
            last = hist[-STOP_AFTER:]
            if (len(last) == STOP_AFTER and len({e["sig"] for e in last}) == 1
                    and not any(_progress(a, b) for a, b in zip(last, last[1:]))):
                verdict[0] = (f"no progress: {stage}: {STOP_AFTER} equivalent failures in a row without fewer failing checks; "
                              f"last: {entry['error'][:200]}")
        holder[1](add)
        return verdict[0]
    except Exception:  # noqa: BLE001
        return None


# ---------------- recovery snapshot ----------------

_AC = re.compile(r"\bAC-\d{3,}\.\d+\b")
_TESTFILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test\.[a-z]+|[^/]*\.(test|spec)\.[a-z]+|[^/]*Tests?\.[a-z]+)$")


def _git(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo, check=False).stdout


def changed_files(repo: Path) -> list[str]:
    names: set[str] = set()
    base = None
    for ref in ("origin/main", "main", "origin/master", "master"):
        out = run(["git", "merge-base", "HEAD", ref], cwd=repo, check=False)
        if out.returncode == 0 and out.stdout.strip():
            base = out.stdout.strip()
            break
    for args in ((["diff", "--name-only", base] if base else []), ["diff", "--name-only", "HEAD"]):
        if args:
            names |= {ln.strip() for ln in _git(repo, *args).splitlines() if ln.strip()}
    for ln in _git(repo, "status", "--porcelain", "-uall").splitlines():
        if len(ln) > 3:
            names.add(ln[3:].split(" -> ")[-1].strip().strip('"'))
    return sorted(names)[:200]


def snapshot(repo: Path, stage: str, excerpt: str, criteria: list[str] | tuple = ()) -> Path | None:
    """`<git common dir>/cplat-recovery.json`: stage, redacted last 40 lines, changed files, criteria ids, the stage's attempts.
    Local only; no prompts and no full logs. Never raises."""
    try:
        repo = Path(repo)
        common = runs._git_common_dir(repo)
        if common is None:
            return None
        text = feedback.redact("\n".join(str(excerpt).strip().splitlines()[-EXCERPT_LINES:]))
        files = changed_files(repo)
        ids: list[str] = list(criteria) + _AC.findall(text)
        for f in files:
            if _TESTFILE.search(f) and (repo / f).is_file():
                try:
                    ids += _AC.findall((repo / f).read_text(errors="replace")[:100_000])
                except OSError:
                    pass
        holder = _holder(repo)
        attempts = ((holder[0]().get("attempts") or {}).get(stage) or []) if holder else []
        data = {"stage": stage, "excerpt": text, "changed_files": files, "criteria": list(dict.fromkeys(ids)),
                "attempts": attempts, "at": _iso(runs.utcnow())}
        path = common / RECOVERY_FILE
        runs._atomic_write(path, json.dumps(data, indent=2) + "\n")
        return path
    except Exception:  # noqa: BLE001
        return None


def read_snapshot(repo: Path) -> dict | None:
    try:
        common = runs._git_common_dir(Path(repo))
        data = json.loads((common / RECOVERY_FILE).read_text()) if common else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------- verified stages ----------------

def _head_and_inputs(repo: Path) -> tuple[str, str]:
    head = _git(repo, "rev-parse", "HEAD").strip()
    material = _git(repo, "status", "--porcelain") + "\0" + _git(repo, "diff", "HEAD")
    return head, hashlib.sha1(material.encode()).hexdigest()


def record_stage(repo: Path, name: str, result: str) -> None:
    """Record `{result, head, inputs}` for a stage of build or ship. Never raises."""
    try:
        if name not in STAGES or result not in ("passed", "failed", "skipped"):
            return
        holder = _holder(Path(repo))
        if holder is None:
            return
        head, inputs = _head_and_inputs(Path(repo))
        holder[1](lambda d: d.setdefault("stages", {}).__setitem__(name, {"result": result, "head": head, "inputs": inputs}))
    except Exception:  # noqa: BLE001
        pass


def decisions(repo: Path) -> list[tuple[str, str, str]]:
    """(stage, "skip" | "run", reason) for every stage; only a passed result for the current HEAD and inputs is skipped."""
    holder = _holder(Path(repo))
    stages = (holder[0]().get("stages") if holder else None) or {}
    stages = stages if isinstance(stages, dict) else {}
    head, inputs = _head_and_inputs(Path(repo))
    snap = read_snapshot(repo) or {}
    out = []
    for name in STAGES:
        entry = stages.get(name)
        if snap.get("stage") == name:
            out.append((name, "run", "the last stop was here"))
        elif entry is None:
            out.append((name, "run", "missing"))
        elif not (isinstance(entry, dict) and entry.get("result") in ("passed", "failed", "skipped")
                  and isinstance(entry.get("head"), str) and isinstance(entry.get("inputs"), str)):
            out.append((name, "run", "unreadable"))
        elif entry["result"] != "passed":
            out.append((name, "run", entry["result"]))
        elif entry["head"] != head or entry["inputs"] != inputs:
            out.append((name, "run", "stale: HEAD or inputs changed since the pass"))
        else:
            out.append((name, "skip", f"passed at {head[:7]}, inputs unchanged"))
    return out


# ---------------- CLI ----------------

def _show(repo: Path, as_json: bool) -> int:
    rid = current_run(repo)
    found = find(rid)
    if found is None:
        print(json.dumps({"budget": None}) if as_json else "no budget: not inside a run")
        return 0
    data, root = found[1], root_of(rid)
    used = used_of(data)
    if as_json:
        print(json.dumps({"limits": data["limits"], "used": used, "root": root, "key": data["key"],
                          "state": data.get("state"), "changes": data.get("changes", [])}, indent=2))
        return 0
    print(f"budget of {data['key']} (root run {root})")
    for name in LIMITS:
        limit, value = data["limits"].get(name), used[name]
        shown = "off" if limit is None else (f"${limit}" if name == "cost" else str(limit))
        spent = f"${value}" if name == "cost" and value != UNKNOWN else str(value)
        print(f"  {name:<12} {spent} of {shown}")
    return 0


def _gate(repo: Path, invocation: bool) -> int:
    rid = current_run(repo)
    if find(rid) is None:
        return 0
    limit = check(rid, "subagent")
    if limit:
        print(f"budget exhausted: {limit}: no subagent is started; finish the step, then stop with "
              f"`cplat ship escalate 'budget exhausted: {limit}' --cause decision` (raise the limit with --budget {limit}=N "
              "when the run is started again)", file=sys.stderr)
        return 2
    if invocation:
        count_invocation(rid)
    return 0


def _attempt_cli(ns: argparse.Namespace, repo: Path) -> int:
    try:
        error = Path(ns.error_file).read_text(errors="replace") if ns.error_file else (ns.error or "")
    except OSError as e:
        raise PlatformError(f"cannot read {ns.error_file}: {e.strerror}") from None
    names = [n.strip() for n in (ns.names or "").split(",") if n.strip()]
    reason = attempt(repo, ns.stage, error, ns.failing, names)
    if not reason:
        return 0
    print(reason)
    import ship
    try:
        st = ship.load_state(repo)
    except PlatformError:
        st = None
    if st and not st.get("escalated") and st.get("phase") != "done":
        ship.escalate(repo, reason, "code", evidence=error, stage=ns.stage)
    else:
        snapshot(repo, ns.stage, error, [])
    return 3


def _resume(repo: Path, as_json: bool) -> int:
    rows = decisions(repo)
    snap = read_snapshot(repo)
    if as_json:
        print(json.dumps({"snapshot": snap, "stages": [{"stage": s, "action": a, "reason": r} for s, a, r in rows]}, indent=2))
        return 0
    if snap:
        print(f"last stop (recovery snapshot): stage {snap.get('stage')}")
        for ln in str(snap.get("excerpt") or "").splitlines():
            print(f"  | {ln}")
        if snap.get("changed_files"):
            print(f"  changed files: {', '.join(snap['changed_files'][:20])}")
    for stage, action, reason in rows:
        print(f"{stage}: {action} ({reason})")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat budget", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", help="limits, usage and the root run")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("gate", help="PreToolUse hook: exit 2 refuses a subagent when the budget is used up")
    p.add_argument("--invocation", action="store_true", help="count the subagent as an invocation")
    p = sub.add_parser("attempt", help="record a failed fix round; exit 3 and the reason when nothing improves")
    p.add_argument("stage")
    p.add_argument("--failing", type=int, required=True, help="how many checks fail now")
    p.add_argument("--names", default="", help="comma separated names of the failing checks")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--error-file")
    g.add_argument("--error")
    p = sub.add_parser("stage", help="record a verified stage result for HEAD + inputs")
    p.add_argument("name", choices=STAGES)
    p.add_argument("result", choices=("passed", "failed"))
    p = sub.add_parser("resume", help="per stage: skip (passed for this HEAD and inputs) or run")
    p.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    repo = Path.cwd()
    if ns.cmd == "show":
        return _show(repo, ns.json)
    if ns.cmd == "gate":
        return _gate(repo, ns.invocation)
    if ns.cmd == "attempt":
        return _attempt_cli(ns, repo)
    if ns.cmd == "stage":
        record_stage(repo, ns.name, ns.result)
        print(f"{ns.name}: {ns.result}")
        return 0
    return _resume(repo, ns.json)

