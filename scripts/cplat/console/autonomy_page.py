"""System > Autonomy tab of the console (spec 124, AC-124.13, AC-124.15, AC-124.16, AC-124.19, AC-124.21, AC-124.22).

  body(ctx) -> str    the HTML of `/system?tab=autonomy` inside the System page

It reads only the `autonomy` source (`cplat system autonomy show --json`) and the repo slug. Per environment it shows the
declared level as a form that previews through `/api/preview` (form `autonomy`), the effective guardrails, the engine state with
its heartbeat, and what is not confirmed or capped. Pause, Resume and Undo are actions; a level change is a pull request
(the confirm is the `model` action of the preview, as in the other forms)."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from console import system_page
from console.html import (action_button, command_block, engine_badge, esc, guardrails, level_name, level_sentence, short_version, table,
                          unavailable)

LEVELS = ("observe", "advise", "propose", "act", "improve")
PAUSE_MEANS = ("Every environment acts as observe within 60 seconds and running fixes stop at their next step. "
               "A pull request records the pause, and Resume brings back the levels declared in system.yaml.")


def _map(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _time(iso: object) -> str:
    return esc(str(iso or "").replace("T", " ").replace("Z", " UTC"))


# ---------------- pause ----------------

def _pause(repo: str, paused: bool) -> str:
    obj = json.dumps({"repo": repo})
    if paused:
        button = action_button("resume", "Resume", None, attrs={"data_object": obj, "data_args": "{}"}, primary=True)
        banner = ('<section class="banner" data-paused="true"><strong>All autonomy is paused.</strong> '
                  'Every environment acts as observe until you resume.</section>')
        return banner + f'<p>{button} {command_block("/system:autonomy resume")}</p>'
    button = action_button("pause", "Pause all autonomy", None,
                           attrs={"data_object": obj, "data_args": "{}",
                                  "data_confirm": "Pause all autonomy? Every environment acts as observe within 60 seconds."})
    return f'<p>{button} {command_block("/system:autonomy pause")}</p><p class="muted" data-pause-means>{esc(PAUSE_MEANS)}</p>'


# ---------------- one environment ----------------

def _radios(env: str, declared: str, cap: str) -> str:
    out = []
    limit = LEVELS.index(cap) if cap in LEVELS else len(LEVELS) - 1
    for i, level in enumerate(LEVELS):
        checked = " checked" if level == declared else ""
        off = i > limit
        flags = ' disabled aria-disabled="true"' if off else ""
        reason = f' <span class="reason" data-disabled-reason>{esc(f"{cap} is the highest level allowed in {env}")}</span>' if off else ""
        out.append(f'<label title="{esc(level_sentence(level))}"><input type="radio" name="level" value="{level}"{checked}{flags}> '
                   f'{esc(level_name(level))}</label>{reason}')
    return '<div class="levels">' + " ".join(out) + "</div>"


def _form(env: str, declared: str, cap: str, repo: str) -> str:
    obj = json.dumps({"type": "system", "repo": repo})
    sentence = esc(level_sentence(declared))
    knobs = "".join(f'<p><label>{esc(label)} <input name="{name}" autocomplete="off" size="6"></label></p>'
                    for name, label in (("maxLines", "Max lines"), ("maxFiles", "Max files"), ("runsPerDay", "Runs per day"),
                                        ("mergesPerDay", "Merges per day")))
    confirm = (f'<button type="button" class="btn primary" data-action="model" data-object="{esc(obj)}" data-args="{{}}" '
               'disabled aria-disabled="true">Open PR</button>')
    return (f'<form data-form="autonomy" data-post="/api/preview" data-wrap><input type="hidden" name="env" value="{esc(env)}">'
            f'{_radios(env, declared, cap)}<p class="muted">At {esc(declared)}: {sentence}</p>'
            f'<details><summary>Change a guardrail</summary>{knobs}</details>'
            '<div data-preview><p class="muted">Pick a level to see the command, the diff and the checks.</p>'
            '<code data-command></code><pre data-diff></pre></div>'
            f'<div data-result></div><p>{confirm}</p></form>')


def _engine(env: str, engine: Mapping) -> str:
    state = str(engine.get("state") or "none")
    name = engine.get("name")
    parts = [f'<p>Engine {engine_badge(name)} <span data-engine-state="{esc(state)}">{esc(state)}</span>']
    if engine.get("version"):
        parts.append(f' <span class="muted">v{esc(engine["version"])}</span>')
    beat = engine.get("heartbeat_at")
    if beat:
        parts.append(f' <span class="muted">heartbeat <time data-heartbeat="{esc(beat)}">{_time(beat)}</time></span>')
    parts.append("</p>")
    if state == "unreachable":
        note = unavailable(f"engine:{env}", beat, f"The engine of {env} does not answer; {env} is not supervised.")
        parts.append(note.replace("</section>", "<p>Not supervised: the level is declared but nothing acts on it. "
                                  "The last heartbeat is shown above.</p></section>"))
    elif state == "none":
        parts.append(f'<p class="muted">No engine is declared for {esc(env)}, so it is not supervised.</p>')
    return "".join(parts)


def _env(e: Mapping, repo: str) -> str:
    name = str(e.get("name") or "")
    declared = str(e.get("declared") or "observe")
    effective = str(e.get("effective") or declared)
    supervised = "true" if e.get("supervised") else "false"
    confirmed = "false" if e.get("confirmed") is False else "true"
    notes = []
    if effective != declared:
        notes.append(f'<span class="muted">acts as {esc(level_name(effective))}</span>')
    if confirmed == "false":
        kinds = ", ".join(esc(p.get("kind")) for p in e.get("pending") or [] if isinstance(p, Mapping))
        notes.append(f'<span class="stale" data-unconfirmed>not confirmed{f" ({kinds})" if kinds else ""}: the engine has not yet answered</span>')
    for c in e.get("caps") or []:
        c = _map(c)
        notes.append(f'<span class="muted" data-cap="{esc(c.get("component"))}">{esc(c.get("component"))}: max {esc(c.get("max"))}</span>')
    head = f'<h3>{esc(name)} <span class="muted">declared {esc(level_name(declared))}</span> {" ".join(notes)}</h3>'
    return (f'<section data-env="{esc(name)}" data-level="{esc(effective)}" data-supervised="{supervised}" data-confirmed="{confirmed}">'
            f'{head}{_form(name, declared, str(e.get("cap") or "improve"), repo)}'
            f'<h4>Guardrails now</h4>{guardrails({"guardrails": e.get("guardrails"), "undoWindow": e.get("undoWindow")})}'
            f'{_engine(name, _map(e.get("engine")))}</section>')


# ---------------- done on its own ----------------

def _what(ev: Mapping) -> str:
    obj = _map(ev.get("object"))
    text = esc(ev.get("kind"))
    if obj.get("version") or obj.get("previous"):
        text += f' pinned {esc(short_version(obj.get("version")))}, previous {esc(short_version(obj.get("previous")))}'
    elif obj.get("number") and obj.get("url"):
        text += f' <a href="{esc(obj["url"])}">#{esc(obj["number"])}</a>'
    where = " ".join(str(x) for x in (ev.get("component"), ev.get("environment")) if x)
    return text + (f' <span class="muted">{esc(where)}</span>' if where else "")


def _undo(ev: Mapping, repo: str) -> str:
    info = _map(ev.get("undo"))
    allowed = bool(info.get("allowed"))
    reason = None if allowed else str(info.get("reason") or "This cannot be undone.")
    eid = str(ev.get("event_id") or "")
    button = action_button("undo", "Undo", None, reason, attrs={"data_object": json.dumps({"repo": repo, "event": eid}), "data_args": "{}"})
    return button + (command_block(str(info["command"])) if allowed and info.get("command") else "")


def _actions(rows: list, repo: str) -> str:
    events = [_map(r) for r in rows]
    if not events:
        return '<p class="empty">Nothing was done on its own in the last 24 hours.</p>'
    cells, attrs = [], []
    for ev in events:
        pol = _map(ev.get("policy"))
        actor = _map(ev.get("actor"))
        cells.append([_time(ev.get("at")), esc(actor.get("name")), _what(ev),
                      f'{esc(pol.get("level"))} <span class="muted">{esc(str(pol.get("commit") or "")[:7])}</span>', _undo(ev, repo)])
        attrs.append(f'data-event="{esc(ev.get("event_id"))}" data-event-kind="{esc(ev.get("kind"))}"')
    return table(cells, ["When", "Who", "What", "Policy", ""], row_attrs=attrs)


# ---------------- the tab ----------------

def body(ctx: Any) -> str:
    """The Autonomy tab: pause, one section per environment, and what was done on its own."""
    doc = ctx.data("autonomy")
    src = ctx.source("autonomy")
    if system_page._down(ctx, "autonomy") or not doc:
        if src is None:
            return '<section><h2>Autonomy</h2><p class="empty">The autonomy source is not configured.</p></section>'
        return "<section><h2>Autonomy</h2>" + system_page._part(ctx, "autonomy", "") + "</section>"
    model = ctx.data("model") or {}
    system = model.get("system") if isinstance(model.get("system"), Mapping) else {}
    repo = system_page._own_slug(ctx) or (f"{system['owner']}/{system['name']}-gitops" if system.get("owner") and system.get("name") else "")
    envs = "".join(_env(_map(e), repo) for e in doc.get("environments") or [])
    done = _actions(doc.get("actions") or [], repo)
    return (system_page._part(ctx, "autonomy",
            f'<section><h2>Autonomy</h2><p class="lede">What the engine may do on its own in each environment. '
            f'A level change is a pull request; pausing is immediate.</p>{_pause(repo, bool(doc.get("paused")))}</section>'
            f'<section>{envs}</section><section><h2>Done on its own (last 24 hours)</h2>{done}</section>'))
