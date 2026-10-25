"""The evidence summary `cplat promote … staging prod` shows before a production promotion (spec 093, ADR-041).

It reads the run store (spec 085) for the smoke outcomes of the release's commit in dev and in staging, and the open
`smoke-failure` and `alert` issues of the service repo. It never blocks and never raises: what it cannot read becomes
`no record (<why>)` or `unknown (<why>)`, and a release without a green staging smoke gets a WARNING line first.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from datetime import date

import runs
from core import PlatformError, run

RELEASE_FILES = {"CHANGELOG.md", "pyproject.toml", "uv.lock", "package.json", "pom.xml"}
LABELS = ("smoke-failure", "alert")
GREEN = {"passed", "passed-on-retry"}
SHA40 = re.compile(r"^sha-([0-9a-f]{40})$")
SHA7 = re.compile(r"^sha-([0-9a-f]{7})$")
RELEASE = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


def open_store(slug: str):   # tests replace this
    return runs.open_store(slug)


def today() -> date:         # tests replace this
    return dt.datetime.now(dt.timezone.utc).date()


@dataclass
class Evidence:
    service: str
    version: str
    commit: str | None = None
    evidence_commit: str | None = None
    note: str | None = None
    staging_tag: str | None = None
    staging_commit: str | None = None
    dev: dict = field(default_factory=dict)
    staging: dict = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    issues_error: str | None = None
    warning: str | None = None

    def lines(self) -> list[str]:
        short = lambda s: (s or "unknown")[:7]   # noqa: E731
        out = []
        if self.warning:
            out.append(f"WARNING: {self.version} of {self.service} has no green staging smoke: {self.warning}")
        out.append(f"evidence for {self.service} {self.version} (commit {short(self.commit)}):")
        if self.note:
            out.append(f"- evidence commit: {short(self.evidence_commit)} ({self.note})")
        if self.staging_commit:
            out.append(f"- staging runs: commit {short(self.staging_commit)} ({self.staging_tag})")
        else:
            out.append(f"- staging runs: {self.staging_tag}" if self.staging_tag and self.staging_tag != "latest"
                       else "- staging runs: no pinned build")
        for env, rec in (("dev", self.dev), ("staging", self.staging)):
            out.append(f"- smoke ({env}): " + ", ".join(p for p in (rec.get("text"), rec.get("at_text"), rec.get("link")) if p))
        if self.issues_error is not None:
            out.append(f"- open issues: unknown ({self.issues_error})")
        elif self.issues:
            out.append(f"- open issues ({', '.join(LABELS)}): {len(self.issues)}: " + ", ".join(i["url"] for i in self.issues))
        else:
            out.append(f"- open issues ({', '.join(LABELS)}): none")
        return out

    def data(self) -> dict:
        return {"service": self.service, "version": self.version, "commit": self.commit, "evidence_commit": self.evidence_commit,
                "note": self.note, "staging_tag": self.staging_tag, "staging_commit": self.staging_commit, "dev": self.dev,
                "staging": self.staging, "issues": self.issues, "issues_error": self.issues_error, "warning": self.warning}


def _api(repo: str, ref: str) -> dict:
    data = json.loads(gh(["api", f"repos/{repo}/commits/{ref}"]) or "null")
    if not isinstance(data, dict):
        raise ValueError("unreadable commit")
    return data


def _release_commit(repo: str, version: str) -> tuple[str | None, str | None, str | None]:
    """(commit, evidence commit, note): a release-PR merge commit is looked up by its first parent."""
    try:
        c = _api(repo, version if version.startswith("v") else f"v{version}")
    except (PlatformError, ValueError):
        return None, None, None
    sha = c.get("sha")
    parents = [p.get("sha") for p in c.get("parents") or [] if isinstance(p, dict)]
    files = [f.get("filename") for f in c.get("files") or [] if isinstance(f, dict)]
    if len(parents) == 2 and files and all(f in RELEASE_FILES for f in files):
        return sha, parents[0], "the release commit only changes " + ", ".join(sorted(files))
    return sha, sha, None


def _staging_commit(repo: str, tag: str | None) -> str | None:
    if not tag:
        return None
    if m := SHA40.match(tag):
        return m.group(1)
    if m := SHA7.match(tag):
        ref = m.group(1)
    elif m := RELEASE.match(tag):
        ref = f"v{m.group(1)}"
    else:
        return None
    try:
        return _api(repo, ref).get("sha")
    except (PlatformError, ValueError):
        return None


def _word(sec: dict) -> str:
    o = sec.get("outcome")
    if o == "passed":
        return f"passed {sec.get('passed', 0)}/{sec.get('total', 0)}"
    if o == "passed-on-retry":
        return "passed on retry"
    if o == "timed-out":
        return "red (timed out after 600s)"
    if o == "not-run":
        return f"not run: {sec.get('reason')}"
    return f"red ({len(sec.get('failing') or [])} failing)"


def _stamp(at: str | None) -> str | None:
    try:
        return dt.datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return None


def _entry(sec: dict, path: str, store: str, fallback: str | None) -> dict:
    at = sec.get("at") or fallback
    return {"outcome": sec.get("outcome"), "text": _word(sec), "at": at, "at_text": _stamp(at), "reason": sec.get("reason"),
            "path": path, "rank": "", "link": f"https://github.com/{store}/blob/HEAD/{path}"}


def _records(svc_repo: str, shas: set[str], days: int) -> tuple[dict | None, dict | None, str | None]:
    """(newest dev entry, newest staging entry, why not) from the last 30 days of the run store."""
    store = runs.configured_repo()
    if not store:
        return None, None, "no run store configured: set CPLAT_RUNS_REPO"
    try:
        days = [today() - dt.timedelta(days=n) for n in range(days)]
        files = open_store(store).read(days)
    except Exception as e:  # noqa: BLE001  (an unreadable store is "no record")
        return None, None, f"run store {store} not readable: {e}"
    best: dict[str, dict] = {}
    for path, text in files:
        try:
            rec = json.loads(text)
            sec = rec["smoke"]
            if rec.get("kind") != "ship" or rec.get("repo") != svc_repo or not isinstance(sec, dict):
                continue
            for env, s in (("dev", sec), ("staging", sec.get("staging"))):
                if isinstance(s, dict) and s.get("image") in shas:
                    e = _entry(s, path, store, rec.get("ended_at"))
                    e["rank"] = str(sec.get("at") or rec.get("ended_at") or "")   # the record's time, dev's `at` first
                    if env not in best or e["rank"] > best[env]["rank"]:
                        best[env] = e
        except (ValueError, KeyError, TypeError):
            continue
    return best.get("dev"), best.get("staging"), None


def _issues(repo: str) -> tuple[list[dict], str | None]:
    seen: dict[str, dict] = {}
    for label in LABELS:
        try:
            rows = json.loads(gh(["issue", "list", "-R", repo, "--state", "open", "--label", label,
                                  "--json", "number,title,url", "--limit", "50"]) or "[]")
        except (PlatformError, ValueError) as e:
            return [], str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("url"):
                seen.setdefault(r["url"], {"number": r.get("number"), "title": r.get("title"), "url": r["url"]})
    return list(seen.values()), None


def summary(svc: dict, version: str, staging_tag: str | None, *, days: int = 30) -> Evidence:
    """The evidence for `svc` at release `version` (e.g. v1.4.0) with staging pinned to `staging_tag`. Never raises."""
    ev = Evidence(service=str(svc.get("name")), version=version, staging_tag=staging_tag)
    try:
        repo = str(svc.get("repo"))
        ev.commit, ev.evidence_commit, ev.note = _release_commit(repo, version)
        ev.staging_commit = _staging_commit(repo, staging_tag)
        shas = {s for e in (ev.evidence_commit,) if e for s in (f"sha-{e}", f"sha-{e[:7]}")}
        dev, stg, why = _records(repo, shas, days)
        absent = f"no record ({why})" if why else "no record"
        ev.dev = dev or {"outcome": None, "text": absent}
        ev.staging = stg or {"outcome": None, "text": absent}
        ev.issues, ev.issues_error = _issues(repo)
        ev.warning = _warning(ev, why)
    except Exception as e:  # noqa: BLE001  (the summary never blocks a promotion)
        ev.warning = ev.warning or f"evidence could not be read: {e}"
        ev.dev = ev.dev or {"outcome": None, "text": "no record"}
        ev.staging = ev.staging or {"outcome": None, "text": "no record"}
    return ev


def _warning(ev: Evidence, why: str | None) -> str | None:
    e, s = ev.evidence_commit, ev.staging_commit
    if e and s and not (s == e or s[:7] == e[:7]):
        return f"staging runs {s[:7]}, not {e[:7]}"
    o = ev.staging.get("outcome")
    if o in GREEN:
        return None
    if o in {"red", "timed-out"}:
        return "staging smoke red"
    if o == "not-run":
        return f"staging smoke not run: {ev.staging.get('reason')}"
    return "no staging smoke record"
