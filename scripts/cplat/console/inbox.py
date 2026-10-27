"""The Inbox of the console (spec 122, AC-122.6, .16, .17, .34, .35, .40): the decisions that wait for the user, oldest first.

  page(ctx, query)        the list of `needs` items; an empty one lists the next steps to a first change
  panel_need(ctx, id)     the detail of one item as a side panel, with the buttons that decide it

Everything shown comes from the `needs`, `runs`, `status` and `specs:<repo>` sources; no stage or status is mapped here.
An action button shows its command, its key and, when it cannot run, why not (missing piece or a running action)."""
from __future__ import annotations

import json
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from console import actions, handoff, layout, sources as sources_mod
from console.html import action_button, command_block, esc, freshness, stage_badge, table, unavailable

DEFAULT_BUDGET = "15"
WAY_BACK_TITLE = "The way back"


# ---------------- helpers ----------------

def _items(ctx: Any) -> list[dict]:
    data = ctx.data("needs")
    items = data.get("items") if isinstance(data, dict) else None
    return sorted((i for i in items or [] if isinstance(i, dict)), key=lambda i: str(i.get("since") or ""))


def _now(ctx: Any) -> datetime:
    value = ctx.state().get("now")
    return value if isinstance(value, datetime) else datetime.now(timezone.utc)


def age(since: str | None, now: datetime) -> str:
    """`3d`, `5h` or `12m` since `since`."""
    when = sources_mod.parse_iso(since)
    if when is None:
        return "unknown"
    seconds = max(0, int((now - when).total_seconds()))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return "now"


def _level(item: dict) -> str:
    found = re.match(r"/(component|system):", str(item.get("command") or ""))
    return found.group(1) if found else "component"


def _spec_no(obj: dict) -> str:
    return str(obj.get("spec") or "").split("-", 1)[0]


def _spec_row(ctx: Any, obj: dict) -> dict | None:
    rows = ctx.data(f"specs:{obj.get('repo')}")
    return next((r for r in rows or [] if isinstance(r, dict) and r.get("id") == obj.get("spec")), None) if isinstance(rows, list) else None


def _run_of(ctx: Any, obj: dict) -> dict | None:
    data = ctx.data("runs")
    runs = data.get("runs") if isinstance(data, dict) else None
    return next((r for r in runs or [] if r.get("run_id") == obj.get("run_id")), None)


def _missing_pieces(ctx: Any) -> dict[str, str]:
    """The pieces the health check found missing (`claude`, `gh`, `kube:<env>`) with their fix."""
    return {str(b.get("piece")): str(b.get("fix") or "") for b in ctx.api_state().get("banner") or []}


def _budget_default() -> str:
    path = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")) / "sdlc-foundry" / "settings.yml"
    try:
        data = yaml.safe_load(path.read_text()) or {}
        value = ((data.get("console") or {}).get("default_budget"))
    except (OSError, yaml.YAMLError, AttributeError):
        value = None
    return str(value) if value else DEFAULT_BUDGET


class Decide:
    """Builds the action buttons of one item: each with its command, key and the reason it is disabled."""

    def __init__(self, ctx: Any, item: dict):
        self.item, self.obj = item, dict(item.get("object") or {})
        self.missing = _missing_pieces(ctx)
        self.running = actions.active_for(self.obj)

    def reason(self, kind: str, extra: str | None = None, needs: tuple[str, ...] = ("claude", "gh")) -> str | None:
        for piece in needs:
            if piece in self.missing:
                return f"Needs {piece}. {self.missing[piece]}".strip()
        if self.running:
            return "Another action on this object is running."
        return extra

    def button(self, kind: str, label: str, key: str | None, command: str, *, args: dict | None = None, primary: bool = False,
               confirm: str | None = None, extra: str | None = None, needs: tuple[str, ...] = ("claude", "gh")) -> str:
        attrs = {"data_object": json.dumps(self.obj), "data_args": json.dumps(args or {}), "data_confirm": confirm}
        button = action_button(kind, label, key, self.reason(kind, extra, needs), attrs=attrs, primary=primary)
        return f'<div class="act">{button}{command_block(command)}</div>'


