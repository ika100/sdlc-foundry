"""`alertissues`: firing alerts become GitHub issues, and stop being issues when they stop firing (spec 092, ADR 035).

`reconcile()` takes the alerts of one application's poll and does every GitHub action: file in the owning repo (fallback:
the gitops-app repo), comment `Fired again`, reopen within 7 days, honour `wontfix`, cap new issues per poll with a summary
issue, and resolve (and close while untriaged) what no longer fires. It reuses 088's signature, redaction and tracker, but
not `autoissue.file()`: it never touches the cap ledger or the run store. It never raises and never prints.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

import alertsources
import autoissue
import triage
from alertsources import SEVERITIES, Alert
from autoissue import Issue, TrackerError

CAP_PER_POLL = 10
REOPEN_WINDOW = datetime.timedelta(days=7)
RESOLVED = "**Resolved** at "
FIRED_AGAIN = "**Fired again** "
DEFERRED = "**Deferred** at "
ISSUE_LABELS = ["triage", "auto-filed", "alert"]          # == autoissue.BASE_LABELS + KIND_LABELS["alert"]
NO_ACCESS = re.compile(r"(?i)(HTTP 40[34]|not accessible|could not resolve to a repository|must have (admin|push|triage|write))")
META_SERVICE = "alert-poll"
DEFERRED_NAME = "AlertsDeferred"
POLL_FAILING_NAME = "AlertPollFailing"
_CALL_S = 10.0
_SIGNATURE = re.compile(r"^Signature: (alert:[0-9a-f]{16})$", re.M)
_NEUTRAL = str.maketrans({"`": "'", "*": "·", "_": "·", "[": "(", "]": ")", "<": "‹", ">": "›", "@": "＠"})


class AlertTracker(autoissue.Tracker, Protocol):
    def open_issues(self, repo: str, labels: list[str], timeout: float) -> list[Issue]: ...
    def close(self, repo: str, number: int, timeout: float) -> None: ...
    def reopen(self, repo: str, number: int, timeout: float) -> None: ...
    def ensure_labels(self, repo: str, labels: dict[str, tuple[str, str]], timeout: float) -> None: ...


class _Router:
    """The gitops repo is written with the workflow's GH_TOKEN, any other repo with $ALERTS_TOKEN when set (AC-092.9)."""
    _NAMES = ("find", "comments", "create", "comment", "open_issues", "close", "reopen", "ensure_labels")

    def __init__(self, gitops_repo: str):
        self.gitops_repo = gitops_repo

    def _for(self, repo: str) -> autoissue.GhTracker:
        token = os.environ.get("ALERTS_TOKEN", "").strip()
        return autoissue.GhTracker(token=token) if token and repo != self.gitops_repo else autoissue.GhTracker()

    def __getattr__(self, name: str):
        if name not in self._NAMES:
            raise AttributeError(name)

        def call(repo, *args, **kwargs):
            return getattr(self._for(repo), name)(repo, *args, **kwargs)
        return call


def tracker(gitops_repo: str) -> AlertTracker:
    """Seam: tests replace it."""
    return _Router(gitops_repo)  # type: ignore[return-value]


@dataclass
class Action:
    verb: str          # file | fired-again | reopen | suppressed | resolve | close | defer | summary | summary-comment
    repo: str
    title: str
    number: int | None = None
    url: str | None = None
    detail: str = ""


@dataclass
class Result:
    actions: list[Action]
    lines: list[str]
    errors: list[str]
    rerouted: list[str]


# ---------------- text ----------------

def _stamp(at: datetime.datetime) -> str:
    return at.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _line(text: str) -> str:
    return re.sub(r"\s+", " ", autoissue.scrub(text)).strip()


def _plain(text: str) -> str:
    """A label value in prose: one line, redacted, and nothing that renders as Markdown, a link or a mention."""
    return _line(text).translate(_NEUTRAL)


def title(alert: Alert) -> str:
    if alert.service == META_SERVICE and alert.environment == "*" and alert.name == DEFERRED_NAME:
        core = f"more than {CAP_PER_POLL} new alerts: {_line(alert.app)}"
    elif alert.service == META_SERVICE and alert.environment == "*" and alert.name == POLL_FAILING_NAME:
        core = f"alert poll is failing: {_line(alert.app)}"
    else:
        core = f"{_line(alert.name)}: {_line(alert.service) or 'unknown'} in {_line(alert.environment)}"
    text = "[auto] [alert] " + core
    return text if len(text) <= 100 else text[:99] + "…"


