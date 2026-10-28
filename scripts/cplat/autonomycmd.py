# SPDX-FileCopyrightText: 2026 Eike Hensler
#
# SPDX-License-Identifier: Apache-2.0
"""`cplat system autonomy show|set|pause|resume|undo|approve`: autonomy per environment (spec 124, AC-124.5 to AC-124.8, AC-124.13, AC-124.21).

`show` reads system.yaml, the engines (`engine.status`), the audit events and the run list; it exits 0 when an engine or the store
fails. `set`, `pause` and `resume` edit system.yaml with round-trip YAML, render, and with `--pr` signal the engines (only to tighten),
open the pull request and write the audit event. `undo` and `approve` are `autonomy_actions`. Contract: design.md "`cplat system autonomy`".
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json as jsonlib
import re
import sys
from pathlib import Path

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

import audit
import autonomy
import engine
import gitops
import model
import runs
import systemset
from core import PlatformError, Report, run

VERBS = ("show", "set", "pause", "resume", "undo", "approve")
PAUSE_BRANCH = "system/autonomy-pause"
_CLOCK = re.compile(r"^\d{1,2}:\d{2}$")


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *[str(a) for a in args]]).stdout


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--repo-dir", default=".", help="the gitops-app repo (default: current directory)")
    p.add_argument("--system", help="system name when the repo has several")
    p.add_argument("--json", action="store_true")
    return p


def _outward() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--pr", action="store_true", help="signal the engines, open the pull request and write the audit event")
    p.add_argument("--dry-run", action="store_true")
    return p


def build_parser() -> argparse.ArgumentParser:
    common, outward = _common(), _outward()
    p = argparse.ArgumentParser(prog="cplat system autonomy", description=__doc__)
    sub = p.add_subparsers(dest="verb", required=True)
    sub.add_parser("show", parents=[common], help="levels, guardrails, engines and what was done on its own")
    s = sub.add_parser("set", parents=[common, outward], help="change one environment's autonomy")
    s.add_argument("env")
    s.add_argument("level", choices=autonomy.LEVELS)
    s.add_argument("--routes", choices=("fix", "none"))
    s.add_argument("--max-criticality", dest="max_criticality")
    s.add_argument("--max-files", type=int, dest="max_files")
    s.add_argument("--max-lines", type=int, dest="max_lines")
    s.add_argument("--regression-test", choices=("true", "false"), dest="regression_test")
    s.add_argument("--second-review", choices=("true", "false"), dest="second_review")
    s.add_argument("--runs-per-day", type=int, dest="runs_per_day")
    s.add_argument("--merges-per-day", type=int, dest="merges_per_day")
    s.add_argument("--per-run", action="append", default=[], metavar="KEY=VALUE", dest="per_run")
    s.add_argument("--days", help="comma separated: mon,tue,...")
    s.add_argument("--from", dest="from_")
    s.add_argument("--to")
    s.add_argument("--timezone")
    s.add_argument("--undo-window", dest="undo_window")
    s.add_argument("--engine")
    sub.add_parser("pause", parents=[common, outward], help="pause the engines of every environment")
    sub.add_parser("resume", parents=[common, outward], help="lift a pause")
    u = sub.add_parser("undo", parents=[common], help="take back something an engine did")
    u.add_argument("event_id")
    u.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("approve", parents=[common], help="approve an engine's fix pull request and merge it")
    a.add_argument("target", metavar="<owner/repo>#<n>")
    a.add_argument("--dry-run", action="store_true")
    return p


# ---------------- shared helpers ----------------

def _login() -> str:
    return gh(["api", "user", "-q", ".login"]).strip() or "unknown"


def _iso(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(value):
    """A ruamel document as plain dicts, lists and scalars."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    return value


def _record(event: dict) -> None:
    reason = runs.record_audit(event)
    if reason:
        print(f"note: {reason}", file=sys.stderr)


def _targets(m: model.Model) -> dict[str, str]:
    return {e.name: e.autonomy["engine"] for e in m.environments if (e.autonomy or {}).get("engine")}


def _env_of(m: model.Model, name: str):
    return next((e for e in m.environments if e.name == name), None)


# ---------------- pending signals (the local cache) ----------------

