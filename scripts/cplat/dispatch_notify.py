"""Spec 167: the dispatcher's inbox, its needs file, its notification pass and its daily digest (design.md "Needs",
"Notifications and digest").

  stuck_need(slug, unit, cause)        the `stuck` item of a unit that ended twice without finishing
  write_needs(slug, items, issues)     `needs.json`: today's `budget` item and the `stuck` items still open
  inbox(repo) -> doc                   `cplat needs` in repo scope, only the six kinds the dispatcher cares about
  notify_pass(repo, slug, doc)         instant notifications for those kinds (`notify.process`) and the daily digest
  digest(slug, cfg, state, doc, when)  Delivered, Escalated, Held, Queue and Tokens since the last digest

Only `approve`, `answer`, `escalation`, `triage`, `budget` and `stuck` are ever notified: a unit that starts, lands or ends well
is no event. A repo linked to a system (`.platform-app.yml`) leaves the first four to the console notifier of the system.
"""
from __future__ import annotations

import datetime as dt
import functools
from pathlib import Path

import dispatch_state as ds
import needs
import notify
import notify_config

KINDS = ("approve", "answer", "escalation", "triage", "budget", "stuck")
SYSTEM_KINDS = ("budget", "stuck")           # the kinds left to the dispatcher when the repo belongs to a system
APP_FILE = ".platform-app.yml"
NEEDS_DECISION = "needs-decision"


# ---------------- the needs file ----------------

def stuck_need(slug: str, unit: dict, cause: str = "environment") -> dict:
    """The `stuck` item of `unit` (its unit file): the command that lets the dispatcher try the item again."""
    key = unit.get("key") or ds.unit_key(unit["unit"])
    issue = int(key.split("-", 1)[1]) if key.startswith("issue-") else None
    spec = None if issue else (unit.get("item") or key)
    log = unit.get("log") or ""
    return {"id": f"stuck:{slug}:{unit['unit']}", "kind": "stuck", "stage": "Build",
            "object": {"type": "run", "repo": slug, "spec": spec, "run_id": unit.get("run_id"), "issue": issue, "log": log,
                       "component": None, "version": None, "pr": None, "url": None},
            "since": unit.get("ended_at") or ds.now().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason": f"unit {unit['unit']} ended twice without finishing (cause {cause}); log: {log}",
            "command": f"gh issue edit {issue} --remove-label {NEEDS_DECISION}" if issue else f"cplat dispatch resume {spec}",
            "cwd_repo": slug, "consequence": {"log": log, "starts": int(unit.get("starts") or 2)}, "way_back": None}


def _stuck_open(slug: str, item: dict, issues: list[dict] | None, holds: dict) -> bool:
    """A stuck need stays while its item still carries `needs-decision` (an issue) or is still held (a spec)."""
    obj = item.get("object") or {}
    if obj.get("issue"):
        if issues is None:
            return True                                  # the issues could not be read: keep what is there
        for i in issues:
            if i.get("number") == obj["issue"]:
                return NEEDS_DECISION in {(lb.get("name") if isinstance(lb, dict) else lb) for lb in i.get("labels") or []}
        return False                                     # closed or gone
    unit = item["id"].split(":", 2)[-1]
    return ds.unit_key(unit) in holds or (obj.get("spec") or "") in holds


def write_needs(slug: str, items: list[dict], issues: list[dict] | None = None) -> list[dict]:
    """Write the repo's `needs.json` (`{"items": [...]}`) and return the items.

    `items` are what the cycle found now: today's `budget` item (when the limit is reached) and new `stuck` items. The `stuck`
    items already in the file stay while they are open (`issues` is the snapshot's open issues; None = unknown, keep them); a
    `budget` item of an earlier day, or one the cycle no longer reports, is resolved and dropped."""
    given = {i["id"]: i for i in items}
    old = ds.read_json(ds.needs_path(slug)) or {}
    holds = ds.load(slug)["steering"].get("holds") or {}
    kept = [i for i in old.get("items") or []
            if isinstance(i, dict) and i.get("kind") == "stuck" and i.get("id") not in given
            and _stuck_open(slug, i, issues, holds)]
    out = sorted([*kept, *given.values()], key=lambda i: i.get("since") or "")
    if out or old:
        ds.write_json(ds.needs_path(slug), {"items": out})
    return out


# ---------------- the inbox ----------------

def inbox(repo: Path) -> dict:
    """The needs document of the repo (`cplat needs` in repo scope) limited to the six kinds."""
    doc = needs.collect_repo(Path(repo))
    doc["items"] = [i for i in doc.get("items") or [] if i.get("kind") in KINDS]
    return doc


