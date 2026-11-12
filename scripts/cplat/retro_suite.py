"""The retro section "Test suite time" (spec 185, AC-185.8): the `main` CI runs with timing data, their median times per week,
and the slowest tests of the retro week. `fetch` is the one seam to GitHub; it raises `SuiteTimeError` with the reason."""
from __future__ import annotations

import datetime
import json
import statistics
import tempfile
from pathlib import Path

import retro_github
import retro_report
import retro_rules

ARTIFACT = "cplat-suite-time"
TOP = 15
_FILE = "suite-time.json"


class SuiteTimeError(Exception):
    """Timing data that cannot be read; the message is the reason shown in the retro."""


def _gh(args: list[str]) -> str:
    code, out, err = retro_github.gh(args, timeout=120.0)
    if code != 0:
        raise SuiteTimeError((err or out).strip().splitlines()[0] if (err or out).strip() else f"gh exited with {code}")
    return out


def _pages(text: str) -> list[dict]:
    """`gh api --paginate` prints one JSON document per page, back to back."""
    dec, i, pages = json.JSONDecoder(), 0, []
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        obj, i = dec.raw_decode(text, i)
        pages.append(obj)
    return pages


def fetch(repo: str, since: datetime.date) -> list[dict]:
    try:
        text = _gh(["api", "--paginate", f"repos/{repo}/actions/artifacts?name={ARTIFACT}&per_page=100"])
        found: dict[str, str] = {}
        for page in _pages(text):
            for a in page.get("artifacts", []):
                run = a.get("workflow_run") or {}
                created = str(a.get("created_at") or "")
                if (a.get("name") != ARTIFACT or a.get("expired") or run.get("head_branch") != "main"
                        or datetime.date.fromisoformat(created[:10]) < since):
                    continue
                found[str(run.get("id"))] = created
        runs = []
        for run_id, created in sorted(found.items()):
            with tempfile.TemporaryDirectory(prefix="suite-time-") as tmp:
                _gh(["run", "download", run_id, "-R", repo, "-n", ARTIFACT, "-D", tmp])
                runs.append({"run_id": run_id, "created_at": created, "data": json.loads((Path(tmp) / _FILE).read_text(encoding="utf-8"))})
        return runs
    except SuiteTimeError:
        raise
    except (ValueError, OSError, AttributeError, TypeError) as e:
        raise SuiteTimeError(f"{type(e).__name__}: {e}") from None


REAL_FETCH = fetch


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _week_of(created: str) -> str | None:
    try:
        return retro_report._week_str(datetime.datetime.fromisoformat(created.replace("Z", "+00:00")).date())
    except (ValueError, AttributeError):
        return None


def _timed(run: dict) -> bool:
    d = run.get("data")
    return isinstance(d, dict) and _num(d.get("suite_s")) and _num(d.get("slowest_shard_s"))


def section(week: str, runs: list[dict]) -> dict:
    weeks_list = list(reversed(retro_rules.weeks_of(week)))
    by_week: dict[str, list[dict]] = {w: [] for w in weeks_list}
    for r in runs:
        w = _week_of(str(r.get("created_at") or ""))
        if w in by_week and _timed(r):
            by_week[w].append(r)
    weeks = []
    for w in weeks_list:
        rs = by_week[w]
        if rs:
            weeks.append({"week": w, "runs": len(rs), "median_suite_s": float(statistics.median(r["data"]["suite_s"] for r in rs)),
                          "median_slowest_shard_s": float(statistics.median(r["data"]["slowest_shard_s"] for r in rs))})
        else:
            weeks.append({"week": w, "runs": 0})
    seconds: dict[str, list[float]] = {}
    for r in by_week[week]:
        for t in r["data"].get("slowest") or []:
            if isinstance(t, dict) and isinstance(t.get("id"), str) and _num(t.get("s")):
                seconds.setdefault(t["id"], []).append(t["s"])
    ranked = sorted(((float(statistics.median(v)), k, len(v)) for k, v in seconds.items()), key=lambda x: (-x[0], x[1]))[:TOP]
    return {"weeks": weeks, "slowest": [{"id": k, "median_s": m, "runs": n} for m, k, n in ranked], "unavailable": None}


def unavailable(reason: str) -> dict:
    return {"weeks": [], "slowest": [], "unavailable": reason}


def render(sec: dict) -> str:
    out = ["## Test suite time"]
    if sec.get("unavailable"):
        out.append(f"not available: {sec['unavailable']}")
        return "\n".join(out) + "\n"
    out += ["| week | runs | median suite time | median slowest shard |", "|---|---|---|---|"]
    for w in sec["weeks"]:
        if w["runs"]:
            out.append(f"| {w['week']} | {w['runs']} | {w['median_suite_s']:.1f} s | {w['median_slowest_shard_s']:.1f} s |")
        else:
            out.append(f"| {w['week']} | no data | | |")
    week = sec["weeks"][0]["week"] if sec["weeks"] else ""
    if sec["slowest"]:
        out.append(f"Slowest tests of {week} (median over runs):")
        out += [f"  {i}. {t['median_s']:.1f} s  {t['id']} ({t['runs']} runs)" for i, t in enumerate(sec["slowest"], 1)]
    else:
        out.append(f"Slowest tests of {week}: no data")
    return "\n".join(out) + "\n"
