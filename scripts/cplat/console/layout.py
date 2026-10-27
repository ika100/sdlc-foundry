"""The page shell of the console (spec 122, design.md "Markup contract").

  page(title, place, body, *, panel=None, state) -> str

`place` is `inbox`, `board` or `system`. `body` and `panel` are HTML strings (a panel is the `<aside data-panel>` fragment).
`state` is the JSON of `GET /api/state` plus the per-start `token`:

  {"token", "read_at", "stale", "badge", "actions": {"running", "failed"}, "banner": [{"piece", "fix"}], "now"?}

Missing keys fall back to empty values, so a page still renders when a source is down."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from console import help as help_text
from console.html import esc, freshness

PLACES = (("inbox", "Inbox", "/inbox"), ("board", "Board", "/board"), ("system", "System", "/system"))

MENU = (("Settings", "/settings"), ("Notifications", "/settings#notifications"), ("Switch system", "/switch"))


def _nav(place: str, badge: int) -> str:
    links = []
    for key, label, href in PLACES:
        current = ' aria-current="page"' if key == place else ""
        count = f' <span class="badge" data-badge="inbox" data-count="{badge}">{badge}</span>' if key == "inbox" else ""
        links.append(f'<a href="{href}" data-place="{key}"{current}>{label}{count}</a>')
    return f'<nav aria-label="Places">{"".join(links)}</nav>'


def _menu() -> str:
    items = "".join(f'<li><a href="{href}">{label}</a></li>' for label, href in MENU)
    items += '<li><button type="button" class="link" data-action="stop-console">Stop console</button></li>'
    return f'<details class="menu" data-menu="user"><summary>Menu</summary><ul>{items}</ul></details>'


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
            f'(<code>/platform:doctor</code> checks it):</p><ul>{rows}</ul></div>')


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
<span class="brand">Console</span>
{_nav(place, badge)}
<button type="button" class="btn primary new" data-action="palette" aria-keyshortcuts="Meta+K Control+K">New or ask <kbd>&#8984;K</kbd></button>
<div class="tools">{_activity(actions)}{_menu()}</div>
</header>
<div class="main">
{_banner(banner)}
<div class="work">
<main id="content" tabindex="-1">
<div class="title"><h1>{esc(title)}</h1><span class="stamp">{stamp}</span><a class="btn help" href="/panel/help/{esc(place)}" aria-keyshortcuts="?">Help <kbd>?</kbd></a></div>
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
