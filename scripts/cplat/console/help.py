"""In-console help: one line under each place's title and a help panel per place (`?` or the Help button).

  intro(place) -> str             the one-line answer a place gives, shown under its title
  panel_help(ctx, place) -> str   the side panel: how to work here, the stages, the keys, where data comes from

The text names only real commands and agents; the stage rows come from `stages.explain`, so the Board and the help
never disagree. Nothing here reads a source, so the help works while every source is down."""
from __future__ import annotations

from typing import Any

import stages
from console.html import command_block, esc, stage_badge

GUIDE = "https://github.com/ika100/sdlc-foundry/blob/main/docs/console.md"
PROCESS = "https://github.com/ika100/sdlc-foundry/blob/main/docs/AGENTS.md"

INTRO = {
    "inbox": "What needs your decision, oldest first. Everything else runs without you.",
    "board": "Every open item of the system in the one stage it is in, from issue to prod.",
    "system": "What the system is made of, where it runs at which version, and how to add to it.",
}

STEPS = {
    "inbox": [
        "Select an item (j / k, or click) to open its detail next to the list.",
        "Read what the decision changes and how to undo it, then decide there: answer, approve, promote, take over, fix or dismiss.",
        "Each button shows the exact command it runs; nothing runs before you confirm, and the result is a pull request or a run.",
        "An empty Inbox means nothing waits for you. Start a change with New or ask (⌘K).",
    ],
    "board": [
        "Columns are the eight stages in order; select a column header to see what happens there and who does it.",
        "A card is a spec, a run, an issue or a release. Open it (Enter) for its criteria, its evidence chain and its activity.",
        "Spec, Build and Prod are decision columns: items there may wait for you and also appear in the Inbox.",
        "Switch to List for a table, or Done for what finished in the last 30 or 90 days; search finds ids, titles, components and #issues.",
    ],
    "system": [
        "Where it runs: one row per component and resource, one column per environment with its promotion rule and policy.",
        "A cell shows the running version and its state (pinned, healthy, verified, NOT VERIFIED, alert or unknown).",
        "Promote and Cut release open the decision with its consequence first; the promotion itself is a pull request.",
        "Add to the model: each form previews the exact command, the system.yaml diff and the renderer's checks before anything runs.",
    ],
}

KEYS = (
    ("⌘K / Ctrl+K", "New or ask: describe a change, add to the model, go to, ask"),
    ("?", "this help"),
    ("j / k", "next / previous item in the Inbox"),
    ("← → ↑ ↓", "move across Board columns and cards"),
    ("Enter", "open the selected item"),
    ("Esc", "close the side panel or the palette"),
    ("a / p / t / o", "approve / promote / take over / open in Claude Code, on the selected decision"),
)

SOURCES = ("cplat model show --json", "cplat system status --json", "cplat spec list --json", "cplat needs --json",
           "the run list (--json)")


def intro(place: str) -> str:
    """The one-line answer of a place, or empty for pages that are not a place."""
    text = INTRO.get(place)
    return f'<p class="lede" data-help-intro>{esc(text)}</p>' if text else ""


def _list(items: list[str] | tuple[str, ...], tag: str = "ol") -> str:
    return f"<{tag}>" + "".join(f"<li>{esc(i)}</li>" for i in items) + f"</{tag}>"


def _stages() -> str:
    rows = []
    for name in stages.STAGES:
        e = stages.explain(name)
        decide = f'<br><strong>You decide:</strong> {esc(e["decision"])}' if e["decision"] else ""
        rows.append(f'<li>{stage_badge(name)} {esc(e["what"])}{decide}</li>')
    return '<ul class="plain help-stages">' + "".join(rows) + "</ul>"


def _keys() -> str:
    rows = "".join(f"<tr><td><kbd>{esc(k)}</kbd></td><td>{esc(v)}</td></tr>" for k, v in KEYS)
    return f'<div class="scroll-x"><table class="help-keys"><tbody>{rows}</tbody></table></div>'


def panel_help(ctx: Any, place: str) -> str:
    """The help side panel of a place; an unknown place raises LookupError (404)."""
    if place not in STEPS:
        raise LookupError(f"no help for {place!r}")
    title = {"inbox": "Inbox", "board": "Board", "system": "System"}[place]
    sources = "".join(f"<li><code>{esc(s)}</code></li>" for s in SOURCES)
    body = (
        f"<p>{esc(INTRO[place])}</p>"
        f"<h3>How to work here</h3>{_list(STEPS[place])}"
        "<h3>The process</h3>"
        "<p>A change goes from an idea to prod through eight stages. You are needed at three of them; "
        "the rest runs unattended in Claude Code and CI, and stops to ask you when a rule needs a person.</p>"
        f"{_stages()}"
        "<h3>Start a change</h3>"
        "<p>Press ⌘K and describe it in a sentence. The product manager agent writes a draft spec with acceptance "
        "criteria and open questions; it appears in the Inbox for your answers and approval. In a terminal:</p>"
        f"<p>{command_block('/component:spec <what should change>')}</p>"
        f"<h3>Keys</h3>{_keys()}"
        "<h3>Where the data comes from</h3>"
        f"<p>The console stores nothing. Every value is read from your repos, GitHub and the clusters through:</p>"
        f'<ul class="plain">{sources}</ul>'
        "<p>Every change runs as a slash command in Claude Code and ends in a pull request, so it is reviewable "
        "and can be undone.</p>"
        "<h3>When something is missing</h3>"
        f"<p>A banner names a missing piece (Claude Code, a GitHub login, a cluster context) and its fix. "
        f"Run the full check in a terminal:</p><p>{command_block('/platform:doctor')}</p>"
        f'<h3>More</h3><ul class="plain"><li><a href="{GUIDE}" target="_blank" rel="noopener">Console guide</a></li>'
        f'<li><a href="{PROCESS}" target="_blank" rel="noopener">How the agents work together</a></li></ul>'
    )
    from console.panels import _aside  # noqa: PLC0415 - one panel frame for every side panel

    return _aside(f"Help: {title}", body)