def _kv(labels: dict[str, str]) -> str:
    return ", ".join(f"{k}={json.dumps(str(v), ensure_ascii=False)}" for k, v in sorted(labels.items()))


def _block(lang: str, text: str) -> list[str]:
    text = autoissue.scrub(text)
    fence = autoissue._fence(text)
    return [f"{fence}{lang}", text, fence, ""]


def render_body(alert: Alert, *, gitops_repo: str, closed: Issue | None = None, intended: tuple[str, str] | None = None) -> str:
    am = alert.source == "alertmanager"
    parts: list[str] = []
    if closed is not None:
        parts += [f"Seen again after #{closed.number} was closed.", ""]
    parts += ["## Alert",
              f"- alert: {_plain(alert.name)}",
              f"- severity: {_plain(alert.severity)}",
              f"- environment: {_plain(alert.environment)}",
              f"- service: {_plain(alert.service) or 'unknown'}",
              f"- started firing: {_stamp(alert.started_at)}",
              f"- source: {'Alertmanager' if am else 'Prometheus rule'}",
              f"- application: {_line(alert.app)} ({_line(gitops_repo)})",
              "",
              "## Summary"]
    summary = autoissue.scrub(alert.summary.strip()) if alert.summary.strip() else "(none)"
    parts += [summary.translate(_NEUTRAL) if am else summary, "", "## Query"]
    parts += _block("text" if am else "promql", alert.query.strip() or "(none)")
    parts += ["## Labels"]
    parts += _block("text", "\n".join(_kv(s) for s in alert.series[:10]) or "(none)")
    if am:
        parts += ["## Annotations"]
        parts += _block("text", _kv(alert.annotations) or "(none)")
    if alert.unmapped:
        parts += ["## Not mapped", *(f"- {_line(n)}" for n in alert.unmapped), ""]
    if intended is not None:
        repo, reason = intended
        parts += ["## Intended repo",
                  f"This alert belongs to {_line(repo)}, but the poll's credential cannot write issues there: {_line(reason)}.",
                  "Set the ALERTS_TOKEN secret (`cplat doctor` shows how).", ""]
    parts += ["_Filed automatically by the alert poll (spec 092). Secrets were removed. Route it with /shared:triage._", "",
              f"Signature: {alert.signature}"]
    return "\n".join(parts)


def render_fired_again(alert: Alert, occurrence: int, at: datetime.datetime) -> str:
    return "\n".join([f"{FIRED_AGAIN}(occurrence {occurrence}) at {_stamp(at)}", "",
                      f"- severity: {_plain(alert.severity)}", f"- environment: {_plain(alert.environment)}"])


def render_resolved(alert_title: str, at: datetime.datetime, *, closed: bool) -> str:
    text = f"{RESOLVED}{_stamp(at)}: no longer firing."
    return text + (" Closed by the alert poll because it was still untriaged." if closed else "")


# ---------------- helpers ----------------

def _parse(ts: str | None) -> datetime.datetime | None:
    if not ts:
        return None
    try:
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def _last_poll_comment(comments: list[str]) -> str | None:
    return next((c for c in reversed(comments) if c.startswith(RESOLVED) or c.startswith(FIRED_AGAIN)), None)


def _occurrence(comments: list[str]) -> int:
    return 2 + sum(1 for c in comments if c.startswith(FIRED_AGAIN))


def _url(repo: str, number: int) -> str:
    return f"https://github.com/{repo}/issues/{number}"


def _issue_title(issue: Issue) -> str:
    if issue.title:
        return issue.title
    field = {k: v for k, v in re.findall(r"^- (alert|environment|service): (.*)$", issue.body, re.M)}
    if field.get("alert"):
        return f"[auto] [alert] {field['alert']}: {field.get('service') or 'unknown'} in {field.get('environment', 'unknown')}"
    return f"#{issue.number}"


def _label_set(alert: Alert) -> list[str]:
    return ISSUE_LABELS + ([f"env:{alert.environment}"] if alert.environment != "*" else [])


