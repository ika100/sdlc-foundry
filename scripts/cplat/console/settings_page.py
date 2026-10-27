"""The settings page (spec 122, AC-122.22): what notifications are set up, and how to change them.

  page(ctx, query) -> HTML of `/settings`

The console only shows `notify.yaml`; it never writes it."""
from __future__ import annotations

import notify_config
from console import actions, layout
from console.html import command_block, esc, table
from core import PlatformError

SNIPPET = """preset: recommended
events:
  approve: {slack: instant}
  retro: {email: digest}
digest: {at: "09:00", days: [mon, tue, wed, thu, fri]}
quiet_hours: "22:00-07:00\""""


def _matrix(cfg) -> str:
    rows = [[f"<code>{esc(e)}</code>"] + [f'<span data-cell="{esc(e)}:{c}">{esc(cfg.events[e].get(c, "off"))}</span>'
                                          for c in notify_config.CHANNELS] for e in notify_config.EVENTS]
    return table(rows, ["Event", *notify_config.CHANNELS], caption="Events by channel")


def _missing(checks: list[dict]) -> str:
    if not checks:
        return "<p data-missing-none>Every channel in use has its settings.</p>"
    items = "".join(f'<li data-missing="{esc(c.get("name"))}"><strong>{esc(c.get("name"))}</strong>: {esc(c.get("detail"))}'
                    f' <em>{esc(c.get("fix"))}</em></li>' for c in checks)
    return f"<ul>{items}</ul>"


def page(ctx, query: dict[str, str]) -> str:
    """`/settings`: the matrix, missing secrets, digest, quiet hours, workspace and how to edit the file."""
    path = notify_config.default_path()
    try:
        cfg = notify_config.load()
        top = _matrix(cfg)
        digest = cfg.digest
        extra = (f'<p data-digest>Digest at <time>{esc(digest.get("at"))}</time> on {esc(", ".join(digest.get("days", [])))}.</p>'
                 f'<p data-quiet-hours>Quiet hours: {esc(cfg.quiet_hours or "none")}.</p>')
    except PlatformError as e:
        top, extra = f'<p role="alert" data-error>{esc(e)}</p>', ""
    try:
        checks = notify_config.doctor_checks()
    except Exception as e:  # noqa: BLE001 - the page must still render
        checks = [{"name": "notify", "detail": str(e), "fix": ""}]
    body = (f'<h1>Settings</h1><section id="notifications" data-section="notifications"><h2>Notifications</h2>'
            f'<p>Without a file the Recommended preset applies.</p>{top}{extra}<h3>Missing</h3>{_missing(checks)}'
            f'<h3>Change it</h3><p>File: <code data-path>{esc(path)}</code>. The console never writes it; edit it yourself, for example:</p>'
            f'<pre data-snippet>{esc(SNIPPET)}</pre>{command_block(f"$EDITOR {path}")}</section>'
            f'<section data-section="workspace"><h2>Workspace</h2><p>Local clones live in <code data-workspace>{esc(actions.workspace())}</code>'
            f' (key <code>workspace</code> in <code>settings.yml</code>).</p></section>')
    return layout.page("Settings", "system", body, state=ctx.state())