# ---------------- the notification pass ----------------

def notify_kinds(repo: Path) -> tuple[str, ...]:
    return SYSTEM_KINDS if (Path(repo) / APP_FILE).is_file() else KINDS


def notify_path(slug: str) -> Path:
    return notify.state_path(f"dispatch-{ds.slug_dir(slug)}")


def notify_pass(repo: Path, slug: str, doc: dict | None = None) -> None:
    """Instant notifications for the new items of `doc` (the inbox; read when None), quiet hours kept, and the daily digest."""
    cfg = notify_config.load()
    doc = doc if doc is not None else inbox(repo)
    notify.process(cfg, {"needs": doc}, notify_path(slug), kinds=notify_kinds(repo), digest=functools.partial(digest, slug))


# ---------------- the digest ----------------

def _after(when: str | None, last: dt.datetime | None) -> bool:
    at = notify._parse(when)
    return last is None or (at is not None and at > last)


def _totals(ledger: dict) -> dict[str, int]:
    return {day: sum(int(v or 0) for v in (rec.get("units") or {}).values()) + int(rec.get("agent") or 0)
            for day, rec in ledger.items() if isinstance(rec, dict)}


def _sections(st: dict, last: dt.datetime | None, seen: dict) -> tuple[dict[str, list[str]], int]:
    history = [h for h in st.get("history") or [] if _after(h.get("ended_at"), last)]
    delivered = [f"{h.get('unit')} {h.get('item')}" + (f" {h['pr']}" if h.get("pr") else "")
                 for h in history if h.get("outcome") == "done"]
    escalated = [f"{h.get('unit')} {h.get('item')}: {h.get('reason') or h.get('outcome')}"
                 for h in history if h.get("outcome") in ("escalated", "stuck")]
    escalated += [f"{e.get('unit')} {e.get('item')}: {e.get('reason') or e.get('kind')}"
                  for e in st.get("events") or []
                  if e.get("kind") == "stuck" and _after(e.get("at"), last)
                  and not any(h.get("unit") == e.get("unit") and h.get("outcome") in ("escalated", "stuck") for h in history)]
    cycle = st.get("last_cycle") or {}
    held = [f"{h.get('item')}: {h.get('reason')}" + (f" ({h['detail']})" if h.get("detail") else "") for h in cycle.get("held") or []]
    queue = [f"{q.get('item')} ({q.get('kind')}, {q.get('mode')})" for q in cycle.get("queue") or []]
    booked = sum(max(0, total - int(seen.get(day) or 0)) for day, total in _totals(st.get("ledger") or {}).items())
    tokens = max(booked, sum(int(h.get("tokens") or 0) for h in history))      # the history covers units the ledger lost (pruned)
    return {"Delivered": delivered, "Escalated": escalated, "Held": held, "Queue": queue}, tokens


def digest_text(slug: str, last: dt.datetime | None, seen: dict | None = None) -> tuple[str | None, dict[str, int]]:
    """(the digest body, the ledger totals it covers); the body is None when every section is empty and no tokens were used."""
    totals = _totals(ds.load(slug)["ledger"])
    sections, tokens = _sections(ds.load(slug), last, seen or {})
    if not tokens and not any(sections.values()):
        return None, totals
    lines: list[str] = []
    for head, entries in sections.items():
        if entries:
            lines += [f"{head}:", *[f"- {e}" for e in entries]]
    lines.append(f"Tokens: {tokens:,}")
    return "\n".join(lines), totals


def digest(slug: str, cfg: notify_config.Config, state: dict, doc: dict, when: dt.datetime) -> None:
    """Send the daily digest on every digest channel (slack, email); sets `last_digest` when one went out."""
    body, totals = digest_text(slug, notify._parse(state.get("last_digest")), state.get("ledger_seen"))
    if body is None:
        return
    sent = False
    for channel in notify_config.digest_channels(cfg):
        try:
            if channel == "slack":
                sent = notify._slack(cfg, f"*Digest {slug}*\n{body}") or sent
            elif cfg.email.get("host") and cfg.email.get("to") and cfg.email.get("from"):
                notify.send_mail(cfg, f"[sdlc-foundry] digest {slug}", body + "\n")
                sent = True
        except Exception as e:  # noqa: BLE001
            notify._log(f"digest on {channel} failed: {e}")
    if sent:
        state["last_digest"] = notify._iso(when)
        state["ledger_seen"] = totals


__all__ = ["KINDS", "digest", "digest_text", "inbox", "notify_kinds", "notify_pass", "stuck_need", "write_needs"]