def _read_cache(system: str) -> dict:
    try:
        doc = jsonlib.loads(engine.cache_path(system).read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_cache(system: str, doc: dict) -> None:
    path = engine.cache_path(system)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(jsonlib.dumps(doc, indent=2) + "\n")
    except OSError:
        pass


def _remember_pending(system: str, kind: str, results: dict[str, dict], *, level: str | None = None, pr: str | None = None) -> None:
    """Keep the not confirmed signals of this command (and drop older ones of the same environments)."""
    doc = _read_cache(system)
    pending = [p for p in doc.get("pending") or [] if p.get("environment") not in results]
    for env, res in results.items():
        if not res["confirmed"]:
            pending.append({"signal": res["signal"], "kind": kind, "environment": env, "at": _iso(runs.utcnow()), "pr": pr, "level": level})
    _write_cache(system, {**doc, "pending": pending})


# ---------------- show ----------------

def _store_state() -> tuple[dict, list[dict]]:
    try:
        st = runs.store_status()
    except Exception as e:  # noqa: BLE001  (show never fails on the store)
        return {"state": "unreachable"}, [{"source": "runs", "error": str(e)}]
    bad = [{"source": "runs", "error": st.detail}] if st.state in ("unreachable", "public") else []
    return {"state": st.state}, bad


def _budget_today(env: str, rows: list[dict], events: list[dict], now: dt.datetime, limits: dict) -> dict:
    today = now.date().isoformat()
    mine = [r for r in rows if r.get("kind") == "fix" and r.get("engine") and r.get("environment") == env
            and str(r.get("started_at") or "")[:10] == today]
    cost = sum(float(((r.get("budget") or {}).get("used") or {}).get("cost") or 0) for r in mine)
    merges = [e for e in events if e.get("kind") == "merge" and e.get("environment") == env and str(e.get("at") or "")[:10] == today]
    return {"runs": len(mine), "merges": len(merges), "cost": int(cost) if cost == int(cost) else round(cost, 4),
            "runsPerDay": limits["budget"]["runsPerDay"], "mergesPerDay": limits["budget"]["mergesPerDay"]}


def _override(cur: dict | None, declared: str, system_paused: bool) -> dict | None:
    if not cur:
        return None
    sigs = cur.get("signals") or []
    last = sigs[-1] if sigs else {}
    base = {"signal": last.get("id"), "at": last.get("at"), "pr": None}
    if cur.get("paused") and not system_paused:
        return {"kind": "pause", "level": "observe", **base}
    eff, dec = cur.get("effective"), "act" if declared == "improve" else declared
    if eff in autonomy.LEVELS and dec in autonomy.LEVELS and autonomy.LEVELS.index(eff) < autonomy.LEVELS.index(dec) and not system_paused:
        return {"kind": "lower", "level": eff, **base}
    return None


def collect(app_dir: Path) -> dict:
    """The `show --json` document."""
    m = model.load_dir(app_dir)
    doc = m.to_dict()
    now = runs.utcnow()
    events = audit.read(1)
    unavailable: list[dict] = []
    store, bad = _store_state()
    unavailable += bad
    try:
        rows = runlist_rows()
    except Exception as e:  # noqa: BLE001
        rows = []
        unavailable.append({"source": "runs", "error": str(e)})
    statuses: dict[str, dict | None] = {}
    for url in sorted({e.autonomy["engine"] for e in m.environments if (e.autonomy or {}).get("engine")}):
        statuses[url] = engine.status(url, m.system)
    pending_all = _read_cache(m.system).get("pending") or []
    still: list[dict] = []
    envs = []
    for e in m.environments:
        a = e.autonomy
        url = a.get("engine")
        st = statuses.get(url) if url else None
        beat = (st or {}).get("heartbeat_at") or (engine.last_heartbeat(url, m.system) if url else None)
        if not url:
            state = "none"
        elif st is None:
            state = "unreachable"
            unavailable.append({"source": f"engine:{e.name}", "error": f"{url} cannot be reached"})
        else:
            state = engine.state(st, now)
        pend = []
        for p in pending_all:
            if p.get("environment") != e.name:
                continue
            if engine.confirmed_later(p, st, events):
                continue
            still.append(p)
            pend.append({k: p.get(k) for k in ("signal", "kind", "at", "pr")})
        info = (st or {}).get("engine") or {}
        caps = [{"component": i["component"], "max": i["autonomy"]["max"], "effective": i["autonomy"]["effective"]}
                for i in doc["instances"] if i["environment"] == e.name and (i.get("autonomy") or {}).get("max")]
        envs.append({
            "name": e.name, "declared": a["declared"], "effective": a["effective"], "cap": a["cap"],
            "guardrails": {k: a[k] for k in ("autoMerge", "riskGate", "budget", "window")}, "undoWindow": a["undoWindow"],
            "budget_today": _budget_today(e.name, rows, events, now, a),
            "engine": {"url": url, "state": state, "name": info.get("name"), "version": info.get("version"), "heartbeat_at": beat},
            "supervised": state == "ok", "confirmed": not pend, "pending": pend,
            "override": _override(((st or {}).get("environments") or {}).get(e.name), a["declared"], m.paused), "caps": caps})
    if len(still) != len(pending_all):
        _write_cache(m.system, {**_read_cache(m.system), "pending": still})
    actions = [{**ev, "undo": audit.undo_state(ev, doc, events, now)} for ev in audit.done_on_its_own(events, now)]
    return {"schema": 1, "system": m.system, "read_at": _iso(now), "paused": m.paused,
            "paused_by_signal": any(x["override"] and x["override"]["kind"] == "pause" for x in envs) and not m.paused,
            "environments": envs, "actions": actions, "store": store, "unavailable": unavailable}


def runlist_rows() -> list[dict]:
    import runlist
    return runlist.collect(1).get("runs") or []


def _text(doc: dict) -> str:
    lines = [f"System {doc['system']}" + ("  (all autonomy paused)" if doc["paused"] else "")]
    for e in doc["environments"]:
        g, b, eg = e["guardrails"], e["budget_today"], e["engine"]
        lines += ["", f"{e['name']}: {e['declared']} declared, {e['effective']} effective (at most {e['cap']})"
                  + (", paused" if doc["paused"] else ", not paused"),
                  f"  autoMerge: routes {','.join(g['autoMerge']['routes']) or 'none'}, up to {g['autoMerge']['maxCriticality']} criticality",
                  "  riskGate: " + ", ".join(f"{k} {v}" for k, v in g["riskGate"].items()),
                  f"  budget: {b['runs']}/{b['runsPerDay']} runs, {b['merges']}/{b['mergesPerDay']} merges today, cost {b['cost']}",
                  f"  window: {','.join(g['window']['days'])} {g['window']['from']}-{g['window']['to']} {g['window']['timezone']}; "
                  f"undoWindow {e['undoWindow']}"]
        if eg["url"]:
            lines.append(f"  engine: {eg['name'] or 'engine'} {eg['url']} ({eg['state']}), last heartbeat {eg['heartbeat_at'] or 'never'}")
        else:
            lines.append("  engine: none")
        if e["override"]:
            lines.append(f"  override: {e['override']['kind']} to {e['override']['level']} by signal {e['override']['signal']}")
        for c in e["caps"]:
            lines.append(f"  cap: {c['component']} at most {c['max']} (effective {c['effective']})")
        if not e["supervised"]:
            lines.append("  not supervised")
        for p in e["pending"]:
            lines.append(f"  not confirmed: {p['kind']} signal {p['signal']}")
    if doc["actions"]:
        lines += ["", "Done on its own in the last 24 hours:"]
        for a in doc["actions"]:
            u = a["undo"]
            lines.append(f"  {a['at']} {a['kind']} in {a.get('environment')}: {a['event_id']} "
                         + (f"({u['command']})" if u["allowed"] else f"(no undo: {u['reason']})"))
    for u in doc["unavailable"]:
        lines.append(f"unavailable: {u['source']}: {u['error']}")
    return "\n".join(lines)


def cmd_show(ns: argparse.Namespace) -> int:
    doc = collect(gitops.find_app(Path(ns.repo_dir).resolve(), ns.system))
    print(jsonlib.dumps(doc, indent=2) if ns.json else _text(doc))
    return 0


# ---------------- set ----------------

def _number(text: str):
    try:
        return int(text)
    except ValueError:
        return float(text)


def _block_from_flags(old: dict, ns: argparse.Namespace) -> dict:
    new = copy.deepcopy(old)
    new["level"] = ns.level
    if ns.routes is not None:
        new.setdefault("autoMerge", {})["routes"] = [] if ns.routes == "none" else ["fix"]
    if ns.max_criticality is not None:
        new.setdefault("autoMerge", {})["maxCriticality"] = ns.max_criticality
    for flag, key in (("max_files", "maxFiles"), ("max_lines", "maxLines")):
        if getattr(ns, flag) is not None:
            new.setdefault("riskGate", {})[key] = getattr(ns, flag)
    for flag, key in (("regression_test", "regressionTest"), ("second_review", "secondReview")):
        if getattr(ns, flag) is not None:
            new.setdefault("riskGate", {})[key] = getattr(ns, flag) == "true"
    for flag, key in (("runs_per_day", "runsPerDay"), ("merges_per_day", "mergesPerDay")):
        if getattr(ns, flag) is not None:
            new.setdefault("budget", {})[key] = getattr(ns, flag)
    for item in ns.per_run:
        key, sep, value = item.partition("=")
        if not sep:
            raise PlatformError(f"--per-run {item}: expected KEY=VALUE", hint="e.g. --per-run cost=5")
        try:
            new.setdefault("budget", {}).setdefault("perRun", {})[key] = _number(value)
        except ValueError as e:
            raise PlatformError(f"--per-run {item}: '{value}' is not a number") from e
    if ns.days is not None:
        new.setdefault("window", {})["days"] = [d.strip() for d in ns.days.split(",") if d.strip()]
    for flag, key in (("from_", "from"), ("to", "to"), ("timezone", "timezone")):
        if getattr(ns, flag) is not None:
            new.setdefault("window", {})[key] = getattr(ns, flag)
    if ns.undo_window is not None:
        new["undoWindow"] = ns.undo_window
    if ns.engine is not None:
        new["engine"] = ns.engine
    return new


def _merge_into(target, new: dict, key_path: str = "") -> None:
    """Make the round-trip mapping `target` equal to `new`, keeping comments of what stays."""
    for k in [k for k in target if k not in new]:
        del target[k]
    for k, v in new.items():
        if isinstance(v, dict):
            if not isinstance(target.get(k), CommentedMap):
                target[k] = CommentedMap()
            _merge_into(target[k], v, f"{key_path}{k}.")
        elif isinstance(v, str) and k in ("from", "to") and key_path == "window." and _CLOCK.match(v):
            target[k] = DoubleQuotedScalarString(v)
        elif target.get(k) != v or k not in target:
            target[k] = v


def _show_value(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) or "none"
    if isinstance(v, dict):
        return ", ".join(f"{k} {x}" for k, x in v.items())
    return "-" if v is None else str(v)


def _pr_body(env: str, old: dict, new: dict, ns: argparse.Namespace, effect_line: str) -> str:
    of, nf = autonomy._fields(old), autonomy._fields(new)
    rows = ["| Setting | Old | New |", "| --- | --- | --- |"]
    rows += [f"| {k} | {_show_value(of.get(k))} | {_show_value(nf[k])} |" for k in nf]
    return "\n".join([f"`/system:autonomy set {env} {ns.level}`: autonomy of environment {env}, {old['declared']} → {new['declared']}.", "",
                      *rows, "", f"What {new['declared']} allows: {autonomy.allows(new['declared'])}", "", effect_line,
                      "", "Generated files regenerated by `devbox run render`."])


def _plan_signal(env_obj, old: dict, new: dict, system_paused: bool) -> tuple[dict | None, str]:
    """(the `lower` signal, the effect) of moving `old` to `new`."""
    verdicts = autonomy.compare(old, new)
    changed = {k: v for k, v in verdicts.items() if v != "same"}
    url = old.get("engine")
    if not url or "tighter" not in changed.values():
        return None, "after-merge"
    policy = autonomy.tighten(old, new)
    return {"kind": "lower", "policy": policy, "url": url}, ("now" if set(changed.values()) == {"tighter"} else "mixed")


def cmd_set(ns: argparse.Namespace) -> int:
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.system)
    m = model.load_dir(app_dir)
    env_obj = _env_of(m, ns.env)
    y, data = gitops.load(app_dir)
    envs = data.get("environments") or {}
    if env_obj is None or ns.env not in envs:
        raise PlatformError(f"no environment '{ns.env}' in {app_dir.name}", hint="environments: " + ", ".join(e.name for e in m.environments))
    if envs[ns.env] is None:
        envs[ns.env] = CommentedMap()
    old_block = _plain(envs[ns.env].get("autonomy") or {})
    new_block = _block_from_flags(old_block, ns)
    autonomy.validate(ns.env, new_block)
    if new_block == old_block:
        raise PlatformError("nothing to change", hint=f"{ns.env} already has these autonomy settings")
    old_eff = env_obj.autonomy
    new_eff = autonomy.effective(ns.env, new_block, paused=m.paused, promotion=old_eff["promotion"])
    signal, effect = _plan_signal(env_obj, old_eff, new_eff, m.paused)

    r = Report(title=f"system autonomy set: {ns.env} ({app_dir.name})")
    r.will_do.append(f"set environments.{ns.env}.autonomy: {old_eff['declared']} → {new_eff['declared']}")
    r.will_do.append("regenerate autonomy.json (render.py)")
    if signal:
        r.will_do.append(f"[outward] signal {env_obj.autonomy['engine']}: lower to the tighter values (in effect now)")
    if ns.pr:
        r.will_do.append("[outward] open a pull request (branch system/autonomy-…)")
    r.data = {"signal": {"kind": signal["kind"], "policy": signal["policy"]} if signal else None, "effect": effect, "pr": None}
    if ns.dry_run:
        r.emit(True, ns.json)
        return 0
    gitops.require_clean(repo)
    before = systemset.snapshot(repo)
    _merge_into(envs[ns.env].setdefault("autonomy", CommentedMap()), new_block)
    gitops.save(app_dir, y, data)
    try:
        gitops.render(repo)
    except PlatformError:
        systemset.restore(repo, before)
        raise
    changed = gitops.rendered_changes(repo)
    r.did.append(f"updated system.yaml and regenerated {len(changed)} file(s)")
    url = sid = None
    if ns.pr:
        login = _login()
        if signal:
            res = engine.send({ns.env: signal["url"]}, "lower", system=m.system, actor=login, policy_of={ns.env: signal["policy"]})[ns.env]
            sid = res["signal"]
            _remember_pending(m.system, "lower", {ns.env: res}, level=new_eff["declared"])
            how = "confirmed" if res["confirmed"] else f"not confirmed: {res['reason']}"
            r.did.append(f"signal {sid} to {signal['url']}: {how}")
            effect_line = f"In effect now by signal {sid} ({how}); the rest after the merge."
        else:
            effect_line = "Takes effect after the merge."
        url = gitops.open_pr(repo, f"system/autonomy-{gitops.slug(ns.env)}",
                             f"chore(system): autonomy {ns.env} {old_eff['declared']} → {new_eff['declared']}",
                             _pr_body(ns.env, old_eff, new_eff, ns, effect_line))
        r.did.append(f"opened {url}")
        _record(audit.person_event("set", actor=login, system=m.system, environment=ns.env, object={"type": "system", "environment": ns.env},
                                   policy=new_eff, detail={"old": old_eff, "new": new_eff, "pr": url, "signal": sid}))
        r.next_steps.append("review and merge the PR; a lower level is already in effect by signal, the rest follows the merge")
    else:
        r.next_steps.append("review the diff, then commit (or re-run with --pr)")
    r.undo.append("discard the working-tree changes under applications and bootstrap")
    r.data = {**r.data, "changed": changed, "pr": url}
    r.emit(False, ns.json)
    return 0