def _label_defs(labels: list[str]) -> dict[str, tuple[str, str]]:
    known = {**triage.LABELS, **autoissue.EXTRA_LABELS}
    out: dict[str, tuple[str, str]] = {}
    for name in labels:
        if name.startswith("env:"):
            out[name] = ("5319e7", f"Environment {name[4:]} (spec 092)")
        elif name in known:
            out[name] = known[name]
    return out


def _group(alerts: list[Alert]) -> list[Alert]:
    by_sig: dict[str, Alert] = {}
    for a in alerts:
        old = by_sig.get(a.signature)
        if old is None:
            by_sig[a.signature] = a
            continue
        best = a if SEVERITIES.index(a.severity) < SEVERITIES.index(old.severity) else old
        by_sig[a.signature] = dataclasses.replace(best, started_at=min(a.started_at, old.started_at))
    return sorted(by_sig.values(), key=lambda a: (SEVERITIES.index(a.severity), a.started_at, a.signature))


@dataclass
class _Plan:
    kind: str                      # new | fired-again | reopen | suppressed | quiet
    alert: Alert
    repo: str
    issue: Issue | None = None     # the issue to comment on, reopen or suppress by
    closed: Issue | None = None    # the closed issue a new one links to
    intended: tuple[str, str] | None = None
    occurrence: int = 2


