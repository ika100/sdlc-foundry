"""Shared HTML fragments of the console (spec 122, design.md "Markup contract").

Every function returns a string of HTML that is already escaped; compose them with f-strings. Text that comes from
outside goes through `esc` before it is put in markup. The attribute names here are the hooks `console.js`, `console.css`
and the acceptance tests rely on:

  esc(text)                                       escape text and attribute values
  command_block(cmd)                              <code data-command> plus a <button data-copy>
  action_button(kind, label, key, disabled_reason)  <button data-action aria-keyshortcuts> with <kbd>, or a disabled one with its reason
  stage_badge(stage)                              <span data-stage> whose text is the stage name
  freshness(read_at, now)                         <time data-read-at>, marked stale after 2 minutes
  unavailable(source, since, error)               a part whose source cannot be read, with "Retry now"
  table(rows, cols)                               a table inside <div class="scroll-x">
  engine_badge(name)                              <span class="badge" data-engine> for an item of an engine, "" for none (spec 124)
  guardrails(policy)                              <dl data-guardrails> with a <dd data-key="group.field"> per effective guardrail
  level_name(level), level_sentence(level)        the autonomy level as shown, and what the engine may do at it
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html import escape
import re

STALE_AFTER_SECONDS = 120


def esc(text: object) -> str:
    """Escape `text` for element content and for double-quoted attribute values."""
    return escape("" if text is None else str(text), quote=True)


def short_version(version: object) -> str:
    """A version for display: `sha-<40 hex>` pins become `sha-<7>`, a release version stays as it is."""
    text = "" if version is None else str(version)
    found = re.fullmatch(r"(?:sha-)?([0-9a-f]{40})", text)
    return f"sha-{found.group(1)[:7]}" if found else text


def _attrs(attrs: Mapping[str, object] | None) -> str:
    """Render extra attributes (`data_object` becomes `data-object`); None and False are skipped, True is bare."""
    out = []
    for name, value in (attrs or {}).items():
        if value is None or value is False:
            continue
        name = name.replace("_", "-")
        out.append(f" {esc(name)}" if value is True else f' {esc(name)}="{esc(value)}"')
    return "".join(out)


def command_block(cmd: str) -> str:
    """The command of an action with a button that copies it (AC-122.37)."""
    return (f'<span class="command"><code data-command>{esc(cmd)}</code>'
            '<button type="button" class="ghost" data-copy aria-label="Copy command">Copy</button></span>')


def action_button(kind: str, label: str, key: str | None, disabled_reason: str | None = None, *,
                  attrs: Mapping[str, object] | None = None, primary: bool = False) -> str:
    """A button for an action `kind`. `key` is its single-key shortcut (shown in <kbd>, None for none).

    With `disabled_reason` the button is disabled and the reason is visible next to it (AC-122.41, AC-122.17).
    `attrs` adds attributes such as `data_object` and `data_args` (JSON) that `console.js` posts to /api/actions."""
    shortcut = f' aria-keyshortcuts="{esc(key)}"' if key else ""
    kbd = f" <kbd>{esc(key)}</kbd>" if key else ""
    cls = "btn primary" if primary else "btn"
    if disabled_reason:
        button = (f'<button type="button" class="{cls}" data-action="{esc(kind)}"{shortcut} disabled aria-disabled="true"'
                  f'{_attrs(attrs)}>{esc(label)}{kbd}</button>')
        return (f'<span class="action">{button}'
                f'<span class="reason" data-disabled-reason>{esc(disabled_reason)}</span></span>')
    button = f'<button type="button" class="{cls}" data-action="{esc(kind)}"{shortcut}{_attrs(attrs)}>{esc(label)}{kbd}</button>'
    return f'<span class="action">{button}</span>'


def stage_badge(stage: str) -> str:
    """The only way a stage name is shown (AC-122.32): `data-stage` and the same visible text."""
    return f'<span class="stage" data-stage="{esc(stage)}">{esc(stage)}</span>'


def _parse(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def freshness(read_at: str | datetime | None, now: datetime | None = None, *, stale: bool | None = None) -> str:
    """When the data was read; older than 2 minutes (or `stale=True`, or never read) is marked stale (AC-122.43)."""
    when = _parse(read_at)
    now = _parse(now) or datetime.now(timezone.utc)
    if stale is None:
        stale = when is None or (now - when).total_seconds() > STALE_AFTER_SECONDS
    iso = when.strftime("%Y-%m-%dT%H:%M:%SZ") if when else ""
    shown = f"Read {when.astimezone(timezone.utc).strftime('%H:%M:%S')} UTC" if when else "Not read yet"
    mark = ' data-stale="true"' if stale else ""
    word = ' <span class="stale-word">stale</span>' if stale else ""
    return f'<time class="read-at" data-read-at="{esc(iso)}" datetime="{esc(iso)}"{mark}>{esc(shown)}{word}</time>'


def unavailable(source: str, since: str | datetime | None, error: str | None) -> str:
    """A part whose source cannot be read: the error, `unknown` instead of health, and a retry button (AC-122.42)."""
    since_iso = esc(since.isoformat() if isinstance(since, datetime) else since)
    return (f'<section class="unavailable" data-source="{esc(source)}" data-unavailable-since="{since_iso}">'
            f'<h3>{esc(source)} is not available</h3>'
            f'<p class="error">{esc(error or "no answer")}</p>'
            f'<p>Health: <span class="health">unknown</span>. Showing nothing newer than {since_iso or "the start"}.</p>'
            '<button type="button" class="btn" data-action="retry-source">Retry now</button></section>')


def table(rows: Sequence[Sequence[object]], cols: Sequence[str], *, caption: str | None = None,
          row_attrs: Sequence[str] | None = None) -> str:
    """A table in a box that scrolls sideways (AC-122.28). `cols` are plain-text headings (escaped);
    each cell of `rows` is HTML, so the caller escapes with `esc` or builds it with the fragments above.
    `row_attrs[i]` is ready-made, already escaped attribute text for the i-th `<tr>`."""
    head = "".join(f'<th scope="col">{esc(c)}</th>' for c in cols)
    body = "".join(f"<tr{' ' + row_attrs[i] if row_attrs else ''}>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
                   for i, row in enumerate(rows))
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f'<div class="scroll-x"><table>{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


_LEVEL_MAY = {
    "observe": "record issues from signals",
    "advise": "also triage them and notify",
    "propose": "also open fix pull requests that a person merges",
    "act": "also merge fixes within the guardrails, roll back after a failed smoke, and let a person undo",
    "improve": "act as `act` until a later spec defines it",
}


def level_name(level: str) -> str:
    """An autonomy level as shown to a person."""
    return str(level)


def level_sentence(level: str) -> str:
    """What the engine may do at `level`; the text of `autonomy.allows`, which a test keeps in sync (html.py does not import it)."""
    return f"The engine may {_LEVEL_MAY.get(level, 'do nothing')}."


def engine_badge(name: str | None) -> str:
    """The badge of an item that an engine handled (AC-124.18); nothing for a person's item."""
    if not name:
        return ""
    return f'<span class="badge" data-engine="{esc(name)}">{esc(name)}</span>'


