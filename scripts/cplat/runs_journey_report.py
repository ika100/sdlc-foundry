"""The journey section of `cplat platform runs report --benchmarks` (spec 136, AC-136.8, ADR-081).

Per platform version and coordinator model: per stage, part and journey the median working time and wall clock of the done
journey runs, the budget, the overrun, the median person-wait, external wait and PR count, and the previous version's
medians; the stages ranked by overrun. Pure functions without I/O, tolerant of odd records.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

import runs_journey
import runs_report

FIELDS = (("working_median", "working_minutes"), ("wall_median", "wall_minutes"), ("person_wait_median", "person_wait_minutes"),
          ("external_wait_median", "external_wait_minutes"), ("prs_median", "prs"))


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _median(values: list[float]):
    if not values:
        return None
    m = statistics.median(values)
    return int(m) if float(m).is_integer() else round(m, 1)


def _version_key(version: str) -> tuple:
    parts = re.findall(r"\d+", version.split("+")[0].split("-")[0])
    return tuple(int(p) for p in parts) if parts else (-1,)


def _ran(entry) -> bool:
    return isinstance(entry, dict) and entry.get("status") != "not run" and _num(entry.get("working_minutes")) is not None


def _entries(rec: dict, kind: str) -> dict:
    """{stage id | part number | "journey": entry} of one record."""
    j = rec.get("journey") if isinstance(rec.get("journey"), dict) else {}
    if kind == "stages":
        return {s.get("id"): s for s in j.get("stages") or [] if isinstance(s, dict)}
    if kind == "parts":
        return {p.get("part"): p for p in j.get("parts") or [] if isinstance(p, dict)}
    return {"journey": j.get("total")}


def _row(done: list[dict], kind: str, key, budget: int) -> dict:
    ran = [e for e in (_entries(r, kind).get(key) for r in done) if _ran(e)]
    row = {"runs": len(ran), **{name: _median([v for v in (_num(e.get(f)) for e in ran) if v is not None]) for name, f in FIELDS},
           "budget_minutes": budget}
    w = row["working_median"]
    row["overrun_minutes"] = None if w is None else (lambda o: int(o) if float(o).is_integer() else round(o, 1))(max(0, w - budget))
    return row


def _group(done: list[dict]) -> dict:
    stages = [{"id": sid, "part": part, **_row(done, "stages", sid, budget)} for sid, part, budget in runs_journey.STAGES]
    parts = [{"part": n, **_row(done, "parts", n, b)} for n, b in runs_journey.PART_BUDGETS.items()]
    total = _row(done, "total", "journey", runs_journey.JOURNEY_BUDGET)
    return {"stages": stages, "parts": parts, "total": total}


def _rank(stages: list[dict]) -> list[dict]:
    order = {sid: i for i, sid in enumerate(runs_journey.STAGE_IDS)}
    have = [s for s in stages if s["working_median"] is not None]
    rest = [s for s in stages if s["working_median"] is None]
    return sorted(have, key=lambda s: (-(s["working_median"] - s["budget_minutes"]), order[s["id"]])) + rest


def _prev(row: dict | None) -> dict | None:
    if not row or row.get("working_median") is None:
        return None
    return {"working_median": row["working_median"], "wall_median": row["wall_median"]}


def aggregate(kept: list[dict]) -> dict:
    """`kept`: the records of the report window. Returns the value of the `journey` key."""
    cells: dict[tuple[str, str], list[dict]] = {}
    for r in kept:
        if r.get("kind") != "journey":
            continue
        j = r.get("journey") if isinstance(r.get("journey"), dict) else {}
        model = j.get("coordinator_model") if isinstance(j.get("coordinator_model"), str) and j.get("coordinator_model") else "unknown"
        cells.setdefault((runs_report._text(r.get("platform_version")), model), []).append(r)
    groups: dict[tuple[str, str], dict] = {}
    for (version, model), rs in cells.items():
        done = [r for r in rs if r.get("outcome") == "done"]
        groups[(version, model)] = {"platform_version": version, "coordinator_model": model, "runs": len(rs), "done": len(done),
                                    "outcomes": runs_report._count_sorted(Counter(runs_report._text(r.get("outcome")) for r in rs)),
                                    **_group(done)}
    out: dict[str, dict] = {}
    for (version, model) in sorted(groups, key=lambda k: (_version_key(k[0]), k[0], k[1]), reverse=True):   # newest first
        g = groups[(version, model)]
        earlier = [v for (v, m), x in groups.items() if m == model and x["done"] and _version_key(v) < _version_key(version)]
        prev_v = max(earlier, key=_version_key) if earlier else None
        p = groups.get((prev_v, model)) if prev_v else None
        for s in g["stages"]:
            s["previous"] = _prev(next((x for x in p["stages"] if x["id"] == s["id"]), None)) if p else None
        for part in g["parts"]:
            part["previous"] = _prev(next((x for x in p["parts"] if x["part"] == part["part"]), None)) if p else None
        g["total"]["previous"] = _prev(p["total"]) if p else None
        g["stages"] = _rank(g["stages"])
        out[f"{version} ({model})"] = {**{k: g[k] for k in ("platform_version", "coordinator_model", "runs", "done", "outcomes")},
                                       "previous_version": prev_v, "stages": g["stages"], "parts": g["parts"], "total": g["total"]}
    return out


def _f(x) -> str:
    return "-" if x is None else f"{x:g}"


def render_lines(journey: dict) -> list[str]:
    if not journey:
        return ["Journey: none"]
    lines: list[str] = []
    for key, g in journey.items():
        lines.append(f"Journey {key}: {g['runs']} run(s), {g['done']} done"
                     + (f"; outcomes {runs_report._pairs(g['outcomes'])}" if g["runs"] != g["done"] else ""))
        if not g["done"]:
            lines.append("  no done run")
            continue
        prev = f"prev {g['previous_version']}" if g["previous_version"] else "prev"
        lines.append(f"  {'stage':<16}{'working':>8}{'wall':>7}{'budget':>7}{'over':>6}{'person':>8}{'external':>9}{'PRs':>5}  {prev}")
        rows = [(s["id"], s) for s in g["stages"]] + [(f"part {p['part']}", p) for p in g["parts"]] + [("journey", g["total"])]
        for name, r in rows:
            pv = r.get("previous")
            lines.append(f"  {name:<16}{_f(r['working_median']):>8}{_f(r['wall_median']):>7}{r['budget_minutes']:>7}"
                         f"{_f(r['overrun_minutes']):>6}{_f(r['person_wait_median']):>8}{_f(r['external_wait_median']):>9}"
                         f"{_f(r['prs_median']):>5}  " + (f"{_f(pv['working_median'])} / {_f(pv['wall_median'])}" if pv else "-"))
    lines.append("Working time is wall clock minus person-wait; medians over done runs; stages ranked by overrun (spec 136).")
    return lines