class _Run:
    def __init__(self, *, app, gitops_repo, tr, now, dry_run):
        self.app, self.gitops, self.tr, self.now, self.dry = app, gitops_repo, tr, now, dry_run
        self.res = Result([], [], [], [])
        self.ensured: dict[str, set[str]] = {}

    # ----- errors
    def _no_access(self, repo: str, e: TrackerError) -> bool:
        return repo != self.gitops and NO_ACCESS.search(str(e)) is not None

    def _error(self, repo: str, e: Exception) -> None:
        self.res.errors.append(f"{repo}: {_line(str(e) or type(e).__name__)}")

    def _reroute(self, repo: str, e: TrackerError) -> tuple[str, str]:
        reason = _line(str(e))
        self.res.rerouted.append(f"{repo}: {reason}")
        return repo, reason

    # ----- decide (reads only)
    def decide(self, alert: Alert, target: str, intended: tuple[str, str] | None = None) -> _Plan | None:
        sig = alert.signature
        try:
            found = [i for i in self.tr.find(target, sig, _CALL_S) if autoissue._has_signature(i.body, sig)]
            opened = sorted((i for i in found if i.state == "open"), key=lambda i: (i.created_at, i.number))
            if opened:
                issue = opened[0]
                comments = self.tr.comments(target, issue.number, _CALL_S)
                last = _last_poll_comment(comments)
                if last is not None and last.startswith(RESOLVED):
                    return _Plan("fired-again", alert, target, issue, intended=intended, occurrence=_occurrence(comments))
                return _Plan("quiet", alert, target, issue, intended=intended)
            shut = sorted((i for i in found if i.state != "open"), key=lambda i: (i.closed_at or "", i.number))
            if not shut:
                return _Plan("new", alert, target, intended=intended)
            last_closed = shut[-1]
            if "wontfix" in last_closed.labels:
                return _Plan("suppressed", alert, target, last_closed, intended=intended)
            comments = self.tr.comments(target, last_closed.number, _CALL_S)
            last = _last_poll_comment(comments)
            closed_at = _parse(last_closed.closed_at)
            if (last is not None and last.startswith(RESOLVED) and "Closed by the alert poll" in last and closed_at is not None
                    and closed_at >= self.now - REOPEN_WINDOW):
                return _Plan("reopen", alert, target, last_closed, intended=intended, occurrence=_occurrence(comments))
            return _Plan("new", alert, target, closed=last_closed, intended=intended)
        except TrackerError as e:
            if self._no_access(target, e):
                return self.decide(alert, self.gitops, self._reroute(target, e))
            self._error(target, e)
            return None

    # ----- apply (writes)
    def ensure(self, repo: str, labels: list[str]) -> None:
        if self.dry:
            return
        have = self.ensured.setdefault(repo, set())
        missing = [lb for lb in labels if lb not in have]
        if missing:
            self.tr.ensure_labels(repo, _label_defs(missing), _CALL_S)
            have.update(missing)

    def apply(self, plan: _Plan, labels_for_repo: list[str] | None = None) -> None:
        alert, repo = plan.alert, plan.repo
        name = title(alert)
        try:
            if plan.kind == "quiet":
                return
            if plan.kind == "suppressed":
                n = plan.issue.number  # type: ignore[union-attr]
                self.res.lines.append(f"suppressed by #{n} (wontfix): {name}")
                self.res.actions.append(Action("suppressed", repo, name, n, detail=f"suppressed by #{n}"))
            elif plan.kind == "new":
                self._create(plan, name, labels_for_repo)
            elif plan.kind == "fired-again":
                issue = plan.issue
                assert issue is not None
                body = render_fired_again(alert, plan.occurrence, self.now)
                if self.dry:
                    self.res.lines.append(f"DRY RUN: would comment on {repo}#{issue.number} (fired again): {name}")
                else:
                    self.tr.comment(repo, issue.number, body, _CALL_S)
                    self.res.lines.append(f"fired again {_url(repo, issue.number)}: {name}")
                self.res.actions.append(Action("fired-again", repo, name, issue.number, _url(repo, issue.number)))
            elif plan.kind == "reopen":
                issue = plan.issue
                assert issue is not None
                body = render_fired_again(alert, plan.occurrence, self.now)
                if self.dry:
                    self.res.lines.append(f"DRY RUN: would reopen {repo}#{issue.number}: {name}")
                else:
                    self.tr.reopen(repo, issue.number, _CALL_S)
                    self.tr.comment(repo, issue.number, body, _CALL_S)
                    self.res.lines.append(f"reopened {_url(repo, issue.number)}: {name}")
                self.res.actions.append(Action("reopen", repo, name, issue.number, _url(repo, issue.number)))
        except TrackerError as e:
            if self._no_access(repo, e) and plan.kind != "suppressed":
                again = self.decide(alert, self.gitops, self._reroute(repo, e))
                if again is not None:
                    self.apply(again, labels_for_repo=None)
                return
            self._error(repo, e)

    def _create(self, plan: _Plan, name: str, labels_for_repo: list[str] | None) -> None:
        alert, repo = plan.alert, plan.repo
        labels = _label_set(alert)
        body = render_body(alert, gitops_repo=self.gitops, closed=plan.closed, intended=plan.intended)
        if self.dry:
            self.res.lines.append(f"DRY RUN: would file in {repo}: {name}")
            if plan.intended:
                self.res.lines.append(f"DRY RUN: would file in {self.gitops} instead of {plan.intended[0]}: {plan.intended[1]}")
            self.res.actions.append(Action("file", repo, name))
            return
        self.ensure(repo, sorted(set(labels) | set(labels_for_repo or [])))
        url = self.tr.create(repo, name, body, labels, _CALL_S)
        self.res.lines.append(f"filed {url}: {name}")
        if plan.intended:
            self.res.lines.append(f"filed in {self.gitops} instead of {plan.intended[0]}: {plan.intended[1]}")
        m = re.search(r"/issues/(\d+)\s*$", url)
        self.res.actions.append(Action("file", repo, name, int(m.group(1)) if m else None, url))

    # ----- summary issue of the cap
    def summarise(self, app: str, deferred: list[tuple[Alert, str]]) -> Alert:
        listing = "\n".join(f"- {title(a)} ({repo})" for a, repo in deferred)
        return Alert(app=app, name=DEFERRED_NAME, severity="info", environment="*", service=META_SERVICE, repo=None,
                     started_at=self.now, summary=f"{len(deferred)} new alerts wait for the next poll:\n{listing}",
                     source="rule", query="", series=[])

    def file_summary(self, summary: Alert, deferred: list[tuple[Alert, str]]) -> None:
        sig, name = summary.signature, title(summary)
        try:
            found = [i for i in self.tr.find(self.gitops, sig, _CALL_S) if autoissue._has_signature(i.body, sig) and i.state == "open"]
            if found:
                issue = sorted(found, key=lambda i: (i.created_at, i.number))[0]
                body = "\n".join([f"{DEFERRED}{_stamp(self.now)}: {len(deferred)} alerts wait for the next poll", "",
                                  *(autoissue.scrub(f"- {title(a)} ({repo})") for a, repo in deferred)])
                if self.dry:
                    self.res.lines.append(f"DRY RUN: would comment on {self.gitops}#{issue.number} (deferred list)")
                else:
                    self.tr.comment(self.gitops, issue.number, body, _CALL_S)
                    self.res.lines.append(f"deferred list on {_url(self.gitops, issue.number)}")
                self.res.actions.append(Action("summary-comment", self.gitops, name, issue.number, _url(self.gitops, issue.number)))
                return
            self.apply(_Plan("new", summary, self.gitops))
        except TrackerError as e:
            self._error(self.gitops, e)

    # ----- resolve
    def resolve(self, repos: list[str], firing: set[str]) -> None:
        marker = f"- application: {self.app} ({self.gitops})"
        for repo in sorted(set(repos) | {self.gitops}):
            try:
                issues = self.tr.open_issues(repo, ["auto-filed", "alert"], _CALL_S)
            except TrackerError as e:
                if NO_ACCESS.search(str(e)):
                    continue
                self._error(repo, e)
                continue
            for issue in issues:
                m = _SIGNATURE.search(issue.body or "")
                if not m or marker not in issue.body.splitlines() or m.group(1) in firing:
                    continue
                self._resolve_one(repo, issue)

    def _resolve_one(self, repo: str, issue: Issue) -> None:
        name = _issue_title(issue)
        n = issue.number
        close = "triage" in issue.labels
        try:
            last = _last_poll_comment(self.tr.comments(repo, n, _CALL_S))
            if last is None or not last.startswith(RESOLVED):
                if self.dry:
                    self.res.lines.append(f"DRY RUN: would comment on {repo}#{n} (resolved): {name}")
                else:
                    self.tr.comment(repo, n, render_resolved(name, self.now, closed=close), _CALL_S)
                    self.res.lines.append(f"resolved {_url(repo, n)}: {name}")
                self.res.actions.append(Action("resolve", repo, name, n, _url(repo, n)))
            elif not close:
                return
            if close:
                if self.dry:
                    self.res.lines.append(f"DRY RUN: would close {repo}#{n}: {name}")
                else:
                    self.tr.close(repo, n, _CALL_S)
                    self.res.lines.append(f"closed {_url(repo, n)}: {name}")
                self.res.actions.append(Action("close", repo, name, n, _url(repo, n)))
        except TrackerError as e:
            self._error(repo, e)


