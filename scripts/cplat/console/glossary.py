"""The console's glossary: one text per term, used by the `?` tips on every page and by the "How it works" page (`/help`).

  tip(key, align="") -> str      a small `?` next to a term: its text on hover, tap or keyboard focus, and a link to the page;
                                 no JavaScript (CSS :hover / :focus-within)
  legend(keys) -> str            a row of terms, each with its tip (the colours of the Board cards, the states of an instance)
  page(ctx, query) -> str        GET /help: the process (from `stages.explain`) and every term, grouped by topic

The texts say what the code does: the instance states follow `status.cell_state`, the decision kinds `needs.collect`, the
environment rules the domain model (docs/DOMAIN-MODEL.md), the autonomy levels `html.level_sentence`. A term is linked as
`/help#t-<key>`. Nothing here reads a source, so the help works while every source is down."""
from __future__ import annotations

from typing import Any

import stages
from console.html import _LEVEL_MAY, esc, stage_badge

STALE_MINUTES = 2

# key -> (title, text). Plain sentences; the title is how the term appears on the page.
TERMS: dict[str, tuple[str, str]] = {
    # ---- decisions (the Inbox)
    "decision": (
        "Decision",
        "Something only you can decide: answer, approve, escalation, promote, triage or review. Select a row to see what it "
        "changes and decide there. Everything else runs without you.",
    ),
    "answer": (
        "Answer",
        "A draft spec has open questions for you. Your answers go into the spec; after that it waits for your approval.",
    ),
    "approve": (
        "Approve",
        "A draft spec without open questions waits for your approval. Approve & ship starts a run with the budget you choose: "
        "plan, build, tests, review, merge and deploy to dev and staging run without you.",
    ),
    "escalation": (
        "Escalation",
        "A run stopped because a rule needs a person, for example a gate that stays red or an exhausted budget. Take over in "
        "Claude Code, give it more budget or amend the spec.",
    ),
    "promote": (
        "Promote",
        "A release that staging verified waits to go to prod. The panel shows the commits, specs and migrations in between, "
        "whether the digest is the one staging verified, and the way back. Prod never changes on its own.",
    ),
    "triage": (
        "Triage",
        "A new issue, an alert or a failed smoke. Triage routes it to a fix, a spec or a reply (/issue:triage).",
    ),
    "review": (
        "Review",
        "A fix an engine opened but may not merge by itself (at propose, or outside a guardrail at act). Approve merges it "
        "once every check passed.",
    ),
    "waiting": ("Waiting", "How long the decision has waited. The Inbox lists the oldest first."),
    # ---- the Board
    "stage": (
        "Stage",
        "Every open item is in exactly one of eight stages, from Issue to Prod. Select a stage name for what happens there, "
        "who does it and the commands.",
    ),
    "decision_stage": (
        "You decide",
        "Spec, Build and Prod are where you decide: approving a spec, answering an escalation, promoting to prod. Items "
        "there may also wait in the Inbox.",
    ),
    "spec": (
        "Spec",
        "A feature spec (docs/specs/<NNN>-<slug>/spec.md) with acceptance criteria. A card shows its id and its title.",
    ),
    "run": (
        "Run",
        "An unattended run that ships a spec: plan, build, tests, review, merge and deploy. Its record holds the phase, the "
        "budget and the evidence from pull request to running instance.",
    ),
    "slice": ("Slice", "The part of a system spec that one repo builds, with the criteria the plan assigned to it."),
    "running": ("Running", "A run works on it now."),
    "stopped": (
        "Stopped",
        "The run stopped and needs a person. The card says why in one line; the decision waits in the Inbox.",
    ),
    "waits": ("Waits for you", "It cannot go on without you: open questions, an approval, or a release to promote or cut."),
    "not_started": ("Not started", "No run works on it at the moment."),
    "budget": (
        "Budget",
        "What a run has used of its limit, in US dollars and minutes. A run that reaches its limit stops and asks you.",
    ),
    "done_view": ("Done", "What finished in the last 30 days, 90 days or all time, with its evidence links."),
    # ---- where it runs (System)
    "version": (
        "Version",
        "The image the gitops repo pins in that environment: sha-<7> for a build of main (dev and staging), X.Y.Z for a "
        "release (prod). Select it for the instance's detail.",
    ),
    "pinned": ("pinned", "The version is pinned in the gitops repo, but Argo CD does not report it Synced and Healthy yet."),
    "healthy": ("healthy", "Argo CD reports it Synced and Healthy; there is no smoke result for this version yet."),
    "verified": (
        "verified",
        "The smoke tests passed against this version in this environment. Only a verified version is offered for promotion.",
    ),
    "not_verified": (
        "NOT VERIFIED",
        "The smoke result for this version is not green: the tests failed or did not run. It promotes nothing.",
    ),
    "alert": ("alert", "An open alert issue names this environment (labels alert and env:<env>). Triage it in the Inbox."),
    "unknown": (
        "unknown",
        "The cluster could not be read, so the console does not guess. Actions that need health stay off until it can be read.",
    ),
    "not_deployed": ("not deployed", "The component has no instance in this environment. /instance:promote adds one."),
    "promote_rule": (
        "Promote rule",
        "How a version reaches this environment. none: dev follows main through pin pull requests. after-dev-smoke: staging "
        "follows a green dev smoke on its own. manual: /instance:promote, always the case for prod.",
    ),
    "policy": (
        "Policy",
        "The Kyverno guard rails for workloads here: off, audit (violations are reported) or enforce (violations are refused). "
        "The default is audit in dev and staging, enforce in prod.",
    ),
    "release_candidate": (
        "Cut release",
        "A verified version newer than the last release. Cut release runs /component:release: version, changelog, release "
        "pull request and tag. The tag is what prod can be promoted to.",
    ),
    "model": (
        "Change the model",
        "Every change to system.yaml starts from the item it is about: + Add on a group, Remove or Change APIs in a row's "
        "details, Change rules on an environment. Its form opens at the right, filled in, and first shows the exact command, "
        "the diff and the renderer's checks on a scratch copy; nothing runs before you confirm, and the change is a pull request.",
    ),
    # ---- actions and the data
    "command": (
        "Command",
        "Every button shows the slash command it runs, with a copy button. Nothing runs before you click; the result is a pull "
        "request or a run, so it can be reviewed and undone.",
    ),
    "way_back": (
        "The way back",
        "The command that undoes a decision. For a promotion it promotes the previous version again, with a warning when a "
        "migration in between is not additive.",
    ),
    "actions": ("Actions", "What you started from the console: how many run and how many failed. Select it for their output."),
    "read_at": (
        "Read at",
        "When the console last read its sources. It reads every value from cplat … --json again in the background and stores "
        "nothing of its own.",
    ),
    "stale": (
        "stale",
        f"The data is older than {STALE_MINUTES} minutes or was never read. The page shows the last values it has.",
    ),
    "unavailable": (
        "Not available",
        "A source could not be read, for example a cplat command timed out. The rest of the page still works; Retry now reads "
        "it again, and /platform:doctor finds the cause.",
    ),
    "missing_piece": (
        "Missing piece",
        "An action needs something that is not set up: Claude Code, a GitHub login or a kube context. The banner names the "
        "fix; /platform:doctor checks everything.",
    ),
    # ---- autonomy
    "autonomy_level": (
        "Autonomy level",
        "What an engine may do on its own in an environment. "
        + " ".join(f"{level}: {may}." for level, may in _LEVEL_MAY.items())
        + " A higher level takes effect after its pull request is merged.",
    ),
    "guardrails": (
        "Guardrails",
        "The limits an engine stays within to act on its own: what it may merge and up to which criticality, how large a change "
        "may be, whether a regression test and a second review are needed, runs and merges per day, and a time window.",
    ),
    "engine": (
        "Engine",
        "The process that acts on signals for an environment. Its state is ok, unreachable or none; an environment whose engine "
        "does not answer is marked not supervised.",
    ),
    "pause": ("Pause", "Stops every engine from acting at once. It is the one autonomy change that does not wait for a merge."),
}

