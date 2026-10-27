"""`cplat runs [--json] [--since DAYS] [--repo OWNER/NAME] [--spec ID]`: the run list the console reads (spec 122, AC-122.5).

Active records, the local buffer and the private run store become one row per run (design.md "cplat runs"): the phase, the
stage, the budget, the last activity, the escalation and failure of a stopped run, the session. A store that is unset or
unreachable still lists the local records. Recording and reading never raise.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

import runs
import runs_report
import runs_store
import stages
from core import PlatformError

SCHEMA = 1
ACTIVITY = 10
TOP_PHASES = ("plan", "build", "pr", "land", "deploy", "staging", "done")
_PRODUCT_PHASE = {"plan": "plan", "publish": "plan", "repos": "build", "complete": "done", "done": "done"}
_ALL_DAYS = 366


def _ts(value) -> datetime.datetime | None:
    return runs_report._ts(value)


def _top(name) -> str:
    return str(name).split(":", 1)[0]


def _phase_names(rec: dict) -> list[str]:
    names = [p.get("name") for p in rec.get("phases") or [] if isinstance(p, dict)]
    if rec.get("kind") == "product-ship":
        return [_PRODUCT_PHASE[n] for n in map(_top, names) if n in _PRODUCT_PHASE]
    return [_top(n) for n in names if ":" not in str(n) and _top(n) in TOP_PHASES]


def _derive(rec: dict) -> tuple[str, str | None]:
    """(phase, stopped_in) from the phases a record opened, its outcome and a pending staging section."""
    opened = _phase_names(rec)
    last = opened[-1] if opened else ("plan" if rec.get("kind") in ("ship", "product-ship") else "build")
    if last == "done" and rec.get("outcome") not in ("done", None):
        last = next((n for n in reversed(opened) if n != "done"), "build")
    if rec.get("outcome") == "escalated":
        stop = (rec.get("budget") or {}).get("phase") if isinstance(rec.get("budget"), dict) else None
        where = _top(stop) if stop and _top(stop) in stages._PHASE_STAGE else last
        return "escalated", where if where in stages._PHASE_STAGE else "build"
    if rec.get("outcome") == "done" or last == "done":
        return "done", None
    if last == "deploy" and _staging_pending(rec):
        return "staging", None
    return last, None


def _outcome(section) -> str | None:
    return section.get("outcome") if isinstance(section, dict) else None


def _staging_pending(rec: dict) -> bool:
    """Deployed and smoked in dev, the staging promotion not skipped or failed, and no staging smoke recorded yet."""
    smoke = rec.get("smoke") if isinstance(rec.get("smoke"), dict) else {}
    promo = (rec.get("promotion") or {}).get("staging") if isinstance(rec.get("promotion"), dict) else None
    if smoke.get("staging") or (isinstance(promo, dict) and promo.get("result") in ("skipped", "failed")):
        return False
    return isinstance(promo, dict) and promo.get("result") == "promoted"


def _reached(rec: dict) -> str:
    """The phase a finished run got to last (never `done`): the last opened phase, `staging` when staging was smoked."""
    if isinstance(rec.get("smoke"), dict) and rec["smoke"].get("staging"):
        return "staging"
    opened = [n for n in _phase_names(rec) if n != "done"]
    if opened:
        return opened[-1]
    return "plan" if rec.get("kind") in ("ship", "product-ship") else "build"


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def _escalation(rec: dict) -> dict | None:
    esc = rec.get("escalation")
    if not isinstance(esc, dict):
        return None
    reason = _one_line(esc.get("reason"))
    return {"reason": reason, "cause": runs_report.effective_escalation(rec).cause, "summary": reason}


def _snapshot(repo_dir: str | None) -> dict:
    try:
        import budget
        if repo_dir and Path(repo_dir).is_dir():
            return budget.read_snapshot(Path(repo_dir)) or {}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _snapshot_refs(snap: dict, repo_dir: str | None) -> tuple[str | None, str | None]:
    """(first changed test file, path of the recovery snapshot) of a stopped run's clone; None for what is not there."""
    if not snap:
        return None, None
    try:
        import budget
        import core
        test = next((f for f in snap.get("changed_files") or [] if isinstance(f, str) and budget._TESTFILE.search(f)), None)
        common = core.git_dir(Path(repo_dir)) if repo_dir else None
        return test, str(common / budget.RECOVERY_FILE) if common else None
    except Exception:  # noqa: BLE001
        return None, None