def reconcile(alerts: list[Alert], *, app: str, gitops_repo: str, repos: list[str], tr: AlertTracker,
              now: datetime.datetime, dry_run: bool, resolve: bool) -> Result:
    """Never raises. `repos`: the services' repos + gitops_repo (where resolved issues are looked for).
    resolve=False (a source failed): no resolve and no close at all (AC-092.16)."""
    run = _Run(app=app, gitops_repo=gitops_repo, tr=tr, now=now, dry_run=dry_run)
    try:
        ordered = _group(alerts)
        plans = [p for p in (run.decide(a, a.repo or gitops_repo) for a in ordered) if p is not None]
        # the cap: the first CAP_PER_POLL new issues in sort order are filed, the rest wait for the next poll
        new_seen, deferred = 0, []
        final: list[_Plan | None] = []
        for p in plans:
            if p.kind == "new":
                new_seen += 1
                if new_seen > CAP_PER_POLL:
                    deferred.append((p.alert, p.repo))
                    run.res.lines.append(f"deferred (cap of {CAP_PER_POLL} new issues per poll): {title(p.alert)}")
                    run.res.actions.append(Action("defer", p.repo, title(p.alert)))
                    continue
            final.append(p)
        labels_by_repo: dict[str, set[str]] = {}
        for p in final:
            if p is not None and p.kind == "new":
                labels_by_repo.setdefault(p.repo, set()).update(_label_set(p.alert))
        for p in final:
            if p is not None:
                run.apply(p, sorted(labels_by_repo.get(p.repo, [])) if p.kind == "new" else None)
        firing = {a.signature for a in ordered}
        if deferred:
            summary = run.summarise(app, deferred)
            firing.add(summary.signature)
            run.file_summary(summary, deferred)
        if resolve:
            run.resolve(repos, firing)
    except Exception as e:  # noqa: BLE001  (reconcile never raises)
        run.res.errors.append(f"unexpected failure: {type(e).__name__}: {_line(str(e))}")
    return run.res