# ---------------- pause and resume ----------------

def _print_results(m: model.Model, results: dict[str, dict]) -> list[str]:
    lines = []
    for e in m.environments:
        res = results.get(e.name)
        if res is None:
            lines.append(f"{e.name}: no engine, nothing signalled")
        elif res["confirmed"]:
            lines.append(f"{e.name}: confirmed (signal {res['signal']})")
        elif str(res["reason"]).startswith("no confirmation"):
            lines.append(f"{e.name}: not confirmed within {engine.CONFIRM_SECONDS} s: "
                         f"{str(res['reason']).split(': ', 1)[-1]} (signal {res['signal']})")
        else:
            lines.append(f"{e.name}: not confirmed: {res['reason']} (signal {res['signal']})")
    print("\n".join(lines))
    return lines


def _set_paused(data, paused: bool) -> bool:
    """Set or remove the top-level `autonomy.paused`; False when the file already says so."""
    top = data.get("autonomy")
    if paused:
        if top is not None and top.get("paused") is True:
            return False
        if top is None:
            data.insert(0, "autonomy", CommentedMap([("paused", True)]))
        else:
            top["paused"] = True
        return True
    if top is None or "paused" not in top:
        return False
    del top["paused"]
    if not top:
        del data["autonomy"]
    return True


