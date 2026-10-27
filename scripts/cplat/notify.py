"""`cplat ui notify [--once | --loop] [--repo-dir DIR]`: the local notifier of the console (spec 122, AC-122.2, AC-122.23 - AC-122.26).

It turns events (needs items, open alert/smoke/retro issues, runs newly done) into one notification per `instant` channel,
resolves them everywhere when the event leaves its source, holds them during quiet hours and sends the digest.
State: `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/notify/<system>.json`. Traffic goes only to `gh`, the configured Slack
webhooks and the configured SMTP host. The clock, `gh`, HTTP, SMTP and the desktop are module-level functions the tests replace.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

import notify_config
from core import PlatformError, run

INTERVAL = 60
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
REVIEW_REQUEST = ("approve", "answer")           # GitHub already asks for a review
ASSIGN = ("alert", "smoke", "retro")             # GitHub: assign the user to the existing issue
ISSUE_LABELS = {"alert": "alert", "smoke-failure": "smoke"}
HELD = "held"


# ---------------- replaceable seams ----------------

def now() -> dt.datetime:
    """The local wall clock (tests replace this)."""
    return dt.datetime.now()


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


def http_post(url: str, payload: dict) -> None:
    """POST JSON to a Slack webhook (tests replace this)."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - the URL is the user's own webhook
        resp.read()


def send_mail(cfg: notify_config.Config, subject: str, body: str) -> None:
    """Send one e-mail over SMTP with STARTTLS (tests replace this)."""
    mail = cfg.email
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, mail["from"], mail["to"]
    msg.set_content(body)
    with smtplib.SMTP(mail["host"], int(mail.get("port") or 587), timeout=20) as smtp:
        if mail.get("starttls", True):
            smtp.starttls()
        password = notify_config.secret("CPLAT_SMTP_PASSWORD", notify_config.smtp_account(mail))
        if mail.get("user") and password:
            smtp.login(mail["user"], password)
        smtp.send_message(msg)


def desktop_send(title: str, text: str) -> str:
    """Show a desktop notification; the returned reference is what `desktop_withdraw` needs (tests replace this)."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
        subprocess.run(["osascript", "-e", script, title, text], check=False, capture_output=True, timeout=10)  # noqa: S603, S607
        return ""
    if shutil.which("notify-send"):
        p = subprocess.run(["notify-send", "-p", title, text], check=False, capture_output=True, text=True, timeout=10)  # noqa: S603, S607
        return p.stdout.strip()
    return ""


def desktop_withdraw(ref: str) -> None:
    """Withdraw a desktop notification where the OS allows it (Linux only; macOS cannot) (tests replace this)."""
    if not ref or not sys.platform.startswith("linux") or not shutil.which("gdbus"):
        return
    subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",  # noqa: S603, S607
                    "--object-path", "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.CloseNotification",
                    ref], check=False, capture_output=True, timeout=10)


# ---------------- collecting ----------------

def _label_names(issue: dict) -> set[str]:
    return {(x.get("name") if isinstance(x, dict) else x) for x in issue.get("labels") or []}


def collect(repo_dir: Path) -> dict:
    """{"needs", "runs", "issues", "shipped", "issues_failed"} read from the system's sources (tests replace this)."""
    import model
    import needs
    import runlist
    needs_doc = needs.collect(Path(repo_dir))
    try:
        rows = runlist.collect(30)["runs"]
    except Exception:  # noqa: BLE001
        rows = []
    runs_doc = {"schema": 1, "runs": rows}
    m = model.load_dir(needs.find_system(Path(repo_dir), None))
    _, repos = needs._repos(Path(repo_dir), m)
    issues: list[dict] = []
    failed = False
    from autoissue import DEFAULT_REPO
    for slug, labels in [(r, list(ISSUE_LABELS)) for r in repos] + [(DEFAULT_REPO, ["retro"])]:
        for label in labels:
            try:
                found = json.loads(gh(["issue", "list", "-R", slug, "--state", "open", "--label", label,
                                       "--json", "number,title,labels,createdAt"]) or "[]")
            except Exception:  # noqa: BLE001
                failed = True
                continue
            issues += [{**i, "repo": slug} for i in found]
    shipped = [{"what": f"{r.get('spec') or r['run_id']} shipped", "at": r.get("ended_at")} for r in rows if r.get("phase") == "done"]
    return {"needs": needs_doc, "runs": runs_doc, "issues": issues, "shipped": shipped, "issues_failed": failed}