_GUARDRAIL_ORDER = (
    ("autoMerge", ("routes", "maxCriticality")),
    ("riskGate", ("maxFiles", "maxLines", "regressionTest", "secondReview")),
    ("budget", ("runsPerDay", "mergesPerDay")),
    ("window", ("days", "from", "to", "timezone")),
)
_PER_RUN = ("minutes", "invocations", "reruns", "cost")


def _guardrail_value(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def guardrails(policy: Mapping[str, object]) -> str:
    """The effective guardrails of an environment as a `<dl data-guardrails>` (AC-124.19), one entry per field."""
    rails = policy.get("guardrails")
    rails = rails if isinstance(rails, Mapping) else {}
    entries: list[tuple[str, object]] = []
    for group, fields in _GUARDRAIL_ORDER:
        values = rails.get(group)
        values = values if isinstance(values, Mapping) else {}
        for field in fields:
            if field in values:
                entries.append((f"{group}.{field}", values[field]))
        if group == "budget":
            per_run = values.get("perRun")
            if isinstance(per_run, Mapping):
                entries.extend((f"budget.perRun.{k}", per_run[k]) for k in _PER_RUN if k in per_run)
    if "undoWindow" in policy:
        entries.append(("undoWindow", policy["undoWindow"]))
    body = "".join(f'<dt>{esc(key)}</dt><dd data-key="{esc(key)}">{esc(_guardrail_value(value))}</dd>' for key, value in entries)
    return f"<dl data-guardrails>{body}</dl>"


def definition_list(attr: str, pairs: Sequence[tuple[str, object]]) -> str:
    """`<dl attr>` of (term, already escaped HTML) pairs."""
    rows = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in pairs)
    return f"<dl {attr}>{rows}</dl>"


def signal_facts(sig: Any) -> str:
    """The facts of an engine signal, its triage and the policy decision; `(none)` before triage (AC-124.18)."""
    if not isinstance(sig, dict):
        return ""
    evidence = "".join(
        f'<a href="{esc(e.get("url"))}">{esc(e.get("text") or e.get("url"))}</a> ' if e.get("url") else f"{esc(e.get('text'))} "
        for e in sig.get("evidence") or [] if isinstance(e, dict))
    facts = definition_list("data-signal", [
        ("Component", esc(sig.get("component"))), ("Environment", esc(sig.get("environment"))),
        ("Category", esc(sig.get("category"))), ("Criticality", esc(sig.get("criticality"))),
        ("Seen", esc(sig.get("seen"))), ("First seen", esc(sig.get("first_seen"))), ("Last seen", esc(sig.get("last_seen"))),
        ("Evidence", evidence or "(none)")])
    tri = sig.get("triage")
    if isinstance(tri, dict):
        files = ", ".join(esc(f) for f in tri.get("suspected_files") or []) or "(none)"
        triage = definition_list("data-triage", [("Route", esc(tri.get("route"))), ("Confidence", esc(tri.get("confidence"))),
                                     ("Suspected files", files)])
    else:
        triage = definition_list("data-triage", [("Triage", "(none)")])
    pol = sig.get("policy")
    decision = esc(pol.get("decision")) if isinstance(pol, dict) and pol.get("decision") else "(none)"
    level = f" (level {esc(pol.get('level'))})" if isinstance(pol, dict) and pol.get("level") else ""
    return (f"<h3>The signal</h3>{facts}<h3>Triage</h3>{triage}"
            f"<h3>Policy decision</h3><p data-policy-decision>{decision}{level}</p>")