def _failure(rec: dict, esc: dict | None, repo_dir: str | None) -> dict | None:
    if esc is None and rec.get("outcome") != "failed":
        return None
    snap = _snapshot(repo_dir)
    excerpt = [ln for ln in str(snap.get("excerpt") or "").splitlines() if ln.strip()]
    criteria = snap.get("criteria") or []
    diagnosis = ""
    if isinstance(rec.get("escalation"), dict):
        import escalation_rules
        diagnosis = escalation_rules.message(runs_report.effective_escalation(rec)) or ""
    diagnosis = diagnosis or (esc or {}).get("reason") or str(rec.get("outcome") or "failed")
    test, log = _snapshot_refs(snap, repo_dir)
    return {"check": snap.get("stage"), "test": test, "criterion": criteria[0] if criteria else None,
            "error": excerpt[-1] if excerpt else None, "excerpt": excerpt[-10:], "log": log, "diagnosis": diagnosis}


def _ledger(rec: dict):
    try:
        import budget
        for _, data in budget._all():
            roots = data.get("roots") or []
            if rec["run_id"] in roots or (rec.get("parent") and rec["parent"] in roots):
                return data
    except Exception:  # noqa: BLE001
        pass
    return None


def _budget(rec: dict, active: bool) -> dict:
    import budget
    data = _ledger(rec)
    if data is not None:
        try:
            stop = data.get("stop") or {}
            return {"used": budget.used_of(data, cost=active), "limit": dict(data["limits"]),
                    "exhausted": stop.get("limit")}
        except Exception:  # noqa: BLE001
            pass
    sec = rec.get("budget") if isinstance(rec.get("budget"), dict) else {}
    used = dict(sec.get("used") or {"minutes": 0, "invocations": 0, "reruns": len(rec.get("reruns") or []), "cost": None})
    return {"used": used, "limit": dict(sec.get("limits") or budget.DEFAULTS), "exhausted": sec.get("limit")}


def _activity(rec: dict, esc: dict | None) -> list[dict]:
    items = [{"at": p.get("started_at"), "agent": "orchestrator", "text": f"phase {p.get('name')}"}
             for p in rec.get("phases") or [] if isinstance(p, dict) and p.get("started_at")]
    for entry in rec.get("agents") or []:
        if not isinstance(entry, dict):
            continue
        for ev in entry.get("events") or []:
            if isinstance(ev, dict) and ev.get("at"):
                items.append({"at": ev["at"], "agent": entry.get("agent") or "unknown",
                              "text": _one_line(ev.get("kind") or ev.get("severity") or "event")})
    for rr in rec.get("reruns") or []:
        if isinstance(rr, dict):
            items.append({"at": rec.get("started_at"), "agent": "orchestrator",
                          "text": f"rerun {rr.get('check')} ({rr.get('reason')})"})
    if esc is not None and rec.get("ended_at"):
        items.append({"at": rec["ended_at"], "agent": "orchestrator", "text": f"escalated: {esc['reason']}"})
    items = [i for i in items if i["at"]]
    items.sort(key=lambda i: str(i["at"]), reverse=True)
    return items[:ACTIVITY]


def _session(run_id: str) -> tuple[str | None, str | None]:
    try:
        import runs_usage
        mine = [e for e in runs_usage._load() if e.get("run_id") == run_id and e.get("session")]
        if mine:
            e = max(mine, key=lambda x: str(x.get("started_at") or ""))
            return e["session"], e.get("dir") or None
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _children(rec: dict) -> list[str]:
    return [c for c in rec.get("ships") or [] if isinstance(c, str)]


def lookup_pr(repo: str, branch: str, state: str = "all") -> dict | None:
    """The open or merged PR of a branch through `gh` (tests replace this); None when `gh` cannot say."""
    import json as _json
    from core import run
    try:
        out = run(["gh", "pr", "list", "-R", repo, "--head", branch, "--state", state, "--json", "number,url", "--limit", "1"],
                  check=False, timeout=10).stdout
        found = _json.loads(out or "[]")
    except Exception:  # noqa: BLE001
        return None
    return found[0] if found and isinstance(found[0], dict) and found[0].get("url") else None


