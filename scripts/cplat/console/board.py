"""The Board of the console (spec 122, AC-122.9 .. AC-122.12, AC-122.40, AC-122.48, AC-122.49).

  page(ctx, query) -> full HTML of `/board`

Every open item is in exactly one stage column (`data-column`, `data-card`); `view=list` shows the same items as one table
and `view=done&period=30|90|all` lists what was finished, newest first. `q=` filters open and done items by id, a title
word, a component name or `#n`. Stages are named only through `stages.py` and `html.stage_badge`. The column headers open
`/panel/stage/<name>`; the cards open the side panel of their spec, run, issue or release."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlencode

import stages
from console import actions, handoff, layout, sources as sources_mod
from console.html import action_button, esc, freshness, stage_badge, table, unavailable

PERIODS = {"30": 30, "90": 90, "all": None}
DEFAULT_PERIOD = "30"
VIEWS = (("board", "Columns"), ("list", "List"), ("done", "Done"))
COLUMN_STYLE = "display:flex;gap:var(--s3);align-items:flex-start"
COLUMN_BOX = "flex:0 0 16rem;min-width:16rem"


# ---------------- items ----------------

def _num(value: Any) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def _panel(kind: str, ident: str) -> str:
    return f"/panel/{kind}/{quote(str(ident), safe='')}"


def _run_stage(run: dict) -> tuple[str | None, bool]:
    """`(stage, stopped)` of a run row; `cplat runs` already names the stage, `stages` is the fallback."""
    stage, stopped = run.get("stage"), bool(run.get("stopped"))
    if stage in stages.STAGES:
        return stage, stopped
    try:
        return stages.stage_of_run(str(run.get("phase")), run.get("stopped_in"))
    except ValueError:
        return None, stopped


def _best_run(runs: list[dict], repo: str, spec: str) -> dict | None:
    """The run of a spec: an active one first, else the latest started."""
    mine = [r for r in runs if r.get("repo") == repo and r.get("spec") == spec]
    return max(mine, key=lambda r: (bool(r.get("active")), str(r.get("started_at") or ""))) if mine else None


def _run_info(run: dict | None) -> dict:
    if not run:
        return {}
    budget = run.get("budget") or {}
    used, limit = budget.get("used") or {}, budget.get("limit") or {}
    parts = []
    if limit.get("cost") is not None:
        parts.append(f"Cost {_num(used.get('cost', 0))} of {_num(limit['cost'])} USD")
    if limit.get("minutes") is not None:
        parts.append(f"{_num(used.get('minutes', 0))} of {_num(limit['minutes'])} min")
    return {"budget": ", ".join(parts), "why": ((run.get("escalation") or {}).get("summary") or "") if run.get("stopped") else ""}


def _spec_stage(row: dict, runs: list[dict]) -> tuple[str | None, bool, dict | None]:
    """Stage, stopped and the run of a spec row; a system spec takes the earliest stage of its slices."""
    run = _best_run(runs, str(row.get("repo")), str(row.get("id")))
    pairs = []
    for sl in row.get("slices") or []:
        srun = _best_run(runs, str(sl.get("repo")), str(sl.get("spec")))
        pairs.append((stages.stage_of_spec(str(sl.get("status")), _phase(srun)), bool(srun and srun.get("stopped"))))
    slice_stage = stages.earliest(s for s, _ in pairs)
    if slice_stage:
        return slice_stage, any(stopped for _, stopped in pairs), run
    stage = stages.stage_of_spec(str(row.get("status")), _phase(run))
    return stage, bool(run and run.get("stopped") and stage), run


def _phase(run: dict | None) -> dict | None:
    return {"phase": run.get("phase"), "stopped_in": run.get("stopped_in")} if run else None


def _spec_state(row: dict, stage: str, stopped: bool, run: dict | None) -> str:
    if stopped:
        return "Stopped"
    if run and run.get("active"):
        return "Running"
    if stage == "Spec":
        if row.get("open_questions"):
            return f"{row['open_questions']} open questions"
        if not (row.get("check") or {}).get("ok", True):
            return "Spec check fails"
        return "Waiting for your decision"
    return "Not started"


def _components(ctx: Any) -> dict[str, str]:
    """Component name to repo, from the model."""
    model = ctx.data("model") or {}
    return {c.get("name"): c.get("repo") for c in model.get("components") or [] if c.get("name")}


def open_items(ctx: Any) -> list[dict]:
    """Every open item once: specs, runs without a spec row, untracked issues and releases waiting for prod."""
    runs = (ctx.data("runs") or {}).get("runs") or []
    items: list[dict] = []
    seen_runs: set[str] = set()
    for name in sorted(ctx.sources):
        if not name.startswith("specs:"):
            continue
        for row in ctx.data(name) or []:
            row = {"repo": name[len("specs:"):], **row}
            stage, stopped, run = _spec_stage(row, runs)
            if stage is None:
                continue
            if run:
                seen_runs.add(str(run.get("run_id")))
            items.append({"kind": "spec", "stage": stage, "stopped": stopped, "id": row["id"], "title": row.get("title") or "",
                          "repo": row["repo"], "component": str(row["repo"]).split("/")[-1],
                          "state": _spec_state(row, stage, stopped, run), "open": _panel("spec", f"{row['repo']}:{row['id']}"),
                          **_run_info(run)})
    for run in runs:
        if str(run.get("run_id")) in seen_runs or run.get("phase") == "done" or not (run.get("active") or run.get("stopped")):
            continue
        stage, stopped = _run_stage(run)
        if stage is None:
            continue
        spec = str(run.get("spec") or run.get("run_id"))
        items.append({"kind": "run", "stage": stage, "stopped": stopped, "id": spec, "title": "", "repo": run.get("repo") or "",
                      "component": str(run.get("repo") or "").split("/")[-1],
                      "state": "Stopped" if stopped else "Running", "open": _panel("run", run.get("run_id")), **_run_info(run)})
    items += _need_items(ctx)
    return items


def _need_items(ctx: Any) -> list[dict]:
    repos = _components(ctx)
    items = []
    for need in (ctx.data("needs") or {}).get("items") or []:
        obj = need.get("object") or {}
        if need.get("kind") == "triage" and obj.get("issue") is not None:
            if stages.stage_of_issue({"state": "OPEN", "labels": []}) != "Issue":
                continue
            items.append({"kind": "issue", "stage": "Issue", "stopped": False, "id": f"#{obj['issue']}",
                          "title": need.get("reason") or "", "repo": obj.get("repo") or need.get("cwd_repo") or "",
                          "component": "", "state": "Open, not triaged", "open": _panel("issue", obj["issue"])})
        elif need.get("kind") == "promote" and obj.get("component"):
            if stages.stage_of_release({"verified": True, "running_in_prod": False}) != "Prod":
                continue
            repo = obj.get("repo") or repos.get(obj["component"]) or ""
            items.append({"kind": "release", "stage": "Prod", "stopped": False, "id": f"{obj['component']} {obj.get('version')}",
                          "title": "", "repo": repo, "component": obj["component"], "state": "Verified in staging, waits to be promoted",
                          "open": _panel("release", f"{obj['component']}:{obj.get('version')}")})
    for row in (ctx.data("status") or {}).get("rows") or []:
        cand = row.get("release_candidate")
        if cand and cand.get("version"):
            items.append({"kind": "candidate", "stage": "Prod", "stopped": False, "id": f"{row['component']} {cand['version']}",
                          "title": "", "repo": repos.get(row["component"]) or "", "component": row["component"],
                          "state": "New version ready to release", "version": cand["version"],
                          "open": _panel("release", f"{row['component']}:{cand['version']}")})
    return items


def done_items(ctx: Any) -> list[dict]:
    """Finished runs, newest first, each with the stage it reached and its links."""
    runs = (ctx.data("runs") or {}).get("runs") or []
    titles = {(n[len("specs:"):], r.get("id")): r.get("title") for n in ctx.sources if n.startswith("specs:")
              for r in ctx.data(n) or []}
    out = []
    for run in runs:
        if run.get("active") or not (run.get("phase") == "done" or run.get("outcome") == "done"):
            continue
        stage, _ = _run_stage(run)
        spec = str(run.get("spec") or run.get("run_id"))
        out.append({"kind": "run", "stage": stage, "id": spec, "title": titles.get((run.get("repo"), run.get("spec"))) or "",
                    "repo": run.get("repo") or "", "component": str(run.get("repo") or "").split("/")[-1],
                    "ended": run.get("ended_at") or "", "links": handoff.links_for_work(run), "open": _panel("run", run.get("run_id"))})
    return sorted(out, key=lambda i: i["ended"], reverse=True)


# ---------------- search ----------------

def matches(item: dict, needle: str) -> bool:
    """True if the id, a title word, the component, the repo or `#n` contains the (lower-case) needle."""
    if not needle:
        return True
    hay = " ".join(str(item.get(k) or "") for k in ("id", "title", "repo", "component")).lower()
    return needle.lower().lstrip("#") in hay if needle.startswith("#") else needle in hay


# ---------------- markup ----------------

def _link(item: dict) -> str:
    return f'<a href="{esc(item["open"])}">{esc(item["id"])}</a>'


def _cut_release(item: dict) -> str:
    obj = {"type": "release", "repo": item["repo"], "component": item["component"], "version": item["version"]}
    reasons = actions.prerequisites("cut-release", obj, dict(os.environ))
    reason = f"Needs {', '.join(reasons)}" if reasons else None
    if reason is None and actions.active_for(obj):
        reason = "Another action is running on this release"
    return action_button("cut-release", "Cut release", None, reason, attrs={"data_object": json.dumps(obj)})


def _card(item: dict) -> str:
    title = f"<span>{esc(item['title'])}</span>" if item.get("title") else ""
    why = f'<p class="why">{esc(item["why"])}</p>' if item.get("why") else ""
    budget = f'<p class="muted">{esc(item["budget"])}</p>' if item.get("budget") else ""
    extra = _cut_release(item) if item["kind"] == "candidate" else ""
    return (f'<article class="card" data-card data-open="{esc(item["open"])}" tabindex="0">'
            f'<h3>{_link(item)}</h3>{title}'
            f'<p class="muted">{esc(item["repo"])}</p>'
            f'<p>{stage_badge(item["stage"])} {esc(item["state"])}</p>{budget}{why}{extra}</article>')


def _column(stage: str, cards: list[dict]) -> str:
    info = stages.explain(stage)
    decision = " data-decision" if stage in stages.DECISION else ""
    hints = f'<p class="muted">{esc(info["what"])}</p>'
    if info["decision"]:
        hints += f'<p class="muted">{esc(info["decision"])}</p>'
    href = esc(_panel("stage", stage))
    ordered = sorted(cards, key=lambda i: (not i["stopped"], i["id"]))
    body = "".join(_card(i) for i in ordered)
    return (f'<section class="column" data-column="{esc(stage)}"{decision} style="{COLUMN_BOX}" aria-label="{esc(stage)} column">'
            f'<h2><a href="{href}" data-open="{href}">{stage_badge(stage)}</a> <span class="count">{len(cards)}</span></h2>'
            f'{hints}{body}</section>')


def _columns(items: list[dict]) -> str:
    cols = "".join(_column(s, [i for i in items if i["stage"] == s]) for s in stages.STAGES)
    return f'<div class="scroll-x"><div class="board" style="{COLUMN_STYLE}">{cols}</div></div>'


def _list(items: list[dict]) -> str:
    if not items:
        return "<p>Nothing is open.</p>"
    rows = [[_link(i), esc(i["repo"]), stage_badge(i["stage"]), esc(i["state"] + (f". {i['why']}" if i.get("why") else ""))]
            for i in sorted(items, key=lambda i: (stages.STAGES.index(i["stage"]), i["id"]))]
    return table(rows, ["Item", "Repo", "Stage", "State"])


def _date(stamp: str) -> str:
    return f'<time datetime="{esc(stamp)}">{esc(stamp[:10])}</time>' if stamp else ""


def _done(items: list[dict], empty: str) -> str:
    if not items:
        return f"<p>{esc(empty)}</p>"
    rows = []
    for i in items:
        links = " ".join(f'<a href="{esc(link["url"])}">{esc(link["label"])}</a>' for link in i["links"])
        label = f"{i['id']} {i['title']}".strip()
        rows.append([f'<a href="{esc(i["open"])}">{esc(label)}</a>', esc(i["repo"]),
                     stage_badge(i["stage"]) if i["stage"] else "", _date(i["ended"]), links])
    return table(rows, ["Item", "Repo", "Stage reached", "Finished", "Links"])


def _within(item: dict, period: str, now: Any) -> bool:
    days = PERIODS[period]
    ended = sources_mod.parse_iso(item["ended"])
    return days is None or (ended is not None and now - ended <= timedelta(days=days))


def _nav(view: str, period: str, needle: str) -> str:
    def href(v: str) -> str:
        params = {"view": v, **({"q": needle} if needle else {})}
        return "/board?" + urlencode(params)

    tabs = "".join(f'<a href="{esc(href(v))}"{" aria-current=\"page\"" if v == view else ""}>{label}</a> ' for v, label in VIEWS)
    periods = ""
    if view == "done":
        periods = " ".join(
            f'<a href="{esc("/board?" + urlencode({"view": "done", "period": p, **({"q": needle} if needle else {})}))}"'
            f'{" aria-current=\"true\"" if p == period else ""}>{"All" if p == "all" else f"Last {p} days"}</a>' for p in PERIODS)
    return (f'<nav aria-label="Board views" class="views">{tabs}{periods}</nav>'
            f'<form method="get" action="/board" role="search"><input type="hidden" name="view" value="{esc(view)}">'
            + (f'<input type="hidden" name="period" value="{esc(period)}">' if view == "done" else "")
            + f'<input type="search" name="q" value="{esc(needle)}" aria-label="Search the board" placeholder="Id, title, component or #n">'
            ' <button type="submit" class="btn">Search</button></form>')


def _unavailable(ctx: Any) -> str:
    out = ""
    for name in ["runs", "needs", "status", *sorted(n for n in ctx.sources if n.startswith("specs:"))]:
        src = ctx.source(name)
        if src is not None and src.data is None and src.error:
            out += unavailable(name, src.unavailable_since, src.error)
    return out


def page(ctx: Any, query: dict[str, str]) -> str:
    """The Board: columns by default, `view=list`, or `view=done&period=…`; `q=` filters all of them."""
    view = query.get("view") if query.get("view") in {v for v, _ in VIEWS} else "board"
    period = query.get("period") if query.get("period") in PERIODS else DEFAULT_PERIOD
    needle = (query.get("q") or "").strip()
    now = sources_mod.utcnow()
    opened = [i for i in open_items(ctx) if matches(i, needle.lower())]
    finished = [i for i in done_items(ctx) if matches(i, needle.lower())]
    runs_source = ctx.source("runs")
    stamp = f'<p class="muted">{freshness(runs_source.read_at if runs_source else None, now)}</p>'
    if view == "done":
        shown = finished if needle else [i for i in finished if _within(i, period, now)]
        body = _done(shown, "Nothing was finished in this period." if not needle else "No finished item matches.")
    elif view == "list":
        body = _list(opened)
        if needle and finished:
            body += "<h2>Done</h2>" + _done(finished, "")
    else:
        body = _columns(opened)
        if needle and finished:
            body += "<h2>Done</h2>" + _done(finished, "")
    return layout.page("Board", "board", _nav(view, period, needle) + _unavailable(ctx) + stamp + body, state=ctx.state())
