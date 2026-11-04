"""System place of the console (spec 122, AC-122.7, AC-122.8, AC-122.20, AC-122.40, AC-122.47, AC-122.50, AC-122.51).

  page(ctx, query) -> str        the full HTML of `/system`
  model_forms(ctx) -> str        the five model forms as disclosures, for the palette
  drawer(ctx) -> str             the same forms in the System page's drawer

The page shows the system as one tree: groups of components, libraries, resources and APIs, each item a row. A component or
resource row has one column per environment in promotion order; a cell shows the version and the state exactly as
`system status` reports them; while the status cannot be read every state is `unknown` and the actions that depend on health
are disabled (AC-122.42). A row's toggle opens its detail row: its relations and the changes it offers. Every change opens its
form in the drawer, filled in from the row (`data-form-open`, `data-prefill`); the forms post to `/api/preview` and
`console.js` fills the preview and enables the confirm."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from console import actions, glossary
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
    return (f'<th scope="col" data-env="{esc(rule.get("name"))}"><span class="env-name">{esc(rule.get("name"))}</span> '
            f'<span class="muted env-rules"><span class="chip">promote {esc(rule.get("promote") or "none")}{glossary.tip("promote_rule")}</span> '
            f'<span class="chip">policy {esc(rule.get("policy") or "none")}{glossary.tip("policy")}</span></span> '
            f'<a href="#form-environment" class="edit-env" data-edit-env="{esc(rule.get("name"))}">Change rules</a></th>')


# ---------------- cells ----------------

def _state_html(state: str) -> str:
    cls = "ok" if state in GOOD else "failed" if state in BAD else "muted"
    return f'<span class="pill {cls}" data-state="{esc(state)}">{esc(state)}</span>'


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
        return f'<td data-env="{esc(env)}"><span class="muted absent">not deployed</span></td>'
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
        return f'<td data-env="{esc(env)}"><span class="muted absent">not deployed</span></td>'
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


def _opener(form: str, label: str, name: str = "", cls: str = "btn", **fields: str) -> str:
    """A button that opens `form` in the drawer with `fields` filled in; `name` goes into its accessible name."""
    aria = f' aria-label="{esc(label)} {esc(name)}"' if name else ""
    return (f'<button type="button" class="{cls}" data-form-open="{esc(form)}" data-prefill="{esc(json.dumps(fields))}"{aria}>'
            f'{esc(label)}</button>')


def _node(kind: str, name: str, label: str) -> str:
    """The name cell of a row with the toggle that shows its children."""
    return (f'<button type="button" class="twisty" data-toggle="{esc(kind)}:{esc(name)}" aria-expanded="false" '
            f'aria-label="Show the details of {esc(name)}"></button><span class="node-name">{esc(name)}</span>'
            f' <span class="muted">{esc(label)}</span>')


def _detail(kind: str, name: str, width: int, facts: list[tuple[str, str]], buttons: str) -> str:
    dl = "".join(f"<div><dt>{esc(k)}</dt><dd>{v}</dd></div>" for k, v in facts)
    return (f'<tr class="node-detail" data-detail-of="{esc(kind)}:{esc(name)}" hidden><td colspan="{width}">'
            f'<dl class="facts">{dl}</dl><div class="node-actions">{buttons}</div></td></tr>')


def _group(title: str, count: int, width: int, add: str) -> str:
    return (f'<tr class="group"><th scope="rowgroup" colspan="{width}"><span class="group-title">{esc(title)}</span>'
            f' <span class="count">{count}</span>{add}</th></tr>')


def _repo_link(repo: str) -> str:
    return f'<a href="https://github.com/{esc(repo)}" target="_blank" rel="noopener noreferrer">{esc(repo)}</a>' if repo else "\u2013"


def _grid(ctx: Any, status: Mapping, model: Mapping) -> str:
    """The system as a tree: components, libraries, resources and APIs, each a row; a component or resource row has a cell
    per environment, and its detail row (opened by its toggle) holds its relations and the changes it offers."""
    rules = _rules(status, model)
    envs = [str(r["name"]) for r in rules]
    down = _down(ctx, "status")
    comps, res = status.get("rows"), status.get("resources")
    if not status:
        comps, res = _rows_from_model(model, envs)
    width = len(envs) + 1
    pieces = _banner_names(ctx)
    repos = _repos(model)
    by_name = {str(c.get("name")): c for c in model.get("components") or [] if isinstance(c, Mapping)}
    by_res = {str(r.get("name")): r for r in model.get("resources") or [] if isinstance(r, Mapping)}
    head = '<th scope="col">Name</th>' + "".join(_head(r) for r in rules)

    rows = [_group("Components", len(comps or []), width, _opener("component", "+ Add component", cls="ghost", action="add"))]
    for row in comps or []:
        name = str(row["component"])
        c = by_name.get(name, {})
        cut_env = _cut_env(row, envs)
        tds = "".join(_cell(ctx, row, e, i, rules, down, repos.get(name) or name, pieces, cut_env) for i, e in enumerate(envs))
        rows.append(f'<tr class="node" data-component="{esc(name)}"><th scope="row">{_node("component", name, str(row.get("type") or c.get("type") or ""))}</th>{tds}</tr>')
        facts = [("Repo", _repo_link(repos.get(name, ""))), ("Provides", _names(c.get("provides")) or "nothing"),
                 ("Consumes", _names(c.get("consumes")) or "nothing"), ("Uses", _names(c.get("uses")) or "nothing")]
        buttons = (_opener("api", "Change APIs", name, component=name)
                   + _opener("component", "Remove", name, action="remove", component=name))
        rows.append(_detail("component", name, width, facts, buttons))
    if not comps:
        rows.append(f'<tr class="empty-row"><td colspan="{width}" class="muted">No component runs yet. Add one, then promote it '
                    'to its first environment.</td></tr>')

    libraries = [(lb.get("component"), lb.get("used_by")) for lb in status.get("libraries") or [] if isinstance(lb, Mapping)]
    if not libraries:
        libraries = [(c.get("name"), c.get("used_by")) for c in by_name.values() if c.get("type") == "library"]
    if libraries:
        rows.append(_group("Libraries", len(libraries), width, ""))
        for lib, used in libraries:
            rows.append(f'<tr class="node leaf" data-library="{esc(lib)}"><th scope="row"><span class="node-name">{esc(lib)}</span>'
                        f' <span class="muted">library</span></th><td colspan="{len(envs)}" class="muted">no instances; used by '
                        f'{_names(used) or "nothing yet"}</td></tr>')

    rows.append(_group("Resources", len(res or []), width, _opener("resource", "+ Add resource", cls="ghost", action="add")))
    for row in res or []:
        name = str(row["resource"])
        r = by_res.get(name, {})
        tds = "".join(_resource_cell(e, (row.get("cells") or {}).get(e), down) for e in envs)
        rows.append(f'<tr class="node" data-resource="{esc(name)}"><th scope="row">{_node("resource", name, str(r.get("type") or "resource"))}</th>{tds}</tr>')
        rows.append(_detail("resource", name, width, [("Type", esc(r.get("type") or "\u2013")),
                                                      ("Used by", _names(r.get("used_by")) or "nothing yet")],
                            _opener("resource", "Remove", name, action="remove", resource=name)))

    apis = [a for a in model.get("apis") or [] if isinstance(a, Mapping)]
    rows.append(_group("APIs", len(apis), width, _opener("api", "+ Add API", cls="ghost")))
    for a in apis:
        name, provider = str(a.get("name")), str(a.get("provider") or "")
        rows.append(f'<tr class="node leaf" data-api="{esc(name)}"><th scope="row"><span class="node-name">{esc(name)}</span>'
                    f' <span class="muted">{esc(a.get("type"))}</span></th><td colspan="{len(envs)}">provided by {esc(provider)}; '
                    f'consumed by {_names(a.get("consumers")) or "nobody yet"} '
                    f'{_opener("api", "Change", name, cls="ghost", component=provider) if provider else ""}</td></tr>')
    if not envs:
        return '<p class="empty">The system has no environments yet.</p>'
    return f'<div class="scroll-x tree"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


# ---------------- parts and relations ----------------

def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""


def _names(values: Any) -> str:
    return ", ".join(esc(v) for v in values or [])


# ---------------- Add to the model ----------------

API_TYPES = ("openapi", "grpc", "graphql", "events")
RESOURCE_TYPES = ("database", "bucket", "cache", "broker")
RESOURCE_VERSIONS = "database 15-18 (default 17), cache 8 or 9, broker 2.14 or 2.15"
COMPONENT_TYPES = ("service", "website", "library")
LANGUAGES = ("python", "java", "go", "typescript")
PROMOTE_RULES = {"dev": (), "staging": ("after-dev-smoke", "manual"), "prod": ("manual",)}
POLICIES = ("audit", "enforce", "off")


def _field(label: str, name: str, *, kind: str = "text", options: list | tuple | None = None, hint: str = "",
           required: bool = False, when: str | None = None, active: bool = True, key: str = "") -> str:
    """One labelled control. `options` makes it a select: a value, or (value, label); "" reads "keep as is".

    `when="action=remove"` (or `env=dev|staging`) shows the field only while that other field has that value: `console.js`
    switches it, and a hidden field is disabled so it is not sent. `active` is its state before the script runs; `key` keeps
    the ids of two fields with the same name apart."""
    fid = f"f-{name}-{(key or label).lower().replace(' ', '-')}"
    off = "" if active else " disabled"
    if options is not None:
        pairs = [o if isinstance(o, tuple) else (o, o or "keep as is") for o in options]
        opts = "".join(f'<option value="{esc(v)}">{esc(lab)}</option>' for v, lab in pairs)
        control = f'<select id="{fid}" name="{esc(name)}"{off}>{opts}</select>'
    else:
        req = " required" if required else ""
        control = f'<input id="{fid}" name="{esc(name)}" type="{kind}" autocomplete="off"{req}{off}>'
    note = f' <span class="muted">{esc(hint)}</span>' if hint else ""
    cond = f' data-show-when="{esc(when)}"' + ("" if active else " hidden") if when else ""
    return f'<p class="field"{cond}><label for="{fid}">{esc(label)}</label> {control}{note}</p>'


def _pick(names: list[str], what: str) -> list:
    """The options of a select of existing things; a placeholder first so nothing is chosen by accident."""
    return [("", f"choose {what}")] + names if names else [("", f"no {what} yet")]


def _form(kind: str, title: str, fields: str, repo: str) -> tuple[str, str, str]:
    """(kind, title, the form): every model form posts to /api/preview and keeps its confirm off until the preview is valid."""
    obj = json.dumps({"type": "system", "repo": repo})
    confirm = (f'<button type="button" class="btn primary" data-action="model" data-object="{esc(obj)}" data-args="{{}}" '
               f'disabled aria-disabled="true">Confirm</button>')
    return (kind, title, f'<form data-form="{kind}" data-post="/api/preview" data-wrap>{fields}'
            '<div data-preview><p class="muted">Fill in the form to see the command, the diff and the checks.</p>'
            '<code data-command></code></div>'
            f'<div data-result></div><p>{confirm}</p></form>')


def _own_slug(ctx: Any) -> str:
    """`owner/name` of the repo the console serves (git remote origin), or "" when it cannot be read."""
    import needs
    import status
    return needs._slug_of(status.sh(["git", "-C", str(ctx.repo_dir), "remote", "get-url", "origin"])) or ""


def model_forms(ctx: Any) -> str:
    """The five model forms as disclosures, for the palette (the System page opens the same forms in its drawer)."""
    forms = "".join(f'<details id="palette-form-{kind}"><summary>{esc(title)}</summary>{form}</details>'
                    for kind, title, form in _forms(ctx))
    return ('<section id="add-to-the-model"><h2>Add to the model</h2>'
            '<p class="muted">Each change shows its command, diff and checks before anything runs.</p>' + forms + "</section>")


def drawer(ctx: Any) -> str:
    """The model forms of the System page in a drawer at the right edge; the buttons of the tree open one, filled in."""
    boxes = "".join(f'<section class="drawer-form" id="form-{kind}" data-form-box="{kind}" hidden><h2>{esc(title)}</h2>{form}</section>'
                    for kind, title, form in _forms(ctx))
    return (f'<aside id="model-drawer" class="drawer" aria-label="Change the model" hidden>'
            f'<header><span class="muted">Change the model{glossary.tip("model", "left")}</span>'
            '<button type="button" class="ghost" data-action="close-drawer" aria-label="Close the form">Close <kbd>Esc</kbd></button>'
            f'</header>{boxes}</aside>')


def _forms(ctx: Any) -> list[tuple[str, str, str]]:
    """The five model forms (component, API, resource, environment rules, new system) as (kind, title, form)."""
    model = ctx.data("model") or {}
    system = model.get("system") if isinstance(model.get("system"), Mapping) else {}
    repo = _own_slug(ctx) or (f"{system['owner']}/{system['name']}-gitops" if system.get("owner") and system.get("name") else "")
    rules = _rules(ctx.data("status") or {}, model)
    envs = [str(r["name"]) for r in rules]
    comps = [str(c["name"]) for c in model.get("components") or [] if isinstance(c, Mapping) and c.get("name")]
    apis = [str(a["name"]) for a in model.get("apis") or [] if isinstance(a, Mapping) and a.get("name")]
    resources = [str(r["name"]) for r in model.get("resources") or [] if isinstance(r, Mapping) and r.get("name")]

    def env_fields(rule: Mapping, first: bool) -> str:
        env = str(rule.get("name"))
        now_promote, now_policy = rule.get("promote") or "none", rule.get("policy") or "none"
        allowed = PROMOTE_RULES.get(env, ("after-dev-smoke", "manual"))
        promote = [("", f"keep as is ({now_promote})")] + [r for r in allowed if r != now_promote]
        why = {"dev": "dev always follows main", "prod": "prod is always manual"}.get(env, "")
        return (_field("Promote", "promote", options=promote, hint=why if len(promote) == 1 else "", when=f"env={env}",
                       active=first, key=env)
                + _field("Policy", "policy", options=[("", f"keep as is ({now_policy})")] + [x for x in POLICIES if x != now_policy],
                         when=f"env={env}", active=first, key=env))

    forms = [
        _form("component", "Add or remove a component", _field("Action", "action", options=[("add", "add a new component"), ("remove", "remove one")])
              + _field("Component", "component", required=True, hint="the name of its repo, for example todo-api",
                       when="action=add", key="new")
              + _field("Component", "component", options=_pick(comps, "a component"), when="action=remove", active=False,
                       key="existing"), repo),
        _form("api", "APIs of a component", _field("Component", "component", options=_pick(comps, "a component"), key="existing")
              + _field("Provides", "provides", hint="the name of a new API, for example orders")
              + _field("Type", "provides_type", options=[("", "type")] + list(API_TYPES))
              + _field("Consumes", "consumes", options=[("", "nothing")] + apis if apis else [("", "no API yet")])
              + '<input type="hidden" name="action" value="set">', repo),
        _form("resource", "Add or remove a resource", _field("Action", "action", options=[("add", "add a new resource"), ("remove", "remove one")])
              + _field("Resource", "resource", required=True, hint="for example postgres", when="action=add", key="new")
              + _field("Type", "type", options=[("", "choose a type")] + list(RESOURCE_TYPES), when="action=add")
              + _field("Version", "version", hint=RESOURCE_VERSIONS, when="action=add")
              + _field("Resource", "resource", options=_pick(resources, "a resource"), when="action=remove", active=False,
                       key="existing"), repo),
        _form("environment", "Environment rules", _field("Environment", "env", options=envs or [""])
              + "".join(env_fields(r, i == 0) for i, r in enumerate(rules))
              + _field("Host", "host", hint="with {component}, {system} and {env}"), repo),
        _form("system", "New system", _field("Name", "name", required=True, hint="kebab-case, 2-40 characters, starts with a letter")
              + _field("Owner", "owner", required=True) + _field("First component", "component", required=True)
              + _field("Type", "type", options=list(COMPONENT_TYPES)) + _field("Language", "lang", options=list(LANGUAGES))
              + _field("Description", "description"), repo),
    ]
    return forms


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
    states = glossary.legend(("pinned", "healthy", "verified", "not_verified", "alert", "unknown", "not_deployed"),
                             "Instance states", swatch="state")
    name = (model.get("system") or {}).get("name") if isinstance(model.get("system"), Mapping) else None
    where = _part(ctx, "status", f'<div class="tree-head"><h2>{esc(name or "The system")}{glossary.tip("version")}</h2>'
                                 f'{_opener("system", "New system", cls="ghost")}</div>{_grid(ctx, status, model)}'
                                 f'<div class="board-legend">{states}</div>{gaps}')
    if ctx.source("model") and _down(ctx, "model"):
        where = _part(ctx, "model", "") + where
    body = _tabs(tab) + f'<section class="where">{where}</section>{drawer(ctx)}'
    return layout.page("System", "system", body, state=ctx.state())