def _head(item: dict, now: datetime) -> str:
    return (f'<p>{stage_badge(str(item.get("stage")))} <strong>{esc(item.get("kind"))}</strong> '
            f'<time datetime="{esc(item.get("since"))}">waiting {esc(age(item.get("since"), now))}</time></p>'
            f'<p>{esc(item.get("reason"))}</p>')


def _way_back(item: dict) -> str:
    way = item.get("way_back") or {}
    text = way.get("text") or way.get("warning") or ""
    command = way.get("command")
    if not (text or command):
        return ""
    out = f"<h3>{WAY_BACK_TITLE}</h3>"
    if text and way.get("text"):
        out += f"<p>{esc(text)}</p>"
    if command:
        out += command_block(command)
        if way.get("warning"):
            out += f'<p class="failed">Careful: {esc(way["warning"])}.</p>'
    return out


def _panel(label: str, body: str) -> str:
    return (f'<aside data-panel role="dialog" aria-modal="false" aria-label="{esc(label)}" tabindex="-1">'
            '<button type="button" class="ghost" data-action="close-panel" aria-label="Close panel">Close</button>'
            f'{body}</aside>')


# ---------------- the page ----------------

def _row(item: dict, now: datetime) -> tuple[str, list[str]]:
    """The attributes of the `<tr>` and its cells."""
    attrs = f'data-need="{esc(item.get("id"))}" data-open="/panel/need/{esc(_quote(str(item.get("id"))))}" tabindex="0"'
    cells = [f'<strong>{esc(item.get("kind"))}</strong>', stage_badge(str(item.get("stage"))),
             f'<time datetime="{esc(item.get("since"))}">{esc(age(item.get("since"), now))}</time>',
             f'<span class="reason-text">{esc(item.get("reason"))}</span>']
    return attrs, cells


def _quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")


def _first_steps(ctx: Any) -> str:
    status = ctx.data("status")
    rows = status.get("rows") if isinstance(status, dict) else None
    running = ""
    if rows:
        names = ", ".join(f"<strong>{esc(r.get('component'))}</strong>" for r in rows)
        running = f"<p>Already running: {names}.</p>"
    return ('<section class="empty"><h2>Nothing waits for you</h2>' + running +
            "<p>Next steps to a first change:</p><ol>"
            '<li><button type="button" class="btn primary" data-action="palette">Describe your first change</button></li>'
            '<li><a href="/settings#notifications">Choose notifications</a> so the console tells you when a decision waits.</li>'
            "</ol></section>")


def page(ctx: Any, query: dict[str, str]) -> str:
    """The Inbox: one row per decision, oldest first."""
    source = ctx.source("needs")
    items = _items(ctx)
    parts = []
    if source is not None and source.error:
        parts.append(unavailable("needs", source.unavailable_since, source.error))
    if items:
        now = _now(ctx)
        rows = [_row(i, now) for i in items]
        parts.append(table([c for _, c in rows], ["Decision", "Stage", "Waiting", "Why"], caption="Decisions, oldest first",
                           row_attrs=[a for a, _ in rows]))
    elif source is None or not source.error:
        parts.append(_first_steps(ctx))
    if source is not None:
        parts.append(f"<p>{freshness(source.read_at)}</p>")
    return layout.page("Inbox", "inbox", "".join(parts), state=ctx.state())


# ---------------- the panels ----------------

def panel_need(ctx: Any, ident: str) -> str:
    """The detail of one decision with the buttons that decide it. Raises LookupError for an unknown id."""
    item = next((i for i in _items(ctx) if i.get("id") == ident), None)
    if item is None:
        raise LookupError(ident)
    kind = str(item.get("kind"))
    build = {"answer": _answer, "approve": _approve, "promote": _promote, "escalation": _escalation, "triage": _triage}.get(kind)
    if build is None:
        raise LookupError(ident)
    d = Decide(ctx, item)
    body = f'<h2>{esc(kind)} {esc(item.get("object", {}).get("spec") or "")}</h2>' + _head(item, _now(ctx)) + build(ctx, item, d)
    return _panel(f"Decision: {kind}", body)


