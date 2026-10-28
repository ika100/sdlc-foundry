"""System place of the console (spec 122, AC-122.7, AC-122.8, AC-122.20, AC-122.40, AC-122.47, AC-122.50, AC-122.51).

  page(ctx, query) -> str        the full HTML of `/system`
  model_forms(ctx) -> str        the five "Add to the model" forms (component, API, resource, environment rules, new system);
                                 the palette shows the same forms

"Where it runs" is one row per component with instances and one per resource, one column per environment in promotion order.
A cell shows the version and the state exactly as `system status` reports them; while the status cannot be read every state is
`unknown` and the actions that depend on health are disabled (AC-122.42). The parts, libraries and relations come from the model
and are lists, never empty tables (AC-122.40). The forms post to `/api/preview`; `console.js` fills the preview and enables the confirm."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from console import actions
from console.html import _parse, action_button, command_block, esc, freshness, short_version, unavailable

UNKNOWN = "unknown"
GOOD = ("healthy", "verified")
BAD = ("NOT VERIFIED", "alert")


# ---------------- sources ----------------

def _part(ctx: Any, name: str, body: str) -> str:
    """`body` of one source with its freshness; an unreadable source adds the unavailable part in front of the last data."""
    src = ctx.source(name)
    if src is None:
        return body
    if getattr(src, "error", None) or getattr(src, "unavailable_since", None):
        note = unavailable(name, src.unavailable_since, src.error)
        stale = f'<p class="stale">Last data: {freshness(src.read_at, stale=True)}</p>' if src.data else ""
        return note[: -len("</section>")] + stale + "</section>" + body
    return f'{_stamp(ctx, src)}{body}'


def _stamp(ctx: Any, src: Any) -> str:
    """The read time of a part; omitted while it equals the one in the page title, so it is not repeated (AC-122.3)."""
    page_read = _parse(ctx.state().get("read_at"))
    read = _parse(src.read_at)
    if read is not None and page_read is not None and read.replace(microsecond=0) == page_read.replace(microsecond=0):
        return ""
    return f'<p class="stamp">{freshness(src.read_at)}</p>'


def _down(ctx: Any, name: str) -> bool:
    src = ctx.source(name)
    return bool(src and (src.error or src.unavailable_since))


def _banner_names(ctx: Any) -> dict[str, str]:
    return {str(b.get("piece")): str(b.get("fix") or "") for b in ctx.state().get("banner") or []}


def _missing(pieces: dict[str, str], *needed: str) -> str | None:
    for piece in needed:
        if piece in pieces:
            return f"Needs {piece}. {pieces[piece]}".strip()
    return None


# ---------------- the environments ----------------

def _rules(status: Mapping, model: Mapping) -> list[dict]:
    """The environments in promotion order with their `promote` and `policy` (status first, the model as fallback)."""
    rules = status.get("environment_rules")
    if isinstance(rules, list) and rules:
        return [dict(r) for r in rules if isinstance(r, Mapping)]
    return [{"name": e.get("name"), "promote": e.get("promotion") if e.get("promotion") != "main" else None,
             "policy": e.get("policy")} for e in model.get("environments") or [] if isinstance(e, Mapping)]


def _head(rule: Mapping) -> str:
    return (f'<th scope="col" data-env="{esc(rule.get("name"))}"><strong>{esc(rule.get("name"))}</strong> '
            f'<span class="muted">promote {esc(rule.get("promote") or "none")} policy {esc(rule.get("policy") or "none")}</span> '
            f'<a href="#form-environment" data-edit-env="{esc(rule.get("name"))}">edit rules</a></th>')


# ---------------- cells ----------------

def _state_html(state: str) -> str:
    cls = "ok" if state in GOOD else "failed" if state in BAD else "muted"
    return f'<span class="{cls}" data-state="{esc(state)}">{esc(state)}</span>'


def _obj(repo: str, component: str, version: str) -> str:
    return json.dumps({"type": "release", "repo": repo, "component": component, "version": version})


def _need_panel(ctx: Any, comp: str, version: str) -> str | None:
    """The Inbox panel of the promote need of this release, which shows the consequence and the way back first."""
    for item in (ctx.data("needs") or {}).get("items") or []:
        obj = item.get("object") or {}
        if item.get("kind") == "promote" and obj.get("component") == comp and str(obj.get("version")) == version:
            return f"/panel/need/{quote(str(item.get('id')), safe='')}"
    return None


def _promote(ctx: Any, comp: str, repo: str, version: str, target: str, unknown: bool, pieces: dict[str, str],
             source: str = "") -> str:
    obj = {"type": "release", "repo": repo, "component": comp, "version": version}
    reason = None
    if unknown:
        reason = "Health is unknown until the status can be read."
    else:
        reason = _missing(pieces, "claude", "gh", f"kube:{target}")
    if not reason and actions.active_for(obj):
        reason = "Another action runs on this release."
    panel = _need_panel(ctx, comp, version) if target == "prod" else None
    panel = panel or f"/panel/promote/{quote(f'{comp}:{source}:{target}', safe='')}"
    attrs = {"data_object": json.dumps(obj), "data_args": json.dumps({"to": target})}
    # The panel shows what lies between the versions and the way back; the confirm is there (AC-122.34, AC-122.35).
    attrs["data_open"] = panel
    button = action_button("promote", f"Promote to {target}", None, reason, attrs=attrs, primary=True)
    return f'<div class="offer">{button}{command_block(f"/instance:promote {comp} --to {target} --version {version}")}</div>'


def _cut(ctx: Any, comp: str, repo: str, cand: Mapping, unknown: bool, pieces: dict[str, str]) -> str:
    version = str(cand.get("version") or "")
    obj = {"type": "release", "repo": repo, "component": comp, "version": version}
    reason = "Health is unknown until the status can be read." if unknown else _missing(pieces, "claude", "gh")
    if not reason and actions.active_for(obj):
        reason = "Another action runs on this release."
    panel = f"/panel/release/{quote(f'{comp}:{version}', safe='')}"
    button = action_button("cut-release", f"Cut release {version}", None, reason,
                           attrs={"data_object": json.dumps(obj), "data_args": "{}", "data_open": panel})
    return (f'<div class="offer"><a href="{panel}" data-open="{panel}">{esc(version)} is ready</a> {button}'
            f'{command_block("/component:release")}</div>')


def _cell(ctx: Any, row: Mapping, env: str, index: int, rules: list[dict], down: bool, repo: str,
          pieces: dict[str, str], cut_env: str | None) -> str:
    cells = row.get("cells") or {}
    cell = cells.get(env)
    comp = str(row["component"])
    if not cell:
        return f'<td data-env="{esc(env)}"><span class="muted">not deployed</span></td>'
    raw = str(cell.get("state") or UNKNOWN)
    shown = UNKNOWN if down else raw
    version = str(cell.get("version") or "")
    if not re.fullmatch(r"\S{3,}", version) and cell.get("tag"):   # a stray one-character version: show the pin instead
        version = str(cell["tag"])
    raw_version, version = version, short_version(version)
    panel = f"/panel/instance/{quote(f'{comp}:{env}', safe='')}"
    link = f'<a href="{panel}" data-open="{panel}">{esc(version)}</a>' if version else ""
    out = [f'<div>{link} {_state_html(shown)}</div>']
    nxt = rules[index + 1] if index + 1 < len(rules) else None
    if raw == "verified" and nxt and nxt.get("promote") == "manual":
        target = str(nxt["name"])
        nxt_cell = cells.get(target) or {}
        unknown = down or raw == UNKNOWN or str(nxt_cell.get("state") or "") == UNKNOWN
        out.append(_promote(ctx, comp, repo, raw_version, target, unknown, pieces, env))
    cand = row.get("release_candidate")
    if isinstance(cand, Mapping) and env == cut_env:
        out.append(_cut(ctx, comp, repo, cand, down, pieces))
    return f'<td data-env="{esc(env)}" data-state="{esc(shown)}">{"".join(out)}</td>'


def _cut_env(row: Mapping, envs: list[str]) -> str | None:
    cells = row.get("cells") or {}
    for env in envs:
        if (cells.get(env) or {}).get("state") == "verified":
            return env
    return next((e for e in envs if cells.get(e)), None)


def _resource_state(cell: Mapping) -> str:
    """The shown state of a resource cell: `state` when status gives it, else derived from the Argo CD state (AC-122.7)."""
    if cell.get("state"):
        return str(cell["state"])
    argo = str(cell.get("argo") or "")
    if argo == "Synced/Healthy":
        return "healthy"
    if argo == "missing":
        return "not deployed"
    return "external" if argo == "external" else UNKNOWN


def _resource_cell(env: str, cell: Mapping | None, down: bool) -> str:
    if not cell:
        return f'<td data-env="{esc(env)}"><span class="muted">not deployed</span></td>'
    state = UNKNOWN if down else _resource_state(cell)
    return f'<td data-env="{esc(env)}" data-state="{esc(state)}">{_state_html(state)}</td>'


def _repos(model: Mapping) -> dict[str, str]:
    return {str(c.get("name")): str(c.get("repo") or "") for c in model.get("components") or [] if isinstance(c, Mapping)}


def _rows_from_model(model: Mapping, envs: list[str]) -> tuple[list[dict], list[dict]]:
    """Without a status: the components with instances and the resources of the model, with no cells to read."""
    inst = {(i.get("component"), i.get("environment")) for i in model.get("instances") or [] if isinstance(i, Mapping)}
    comps = [{"component": c["name"], "type": c.get("type"),
              "cells": {e: ({"state": UNKNOWN, "version": ""} if (c["name"], e) in inst else None) for e in envs},
              "release_candidate": None}
             for c in model.get("components") or [] if isinstance(c, Mapping) and c.get("environments")]
    res = [{"resource": r["name"], "cells": {e: ({"state": UNKNOWN} if e in envs else None) for e in envs}}
           for r in model.get("resources") or [] if isinstance(r, Mapping)]
    return comps, res


def _grid(ctx: Any, status: Mapping, model: Mapping) -> str:
    rules = _rules(status, model)
    envs = [str(r["name"]) for r in rules]
    down = _down(ctx, "status")
    comps, res = status.get("rows"), status.get("resources")
    if not status:
        comps, res = _rows_from_model(model, envs)
    if not envs or not (comps or res):
        return '<p class="empty">Nothing runs yet. Add a component below, then promote it to its first environment.</p>'
    pieces = _banner_names(ctx)
    repos = _repos(model)
    head = '<th scope="col">Name</th>' + "".join(_head(r) for r in rules)
    body = []
    for row in comps or []:
        name = str(row["component"])
        cut_env = _cut_env(row, envs)
        tds = "".join(_cell(ctx, row, e, i, rules, down, repos.get(name) or name, pieces, cut_env) for i, e in enumerate(envs))
        body.append(f'<tr data-component="{esc(name)}"><th scope="row">{esc(name)} <span class="muted">{esc(row.get("type"))}</span></th>{tds}</tr>')
    for row in res or []:
        name = str(row["resource"])
        tds = "".join(_resource_cell(e, (row.get("cells") or {}).get(e), down) for e in envs)
        body.append(f'<tr data-resource="{esc(name)}"><th scope="row">{esc(name)} <span class="muted">resource</span></th>{tds}</tr>')
    return f'<div class="scroll-x"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


# ---------------- parts and relations ----------------

def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""


def _names(values: Any) -> str:
    return ", ".join(esc(v) for v in values or [])


def _parts(status: Mapping, model: Mapping) -> str:
    out = []
    comps = [c for c in model.get("components") or [] if isinstance(c, Mapping)]
    libs = [c for c in comps if c.get("type") == "library"]
    others = [c for c in comps if c.get("type") != "library"]
    if others:
        lines = []
        for c in others:
            rel = [f"{label} {_names(c.get(key))}" for label, key in
                   (("provides", "provides"), ("consumes", "consumes"), ("uses", "uses")) if c.get(key)]
            lines.append(f'<strong>{esc(c.get("name"))}</strong> <span class="muted">{esc(c.get("type"))}</span>'
                         + (" - " + "; ".join(rel) if rel else ""))
        out.append("<h3>Components</h3>" + _list(lines))
    libraries = [(lb.get("component"), lb.get("used_by")) for lb in status.get("libraries") or [] if isinstance(lb, Mapping)]
    if not libraries:
        libraries = [(c.get("name"), c.get("used_by")) for c in libs]
    if libraries:
        out.append("<h3>Libraries</h3>" + _list(
            [f'<strong>{esc(n)}</strong> <span class="muted">used by</span> {_names(u) or "nothing yet"}' for n, u in libraries]))
    apis = [a for a in model.get("apis") or [] if isinstance(a, Mapping)]
    if apis:
        out.append("<h3>APIs</h3>" + _list(
            [f'<strong>{esc(a.get("name"))}</strong> <span class="muted">{esc(a.get("type"))}</span> provided by '
             f'{esc(a.get("provider"))}; consumed by {_names(a.get("consumers")) or "nobody yet"}' for a in apis]))
    resources = [r for r in model.get("resources") or [] if isinstance(r, Mapping)]
    if resources:
        out.append("<h3>Resources</h3>" + _list(
            [f'<strong>{esc(r.get("name"))}</strong> <span class="muted">{esc(r.get("type"))}</span> used by '
             f'{_names(r.get("used_by")) or "nothing yet"}' for r in resources]))
    return "".join(out) or '<p class="empty">The model lists no components, APIs or resources yet.</p>'


# ---------------- Add to the model ----------------

def _field(label: str, name: str, *, kind: str = "text", options: list[str] | None = None, hint: str = "",
           required: bool = False) -> str:
    fid = f"f-{name}-{label.lower().replace(' ', '-')}"
    if options is not None:
        opts = "".join(f'<option value="{esc(o)}">{esc(o or "keep as is")}</option>' for o in options)
        control = f'<select id="{fid}" name="{esc(name)}">{opts}</select>'
    else:
        req = " required" if required else ""
        control = f'<input id="{fid}" name="{esc(name)}" type="{kind}" autocomplete="off"{req}>'
    note = f' <span class="muted">{esc(hint)}</span>' if hint else ""
    return f'<p><label for="{fid}">{esc(label)}</label> {control}{note}</p>'


def _form(kind: str, title: str, fields: str, repo: str) -> str:
    obj = json.dumps({"type": "system", "repo": repo})
    confirm = (f'<button type="button" class="btn primary" data-action="model" data-object="{esc(obj)}" data-args="{{}}" '
               f'disabled aria-disabled="true">Confirm</button>')
    return (f'<details id="form-{kind}"><summary>{esc(title)}</summary>'
            f'<form data-form="{kind}" data-post="/api/preview" data-wrap>{fields}'
            '<div data-preview><p class="muted">Fill in the form to see the command, the diff and the checks.</p>'
            '<code data-command></code></div>'
            f'<div data-result></div><p>{confirm}</p></form></details>')


def _own_slug(ctx: Any) -> str:
    """`owner/name` of the repo the console serves (git remote origin), or "" when it cannot be read."""
    import needs
    import status
    return needs._slug_of(status.sh(["git", "-C", str(ctx.repo_dir), "remote", "get-url", "origin"])) or ""


def model_forms(ctx: Any) -> str:
    """The five "Add to the model" forms; each posts to /api/preview and keeps its confirm disabled until the preview is valid."""
    model = ctx.data("model") or {}
    system = model.get("system") if isinstance(model.get("system"), Mapping) else {}
    repo = _own_slug(ctx) or (f"{system['owner']}/{system['name']}-gitops" if system.get("owner") and system.get("name") else "")
    rules = _rules(ctx.data("status") or {}, model)
    envs = [str(r["name"]) for r in rules]
    forms = [
        _form("component", "Component", _field("Action", "action", options=["add", "set", "remove"])
              + _field("Component", "component", required=True, hint="for example todo-api"), repo),
        _form("api", "API", _field("Action", "action", options=["set", "add"])
              + _field("Component", "component", required=True)
              + _field("Provides", "provides", hint="NAME or NAME:TYPE, for example orders:grpc")
              + _field("Consumes", "consumes", hint="the name of an API another component provides"), repo),
        _form("resource", "Resource", _field("Action", "action", options=["add", "remove"])
              + _field("Resource", "resource", required=True, hint="for example postgres")
              + _field("Type", "type") + _field("Version", "version"), repo),
        _form("environment", "Environment rules", _field("Environment", "env", options=envs or [""])
              + _field("Promote", "promote", options=["", "after-dev-smoke", "manual"])
              + _field("Policy", "policy", options=["", "audit", "enforce", "off"])
              + _field("Host", "host", hint="with {component}, {system} and {env}"), repo),
        _form("system", "New system", _field("Name", "name", required=True, hint="kebab-case, 2-40 characters, starts with a letter")
              + _field("Owner", "owner", required=True) + _field("First component", "component", required=True)
              + _field("Type", "type", hint="service, website or library") + _field("Language", "lang", hint="python, java, go or typescript")
              + _field("Description", "description"), repo),
    ]
    return ('<section id="add-to-the-model"><h2>Add to the model</h2>'
            '<p class="muted">Each change shows its command, diff and checks before anything runs.</p>' + "".join(forms) + "</section>")


# ---------------- the page ----------------

TABS = ("overview", "autonomy")


def _tabs(current: str) -> str:
    links = "".join(f'<a href="/system?tab={t}" data-tab="{t}"{" aria-current=" + chr(34) + "page" + chr(34) if t == current else ""}>{t.capitalize()}</a>'
                    for t in TABS)
    return f'<nav aria-label="System sections" class="tabs">{links}</nav>'


def page(ctx: Any, query: dict[str, str]) -> str:
    """The full HTML of `/system`."""
    from console import layout   # imported here: layout is shared and may be replaced in tests

    tab = query.get("tab") or "overview"
    if tab not in TABS:
        raise LookupError(f"no such System tab {tab!r}")
    if tab == "autonomy":
        from console import autonomy_page
        return layout.page("System", "system", _tabs(tab) + autonomy_page.body(ctx), state=ctx.state())
    status = ctx.data("status") or {}
    model = ctx.data("model") or {}
    gaps = _list([f'<strong>{esc(u.get("source"))}</strong> cannot be read: {esc(u.get("error"))}. Its cells show unknown.'
                  for u in status.get("unavailable") or [] if isinstance(u, Mapping)])
    where = _part(ctx, "status", f"<h2>Where it runs</h2>{_grid(ctx, status, model)}{gaps}")
    parts = _part(ctx, "model", f"<h2>Parts and relations</h2>{_parts(status, model)}") if ctx.source("model") else \
        f"<h2>Parts and relations</h2>{_parts(status, model)}"
    body = _tabs(tab) + f"<section>{where}</section><section>{parts}</section>{model_forms(ctx)}"
    return layout.page("System", "system", body, state=ctx.state())