def _pause_resume(ns: argparse.Namespace, kind: str) -> int:
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.system)
    m = model.load_dir(app_dir)
    targets = _targets(m)
    pausing = kind == "pause"
    r = Report(title=f"system autonomy {kind} ({app_dir.name})")
    r.will_do += [f"[outward] signal {kind} to the engine of {', '.join(targets) or 'no environment (none has an engine)'}",
                  f"{'set' if pausing else 'remove'} autonomy.paused in system.yaml and regenerate autonomy.json (render.py)",
                  "[outward] " + ("open a pull request (branch system/autonomy-pause)" if pausing
                                  else f"close the open pause pull request, else open one (branch system/autonomy-resume)")]
    r.data = {"signal": {"kind": kind, "environments": list(targets)}, "effect": "now", "pr": None}
    if ns.dry_run:
        r.emit(True, ns.json)
        return 0
    if not ns.pr:
        raise PlatformError(f"{kind} needs --pr", hint=f"run `cplat system autonomy {kind} --dry-run` to preview, then with --pr")
    login = _login()
    results = engine.send(targets, kind, system=m.system, actor=login) if targets else {}
    _remember_pending(m.system, kind, results)
    r.did += _print_results(m, results) if not ns.json else [f"{n}: {'confirmed' if x['confirmed'] else 'not confirmed: ' + str(x['reason'])}" for n, x in results.items()]
    url = None
    try:
        url = _land(repo, app_dir, ns, kind, login, r)
    finally:
        sigs = {n: x["signal"] for n, x in results.items()}
        lead = next((x["signal"] for x in results.values() if not x["confirmed"]), next(iter(sigs.values()), None))   # an unconfirmed one first
        _record(audit.person_event(kind, actor=login, system=m.system, environment=None, object={"type": "system"}, policy={},
                                   detail={"confirmed": sorted(n for n, x in results.items() if x["confirmed"]),
                                           "unconfirmed": sorted(n for n, x in results.items() if not x["confirmed"]),
                                           "pr": url, "signal": lead, "signals": sigs}))
    r.data = {**r.data, "pr": url, "results": {n: {"confirmed": x["confirmed"], "reason": x["reason"]} for n, x in results.items()}}
    if ns.json:
        r.emit(False, True)
    return 0


