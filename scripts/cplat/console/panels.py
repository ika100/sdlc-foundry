"""Side panels of the console (spec 122: AC-122.12 - AC-122.15, AC-122.33 - AC-122.36, AC-122.39, AC-122.47).

  panel_spec(ctx, spec_id)       stage strip, one line per slice, criteria, evidence chain
  panel_run(ctx, run_id)         one run: budget, failure, ways forward, links
  panel_issue(ctx, number)       a triage issue: fix, make a spec, dismiss
  panel_instance(ctx, ident)     one component (or resource) in one environment, with its Argo CD / Grafana / logs links
  panel_release(ctx, ident)      a release candidate and what "Cut release" does
  panel_stage(ctx, stage)        what a Board column means (`stages.explain`)

`ident` of a spec is `<repo>:<spec id>`, of an instance `<component>:<env>` (`/` and `@` also work), of a release
`<component>:<version>` (or `<component>-<version>`), of an issue `<n>` (or `<repo>#<n>`).
Each view returns an `<aside data-panel>` fragment and raises `LookupError` for an unknown id (HTTP 404).
Stage names are computed by `stages`; this module never maps a status or a phase itself."""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

import stages
from console import actions, handoff
from console.html import action_button, command_block, engine_badge, esc, freshness, short_version, signal_facts, stage_badge

_SPLIT = re.compile(r"[:@/]")
_BUDGET_LIMITS = ("minutes", "invocations", "reruns", "cost")
_MISSING_WORDS = {
    "claude": "Needs Claude Code on this machine (the claude command)",
    "gh": "Needs the GitHub CLI signed in: run gh auth login",
}
_WAY_BACK_RELEASE = ("Cut release opens a release pull request and, when it merges, creates the tag and builds the image; "
                     "its digest is what staging verified. The way back before it merges: close the release pull request.")


# ---------------- small helpers ----------------

def _aside(label: str, body: str, ctx: Any = None, read_at: str | None = None) -> str:
    stamp = f'<p class="stamp">{freshness(read_at)}</p>' if read_at else ""
    return (f'<aside data-panel role="dialog" aria-modal="false" aria-label="{esc(label)}" tabindex="-1">'
            f'<header><h2>{esc(label)}</h2> <button type="button" class="link" data-action="close-panel">Close</button></header>'
            f'{stamp}{body}</aside>')


def _link(label: str, url: str | None) -> str:
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>' if url else esc(label)


def _section(title: str, body: str) -> str:
    return f"<section><h3>{esc(title)}</h3>{body}</section>"