def events_of(doc: dict) -> dict[str, dict]:
    """key -> event: `event`, `title`, `text`, `repo`, `number`, `prod`, `spec`."""
    out: dict[str, dict] = {}
    for it in (doc.get("needs") or {}).get("items") or []:
        if it.get("kind") not in ("approve", "answer", "escalation", "promote"):
            continue
        obj = it.get("object") or {}
        what = obj.get("spec") or obj.get("version") or obj.get("run_id") or ""
        out[it["id"]] = {"event": it["kind"], "title": f"{it['kind']}: {what}", "text": it.get("reason") or "",
                         "repo": obj.get("repo") or it.get("cwd_repo"), "number": None, "prod": False, "spec": what}
    for i in doc.get("issues") or []:
        names = _label_names(i)
        event = next((ev for label, ev in {**ISSUE_LABELS, "retro": "retro"}.items() if label in names), None)
        if event is None:
            continue
        key = f"{event}:{i['repo']}#{i['number']}"
        out[key] = {"event": event, "title": f"{event}: {i.get('title') or ''}".strip(), "text": f"{i['repo']}#{i['number']}",
                    "repo": i["repo"], "number": i["number"], "prod": "env:prod" in names, "spec": i.get("title") or ""}
    for r in (doc.get("runs") or {}).get("runs") or []:
        if r.get("phase") == "done":
            what = r.get("spec") or r["run_id"]
            out[f"run-done:{r['run_id']}"] = {"event": "run-done", "title": f"run done: {what}", "text": r.get("outcome") or "",
                                              "repo": r.get("repo"), "number": None, "prod": False, "spec": what}
    return out


# ---------------- state ----------------

def state_path(system: str) -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "sdlc-foundry" / "notify" / f"{system}.json"