def _as_pr(value) -> dict | None:
    """`{number, url}` from a PR url, a number-and-url dict or None."""
    url = value.get("url") if isinstance(value, dict) else value if isinstance(value, str) else None
    if not url:
        return None
    number = value.get("number") if isinstance(value, dict) else None
    if number is None and (m := re.search(r"/pull/(\d+)", url)):
        number = int(m.group(1))
    return {"number": number, "url": url}


def _state_pr(rec: dict, repo_dir: str | None) -> dict | None:
    """The PR the unfinished ship state of the run's clone names (`st["pr"]` is a url)."""
    try:
        import ship
        st = ship.load_state(Path(repo_dir)) if repo_dir and Path(repo_dir).is_dir() else None
    except Exception:  # noqa: BLE001
        return None
    return _as_pr(st.get("pr")) if st and st.get("run_id") == rec.get("run_id") else None


def _pr(rec: dict, repo_dir: str | None, phase: str) -> dict | None:
    """The run's PR: a recorded one, else the ship state's, else (running or stopped runs) the `feature/<spec>` branch's."""
    found = _as_pr(rec.get("pr")) or _state_pr(rec, repo_dir)
    if found or not rec.get("repo") or not rec.get("spec"):
        return found
    if phase == "done":
        return _merged_pr(rec)
    return _as_pr(lookup_pr(rec["repo"], f"feature/{rec['spec']}"))


def _pr_cache_file() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "sdlc-foundry" / "console" / "prs.json"


def _merged_pr(rec: dict) -> dict | None:
    """The merged PR of a finished run's `feature/<spec>` branch, cached per run so finished runs ask `gh` once."""
    import json as _json
    path, run_id = _pr_cache_file(), str(rec["run_id"])
    try:
        cache = _json.loads(path.read_text())
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    if isinstance(cache.get(run_id), dict):
        return _as_pr(cache[run_id])
    try:
        found = _as_pr(lookup_pr(rec["repo"], f"feature/{rec['spec']}", state="merged"))
    except Exception:  # noqa: BLE001
        return None
    if found:
        cache[run_id] = found
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_json.dumps(cache))
        except OSError:
            pass
    return found


def _image(rec: dict) -> str | None:
    smoke = rec.get("smoke") if isinstance(rec.get("smoke"), dict) else {}
    staging = smoke.get("staging") if isinstance(smoke.get("staging"), dict) else {}
    return rec.get("image") or smoke.get("image") or staging.get("image") or None


_GREEN = ("passed", "passed-on-retry")


def _smoke_cell(section, repo: str | None, env: str) -> dict | None:
    outcome = _outcome(section)
    if not outcome:
        return None
    result = "passed" if outcome in _GREEN else "not-run" if outcome == "not-run" else "failed"
    cell = {"result": result, "instance": f"{(repo or '').rsplit('/', 1)[-1]}/{env}"}
    if reason := _one_line(section.get("reason") or ""):
        cell["reason"] = reason
    return cell


def _smoke(rec: dict) -> dict:
    """`{dev, staging}` as `{result: passed|failed|not-run, instance: <component>/<env>}` from the record's smoke sections."""
    smoke = rec.get("smoke") if isinstance(rec.get("smoke"), dict) else {}
    return {"dev": _smoke_cell(smoke, rec.get("repo"), "dev"), "staging": _smoke_cell(smoke.get("staging"), rec.get("repo"), "staging")}