SECTIONS = (
    ("decisions", "Your decisions", "The Inbox lists what only you can decide. Each kind:",
     ("decision", "answer", "approve", "escalation", "promote", "triage", "review", "waiting")),
    ("board", "Items and their state", "The Board shows every open item in its stage; the colour of a card is its state.",
     ("stage", "decision_stage", "spec", "run", "slice", "running", "stopped", "waits", "not_started", "budget", "done_view")),
    ("where", "The system and where it runs", "System shows the system as a tree: its components, libraries, resources and "
     "APIs, each a row; a component or resource has a cell per environment with the running version and its state.",
     ("version", "pinned", "healthy", "verified", "not_verified", "alert", "unknown", "not_deployed", "promote_rule", "policy",
      "release_candidate", "model")),
    ("actions", "Actions and the data", "The console only reads; every change is a slash command that ends in a pull request.",
     ("command", "way_back", "actions", "read_at", "stale", "unavailable", "missing_piece")),
    ("autonomy", "Autonomy", "Optional and off by default: every environment observes until system.yaml declares more.",
     ("autonomy_level", "guardrails", "engine", "pause")),
)


def text(key: str) -> tuple[str, str]:
    """(title, text) of a term; an unknown key raises KeyError, so a page cannot link a term the glossary lacks."""
    return TERMS[key]


