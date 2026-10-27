"""The engine HTTP client: signals (pause, resume, lower), status and heartbeat (spec 124, AC-124.7, AC-124.9, AC-124.13, AC-124.21).

Contract: design.md "Engine HTTP" and contract.openapi.yaml. Every request carries `Authorization: Bearer <token>`; the token is
never logged or put in a result. `_http`, `monotonic` and `sleep` are the seams the tests replace.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

KINDS = ("pause", "resume", "lower")
LEVELS = ("observe", "advise", "propose", "act", "improve")
CONFIRM_SECONDS = 60
POST_TIMEOUT = 10
HEARTBEAT_MAX_AGE = 300
NO_TOKEN = "no engine token"

monotonic = time.monotonic
sleep = time.sleep


def _http(method: str, url: str, body: dict | None, token: str, timeout: float) -> tuple[int, dict]:
    """One request; returns (status, JSON document). Raises OSError when the engine cannot be reached."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 (https engine URL from system.yaml)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            code, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except ValueError as e:  # a malformed URL
        raise OSError(str(e)) from e
    try:
        doc = json.loads(raw.decode() or "{}")
    except ValueError:
        doc = {}
    return code, doc if isinstance(doc, dict) else {}


def token(url: str) -> str | None:
    """`CPLAT_ENGINE_TOKEN`, else the keychain item `engine:<host of url>`; None when neither has it."""
    import notify_config
    host = urllib.parse.urlsplit(url).hostname or ""
    return notify_config.secret("CPLAT_ENGINE_TOKEN", f"engine:{host}")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reason(code: int, doc: dict) -> str:
    text = str(doc.get("error") or f"engine answered {code}")
    if doc.get("detail"):
        text += f": {doc['detail']}"
    if doc.get("fields"):
        text += " (" + ", ".join(str(f) for f in doc["fields"]) + ")"
    return text


def send(targets: dict[str, str], kind: str, *, system: str, actor: str, policy_of: dict[str, dict] | None = None,
         pr: str | None = None) -> dict[str, dict]:
    """Send one signal to each environment's engine (`targets`: env -> URL); retry what cannot be reached for 60 s.

    Returns env -> {"signal", "confirmed", "effective", "reason"}. Only `pause`, `resume` and `lower` exist (a signal never raises
    autonomy); another kind raises ValueError before anything is sent. A 4xx answer is final.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown signal kind {kind!r}: only pause, resume and lower exist")
    deadline = monotonic() + CONFIRM_SECONDS
    result: dict[str, dict] = {}
    waiting: dict[str, dict] = {}
    for env, url in targets.items():
        sid = "sig-" + secrets.token_hex(6)
        result[env] = {"signal": sid, "confirmed": False, "effective": None, "reason": None}
        tok = token(url)
        if not tok:
            result[env]["reason"] = NO_TOKEN
            continue
        body = {"id": sid, "kind": kind, "system": system, "environment": env, "at": _now(), "actor": actor,
                "policy": (policy_of or {}).get(env), "pr": pr}
        waiting[env] = {"url": url.rstrip("/") + "/v1/signals", "token": tok, "body": body}
    delay = 1.0
    while waiting:
        for env in list(waiting):
            item = waiting[env]
            try:
                code, doc = _http("POST", item["url"], item["body"], item["token"], POST_TIMEOUT)
            except OSError as e:
                result[env]["reason"] = f"engine not reachable: {e}"
                continue
            if code >= 500:
                result[env]["reason"] = _reason(code, doc)
                continue
            del waiting[env]
            if code == 200 and doc.get("confirmed") is True:
                result[env].update(confirmed=True, effective=doc.get("effective"), reason=None)
            else:
                result[env]["effective"] = doc.get("effective")
                result[env]["reason"] = _reason(code, doc) if code != 200 else "the engine did not confirm"
        left = deadline - monotonic()
        if not waiting or left <= 0:
            break
        sleep(min(delay, left))
        delay = min(delay * 2, 10.0)
    for env in waiting:
        result[env]["reason"] = f"no confirmation within {CONFIRM_SECONDS} s: {result[env]['reason']}"
    return result


def _parse(stamp: object) -> dt.datetime | None:
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def state(status_doc: dict | None, now: dt.datetime | None = None) -> str:
    """`ok` when the heartbeat is at most 5 minutes old, else `unreachable`."""
    when = _parse((status_doc or {}).get("heartbeat_at"))
    if when is None:
        return "unreachable"
    age = ((now or dt.datetime.now(dt.timezone.utc)) - when).total_seconds()
    return "ok" if age <= HEARTBEAT_MAX_AGE else "unreachable"


def cache_path(system: str) -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "sdlc-foundry" / "autonomy" / f"{system}.json"


def last_heartbeat(url: str, system: str) -> str | None:
    """The last heartbeat seen from `url` for `system`, from the cache."""
    try:
        doc = json.loads(cache_path(system).read_text())
    except (OSError, ValueError):
        return None
    beats = doc.get("heartbeats") if isinstance(doc, dict) else None
    value = beats.get(url) if isinstance(beats, dict) else None
    return value if isinstance(value, str) else None


def _remember(url: str, system: str, heartbeat: str) -> None:
    path = cache_path(system)
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        doc = {}
    beats = doc.get("heartbeats") if isinstance(doc.get("heartbeats"), dict) else {}
    beats[url] = heartbeat
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**doc, "heartbeats": beats}, indent=2) + "\n")
    except OSError:
        pass


def status(url: str, system: str) -> dict | None:
    """`GET /v1/status?system=<system>`; the document, or None when the engine cannot be reached or answers badly. Never raises."""
    tok = token(url)
    if not tok:
        return None
    full = url.rstrip("/") + "/v1/status?" + urllib.parse.urlencode({"system": system})
    try:
        code, doc = _http("GET", full, None, tok, POST_TIMEOUT)
    except OSError:
        return None
    if code != 200 or not doc:
        return None
    if isinstance(doc.get("heartbeat_at"), str):
        _remember(url, system, doc["heartbeat_at"])
    return doc


def confirmed_later(pending: dict[str, Any], status_doc: dict | None, events: list[dict]) -> bool:
    """Whether a not confirmed signal counts as confirmed now: the engine lists its id, shows the requested state, or an event says so."""
    sid, kind, env = pending.get("signal"), pending.get("kind"), pending.get("environment")
    if any(e.get("kind") == "signal-honoured" and (e.get("object") or {}).get("signal") == sid for e in events):
        return True
    cur = ((status_doc or {}).get("environments") or {}).get(env)
    if not cur:
        return False
    if any(s.get("id") == sid for s in cur.get("signals") or []):
        return True
    if kind == "pause":
        return cur.get("paused") is True
    if kind == "resume":
        return cur.get("paused") is False
    if kind == "lower" and pending.get("level") in LEVELS and cur.get("effective") in LEVELS:
        return LEVELS.index(cur["effective"]) <= LEVELS.index(pending["level"])
    return False
