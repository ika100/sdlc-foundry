"""The page shell of the console (spec 122, design.md "Markup contract").

  page(title, place, body, *, panel=None, state) -> str

`place` is `inbox`, `board` or `system`. `body` and `panel` are HTML strings (a panel is the `<aside data-panel>` fragment).
`state` is the JSON of `GET /api/state` plus the per-start `token`:

  {"token", "read_at", "stale", "badge", "actions": {"running", "failed"}, "banner": [{"piece", "fix"}], "now"?}

Missing keys fall back to empty values, so a page still renders when a source is down."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from console import glossary, help as help_text
from console.html import esc, freshness

PLACES = (("inbox", "Inbox", "/inbox"), ("board", "Board", "/board"), ("system", "System", "/system"))

MENU = (("How it works", "/help"), ("Guide", "/guide"), ("Settings", "/settings"), ("Notifications", "/settings#notifications"), ("Switch system", "/switch"))


# 20px line icons of the places (decorative: the link text names the place)
_ICON_PATHS = {
    "inbox": '<path d="M3 13h4l1.5 2.5h3L13 13h4"/><path d="M5 4h10l2 9v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-3z"/>',
    "board": '<rect x="3" y="3.5" width="4" height="13" rx="1"/><rect x="8" y="3.5" width="4" height="9" rx="1"/>'
             '<rect x="13" y="3.5" width="4" height="6" rx="1"/>',
    "system": '<path d="M10 2.5 17 6.5v7L10 17.5 3 13.5v-7z"/><path d="M3 6.5 10 10.5 17 6.5M10 10.5v7"/>',
    "menu": '<circle cx="10" cy="4.5" r="1.25"/><circle cx="10" cy="10" r="1.25"/><circle cx="10" cy="15.5" r="1.25"/>',
}


def icon(name: str) -> str:
    """An inline line icon, hidden from assistive technology."""
    return (f'<svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false" fill="none" '
            f'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{_ICON_PATHS[name]}</svg>')


def _nav(place: str, badge: int) -> str:
    links = []
    for key, label, href in PLACES:
        current = ' aria-current="page"' if key == place else ""
        count = f' <span class="badge" data-badge="inbox" data-count="{badge}">{badge}</span>' if key == "inbox" else ""
        links.append(f'<a href="{href}" data-place="{key}"{current}><span class="place">{icon(key)}{label}</span>{count}</a>')
    return f'<nav aria-label="Places">{"".join(links)}</nav>'


def _menu() -> str:
    items = "".join(f'<li><a href="{href}">{label}</a></li>' for label, href in MENU)
    items += '<li><button type="button" class="link" data-action="stop-console">Stop console</button></li>'
    return f'<details class="menu" data-menu="user"><summary>{icon("menu")}Menu</summary><ul>{items}</ul></details>'


def _activity(actions: Mapping[str, object]) -> str:
    running, failed = int(actions.get("running") or 0), int(actions.get("failed") or 0)
    return (f'<button type="button" class="activity" data-activity data-running="{running}" data-failed="{failed}"'
            f' aria-controls="activity-panel" aria-expanded="false">Actions '
            f'<span data-activity-text>{running} running, {failed} failed</span></button>')


def _fix(fix: object) -> str:
    """The fix text. A placeholder such as `<prod-context>` would vanish as an unknown tag, so text with `<` goes
    in a read-only textarea (its content is raw text, ends only at `</textarea`); `</` forces full escaping."""
    text = str(fix or "")
    if "<" in text and "</" not in text:
        return f'<textarea class="fix" readonly rows="1" aria-label="Fix">{text.replace("&", "&amp;")}</textarea>'
    return esc(text)


def _banner(items: list) -> str:
    if not items:
        return '<div id="banner" class="banner" role="status" hidden></div>'
    rows = "".join(f'<li><strong>{esc(i.get("piece"))}</strong> is missing. {_fix(i.get("fix"))}</li>' for i in items)
    return (f'<div id="banner" class="banner" role="status"><p>Some actions are off until this is fixed '
            f'(<code>/platform:doctor</code> checks it){glossary.tip("missing_piece")}:</p><ul>{rows}</ul></div>')


def page(title: str, place: str, body: str, *, panel: str | None = None, state: Mapping[str, object] | None = None) -> str:
    """The full HTML document of one place, with the side panel next to its content when `panel` is given."""
    if place not in {p[0] for p in PLACES}:
        raise ValueError(f"unknown place {place!r}")
    state = state or {}
    now = state.get("now")
    stamp = freshness(state.get("read_at"), now if isinstance(now, datetime) else None,
                      stale=bool(state["stale"]) if "stale" in state else None)
    badge = int(state.get("badge") or 0)
    actions = state.get("actions") if isinstance(state.get("actions"), Mapping) else {}
    banner = state.get("banner") if isinstance(state.get("banner"), list) else []
    system = state.get("system")
    system_name = (f'<a class="system-name" href="/switch" title="Switch system">{esc(system)}</a>'
                   if isinstance(system, str) and system else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="console-token" content="{esc(state.get("token", ""))}">
<title>{esc(title)} - Console</title>
<link rel="stylesheet" href="/static/console.css">
<script src="/static/console.js" defer></script>
</head>
<body data-place="{esc(place)}">
<a class="skip" href="#content">Skip to content</a>
<div class="shell">
<header class="side">
<span class="brand"><span class="logo" aria-hidden="true"></span><span>Console{system_name}</span></span>
{_nav(place, badge)}
<button type="button" class="btn primary new" data-action="palette" aria-keyshortcuts="Meta+K Control+K">New or ask <kbd>&#8984;K</kbd></button>
<div class="tools">{_activity(actions)}{_menu()}</div>
</header>
<div class="main">
{_banner(banner)}
<div class="work">
<main id="content" tabindex="-1">
<div class="title"><h1>{esc(title)}</h1><span class="stamp">{stamp}{glossary.tip("read_at")}</span><a class="btn help" href="/panel/help/{esc(place)}" aria-keyshortcuts="?">Help <kbd>?</kbd></a></div>
{help_text.intro(place) if title == dict((k, v) for k, v, _ in PLACES).get(place) else ""}
{body}
</main>
<div id="panel-slot">{panel or ""}</div>
</div>
</div>
</div>
<section id="activity-panel" class="activity-panel" aria-label="Actions" hidden></section>
<div id="palette" class="palette" role="dialog" aria-modal="true" aria-label="New or ask" hidden>
<div class="palette-box">
<input id="palette-q" type="search" placeholder="Describe a change, add to the model, go to, or ask" aria-label="New or ask" autocomplete="off">
<div id="palette-results"></div>
</div>
</div>
<div id="toast" class="toast" role="status" aria-live="polite"></div>
</body>
</html>
"""
