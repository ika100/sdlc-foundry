"""`notify.yaml`: which event reaches which channel, the Recommended preset, secret lookup and the doctor checks (spec 122, AC-122.22, AC-122.27).

The file is `${XDG_CONFIG_HOME:-~/.config}/sdlc-foundry/notify.yaml`. Webhook URLs and SMTP passwords are never read from it:
they come from the environment or the OS keychain (`secret`).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core import PlatformError

EVENTS = ("approve", "answer", "escalation", "promote", "alert", "smoke", "run-done", "retro", "review", "signal", "done-on-its-own")
CHANNELS = ("github", "slack", "email", "desktop")
VALUES = ("off", "instant", "digest")
DIGEST_CHANNELS = ("slack", "email")
FORBIDDEN = ("webhook", "url", "password", "token")
TOP_KEYS = ("preset", "events", "slack", "email", "digest", "quiet_hours")
EMAIL_KEYS = ("to", "from", "host", "port", "user", "starttls")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
KEYCHAIN_SERVICE = "sdlc-foundry"
GITHUB_INSTANT = ("approve", "answer", "escalation", "alert", "smoke", "review", "signal")
DESKTOP_INSTANT = ("approve", "answer", "escalation", "promote", "alert", "smoke", "review", "signal", "done-on-its-own")
HINT = "see docs/console.md (notifications)"


@dataclass
class Config:
    events: dict[str, dict[str, str]]
    slack_channels: list[str] = field(default_factory=list)
    email: dict = field(default_factory=dict)
    digest: dict = field(default_factory=lambda: {"at": "09:00", "days": ["mon", "tue", "wed", "thu", "fri"]})
    quiet_hours: str | None = None


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sdlc-foundry" / "notify.yaml"


def recommended() -> dict[str, dict[str, str]]:
    """The preset that works with no setup (design.md, notify.yaml)."""
    return {e: {"github": "instant" if e in GITHUB_INSTANT else "off", "slack": "off", "email": "off",
                "desktop": "instant" if e in DESKTOP_INSTANT else "off"} for e in EVENTS}


def _bad(key: str, why: str) -> PlatformError:
    return PlatformError(f"notify.yaml: {key}: {why}", HINT)


def _refuse_secrets(node, where: str = "") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).lower() in FORBIDDEN:
                raise _bad(f"{where}{k}", "secrets do not belong in this file; use the environment or the OS keychain")
            _refuse_secrets(v, f"{where}{k}.")
    elif isinstance(node, list):
        for v in node:
            _refuse_secrets(v, where)


def _mapping(node, key: str) -> dict:
    if node is None:
        return {}
    if not isinstance(node, dict):
        raise _bad(key, "must be a mapping")
    return node


def _apply_events(events: dict, node) -> None:
    for event, cells in _mapping(node, "events").items():
        if event not in EVENTS:
            raise _bad(f"events.{event}", f"unknown event (one of {', '.join(EVENTS)})")
        for channel, value in _mapping(cells, f"events.{event}").items():
            key = f"events.{event}.{channel}"
            if channel not in CHANNELS:
                raise _bad(key, f"unknown channel (one of {', '.join(CHANNELS)}; the console is always on)")
            if value not in VALUES:
                raise _bad(key, f"unknown value {value!r} (one of {', '.join(VALUES)})")
            if value == "digest" and channel not in DIGEST_CHANNELS:
                raise _bad(key, "'digest' is only for slack and email")
            events[event][channel] = value


def _digest(node) -> dict:
    out = {"at": "09:00", "days": ["mon", "tue", "wed", "thu", "fri"]}
    for k, v in _mapping(node, "digest").items():
        if k == "at":
            if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
                raise _bad("digest.at", f"{v!r} is not HH:MM")
            out["at"] = v
        elif k == "days":
            if not isinstance(v, list) or not v or any(d not in DAYS for d in v):
                raise _bad("digest.days", f"must be a list of {', '.join(DAYS)}")
            out["days"] = list(v)
        else:
            raise _bad(f"digest.{k}", "unknown key (at, days)")
    return out


def load(path: Path | str | None = None) -> Config:
    """Read `notify.yaml` over the Recommended preset; an unknown or secret key is a PlatformError naming it."""
    p = Path(path) if path else default_path()
    cfg = Config(events=recommended())
    if not p.is_file():
        return cfg
    try:
        doc = yaml.safe_load(p.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise PlatformError(f"notify.yaml: cannot read {p}: {e}", HINT) from e
    doc = _mapping(doc, "(top level)")
    _refuse_secrets(doc)
    for k in doc:
        if k not in TOP_KEYS:
            raise _bad(str(k), f"unknown key (one of {', '.join(TOP_KEYS)})")
    if doc.get("preset", "recommended") != "recommended":
        raise _bad("preset", f"unknown preset {doc['preset']!r} (recommended)")
    _apply_events(cfg.events, doc.get("events"))
    slack = _mapping(doc.get("slack"), "slack")
    for k in slack:
        if k != "channels":
            raise _bad(f"slack.{k}", "unknown key (channels)")
    channels = slack.get("channels") or []
    if not isinstance(channels, list) or not all(isinstance(c, str) for c in channels):
        raise _bad("slack.channels", "must be a list of channel names")
    cfg.slack_channels = list(channels)
    email = _mapping(doc.get("email"), "email")
    for k in email:
        if k not in EMAIL_KEYS:
            raise _bad(f"email.{k}", f"unknown key (one of {', '.join(EMAIL_KEYS)})")
    cfg.email = dict(email)
    cfg.digest = _digest(doc.get("digest"))
    qh = doc.get("quiet_hours")
    if qh is not None and not (isinstance(qh, str) and re.fullmatch(r"\d\d:\d\d-\d\d:\d\d", qh)):
        raise _bad("quiet_hours", f"{qh!r} is not HH:MM-HH:MM")
    cfg.quiet_hours = qh
    return cfg


def slack_env_name(channel: str) -> str:
    """`#shop-dev` -> `CPLAT_SLACK_WEBHOOK_SHOP_DEV`."""
    return "CPLAT_SLACK_WEBHOOK_" + re.sub(r"[^A-Za-z0-9]+", "_", channel.lstrip("#")).strip("_").upper()


def slack_account(channel: str) -> str:
    return f"slack-webhook:{channel}"


def smtp_account(email: dict) -> str:
    return f"smtp:{email.get('user', '')}@{email.get('host', '')}"


def secret(name: str, account: str | None = None) -> str | None:
    """The environment variable `name`, else the keychain item (service `sdlc-foundry`, `account`); None when neither has it."""
    value = os.environ.get(name)
    if value:
        return value
    if not account:
        return None
    if sys.platform == "darwin":
        argv = ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"]
    elif sys.platform.startswith("linux"):
        argv = ["secret-tool", "lookup", "service", KEYCHAIN_SERVICE, "account", account]
    else:
        return None
    exe = shutil.which(argv[0])
    if not exe:
        return None
    try:
        p = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or "").strip()
    return out if p.returncode == 0 and out else None


def used_channels(cfg: Config) -> set[str]:
    """Channels set to `instant` or `digest` for at least one event."""
    return {c for cells in cfg.events.values() for c, v in cells.items() if v != "off"}


def doctor_checks() -> list[dict]:
    """One `warn` per channel in use whose webhook, address, host or password is missing (AC-122.27)."""
    from doctor import WARN, check
    try:
        cfg = load()
    except PlatformError as e:
        return [check(WARN, "notify.yaml", str(e), f"fix {default_path()}")]
    used = used_channels(cfg)
    out = []
    if "slack" in used:
        if not cfg.slack_channels:
            out.append(check(WARN, "notify:slack", "slack is in use but notify.yaml lists no slack.channels",
                             f"add slack: {{channels: [\"#channel\"]}} to {default_path()}"))
        for ch in cfg.slack_channels:
            env = slack_env_name(ch)
            if not secret(env, slack_account(ch)):
                out.append(check(WARN, "notify:slack", f"no webhook for {ch}",
                                 f"export {env}=<incoming webhook URL> (or keychain item {KEYCHAIN_SERVICE} / {slack_account(ch)})"))
    if "email" in used:
        for key in ("to", "from", "host"):
            if not cfg.email.get(key):
                out.append(check(WARN, "notify:email", f"email.{key} is missing", f"set email.{key} in {default_path()}"))
        if cfg.email.get("user") and cfg.email.get("host") and not secret("CPLAT_SMTP_PASSWORD", smtp_account(cfg.email)):
            out.append(check(WARN, "notify:email", f"no SMTP password for {cfg.email['user']}@{cfg.email['host']}",
                             f"export CPLAT_SMTP_PASSWORD=<password> (or keychain item {KEYCHAIN_SERVICE} / {smtp_account(cfg.email)})"))
    return out