def tip(key: str, align: str = "") -> str:
    """A `?` next to a term. `align` is `left` (the text opens to the left, for terms near the right edge) or `right`."""
    title, body = TERMS[key]
    cls = f"tip {align}".strip()
    return (f'<span class="{cls}" data-tip="{esc(key)}"><button type="button" class="tip-btn" aria-label="What is {esc(title)}?">'
            f'?</button><span class="tip-body" role="tooltip"><strong>{esc(title)}</strong> {esc(body)} '
            f'<a href="/help#t-{esc(key)}">More</a></span></span>')


def legend(keys: tuple[str, ...] | list[str], label: str, swatch: str = "tone") -> str:
    """A row of terms with their tips. `swatch` is `tone` (a Board card colour) or `state` (an instance state pill)."""
    tones = {"running": "running", "stopped": "stopped", "waits": "decide", "not_started": "idle"}
    items = []
    for key in keys:
        title = TERMS[key][0]
        if swatch == "tone":
            mark = f'<span class="pill" data-tone="{tones.get(key, "idle")}">{esc(title)}</span>'
        else:
            cls = "ok" if key in {"healthy", "verified"} else "failed" if key in {"not_verified", "alert"} else "muted"
            mark = (f'<span class="muted absent">{esc(title)}</span>' if key == "not_deployed"
                    else f'<span class="pill {cls}">{esc(title)}</span>')
        items.append(f"<li>{mark}{tip(key)}</li>")
    return f'<ul class="legend" aria-label="{esc(label)}">{"".join(items)}</ul>'


# ---------------- the page ----------------

def _process() -> str:
    steps = []
    for name in stages.STAGES:
        e = stages.explain(name)
        who = ", ".join(e["agents"]) if e["agents"] else ""
        agents = f'<span class="muted step-who">{esc(who)}</span>' if who else ""
        decide = f'<span class="step-decide"><strong>You decide:</strong> {esc(e["decision"])}</span>' if e["decision"] else ""
        steps.append(f'<li{" data-decision" if e["decision"] else ""}>{stage_badge(name)}<span>{esc(e["what"])}</span>'
                     f'{agents}{decide}</li>')
    return f'<ol class="steps">{"".join(steps)}</ol>'


def page(ctx: Any, query: dict[str, str]) -> str:
    """How it works: the eight stages, then every term grouped by topic, each with an anchor `t-<key>`."""
    toc = '<a href="#process">The process</a>' + "".join(f'<a href="#{sid}">{esc(title)}</a>' for sid, title, _, _ in SECTIONS)
    sections = []
    for sid, title, intro, keys in SECTIONS:
        terms = "".join(f'<div id="t-{esc(k)}"><dt>{esc(TERMS[k][0])}</dt><dd>{esc(TERMS[k][1])}</dd></div>' for k in keys)
        sections.append(f'<section class="sheet" id="{sid}"><h2>{esc(title)}</h2><p class="muted">{esc(intro)}</p>'
                        f'<dl class="glossary">{terms}</dl></section>')
    body = (
        '<p class="lede">The console shows one system: what needs your decision, where every change is, and what runs where. '
        'It proposes and runs; you decide at three stages. Look for the <span class="tip demo"><span class="tip-btn">?</span>'
        '</span> next to a term anywhere in the console for a short explanation.</p>'
        f'<nav class="toc" aria-label="On this page">{toc}</nav>'
        '<section class="sheet" id="process"><h2>The process</h2><p class="muted">A change goes from an idea to prod through '
        'eight stages. The highlighted ones wait for you; the rest runs in Claude Code and CI and stops to ask when a rule '
        f'needs a person.</p>{_process()}</section>'
        + "".join(sections)
        + '<p class="muted">The keys, the sources and every command are in the <a href="/guide">guide</a> '
        '(<kbd>g</kbd>); the help of each page is under <kbd>?</kbd>.</p>'
    )
    from console import layout  # noqa: PLC0415 - layout uses the tips of this module

    return layout.page("How it works", "system", body, state=ctx.state())