def _land(repo: Path, app_dir: Path, ns: argparse.Namespace, kind: str, login: str, r: Report) -> str | None:
    """Close the open pause PR (resume), or edit, render and open the PR. Returns the PR URL."""
    if kind == "resume":
        open_prs = jsonlib.loads(gh(["pr", "list", "--head", PAUSE_BRANCH, "--state", "open", "--json", "number,url"]) or "[]")
        if open_prs:
            pr = open_prs[0]
            gh(["pr", "close", pr["number"], "--comment", f"Resumed by {login} at {_iso(runs.utcnow())} before this merged."])
            r.did.append(f"closed the open pause pull request {pr.get('url') or pr['number']}")
            print(f"Closed the open pause pull request {pr.get('url') or pr['number']}")
            return pr.get("url")
    gitops.require_clean(repo)
    y, data = gitops.load(app_dir)
    if not _set_paused(data, kind == "pause"):
        r.did.append(f"system.yaml already {'paused' if kind == 'pause' else 'not paused'}: no pull request")
        print(f"system.yaml already {'says paused' if kind == 'pause' else 'has no pause'}: no pull request needed")
        return None
    before = systemset.snapshot(repo)
    gitops.save(app_dir, y, data)
    try:
        gitops.render(repo)
    except PlatformError:
        systemset.restore(repo, before)
        raise
    title = "chore(system): pause all autonomy" if kind == "pause" else "chore(system): resume autonomy"
    body = (f"`/system:autonomy {kind}`: " + ("sets `autonomy.paused: true`, so every environment acts as observe."
                                             if kind == "pause" else "removes `autonomy.paused`; the levels in system.yaml apply again.")
            + "\n\nThe engines were signalled first; this pull request records it in git.")
    url = gitops.open_pr(repo, PAUSE_BRANCH if kind == "pause" else "system/autonomy-resume", title, body)
    r.did.append(f"opened {url}")
    print(f"Opened {url}")
    return url


# ---------------- main ----------------

def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    if ns.verb == "show":
        return cmd_show(ns)
    if ns.verb == "set":
        return cmd_set(ns)
    if ns.verb in ("pause", "resume"):
        return _pause_resume(ns, ns.verb)
    import autonomy_actions
    repo = Path(ns.repo_dir).resolve()
    if ns.verb == "undo":
        return autonomy_actions.undo(repo, ns.event_id, dry_run=ns.dry_run, json=ns.json)
    return autonomy_actions.approve(repo, ns.target, dry_run=ns.dry_run, json=ns.json)