def _spec_blockers(ctx: Any, item: dict) -> str | None:
    """Why a spec cannot be approved and shipped yet (AC-122.17)."""
    row = _spec_row(ctx, item.get("object") or {}) or {}
    open_q = int(row.get("open_questions") or (item.get("consequence") or {}).get("questions") or 0)
    if open_q:
        return f"{open_q} open question{'s' if open_q != 1 else ''} must be answered first."
    check = row.get("check") or {}
    if check and not check.get("ok", True):
        return "The spec check fails: " + "; ".join(str(e) for e in check.get("errors") or ["unknown error"])
    return None


def _answer(ctx: Any, item: dict, d: Decide) -> str:
    row = _spec_row(ctx, d.obj) or {}
    level, n = _level(item), _spec_no(d.obj)
    fields = ""
    for i, q in enumerate(q for q in row.get("questions") or [] if not q.get("answered")):
        options = "".join(f'<label><input type="radio" name="q{i + 1}" value="{esc(o)}"> {esc(o)}</label> ' for o in q.get("options") or [])
        fields += f'<fieldset><legend>{esc(q.get("text"))}</legend>{options}</fieldset>'
    form = (f'<form data-form="answer">{fields}<label>Your own words<br><textarea name="answers" rows="3" '
            'aria-label="Answers in your own words"></textarea></label></form>')
    args = {"level": level}
    button = d.button("answer", "Send answers", None, f"/{level}:spec --amend {n} answers to open questions: <answers>",
                      args=args, primary=True)
    ship = d.button("approve-ship", "Approve & ship", "a", f"/{level}:spec approve {n} and then /{level}:ship {n}",
                    args=args, extra=_spec_blockers(ctx, item) or "Answer the open questions first.")
    return form.replace("</form>", button + "</form>") + ship + _way_back(item)


def _approve(ctx: Any, item: dict, d: Decide) -> str:
    c = item.get("consequence") or {}
    level, n = _level(item), _spec_no(d.obj)
    est = c.get("estimate")
    estimate = (f"about ${est['cost_usd']:g}, {est['minutes']:g} minutes, {est['runs']} runs" if est else "no estimate yet")
    repos = ", ".join(esc(r) for r in c.get("repos") or [])
    stages = " ".join(stage_badge(s) for s in c.get("unattended") or [])
    budget = _budget_default()
    args = {"level": level}
    fields = (f'<label>Budget (cost, USD) <input type="number" name="budget" value="{esc(budget)}" min="1" step="1"></label><br>'
              '<label>Comment for changes<br><textarea name="comment" rows="3"></textarea></label>')
    buttons = (d.button("approve-ship", "Approve & ship", "a", f"/{level}:spec approve {n} and then /{level}:ship {n} --budget cost=<budget>",
                        args=args, primary=True, extra=_spec_blockers(ctx, item))
               + d.button("approve", "Approve only", None, f"/{level}:spec approve {n}", args=args)
               + d.button("request-changes", "Request changes", None, f"/{level}:spec --amend {n} <comment>", args=args))
    return (f"<h3>What approving does</h3><p>Repos: {repos}.</p><p>Runs unattended: {stages}</p><p>Estimate: {esc(estimate)}.</p>"
            f'<form data-form="approve">{fields}{buttons}</form>' + _way_back(item))