def _runs(ctx: Any) -> list[dict]:
    doc = ctx.data("runs")
    rows = doc.get("runs") if isinstance(doc, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def _read_at(ctx: Any, name: str) -> str | None:
    source = ctx.source(name)
    value = getattr(source, "read_at", None) if source else None
    return value.isoformat() if hasattr(value, "isoformat") else value


def _spec_sources(ctx: Any):
    for name, source in ctx.sources.items():
        if name.startswith("specs:") and isinstance(source.data, list):
            yield name.split(":", 1)[1], [s for s in source.data if isinstance(s, dict)]


def _settings() -> dict:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    try:
        data = yaml.safe_load((Path(base) / "sdlc-foundry" / "settings.yml").read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _split(ident: str) -> tuple[str, str]:
    parts = _SPLIT.split(ident, 1)
    return (parts[0], parts[1]) if len(parts) == 2 and parts[0] and parts[1] else (ident, "")


def _split_release(ident: str) -> str:
    """The component of a release id: `<component>:<version>` (`/`, `@`) or `<component>-<version>`."""
    if _SPLIT.search(ident):
        return _split(ident)[0]
    found = re.match(r"^(.+)-(\d.*)$", ident)
    return found.group(1) if found else ident


def _budget_line(run: dict | None) -> str:
    budget = (run or {}).get("budget") or {}
    used, limit = budget.get("used") or {}, budget.get("limit") or {}
    if not used or not limit:
        return "no budget recorded"
    cost = "cost unknown" if used.get("cost") is None else f"${used['cost']}"
    minutes = "minutes unknown" if used.get("minutes") is None else f"{used['minutes']} min"
    return f"{cost} of ${limit.get('cost')}, {minutes} of {limit.get('minutes')} min"


def _run_for(runs: list[dict], spec: str, repo: str | None = None) -> dict | None:
    """The run of a spec (and repo): an active one first, else the newest."""
    mine = [r for r in runs if r.get("spec") == spec and (repo is None or r.get("repo") == repo)]
    mine.sort(key=lambda r: str(r.get("started_at") or ""))
    return next((r for r in reversed(mine) if r.get("active")), mine[-1] if mine else None)


def _disabled_reason(kind: str, obj: dict, repo_dir: str | Path | None = None) -> str | None:
    """Why an action cannot run now: a missing prerequisite or another action on the object (AC-122.41, AC-122.17)."""
    missing = actions.prerequisites(kind, obj, dict(os.environ), repo_dir=repo_dir)
    if kind in ("take-over", "open-in-claude"):
        missing = [m for m in missing if m == "claude"]
    if missing:
        what = missing[0]
        if what.startswith("kube:"):
            return f"Needs kubectl with access to {what[5:]}"
        if what.startswith("clone:"):
            return f"Needs a local clone of {what[6:]}: run gh repo clone {what[6:]}"
        return _MISSING_WORDS.get(what, f"Needs {what}")
    if actions.active_for(obj):
        return "Another action is running on this object"
    return None


def _action(kind: str, label: str, key: str | None, obj: dict, command: str, *, args: dict | None = None,
            primary: bool = False, confirm: str | None = None, repo_dir: str | Path | None = None) -> str:
    attrs: dict[str, object] = {"data_object": json.dumps(obj), "data_args": json.dumps(args or {}), "data_confirm": confirm}
    button = action_button(kind, label, key, _disabled_reason(kind, obj, repo_dir), attrs=attrs, primary=primary)
    return f'<div class="action-row">{button}{command_block(command)}</div>'


def _kv(rows: list[tuple[str, str]]) -> str:
    return "<dl>" + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


# ---------------- spec ----------------

def _strip(current: str | None, stopped: bool) -> str:
    items = []
    for stage in stages.STAGES:
        mark = ""
        if stage == current:
            mark = ' aria-current="step"'
        note = " (stopped)" if stage == current and stopped else ""
        items.append(f'<li><span class="stage" data-stage="{esc(stage)}"{mark}>{esc(stage)}</span>{esc(note)}</li>')
    return f'<ol class="strip" aria-label="Stages">{"".join(items)}</ol>'


def _smoke_text(run: dict | None) -> str:
    smoke = (run or {}).get("smoke") or {}
    parts = []
    for env, result in smoke.items():
        if isinstance(result, dict):
            parts.append(f"{result.get('instance') or env}: smoke {result.get('result')}")
        else:
            parts.append(f"{env}: smoke not run yet")
    return "; ".join(parts) or "smoke not run yet"


def _criterion(c: dict, run: dict | None) -> str:
    tests = c.get("tests") or []
    tests_html = ", ".join(f"<code>{esc(t)}</code>" for t in tests) if tests else "no test yet"
    smoke = f"<br>(smoke) {esc(_smoke_text(run))}" if c.get("smoke") else ""
    return (f'<li data-criterion="{esc(c.get("id"))}"><strong>{esc(c.get("id"))}</strong> {esc(c.get("text"))}<br>'
            f'Tests: {tests_html}. Verdict: {esc(c.get("verdict") or "not judged")}{smoke}</li>')


def _stage_or_done(stage: str | None) -> str:
    """A stage badge, or "Done" outside the stage vocabulary for a finished item (no `data-stage`, AC-122.32)."""
    return stage_badge(stage) if stage else '<span class="muted">Done</span>'


def _slice_line(repo: str, spec_id: str, status: str, run: dict | None) -> str:
    stage = stages.stage_of_spec(status, run) if status else None
    stop = " stopped" if run and run.get("stopped") else ""
    ident = f"/panel/slice/{quote(f'{repo}:{spec_id}', safe='')}"
    return (f'<li data-slice="{esc(repo)}" data-open="{ident}"><a href="{ident}">{esc(repo)}</a> {_stage_or_done(stage)}{esc(stop)} '
            f'{esc(_budget_line(run))}</li>')


def _evidence(repo: str, spec: dict, run: dict | None) -> str:
    base = f"https://github.com/{repo}"
    sid = spec.get("id")
    tracks = spec.get("tracks") or []
    pr = (run or {}).get("pr") or {}
    image = (run or {}).get("image")
    smokes = [v.get("instance") for v in ((run or {}).get("smoke") or {}).values() if isinstance(v, dict) and v.get("instance")]
    draft = spec.get("draft_pr")
    draft_url = draft.get("url") if isinstance(draft, dict) else None
    image_text = None
    if image:
        image_text = image.get("digest") or image.get("tag") if isinstance(image, dict) else str(image)
    steps = [
        ("issue", "Issue", " ".join(_link(f"#{n}", f"{base}/issues/{n}") for n in tracks)),
        ("spec", "Spec", _link(str(spec.get("path") or sid), draft_url or f"{base}/blob/main/{spec.get('path')}")),
        ("plan", "Plan", _link("plan.md", f"{base}/blob/main/docs/specs/{sid}/plan.md") if spec.get("status") != "draft" else ""),
        ("run", "Run", _link(str(run["run_id"]), f"/panel/run/{run['run_id']}") if run else ""),
        ("pr", "Pull request", _link(f"#{pr.get('number')}", pr.get("url")) if pr.get("url") else ""),
        ("image", "Image", f"<code>{esc(image_text)}</code>" if image_text else ""),
        ("instance", "Instance", esc(", ".join(smokes))),
    ]
    items = "".join(f'<li data-evidence="{key}">{esc(label)}: {body or "not yet"}</li>' for key, label, body in steps)
    return f'<ol class="evidence">{items}</ol>'


def panel_spec(ctx: Any, ident: str) -> str:
    """A spec (or a system spec with its slices): stage strip, slices, criteria, evidence, contract change."""
    runs = _runs(ctx)
    want_repo, _, ident = ident.rpartition(":")        # `<repo>:<spec id>`; a bare spec id works too
    found = next(((repo, s) for repo, rows in _spec_sources(ctx) for s in rows
                  if s.get("id") == ident and want_repo in ("", repo)), None)
    if found is None and want_repo:
        found = next(((repo, s) for repo, rows in _spec_sources(ctx) for s in rows if s.get("id") == ident), None)
    if found is None:
        raise LookupError(f"unknown spec {ident!r}")
    repo, spec = found
    run = _run_for(runs, ident, repo) or _run_for(runs, ident)
    current = stages.stage_of_spec(str(spec.get("status")), run)
    slices = spec.get("slices") or []
    if slices:
        lines = "".join(_slice_line(str(s.get("repo")), str(s.get("spec") or ident), str(s.get("status") or ""),
                                    _run_for(runs, str(s.get("spec") or ident), s.get("repo")))
                        for s in slices if isinstance(s, dict))
    else:
        lines = _slice_line(repo, ident, str(spec.get("status")), run)
    criteria = "".join(_criterion(c, run) for c in spec.get("criteria") or [] if isinstance(c, dict)) or "<li>No criteria yet.</li>"
    contract = spec.get("contract_change")
    contract_html = _section("Contract change", f"<p>{esc(contract)}</p>") if contract else ""
    activity = "".join(f"<li>{esc(a.get('at'))} {esc(a.get('agent'))}: {esc(a.get('text'))}</li>" for a in (run or {}).get("activity") or [])
    activity_html = _section("Activity", f"<ul>{activity}</ul>") if activity else ""
    body = (_strip(current, bool(run and run.get("stopped"))) + f"<p>{esc(spec.get('title'))}{'' if current else ' - Done'}</p>"
            + _section("Slices", f'<ul class="slices">{lines}</ul>') + _section("Criteria", f"<ul>{criteria}</ul>")
            + _section("Evidence", _evidence(repo, spec, run)) + contract_html + activity_html)
    return _aside(f"Spec {ident}", body, ctx, _read_at(ctx, f"specs:{repo}"))


def panel_slice(ctx: Any, ident: str) -> str:
    """One slice of a system spec: its repo's stage, budget and the activity of that repo's run of the spec (AC-122.13)."""
    repo, _, spec_id = ident.rpartition(":")
    if not repo or not spec_id:
        raise LookupError(f"unknown slice {ident!r}")
    sl = next((x for _, rows in _spec_sources(ctx) for s in rows for x in s.get("slices") or []
               if isinstance(x, dict) and x.get("repo") == repo and str(x.get("spec") or s.get("id")) == spec_id), None)
    run = _run_for(_runs(ctx), spec_id, repo)
    if sl is None and run is None:
        raise LookupError(f"unknown slice {ident!r}")
    stage = stages.stage_of_spec(str((sl or {}).get("status") or "approved"), run) if sl else None
    activity = "".join(f"<li>{esc(a.get('at'))} {esc(a.get('agent'))}: {esc(a.get('text'))}</li>" for a in (run or {}).get("activity") or [])
    run_link = f'<p><a href="/panel/run/{quote(str(run["run_id"]), safe="")}">Run {esc(run["run_id"])}</a></p>' if run else ""
    body = (_kv([("Repo", esc(repo)), ("Spec", esc(spec_id)), ("Stage", _stage_or_done(stage) + (" stopped" if run and run.get("stopped") else "")),
                 ("Budget", esc(_budget_line(run)))])
            + _section("Activity", f"<ul>{activity}</ul>" if activity else "<p>No activity recorded for this slice yet.</p>") + run_link)
    return _aside(f"Slice {repo} {spec_id}", body, ctx, _read_at(ctx, "runs"))


# ---------------- failures and run ----------------

def _object_of(run: dict) -> dict:
    return {"type": "run", "repo": run.get("repo"), "spec": run.get("spec"), "run_id": run.get("run_id"), "level": run.get("level")}


def _failure_html(run: dict) -> str:
    esc_info, failure = run.get("escalation") or {}, run.get("failure") or {}
    parts = []
    if esc_info:
        parts.append(f"<p>{esc(esc_info.get('summary') or esc_info.get('reason'))}</p>")
        if esc_info.get("reason") and esc_info.get("summary"):
            parts.append(f"<p>Reason: {esc(esc_info['reason'])}</p>")
    rows = [(label, esc(failure[key])) for label, key in (("Check", "check"), ("Test", "test"), ("Criterion", "criterion"),
                                                          ("Last error", "error"), ("Diagnosis", "diagnosis")) if failure.get(key)]
    if rows:
        parts.append(_kv(rows))
    for line in failure.get("excerpt") or []:
        parts.append(f"<pre>{esc(line)}</pre>")
    failed = [(env, v) for env, v in ((run.get("smoke") or {}).items()) if isinstance(v, dict) and v.get("result") == "failed"]
    for env, v in failed:
        parts.append(f"<p>The smoke check in {esc(env)} failed on {esc(v.get('instance') or env)}: smoke result {esc(v.get('result'))}.</p>")
    for env, v in _not_run(run):
        parts.append(f"<p>The smoke check in {esc(env)} did not run on {esc(v.get('instance') or env)}: smoke result {esc(v.get('result'))}. "
                     f"Why: {esc(v.get('reason') or 'no reason recorded')}.</p>")
    unchecked = _unchecked(run)
    if _not_run(run):
        parts.append(f"<p>Criteria left unchecked: {esc(', '.join(unchecked) if unchecked else 'those of ' + str(run.get('spec')))}.</p>")
    return "".join(parts)


def _not_run(run: dict) -> list[tuple[str, dict]]:
    return [(env, v) for env, v in ((run.get("smoke") or {}).items()) if isinstance(v, dict) and v.get("result") == "not-run"]


def _unchecked(run: dict) -> list[str]:
    failure = run.get("failure") or {}
    return [c for c in re.split(r"[,\s]+", str(failure.get("criterion") or "")) if c]


def _smoke_ways(run: dict) -> str:
    """The ways forward of a smoke that did not run: run it again, or check by hand."""
    spec_no = str(run.get("spec") or "").split("-", 1)[0]
    level = run.get("level") or "component"
    return _section("Ways forward",
                    f"<p>Run the smoke check again by shipping again:</p><p>{command_block(f'/{level}:ship {spec_no}')}</p>"
                    "<p>Or check the criteria by hand against the instance (open it from the System page), then ship again "
                    "once you are satisfied.</p>")


def _ways_forward(run: dict, repo_dir: str | Path | None = None) -> str:
    obj = _object_of(run)
    spec_no = str(run.get("spec") or "").split("-", 1)[0]
    level = run.get("level") or "component"
    argv = handoff.claude_command(run, f"docs/specs/{run.get('spec')}/spec.md", run.get("failure"))
    claude = shlex.join(argv)
    ship = f"/{level}:ship {spec_no}"
    limit_form = (f'<form><select name="limit" aria-label="Budget limit">'
                  f'{"".join(f"<option>{x}</option>" for x in _BUDGET_LIMITS)}</select>'
                  f'<input type="text" name="value" aria-label="New value" placeholder="new value" required>'
                  + _action("more-budget", "Give more budget", None, obj, ship + " --budget <limit>=<value>", repo_dir=repo_dir)
                  + "</form>")
    amend_form = (f'<form><textarea name="text" aria-label="Spec change" placeholder="What should change in the spec?" required></textarea>'
                  + _action("amend", "Amend the spec", None, obj, f"/{level}:spec --amend {spec_no} <text>", repo_dir=repo_dir) + "</form>")
    stays = (f"Stopping keeps the branch and the pull request #{(run.get('pr') or {}).get('number')}; nothing was deployed."
             if (run.get("pr") or {}).get("number") else "Stopping keeps the work done so far; nothing reaches prod without you.")
    return (_section("Ways forward",
                     _action("take-over", "Take over", "t", obj, claude, primary=True, repo_dir=repo_dir)
                     + limit_form + amend_form
                     + _action("open-in-claude", "Open in Claude Code", "o", obj, claude, repo_dir=repo_dir))
            + f"<p>{esc(stays)}</p>")


def _record_url(run: dict) -> str | None:
    """The run record in the run store (the repo of `CPLAT_RUNS_REPO`), when known."""
    if run.get("record_url") or run.get("store_url"):
        return str(run.get("record_url") or run.get("store_url"))
    slug = os.environ.get("CPLAT_RUNS_REPO", "").strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", slug) or not run.get("ended_at"):
        return None
    try:
        import runs_store   # noqa: PLC0415 - the layout of the record in the store belongs to the store
        return f"https://github.com/{slug}/blob/main/{runs_store.record_path(run)}"
    except (ImportError, KeyError, ValueError):
        return None


def _engine_html(run: dict) -> str:
    """What an engine fix run did: actor, issue, level, commit, regression test and the guardrails it stood outside of (AC-124.11)."""
    engine = run.get("engine") or (run.get("actor") or {}).get("name")
    fix = run.get("fix") if isinstance(run.get("fix"), dict) else {}
    if not engine:
        return ""
    rows: list[tuple[str, str]] = [("Actor", f"by {esc(engine)} {engine_badge(engine)}")]
    issue = run.get("issue") if isinstance(run.get("issue"), dict) else {}
    if issue.get("url"):
        rows.append(("Issue", _link(f"#{issue.get('number')}", issue["url"])))
    policy = fix.get("policy") or {}
    if policy.get("level"):
        rows.append(("Level", esc(policy["level"])))
    sha = str(policy.get("commit") or "")
    if sha:
        rows.append(("Policy commit", f"<code>{esc(sha[:7])}</code>"))
    reg = fix.get("regression") or {}
    if reg.get("test"):
        rows.append(("Regression test", f"<code>{esc(reg['test'])}</code> {esc(reg.get('before'))} before, {esc(reg.get('after'))} after"))
    decision = fix.get("decision") or {}
    if decision.get("action"):
        outside = decision.get("outside") or []
        text = esc(decision["action"]) + (": outside " + ", ".join(f"<code>{esc(o)}</code>" for o in outside) if outside else "")
        rows.append(("Decision", text))
    return _section("Engine fix", _kv(rows))


def panel_run(ctx: Any, ident: str) -> str:
    """One run: stage, budget, why it stopped, ways forward and the links to its evidence."""
    run = next((r for r in _runs(ctx) if r.get("run_id") == ident), None)
    if run is None:
        raise LookupError(f"unknown run {ident!r}")
    phase, stopped_in = run.get("phase"), run.get("stopped_in")
    stage = run.get("stage") if run.get("stage") in stages.STAGES else None
    if stage is None and phase and phase != "done":
        stage = stages.stage_of_run(str(phase), stopped_in)[0]
    failure = _failure_html(run)
    troubled = bool(run.get("stopped") or run.get("failure") or run.get("escalation")
                    or any(isinstance(v, dict) and v.get("result") in ("failed", "not-run") for v in (run.get("smoke") or {}).values()))
    links = handoff.links_for_work(run)
    if not any(x["label"] == "Run record" for x in links):
        links.append({"label": "Run record", "url": _record_url(run) or f"/panel/run/{ident}"})
    link_html = "<ul>" + "".join(f"<li>{_link(x['label'], x['url'])}</li>" for x in links) + "</ul>"
    head = _kv([("Spec", esc(run.get("spec"))), ("Repo", esc(run.get("repo"))),
                ("Stage", _stage_or_done(stage) + (" stopped" if run.get("stopped") else "")),
                ("Budget", esc(_budget_line(run))), ("Smoke", esc(_smoke_text(run)))])
    body = (head + _engine_html(run) + (_section("Why it stopped", failure or "<p>The run stopped without a recorded failure.</p>") if troubled else "")
            + (_ways_forward(run, ctx.repo_dir) if troubled else "") + (_smoke_ways(run) if _not_run(run) else "") + _section("Where the evidence lives", link_html))
    return _aside(f"Run {ident}", body, ctx, _read_at(ctx, "runs"))


# ---------------- issue ----------------

def panel_issue(ctx: Any, ident: str) -> str:
    """An open issue: fix it, make a spec of it, or dismiss it with a reason (a triage item, or an untracked issue of `needs.issues`)."""
    needs = ctx.data("needs") if isinstance(ctx.data("needs"), dict) else {}
    number = str(ident).rsplit("#", 1)[-1]             # `<n>`, `#<n>` or `<repo>#<n>`
    item = next((i for i in needs.get("items") or [] if str((i.get("object") or {}).get("issue")) == number), None)
    signal = None
    if item is not None:
        obj = dict(item["object"])
        obj.setdefault("repo", item.get("cwd_repo"))
        stage, why, title = item.get("stage") or "Issue", item.get("reason"), ""
        signal = (obj.get("detail") or {}).get("signal") if isinstance(obj.get("detail"), dict) else None
    else:
        found = next((i for i in needs.get("issues") or [] if isinstance(i, dict) and str(i.get("number")) == number), None)
        if found is None:
            raise LookupError(f"unknown issue {ident!r}")
        obj = {"type": "issue", "repo": found.get("repo"), "issue": found["number"], "spec": None}
        stage, why, title = "Issue", "Open and not tracked by a spec.", found.get("title") or ""
        signal = found.get("signal")
    n, repo = obj["issue"], obj.get("repo")
    dismiss = (f'<form><textarea name="reason" aria-label="Reason" placeholder="Why is this not worth fixing?" required></textarea>'
               + _action("dismiss", "Dismiss", "d", obj, f"/issue:triage {n} dismiss as wontfix: <reason>",
                         confirm="Dismiss this issue as wontfix?", repo_dir=ctx.repo_dir) + "</form>")
    facts = [("Issue", _link(f"#{n}", f"https://github.com/{repo}/issues/{n}") if repo else esc(f"#{n}"))]
    facts += [("Title", esc(title))] if title else []
    facts += [("Stage", stage_badge(stage)), ("Why it is here", esc(why))]
    detail = obj.get("detail") if isinstance(obj.get("detail"), dict) else {}
    facts += [(label, esc(detail[key])) for label, key in (("Failing check", "check"), ("Failing test", "test"), ("Criterion", "criterion"),
                                                           ("Last error", "error"), ("Diagnosis", "diagnosis")) if detail.get(key)]
    body = (_kv(facts) + signal_facts(signal)
            + _section("What do you want to do", _action("fix", "Fix it", None, obj, f"/component:fix #{n}", primary=True, repo_dir=ctx.repo_dir)
                       + _action("make-spec", "Make a spec", None, obj, f"/component:spec #{n}", repo_dir=ctx.repo_dir) + dismiss))
    return _aside(f"Issue #{n}", body, ctx, _read_at(ctx, "needs"))


# ---------------- instance ----------------

def _status_rows(ctx: Any) -> list[dict]:
    doc = ctx.data("status")
    rows = (doc.get("rows") or []) if isinstance(doc, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def panel_instance(ctx: Any, ident: str) -> str:
    """One component in one environment: version, state, digest and the deep links to Argo CD, Grafana and logs."""
    component, env = _split(ident)
    doc = ctx.data("status") if isinstance(ctx.data("status"), dict) else {}
    row = next((r for r in _status_rows(ctx) if r.get("component") == component), None)
    cell = ((row or {}).get("cells") or {}).get(env) if row else None
    if row is None or env not in (row.get("cells") or {}):
        raise LookupError(f"unknown instance {ident!r}")
    system = str(doc.get("system") or "")
    facts = [("Version", esc(short_version((cell or {}).get("version")) or "not deployed")), ("State", esc((cell or {}).get("state") or "unknown"))]
    for label, key in (("Digest", "digest"), ("Argo CD", "argo"), ("CI", "ci")):
        if cell and cell.get(key):
            facts.append((label, esc(cell[key])))
    links, reason = handoff.links_for_instance(system, component, env, _settings())
    if links:
        names = {"argocd": "Argo CD", "grafana": "Grafana", "logs": "Logs"}
        link_html = "<ul>" + "".join(f"<li>{_link(names[k], v)}</li>" for k, v in links.items()) + "</ul>"
    else:
        link_html = f"<p>{esc(reason)}</p>"
    return _aside(f"{component} in {env}", _kv(facts) + _section("Where to look", link_html), ctx, _read_at(ctx, "status"))


# ---------------- release ----------------

def _repo_of(ctx: Any, component: str) -> str:
    model = ctx.data("model")
    comps = model.get("components") if isinstance(model, dict) else None
    entry = comps.get(component) if isinstance(comps, dict) else next(
        (c for c in comps or [] if isinstance(c, dict) and c.get("name") == component), None)
    if isinstance(entry, dict) and entry.get("repo"):
        return str(entry["repo"])
    return next((repo for repo, _ in _spec_sources(ctx)), "")


def panel_release(ctx: Any, ident: str) -> str:
    """A release candidate: version, specs, fixes and what "Cut release" does, with the way back."""
    component = _split_release(ident)
    row = next((r for r in _status_rows(ctx) if r.get("component") == component and r.get("release_candidate")), None)
    if row is None:
        raise LookupError(f"no release candidate for {ident!r}")
    cand = row["release_candidate"]
    version = str(cand.get("version"))
    obj = {"type": "release", "repo": _repo_of(ctx, component), "component": component, "version": version}
    lists = [("Specs", cand.get("specs")), ("Fixes", cand.get("fixes"))]
    facts = [("Version", esc(version)), ("Commits", esc(cand.get("commits")))]
    facts += [(label, esc(", ".join(map(str, vals))) if vals else "none") for label, vals in lists]
    if cand.get("digest"):
        facts.append(("Digest", f"<code>{esc(cand['digest'])}</code> (the one staging verified)"))
    what = (f"<p>Cut release opens the release pull request for {esc(component)} {esc(version)}. When it merges, the tag "
            f"v{esc(version)} is created and the image with the digest above is released.</p>"
            f"<p>{esc(_WAY_BACK_RELEASE)}</p>")
    cut = _action("cut-release", "Cut release", "r", obj, "/component:release", primary=True,
                  confirm=f"Cut release {version} of {component}?", repo_dir=ctx.repo_dir)
    return _aside(f"Release {component} {version}", _kv(facts) + _section("What happens", what + cut), ctx, _read_at(ctx, "status"))


# ---------------- promote ----------------

def _cell_ref(cell: dict) -> str:
    return str(cell.get("commit") or cell.get("tag") or cell.get("release") or cell.get("version") or "")


def panel_promote(ctx: Any, ident: str) -> str:
    """Promote a verified cell to the next manual environment: what lies between the versions, the way back, then the button."""
    from console import inbox   # noqa: PLC0415 - the decision markup belongs to the Inbox
    import releases             # noqa: PLC0415
    parts = ident.split(":")
    if len(parts) != 3 or not all(parts):
        raise LookupError(f"unknown promotion {ident!r}")
    component, frm, to = parts
    rows = _status_rows(ctx)
    row = next((r for r in rows if r.get("component") == component), None)
    repo = _repo_of(ctx, component)
    cells = (row or {}).get("cells") or {}
    src, dst = cells.get(frm) or {}, cells.get(to) or {}
    version = str(src.get("version") or "")
    obj = {"type": "release", "repo": repo, "component": component, "version": version}
    source = ctx.source("status")
    stale = bool(source and (source.error or source.unavailable_since))
    down = row is None or not version or stale
    item: dict = {"id": f"promote:{component}:{frm}:{to}", "kind": "promote", "stage": "Prod" if to == "prod" else "Staging",
                  "object": obj, "way_back": {}, "consequence": {"to_env": to}}
    if down:
        item["consequence"]["blocked"] = "The status cannot be read, so the versions to compare are unknown."
        item["way_back"] = {}
        body = f"<p>{esc(item['consequence']['blocked'])}</p>"
    else:
        before, after = _cell_ref(dst), _cell_ref(src)
        between = releases.between(repo, before, after) if repo and before and after else {}
        migrations = between.get("migrations") or []
        bad = [Path(m["file"]).name for m in migrations if not m.get("additive")]
        digest = src.get("digest")
        item["consequence"].update({"from": before or None, "to": after, "specs": between.get("specs") or [],
                                    "criteria": between.get("criteria"), "commits": between.get("commits"),
                                    "migrations": migrations, "digest": digest, "verified_digest": digest,
                                    "digest_matches": digest is not None})
        current = short_version(dst.get("version")) if dst.get("version") else ""
        item["way_back"] = {"command": f"/instance:promote {component} --to {to} --version {dst['version']}" if dst.get("version") else None,
                            "warning": f"migration {', '.join(bad)} is not additive" if bad else None,
                            "text": None if current else f"{to} runs nothing yet, so there is no version to go back to."}
        body = ""
    status = ctx.data("status")
    if not isinstance(status, dict):
        item["consequence"]["blocked"] = "The status cannot be read right now."
    d = inbox.Decide(ctx, item)
    inner = inbox._promote(ctx, item, d) if not down else body + d.button(
        "promote", "Promote", "p", f"/instance:promote {component} --to {to} --version <version>", args={"to": to}, primary=True,
        extra=item["consequence"]["blocked"], needs=("claude", "gh", f"kube:{to}"))
    return _aside(f"Promote {component} to {to}", inner, ctx, _read_at(ctx, "status"))


# ---------------- stage ----------------

def panel_stage(ctx: Any, ident: str) -> str:
    """What a Board column means: what happens there, who does it, the commands, and what you decide."""
    try:
        e = stages.explain(ident)
    except ValueError:
        raise LookupError(f"unknown stage {ident!r}") from None
    agents = ("<ul>" + "".join(f"<li>{esc(a)}</li>" for a in e["agents"]) + "</ul>" if e["agents"]
              else "<p>No agent: the platform script, CI and Argo CD do it.</p>")
    commands = "".join(f"<p>{command_block(c)}</p>" for c in e["commands"])
    if e["decision"]:
        decide = (f'<p data-decision>{esc(e["decision"])}</p>'
                  "<p>When it needs you, it shows up in the Inbox and you get a notification.</p>")
    else:
        decide = "<p>Nothing to decide here: it runs on its own.</p>"
    body = (f"<p>{stage_badge(ident)}</p><p>{esc(e['what'])}</p>" + _section("Agents", agents) + _section("Commands", commands)
            + _section("What you decide", decide))
    return _aside(f"Stage {ident}", body)