def load_state(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def _iso(when: dt.datetime) -> str:
    return when.isoformat(timespec="seconds")


def _parse(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when.astimezone().replace(tzinfo=None) if when.tzinfo else when


# ---------------- quiet hours and digest timing ----------------

def in_quiet_hours(cfg: notify_config.Config, when: dt.datetime) -> bool:
    if not cfg.quiet_hours:
        return False
    start, end = (dt.time.fromisoformat(p) for p in cfg.quiet_hours.split("-"))
    t = when.time()
    return start <= t < end if start <= end else (t >= start or t < end)


def digest_due(cfg: notify_config.Config, state: dict, when: dt.datetime) -> bool:
    if DAYS[when.weekday()] not in cfg.digest["days"] or when.time() < dt.time.fromisoformat(cfg.digest["at"]):
        return False
    last = _parse(state.get("last_digest"))
    return last is None or last.date() < when.date()


# ---------------- channels ----------------

def _signature(key: str) -> str:
    return "Signature: notify:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _send_github(key: str, ev: dict) -> str | None:
    """Returns the reference to resolve later, or None when there is nothing to send."""
    if ev["event"] in REVIEW_REQUEST:
        return "review-request"
    if ev["event"] in ASSIGN:
        if ev["number"] is None:
            return None
        gh(["issue", "edit", str(ev["number"]), "-R", ev["repo"], "--add-assignee", "@me"])
        return f"assign:{ev['repo']}#{ev['number']}"
    if not ev["repo"]:
        return None
    try:
        gh(["api", f"repos/{ev['repo']}/labels", "-f", "name=notify"])
    except PlatformError:
        pass                                        # exists already
    body = f"{ev['text']}\n\n{_signature(key)}\n"
    return gh(["issue", "create", "-R", ev["repo"], "--title", ev["title"], "--body", body, "--label", "notify",
               "--assignee", "@me"]).strip().splitlines()[-1]


def _slack(cfg: notify_config.Config, text: str) -> bool:
    sent = False
    for ch in cfg.slack_channels:
        url = notify_config.secret(notify_config.slack_env_name(ch), notify_config.slack_account(ch))
        if url:
            http_post(url, {"text": text})
            sent = True
    return sent


def _deliver(cfg: notify_config.Config, channel: str, key: str, ev: dict) -> str | None:
    if channel == "github":
        return _send_github(key, ev)
    if channel == "slack":
        return "slack" if _slack(cfg, f"*{ev['title']}*\n{ev['text']}") else None
    if channel == "email":
        if not (cfg.email.get("host") and cfg.email.get("to") and cfg.email.get("from")):
            return None
        send_mail(cfg, f"[sdlc-foundry] {ev['title']}", f"{ev['title']}\n\n{ev['text']}\n")
        return "email"
    return desktop_send(ev["title"], ev["text"]) or "desktop"


def _log(msg: str) -> None:
    print(json.dumps({"level": "warning", "component": "notify", "message": msg}), file=sys.stderr)


def _resolve(rec: dict, when: dt.datetime) -> None:
    for channel, sent in (rec.get("sent") or {}).items():
        ref = sent.get("ref") or ""
        try:
            if channel == "github" and ref.startswith("http"):
                gh(["issue", "close", ref])
            elif channel == "github" and ref.startswith("assign:"):
                repo, number = ref[len("assign:"):].rsplit("#", 1)
                gh(["issue", "edit", number, "-R", repo, "--remove-assignee", "@me"])
            elif channel == "desktop" and ref != HELD:
                desktop_withdraw("" if ref == "desktop" else ref)
        except Exception as e:  # noqa: BLE001
            _log(f"could not resolve {channel} notification {ref}: {e}")
    rec["resolved_at"] = _iso(when)


# ---------------- digest ----------------

def _digest_lines(cfg: notify_config.Config, state: dict, channel: str, doc: dict, last: dt.datetime | None) -> list[str] | None:
    """Sections of the digest for one channel, or None when the channel takes part in no digest."""
    open_, done = [], []
    takes_part = any(cells[channel] == "digest" for cells in cfg.events.values())
    for key, rec in state["events"].items():
        value = cfg.events.get(rec.get("event"), {}).get(channel, "off")
        sent = (rec.get("sent") or {}).get(channel)
        held = bool(sent and sent.get("ref") == HELD)
        if held:
            takes_part = True
        if value != "digest" and not held and not sent:
            continue
        if rec.get("resolved_at"):
            when = _parse(rec["resolved_at"])
            if last is None or (when and when > last):
                done.append(rec.get("title") or key)
        elif value == "digest" or held:
            open_.append(rec.get("title") or key)
    if not takes_part:
        return None
    shipped = [s["what"] for s in doc.get("shipped") or [] if not (last and _parse(s.get("at")) and _parse(s.get("at")) <= last)]
    lines: list[str] = []
    for head, items in (("Open", open_), ("Done", done), ("Shipped", shipped)):
        if items:
            lines += [f"{head}:", *[f"- {i}" for i in items]]
    return lines or None


def _send_digest(cfg: notify_config.Config, state: dict, doc: dict, when: dt.datetime) -> None:
    last = _parse(state.get("last_digest"))
    sent = False
    for channel in ("slack", "email"):
        lines = _digest_lines(cfg, state, channel, doc, last)
        if not lines:
            continue
        text = "\n".join(lines)
        try:
            if channel == "slack":
                sent = _slack(cfg, f"*Digest*\n{text}") or sent
            elif cfg.email.get("host") and cfg.email.get("to") and cfg.email.get("from"):
                send_mail(cfg, "[sdlc-foundry] digest", text + "\n")
                sent = True
        except Exception as e:  # noqa: BLE001
            _log(f"digest on {channel} failed: {e}")
    if sent:
        state["last_digest"] = _iso(when)


# ---------------- the loop body ----------------

def run_once(repo_dir: Path) -> None:
    """One pass: detect events, send instant notifications, resolve gone events, send the digest when due."""
    cfg = notify_config.load()
    doc = collect(Path(repo_dir))
    when = now()
    path = state_path((doc.get("needs") or {}).get("system") or "system")
    state = load_state(path)
    fresh = state is None
    state = state or {"events": {}, "last_digest": None}
    state.setdefault("events", {})
    current = events_of(doc)
    hidden = {k for u in (doc.get("needs") or {}).get("unavailable") or [] for k in u.get("kinds") or []}
    quiet = in_quiet_hours(cfg, when)
    for key, ev in current.items():
        rec = state["events"].get(key)
        if rec is None:
            rec = state["events"][key] = {"first_seen": _iso(when), "sent": {}, "resolved_at": None,
                                          "event": ev["event"], "title": ev["title"]}
            if fresh and ev["event"] == "run-done":
                rec["resolved_at"] = _iso(when)     # baseline: runs finished before the notifier started are not news
        if rec.get("resolved_at") and key in current and ev["event"] != "run-done":
            rec["resolved_at"] = None               # came back
        if rec.get("resolved_at"):
            continue
        for channel, value in cfg.events[ev["event"]].items():
            if value != "instant" or channel in rec["sent"]:
                continue
            if quiet and not (ev["event"] == "alert" and ev["prod"]):
                rec["sent"][channel] = {"at": _iso(when), "ref": HELD}
                continue
            try:
                ref = _deliver(cfg, channel, key, ev)
            except Exception as e:  # noqa: BLE001
                _log(f"{channel} notification for {key} failed: {e}")
                continue
            if ref is not None:
                rec["sent"][channel] = {"at": _iso(when), "ref": ref}
    for key, rec in state["events"].items():
        if key in current or rec.get("resolved_at") or rec.get("event") in hidden:
            continue
        if rec.get("event") in ("alert", "smoke", "retro") and doc.get("issues_failed"):
            continue
        _resolve(rec, when)
    if not quiet and digest_due(cfg, state, when):
        _send_digest(cfg, state, doc, when)
    save_state(path, state)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat ui notify", description="Send notifications and digests for a system (spec 122).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="one pass, then exit (default)")
    mode.add_argument("--loop", action="store_true", help=f"repeat every {INTERVAL} seconds")
    p.add_argument("--repo-dir", default=".", metavar="DIR", help="a gitops-app clone (default .)")
    return p


def main(argv: list[str]) -> int:
    try:
        ns = build_parser().parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    repo = Path(ns.repo_dir)
    if not ns.loop:
        run_once(repo)
        return 0
    while True:
        try:
            run_once(repo)
        except (PlatformError, OSError, ValueError, re.error) as e:
            _log(str(e))
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