def _promote(ctx: Any, item: dict, d: Decide) -> str:
    c = item.get("consequence") or {}
    obj = d.obj
    specs = ", ".join(esc(s) for s in c.get("specs") or []) or "none"
    migrations = "".join(
        f"<li>{esc(m.get('file'))}{'' if m.get('additive') else ' - not additive'}</li>" for m in c.get("migrations") or [])
    migrations = f"<ul>{migrations}</ul>" if migrations else "<p>No migrations.</p>"
    if c.get("digest_matches"):
        digest = f"<p>Digest {esc(c.get('digest'))} is the one verified in staging.</p>"
    else:
        digest = (f'<p class="failed">Digest {esc(c.get("digest"))} is not the one verified in staging '
                  f'({esc(c.get("verified_digest") or "none")}).</p>')
    command = f"/instance:promote {obj.get('component')} --to prod --version {obj.get('version')}"
    button = d.button("promote", "Promote", "p", command, args={"to": "prod"}, primary=True,
                      confirm=f"Promote {obj.get('component')} {obj.get('version')} to prod?", needs=("claude", "gh", "kube:prod"))
    return (f"<h3>Between {esc(c.get('from'))} and {esc(c.get('to'))}</h3><ul><li>{esc(c.get('commits'))} commits</li>"
            f"<li>{esc(c.get('criteria'))} criteria</li><li>Specs: {specs}</li></ul>"
            f"<h3>Migrations</h3>{migrations}{digest}{button}" + _way_back(item))


def _escalation(ctx: Any, item: dict, d: Decide) -> str:
    c = item.get("consequence") or {}
    run = _run_of(ctx, d.obj) or {}
    esc_info, failure = run.get("escalation") or {}, run.get("failure") or {}
    why = "".join(f"<li>{esc(label)}: {esc(failure[key])}</li>" for label, key in
                  (("Check", "check"), ("Test", "test"), ("Criterion", "criterion"), ("Error", "error"), ("Diagnosis", "diagnosis"))
                  if failure.get(key))
    summary = esc_info.get("summary") or item.get("reason")
    budget = run.get("budget") or {}
    used, limit = budget.get("used") or {}, budget.get("limit") or {}
    spend = (f"<p>Budget used: {esc(used.get('minutes'))} of {esc(limit.get('minutes'))} minutes, "
             f"cost {esc(used.get('cost'))} of {esc(limit.get('cost'))}.</p>") if used else ""
    level, n = _level(item), _spec_no(d.obj)
    spec_path = f"docs/specs/{d.obj.get('spec')}/spec.md"
    claude = shlex.join(handoff.claude_command(run or {"run_id": d.obj.get("run_id")}, spec_path, failure or None))
    args = {"level": level}
    more = (f'<form data-form="more-budget"><label>Limit <select name="limit"><option>cost</option><option>minutes</option></select></label> '
            '<label>to <input type="number" name="value" min="1" step="1"></label>'
            + d.button("more-budget", "More budget", None, f"/{level}:ship {n} --budget <limit>=<value>", args=args) + "</form>")
    amend = (f'<form data-form="amend"><label>Change to the spec<br><textarea name="text" rows="2"></textarea></label>'
             + d.button("amend", "Amend the spec", None, f"/{level}:spec --amend {n} <text>", args=args) + "</form>")
    hand = (d.button("take-over", "Take over", "t", claude, needs=("claude",))
            + d.button("open-in-claude", "Open in Claude Code", "o", claude, needs=("claude",)))
    state = ""
    if c.get("branch") or c.get("pr"):
        state = f"<p>Branch {esc(c.get('branch'))}, pull request #{esc(c.get('pr'))}.</p>"
    return (f"<h3>Why it stopped</h3><p>{esc(summary)}</p><ul>{why}</ul>{spend}{state}<h3>Ways forward</h3>{hand}{more}{amend}"
            + _way_back(item))


def _triage(ctx: Any, item: dict, d: Decide) -> str:
    issue = d.obj.get("issue")
    buttons = (d.button("fix", "Fix now", "f", f"/component:fix #{issue}", primary=True)
               + d.button("make-spec", "Make a spec", None, f"/component:spec #{issue}"))
    dismiss = ('<form data-form="dismiss"><label>Reason for dismissing<br><textarea name="reason" rows="2"></textarea></label>'
               + d.button("dismiss", "Dismiss", None, f"/issue:triage {issue} dismiss as wontfix: <reason>",
                          confirm=f"Dismiss issue #{issue}?") + "</form>")
    return f"<h3>What to do with issue #{esc(issue)}</h3>{buttons}{dismiss}" + _way_back(item)
