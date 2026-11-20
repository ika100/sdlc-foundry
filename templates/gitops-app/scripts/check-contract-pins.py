#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Compare the copy of the shared rules at each pinned commit with the plans' current contract (spec 110, AC-110.9).

For every component whose pin (`images[0].newTag` in applications/*/overlays/<env>/<component>/kustomization.yaml) changed
since `git merge-base BASE_REF HEAD`, the script reads `contract/<plan_id>.json` of the component repo at the pinned commit
through the GitHub REST API and compares it with the rules and the error contract of every plan in docs/plan/ that
assigns the component a rule.

Inputs (environment): BASE_REF (default origin/main), SERVICE_REPOS_READ_TOKEN, GITHUB_API_URL (default
https://api.github.com), GITHUB_STEP_SUMMARY (optional). Exit 0 = pass or nothing to check, 1 = an ERROR line was printed.
Every output line has the token value replaced by `***`.
"""
from __future__ import annotations

import base64
import binascii
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import plan
import yaml

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 30
TOKEN = os.environ.get("SERVICE_REPOS_READ_TOKEN", "")
API = os.environ.get("GITHUB_API_URL") or "https://api.github.com"
BASE_REF = os.environ.get("BASE_REF") or "origin/main"
SHA_TAG = re.compile(r"sha-([0-9a-f]{40}|[0-9a-f]{7})")
VERSION_TAG = re.compile(r"\d+\.\d+\.\d+")
RULE_ATTRS = ("endpoint", "field", "kind", "value", "step", "status", "provider", "consumers")
ERROR_ATTRS = (("status",), ("body", "field"), ("body", "rule"), ("body", "message"), ("body", "list"),
               ("unlisted", "message"))
NONE = object()

_failed = False


def redact(text: str) -> str:
    return text.replace(TOKEN, "***") if TOKEN else text


def emit(line: str) -> None:
    """The one place that writes output lines: redacted, to stdout and the step summary."""
    global _failed
    line = redact(line)
    if line.startswith("ERROR:"):
        _failed = True
    print(line, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"- {line}\n")


def git(*args: str) -> str | None:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else None


def new_tag(text: str | None) -> str | None:
    try:
        doc = yaml.safe_load(text or "")
        tag = doc["images"][0]["newTag"]
    except (yaml.YAMLError, KeyError, IndexError, TypeError):
        return None
    return str(tag) if tag is not None else None


def changed_pins() -> list[tuple[str, str, str]]:
    """(system, component, tag) of every pin that differs from the merge base, in path order."""
    base = (git("merge-base", BASE_REF, "HEAD") or "").strip()
    if not base:  # a local `devbox run ci` has no base branch: there is no pin change to compare
        return []
    out = []
    for f in sorted((ROOT / "applications").glob("*/overlays/*/*/kustomization.yaml")):
        tag = new_tag(f.read_text(encoding="utf-8"))
        rel = f.relative_to(ROOT).as_posix()
        old = new_tag(git("show", f"{base}:{rel}")) if base else None
        if tag and tag != old:
            out.append((f.parts[-5], f.parent.name, tag))
    return out


def repo_of(system: str, component: str) -> str | None:
    try:
        data = yaml.safe_load((ROOT / "applications" / system / "system.yaml").read_text(encoding="utf-8"))
        repo = data["components"][component]["repo"]
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return None
    return repo if isinstance(repo, str) and "/" in repo else None


def ref_of(tag: str) -> str | None:
    m = SHA_TAG.fullmatch(tag)
    if m:
        return m.group(1)
    return f"v{tag}" if VERSION_TAG.fullmatch(tag) else None


# --- plans ---

def active_plans() -> list[tuple[str, list[str], list[dict], dict | None]]:
    """(plan_id, repo ids, rules, errors block) of every plan that is not abandoned and has a valid `rules:` block."""
    found = []
    for path in sorted(plan.PLAN_DIR.glob("*.md")):
        try:
            meta, body = plan.load(path)
        except Exception:  # noqa: BLE001
            continue
        if meta.get("status") == "abandoned" or "spec" not in meta:
            continue
        ids = [r.get("id") for r in meta.get("repos") or [] if isinstance(r, dict)]
        contract = plan.contract_text(meta, body, plan.SPEC_DIR)
        if contract is None:
            continue
        rules, _reason, errs = plan.parse_rules(contract, ids)
        if rules is None or errs:
            continue
        block, _errs = plan.parse_errors(contract)
        found.append((str(meta.get("plan_id", path.stem)), ids, rules, block))
    return found


# --- GitHub access (copied from check-service-crds.py: the scripts stay independent) ---

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the token must not leave GITHUB_API_URL."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class ApiError(Exception):
    def __init__(self, status: int | None, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def api_get(path: str) -> Any:
    """GET `path` from the API; one retry on 5xx and connection errors. Raises ApiError."""
    req = urllib.request.Request(API.rstrip("/") + path, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "check-contract-pins"})
    for attempt in (1, 2):
        try:
            with OPENER.open(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt == 1:
                time.sleep(0.5)
                continue
            raise ApiError(e.code, f"HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            if attempt == 1 and not isinstance(e, ValueError):
                time.sleep(0.5)
                continue
            raise ApiError(None, f"network error: {getattr(e, 'reason', None) or e}") from None
    raise AssertionError("unreachable")


def read_copy(slug: str, ref: str, plan_id: str) -> dict | None:
    """The parsed contract/<plan_id>.json at `ref`; None when it is missing. Raises ApiError and ValueError."""
    path = urllib.parse.quote(f"contract/{plan_id}.json", safe="/")
    try:
        reply = api_get(f"/repos/{slug}/contents/{path}?ref={urllib.parse.quote(ref, safe='')}")
    except ApiError as e:
        if e.status == 404:
            return None
        raise
    try:
        doc = json.loads(base64.b64decode(reply["content"]).decode("utf-8"))
    except (KeyError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"contract/{plan_id}.json is not readable: {e}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"contract/{plan_id}.json is not an object")
    return doc


# --- comparison ---

def show(v: Any) -> str:
    return "(none)" if v is NONE else json.dumps(v)


def attr(rule: dict, name: str) -> Any:
    if name not in rule:
        return NONE
    v = rule[name]
    return sorted(v) if name == "consumers" and isinstance(v, list) else v


def nested(d: Any, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return NONE
        d = d[k]
    return d


def differences(rules: list[dict], block: dict | None, doc: dict) -> list[tuple[str, str, str]]:
    """(rule id, plan text, pinned text) per difference; the text is `<attr>=<value>`, `(none)` or `(missing)`."""
    out = []
    pinned = {r.get("id"): r for r in doc.get("rules") or [] if isinstance(r, dict)}
    for r in rules:
        c = pinned.pop(r["id"], None)
        if c is None:
            out.append((r["id"], f"rule={json.dumps(r, sort_keys=True)}", "(missing)"))
            continue
        for a in RULE_ATTRS:
            if attr(r, a) != attr(c, a):
                out.append((r["id"], f"{a}={show(attr(r, a))}", f"{a}={show(attr(c, a))}"))
    for rid, c in pinned.items():
        out.append((str(rid), "(none)", f"rule={json.dumps(c, sort_keys=True)}"))
    mine, theirs = block if isinstance(block, dict) else {}, doc.get("errors")
    for keys in ERROR_ATTRS:
        name = "errors." + ".".join(keys)
        a, b = nested(mine, keys), nested(theirs, keys)
        if a != b:
            out.append(("errors", f"{name}={show(a)}", f"{name}={show(b)}"))
    return out


def check(system: str, component: str, tag: str, plans: list) -> None:
    ref = ref_of(tag)
    if ref is None:
        emit(f"contract pins: {component} is pinned to {tag}, which names no commit: not checked")
        return
    repo = repo_of(system, component)
    repo_name = repo.split("/", 1)[1] if repo else None
    sha7 = ref[:7]
    label = sha7 if not ref.startswith("v") else ref
    mine = []
    for plan_id, ids, rules, block in plans:
        rid = next((i for i in ids if i in (component, repo_name)), None)
        if rid is None:
            continue
        sliced, _ = plan.repo_slice(rules, block, rid)
        if sliced:
            mine.append((plan_id, rid, [r for r in plan.resolved(rules, block) if r["id"] in {s["id"] for s in sliced}], block))
    if not mine:
        emit(f"contract pins: {component} takes part in no rule: not checked")
        return
    if repo is None:
        emit(f"ERROR: contract pins: {component} has no `repo:` in system.yaml to read its contract copy from")
        return
    if not TOKEN:
        emit(f"ERROR: contract pins: {component} needs the secret SERVICE_REPOS_READ_TOKEN to read {repo}; "
             "add it (run cplat doctor in this repo for how)")
        return
    for plan_id, rid, rules, block in mine:
        try:
            doc = read_copy(repo, ref, plan_id)
        except (ApiError, ValueError) as e:
            emit(f"ERROR: {component}: cannot read contract/{plan_id}.json of {repo}@{label}: {getattr(e, 'reason', e)}")
            continue
        if doc is None:
            ids = ", ".join(sorted(r["id"] for r in rules))
            emit(f"ERROR: {component}: plan {plan_id} assigns it rule(s) {ids}, but {repo}@{label} has no "
                 f"contract/{plan_id}.json: run /component:spec --from-plan docs/plan/{plan_id}.md {rid} in {repo}")
            continue
        diffs = differences(rules, block, doc)
        for rule_id, here, there in diffs:
            pinned = f"pinned {repo}@{label} {there}"
            emit(f"ERROR: {component}: plan {plan_id} rule {rule_id}: plan {here}, {pinned}")
        if not diffs:
            emit(f"contract pins: {component}@{label} matches plan {plan_id} ({len(rules)} rules)")


def main() -> int:
    pins = changed_pins()
    if not pins:
        emit("contract pins: no component pin changed: nothing to check")
        return 0
    plans = active_plans()
    for system, component, tag in dict.fromkeys(pins):
        check(system, component, tag, plans)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