def row(rec: dict, active: bool) -> dict:
    """One row of the run list from a run record (active, buffered or stored)."""
    phase, stopped_in = _derive(rec)
    stage, stopped = stages.stage_of_run(_reached(rec) if phase == "done" else phase, stopped_in)
    esc = _escalation(rec)
    session, repo_dir = _session(rec["run_id"])
    pr = _pr(rec, repo_dir, phase)
    return {
        "run_id": rec["run_id"], "kind": rec.get("kind"), "level": "system" if rec.get("kind") == "product-ship" else "component",
        "spec": rec.get("spec"), "repo": rec.get("repo"), "parent": rec.get("parent"), "children": _children(rec),
        "phase": phase, "stopped_in": stopped_in, "stage": stage, "stopped": stopped, "active": active,
        "started_at": rec.get("started_at"), "ended_at": rec.get("ended_at"), "outcome": rec.get("outcome"),
        "escalation": esc, "failure": _failure(rec, esc, repo_dir), "budget": _budget(rec, active),
        "activity": _activity(rec, esc), "session_id": session, "repo_dir": repo_dir,
        "pr": pr, "ci_url": rec.get("ci_url") or (f"{pr['url']}/checks" if pr and pr.get("url") else None),
        "image": _image(rec), "smoke": _smoke(rec),
    }


def _active_records() -> list[dict]:
    out = []
    try:
        files = sorted((runs.state_dir() / "active").glob("*.json"))
    except OSError:
        return out
    for f in files:
        if f.name.endswith(".incomplete.jsonl"):
            continue
        rec = runs.active(f.stem)
        if isinstance(rec, dict) and rec.get("run_id"):
            out.append(rec)
    return out


def _store(since: int) -> tuple[dict, list[dict]]:
    """(store info, records read from the store)."""
    try:
        status = runs.store_status()
    except Exception as e:  # noqa: BLE001
        return {"state": "unreachable", "detail": str(e)}, []
    info = {"state": status.state, "detail": status.slug or status.detail}
    if status.state != "ok" or status.slug is None:
        return info, []
    try:
        now = runs.utcnow()
        days = [now.date() - datetime.timedelta(days=n) for n in range((since or _ALL_DAYS), -1, -1)]
        files = runs.open_store(status.slug).read(days)
    except Exception as e:  # noqa: BLE001
        return {"state": "unreachable", "detail": str(e)}, []
    records, _, _ = runs_report.parse([text for _, text in files])
    return info, records


def collect(since_days: int = 30, repo: str | None = None, spec: str | None = None) -> dict:
    """The run list document (schema 1); `since_days` 0 lists every run. Never raises for a missing store."""
    now = runs.utcnow()
    store, stored = _store(since_days)
    chosen: dict[str, tuple[dict, bool]] = {}
    for rec in stored:
        if rec.get("run_id"):
            chosen[rec["run_id"]] = (rec, False)
    for rec in runs._safe_buffer():
        if rec.get("run_id") and not rec.get("followup"):
            chosen[rec["run_id"]] = (rec, False)
    for rec in _active_records():
        chosen[rec["run_id"]] = (rec, True)
    cutoff = now - datetime.timedelta(days=since_days) if since_days else None
    rows = []
    for rec, active in chosen.values():
        ended = _ts(rec.get("ended_at"))
        if not active and cutoff is not None and ended is not None and ended < cutoff:
            continue
        if (repo and rec.get("repo") != repo) or (spec and rec.get("spec") != spec):
            continue
        rows.append(row(rec, active))
    rows.sort(key=lambda r: str(r["ended_at"] or ""), reverse=True)
    rows.sort(key=lambda r: not r["active"])
    return {"schema": SCHEMA, "read_at": runs._iso(now), "store": store, "runs": rows}


def render(doc: dict) -> str:
    """One line per run."""
    lines = [f"{r['run_id']}  {r['phase']:<9}  {r['stage'] or '-':<8}  {r['spec'] or '-':<22}  {r['repo'] or '-'}"
             + ("  (active)" if r["active"] else f"  ({r['outcome'] or 'ended'})") for r in doc["runs"]]
    return "\n".join(lines) if lines else "no runs"


def _since(text: str) -> int:
    n = int(text)
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 (all) or more")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat runs", description="List active and recent runs (spec 122).")
    p.add_argument("--json", action="store_true")
    p.add_argument("--since", type=_since, default=30, metavar="DAYS", help="window in days (default 30, 0 = all)")
    p.add_argument("--repo", metavar="OWNER/NAME")
    p.add_argument("--spec", metavar="ID")
    return p


def main(argv: list[str]) -> int:
    try:
        ns = build_parser().parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    try:
        doc = collect(ns.since, ns.repo, ns.spec)
    except PlatformError:
        raise
    print(json.dumps(doc, indent=2) if ns.json else render(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
