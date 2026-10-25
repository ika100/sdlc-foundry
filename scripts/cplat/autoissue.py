"""`autoissue`: platform failures become deduplicated GitHub issues (spec 088, ADR 033).

Callers build a `Draft` and call `file()`. It redacts the draft, looks for an issue with the same `Signature:` line,
adds a `+1` comment to the oldest open one, links or suppresses on closed ones, applies the cap, and records the result
with `runs.filed()`. A filing that cannot be sent stays pending in the run store's `filings.jsonl` and is retried by
`retry_filing()` (the filer 087's `runs.flush` calls). The module never prints: `Outcome.lines` is for the caller.

All GitHub access goes through `tracker()`; tests replace it (and `gh()`, `now()`, `monotonic()`).
Specs 091 and 092 reuse this module with the kinds `smoke` and `alert`.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import re
import subprocess
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

import core
import feedback
import runs
import triage

KINDS = ("platform", "smoke", "alert")
KIND_LABELS = {"platform": ["bug"], "smoke": ["smoke-failure"], "alert": ["alert"]}
BASE_LABELS = ["triage", "auto-filed"]
SIGNATURE_LINE = re.compile(r"^Signature: (platform|smoke|alert):[0-9a-f]{16}$", re.M)
DEFAULT_BRANCHES = {"main", "master", "trunk", "develop"}
SUBCOMMAND_GROUPS = {"ship", "spec", "runs", "triage", "compose", "addon", "secret", "pr", "shape"}

CAP = 10                        # new issues per window, per machine and target repo
WINDOW_S = 24 * 3600
TIMEOUT_S = 20.0                # total budget of one file() call
RESULTS = ("new", "+1", "suppressed", "pending", "off")
EXTRA_LABELS = {
    "auto-filed": ("c5def5", "Filed automatically by the platform (spec 088)"),
    "smoke-failure": ("b60205", "A scheduled smoke test failed (spec 091)"),
    "alert": ("d93f0b", "A deployed service raised an alert (spec 092)"),
}
DEFAULT_REPO = "ika100/sdlc-foundry"
_OFF_VALUES = {"off", "0", "false", "no"}
_CALL_S = 10.0


def now() -> datetime.datetime:
    """UTC; tests replace this."""
    return datetime.datetime.now(datetime.timezone.utc)


def monotonic() -> float:
    """Tests replace this."""
    return time.monotonic()


def default_repo() -> str:
    return os.environ.get("CPLAT_FEEDBACK_REPO", "").strip() or DEFAULT_REPO


def enabled() -> bool:
    return os.environ.get("CPLAT_AUTO_ISSUES", "").strip().lower() not in _OFF_VALUES


# ---------------- signature ----------------

_PATH_SEG = r"[\w.@+-]+"
_NORMALISE_STEPS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"https?://\S+"), "<url>"),
    (re.compile(r"sha256:[0-9a-f]{64}"), "<hash>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"), "<date>"),
    (re.compile(r"\d{8}T\d{6}Z"), "<date>"),
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"), "<time>"),
    # a test id (`tests/test_a.py::test_x`, spec 091) is a name, not a volatile path: it keeps its file
    (re.compile(rf"(?:(?:~|\.{{1,2}})?(?:/{_PATH_SEG}){{2,}}|{_PATH_SEG}(?:/{_PATH_SEG})+)(?![\w.@+/-]|::)"), "<path>"),
    (re.compile(r"\b\d{3}-[a-z][a-z0-9-]*\b"), "<spec>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b"
                r"(?:\s\d+(?:\.\d+)?\s?(?:ms|s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b)*"), "<duration>"),
    (re.compile(r"\bv?\d+\.\d+(?:\.\d+)*(?:[-+][\w.]+)?\b"), "<version>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}\b"), "<hash>"),
    (re.compile(r"#\d+"), "#<n>"),
    (re.compile(r"\d+"), "<n>"),
]


def _replace_names(text: str, names: dict[str, str] | None) -> str:
    mapping = names or {}
    for key in sorted(mapping, key=len, reverse=True):
        if key:
            value = mapping[key]
            # a name is not part of a longer name: `todo` stays in `todo-api` and `mytodo`
            text = re.sub(rf"(?<![\w-]){re.escape(key)}(?![\w-])", value.replace("\\", "\\\\"), text, flags=re.I)
    return text


def _signature_names(names: dict[str, str] | None) -> dict[str, str]:
    """For the signature only: the bare repo name of `owner/name` is volatile as well (it is also a consumer name)."""
    out = dict(names or {})
    for key, value in list(out.items()):
        if value == "<repo>" and "/" in key:
            short = key.split("/", 1)[1]
            if len(short) >= 3:
                out.setdefault(short, value)
    # another repo's owner/name or branch is a path in its failure text: both read the same in a signature
    return {k: ("<path>" if v in ("<repo>", "<branch>") else v) for k, v in out.items()}


def normalise(text: str, names: dict[str, str] | None = None) -> str:
    text = feedback.redact(text)
    text = _replace_names(text, _signature_names(names))
    for pattern, repl in _NORMALISE_STEPS:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


def raw_signature(kind: str, *parts: str) -> str:
    """`<kind>:<first 16 hex of the sha256 of the parts joined by newline>`; ValueError for an unknown kind."""
    import hashlib
    if kind not in KINDS:
        raise ValueError(f"unknown signature kind {kind!r}; allowed: {', '.join(KINDS)}")
    return f"{kind}:{hashlib.sha256(chr(10).join(parts).encode()).hexdigest()[:16]}"


def signature(kind: str, *parts: str, names: dict[str, str] | None = None) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown signature kind {kind!r}; allowed: {', '.join(KINDS)}")
    return raw_signature(kind, *(normalise(p, names) for p in parts))


# ---------------- redaction ----------------

def private_names(repo: str | None, spec: str | None, branch: str | None) -> dict[str, str]:
    names: dict[str, str] = {}
    if repo:
        names[repo] = "<repo>"
    if spec:
        names[spec] = "<spec>"
    if branch and branch not in DEFAULT_BRANCHES:
        names[branch] = "<branch>"
    store = runs.configured_repo()
    if store:
        names[store] = "<run-store>"
    return names


_RUN_OF_ONE_CHAR = re.compile(r"(?<!\w)(.)\1{39,}(?!\w)", re.S)    # not glued to other word characters
_SIG_START = re.compile(r"^([ \t]*)Signature:", re.M)


def scrub(text: str, names: dict[str, str] | None = None) -> str:
    """Redact secrets, then private names, then quote every `Signature:` line so a body keeps exactly one."""
    kept: list[str] = []

    def keep(m: re.Match[str]) -> str:     # a run of one repeated character is padding, not an opaque key
        kept.append(m.group(0))
        return f"{len(kept) - 1}"

    text = feedback.redact(_RUN_OF_ONE_CHAR.sub(keep, text))
    text = re.sub("(\\d+)", lambda m: kept[int(m.group(1))], text)
    text = _replace_names(text, names)
    return _SIG_START.sub(r"\1Signature (quoted):", text)


# ---------------- model ----------------

@dataclass
class Draft:
    kind: str                              # platform | smoke | alert
    signature: str
    reason: str                            # one line; the title is built from it
    command: str
    phase: str
    evidence: str = ""
    run_id: str | None = None
    shape: str = "none"
    repo: str | None = None                # target; None -> default_repo()
    names: dict[str, str] = field(default_factory=dict)
    environment: list[str] | None = None   # None -> feedback.diagnostics(Path.cwd()) at render
    sections: list[tuple[str, str]] = field(default_factory=list)
    labels: list[str] | None = None        # None -> BASE_LABELS + KIND_LABELS[kind]

    def to_payload(self) -> dict:
        data = asdict(self)
        data["environment"] = self.env_lines()
        data["sections"] = [[h, t] for h, t in self.sections]
        return json.loads(json.dumps(data))

    @classmethod
    def from_payload(cls, payload: dict) -> "Draft":
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in payload.items() if k in known}
        data["sections"] = [(str(h), str(t)) for h, t in data.get("sections") or []]
        return cls(**data)

    def env_lines(self) -> list[str]:
        if self.environment is not None:
            return list(self.environment)
        try:
            return feedback.diagnostics(Path.cwd())
        except Exception:  # noqa: BLE001  (diagnostics must never fail a filing)
            return []

    def label_list(self) -> list[str]:
        return list(self.labels) if self.labels is not None else BASE_LABELS + KIND_LABELS.get(self.kind, [])


@dataclass
class Issue:
    number: int
    url: str
    state: str                             # "open" | "closed"
    labels: list[str]
    created_at: str
    closed_at: str | None
    body: str
    title: str = ""


@dataclass
class Outcome:
    result: str                            # one of RESULTS
    signature: str
    url: str | None
    number: int | None
    lines: list[str]


class TrackerError(Exception):
    """str(e) is the short reason printed after "not filed: "."""


class Tracker(Protocol):
    def find(self, repo: str, signature: str, timeout: float) -> list[Issue]: ...
    def comments(self, repo: str, number: int, timeout: float) -> list[str]: ...
    def create(self, repo: str, title: str, body: str, labels: list[str], timeout: float) -> str: ...
    def comment(self, repo: str, number: int, body: str, timeout: float) -> str: ...


# ---------------- GitHub ----------------

def gh(args: list[str], *, input: str | None = None, timeout: float = 10.0, token: str | None = None) -> tuple[int, str, str]:
    """(exit code, stdout, stderr). Never raises: a timeout is 124, a missing binary 127. Tests replace this.
    With `token` the child env gets GH_TOKEN=token and no GITHUB_TOKEN (spec 092 writes other repos with it)."""
    kw: dict = {}
    if token:
        kw["env"] = {**{k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}, "GH_TOKEN": token}
    try:
        p = subprocess.run(["gh", *args], input=input, capture_output=True, text=True, timeout=timeout, check=False, **kw)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "gh is missing"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"


def _check(code: int, err: str) -> None:
    if code == 0:
        return
    if code == 127:
        raise TrackerError("gh is missing")
    if code == 124:
        raise TrackerError("timed out")
    if code == 4 or "gh auth login" in err:
        raise TrackerError("gh is not logged in")
    last = next((ln.strip() for ln in reversed(err.strip().splitlines()) if ln.strip()), "no details")
    raise TrackerError(f"GitHub refused: {last}")


def _json_values(text: str) -> list:
    """All JSON values in `text` (gh --paginate prints one array per page)."""
    out, dec, i = [], json.JSONDecoder(), 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        value, i = dec.raw_decode(text, i)
        out.append(value)
    return out


def _items(text: str) -> list[dict]:
    items: list[dict] = []
    try:
        for value in _json_values(text):
            items.extend(value if isinstance(value, list) else value.get("items", []))
    except ValueError as e:
        raise TrackerError(f"GitHub answered with unreadable JSON: {e}") from e
    return [i for i in items if isinstance(i, dict)]


def _to_issue(item: dict) -> Issue:
    return Issue(number=int(item["number"]), url=str(item.get("html_url") or item.get("url") or ""), state=str(item.get("state", "open")),
                 labels=[str(lb.get("name")) if isinstance(lb, dict) else str(lb) for lb in item.get("labels") or []],
                 created_at=str(item.get("created_at") or ""), closed_at=item.get("closed_at"), body=str(item.get("body") or ""),
                 title=str(item.get("title") or ""))


def _has_signature(body: str, sig: str) -> bool:
    return re.search(rf"^Signature: {re.escape(sig)}$", body or "", re.M) is not None


class GhTracker:
    """The Tracker over `gh api` and `gh issue`. `token` (spec 092) makes every call use that GH_TOKEN; `open_issues`,
    `close`, `reopen` and `ensure_labels` are used by the alert poll of spec 092 only."""

    def __init__(self, token: str | None = None):
        self.token = token

    def _gh(self, args: list[str], **kw) -> tuple[int, str, str]:
        if self.token:               # only then, so 088's fake `gh` functions (no `token` parameter) keep working
            kw["token"] = self.token
        return gh(args, **kw)

    def find(self, repo: str, signature: str, timeout: float) -> list[Issue]:
        code, out, err = self._gh(["api", "--paginate", f"repos/{repo}/issues?labels=auto-filed&state=open&per_page=100"], timeout=timeout)
        _check(code, err)
        found = {i.number: i for i in map(_to_issue, (x for x in _items(out) if "pull_request" not in x)) if _has_signature(i.body, signature)}
        if found:
            return list(found.values())          # an open duplicate decides; closed ones do not matter
        query = f'repo:{repo} is:issue in:body "Signature: {signature}"'
        code, out, err = self._gh(["api", "-X", "GET", "search/issues", "-f", f"q={query}", "-f", "per_page=100"], timeout=timeout)
        _check(code, err)
        for item in _items(out):
            if "pull_request" not in item:
                issue = _to_issue(item)
                if _has_signature(issue.body, signature):
                    found.setdefault(issue.number, issue)
        return list(found.values())

    def comments(self, repo: str, number: int, timeout: float) -> list[str]:
        code, out, err = self._gh(["api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100"], timeout=timeout)
        _check(code, err)
        return [str(c.get("body") or "") for c in _items(out)]

    def create(self, repo: str, title: str, body: str, labels: list[str], timeout: float) -> str:
        args = ["issue", "create", "-R", repo, "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        code, out, err = self._gh(args, input=body, timeout=timeout)
        if code != 0 and "not found" in err.lower():
            self._create_labels(repo, labels, timeout)
            code, out, err = self._gh(args, input=body, timeout=timeout)
        _check(code, err)
        return self._last_line(out)

    def comment(self, repo: str, number: int, body: str, timeout: float) -> str:
        code, out, err = self._gh(["issue", "comment", str(number), "-R", repo, "--body-file", "-"], input=body, timeout=timeout)
        _check(code, err)
        return self._last_line(out)

    @staticmethod
    def _last_line(out: str) -> str:
        lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
        if not lines:
            raise TrackerError("GitHub answered without a URL")
        return lines[-1]

    def _create_labels(self, repo: str, labels: list[str], timeout: float) -> None:
        known = {**triage.LABELS, **EXTRA_LABELS}
        for label in labels:
            if label in known:
                color, description = known[label]
                self._gh(["label", "create", label, "-R", repo, "--color", color, "--description", description, "--force"], timeout=timeout)

    def open_issues(self, repo: str, labels: list[str], timeout: float) -> list[Issue]:
        code, out, err = self._gh(["api", "--paginate", f"repos/{repo}/issues?labels={','.join(labels)}&state=open&per_page=100"], timeout=timeout)
        _check(code, err)
        return [_to_issue(x) for x in _items(out) if "pull_request" not in x]

    def close(self, repo: str, number: int, timeout: float) -> None:
        code, _, err = self._gh(["issue", "close", str(number), "-R", repo, "--reason", "completed"], timeout=timeout)
        _check(code, err)

    def reopen(self, repo: str, number: int, timeout: float) -> None:
        code, _, err = self._gh(["issue", "reopen", str(number), "-R", repo], timeout=timeout)
        _check(code, err)

    def ensure_labels(self, repo: str, labels: dict[str, tuple[str, str]], timeout: float) -> None:
        for name, (color, description) in labels.items():
            code, _, err = self._gh(["label", "create", name, "-R", repo, "--color", color, "--description", description], timeout=timeout)
            if code != 0 and "already exists" in err.lower():
                continue
            _check(code, err)


def tracker() -> Tracker:
    """Tests replace this."""
    return GhTracker()


# ---------------- rendering ----------------

def _one_line(text: str) -> str:
    first = (text.strip().splitlines() or [""])[0]
    return re.sub(r"\s+", " ", first).strip()


def _title(draft: Draft) -> str:
    title = "[auto] " + _one_line(scrub(draft.reason, draft.names))
    return title if len(title) <= 100 else title[:99] + "…"


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def render(draft: Draft, *, closed: Issue | None = None) -> tuple[str, str]:
    """(title, body)."""
    n = draft.names
    evidence = scrub(feedback.tail(draft.evidence), n) if draft.evidence.strip() else "(none)"
    fence = _fence(evidence)
    parts: list[str] = []
    if closed is not None:
        parts += [f"Seen again after #{closed.number} was closed.", ""]
    parts += ["## Reason", scrub(draft.reason.strip(), n), "",
              "## Command and phase", f"- command: `{scrub(draft.command, n)}`", f"- phase: `{scrub(draft.phase, n)}`", "",
              "## Evidence", f"{fence}text", evidence, fence, ""]
    for heading, text in draft.sections:
        parts += [f"## {scrub(heading, n)}", scrub(text, n), ""]
    parts += ["## Environment", f"- shape: {scrub(draft.shape, n)}", *(scrub(ln, n) for ln in draft.env_lines()), "",
              "## Run", f"- run id: {draft.run_id or 'none'}", "",
              "_Filed automatically by cplat (spec 088). Secrets, e-mail addresses, home directories, repo, spec and branch names were removed._",
              "", f"Signature: {draft.signature}"]
    return _title(draft), "\n".join(parts)


def render_comment(draft: Draft, occurrence: int) -> str:
    n = draft.names
    return "\n".join([
        f"**Occurrence {occurrence}** of `{draft.signature}`", "",
        f"- date: {now().astimezone(datetime.timezone.utc):%Y-%m-%d}",
        f"- platform: {core.platform_version()}",
        f"- shape: {scrub(draft.shape, n)}",
        f"- run: `{draft.run_id or 'none'}`",
        f"- reason: {_one_line(scrub(draft.reason, n))}",
    ])


# ---------------- cap ledger ----------------

def _ledger() -> Path:
    return runs.state_dir() / "autoissue-ledger.jsonl"


@contextlib.contextmanager
def _ledger_lock() -> Iterator[None]:
    d = runs.state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".autoissue.lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _ledger_entries() -> list[dict]:
    try:
        lines = _ledger().read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
            if isinstance(e, dict) and "at" in e:
                out.append(e)
        except ValueError:
            continue
    return out


def _at(entry: dict) -> datetime.datetime:
    return datetime.datetime.fromisoformat(str(entry["at"]))


def _recent(repo: str, window: float) -> int:
    since = now() - datetime.timedelta(seconds=window)
    count = 0
    for e in _ledger_entries():
        try:
            if e.get("repo") == repo and _at(e) > since:
                count += 1
        except ValueError:
            continue
    return count


def _ledger_add(repo: str, sig: str, url: str, window: float) -> None:
    keep_since = now() - datetime.timedelta(seconds=max(window, WINDOW_S))
    kept = []
    for e in _ledger_entries():
        try:
            if _at(e) > keep_since:
                kept.append(e)
        except ValueError:
            continue
    kept.append({"at": now().isoformat(), "repo": repo, "signature": sig, "url": url})
    _ledger().write_text("".join(json.dumps(e) + "\n" for e in kept))


def _window_text(window: float) -> str:
    return "24 h" if window == WINDOW_S else f"{int(window)} s"


# ---------------- file ----------------

class _Pending(Exception):
    pass


def _off_lines(draft: Draft, repo: str) -> list[str]:
    title, body = render(draft)
    lines = [f"## Draft issue for {repo}", "", f"**{title}**   (labels: {', '.join(draft.label_list())})", ""]
    lines += body.splitlines()
    lines += ["", "Automatic filing is off (CPLAT_AUTO_ISSUES=off); nothing was sent. Run /shared:report-issue to file it; nothing is sent without your OK."]
    return lines


def _file(draft: Draft, run_id: str | None, timeout: float, cap: int, window: float) -> tuple[Outcome, str]:
    """(outcome, pending reason). May raise; `file` turns that into pending."""
    repo = draft.repo or default_repo()
    sig = draft.signature
    if not enabled():
        return Outcome("off", sig, None, None, _off_lines(draft, repo)), ""
    deadline = monotonic() + timeout

    def budget() -> float:
        left = deadline - monotonic()
        if left < 1:
            raise TrackerError("timed out")
        return min(_CALL_S, left)

    tr = tracker()
    matches = [i for i in tr.find(repo, sig, budget()) if _has_signature(i.body, sig)]
    if run_id:
        for i in matches:
            if f"- run id: {run_id}" in i.body.splitlines():
                return Outcome("new", sig, i.url, i.number, [f"issue: {i.url} new"]), ""
    opened = sorted((i for i in matches if i.state == "open"), key=lambda i: (i.created_at, i.number))
    closed_issue: Issue | None = None
    if opened:
        target = opened[0]
        existing = tr.comments(repo, target.number, budget())
        if run_id and any(f"- run: `{run_id}`" in c for c in existing):
            return Outcome("+1", sig, target.url, target.number, [f"issue: {target.url} +1"]), ""
        occurrence = 2 + sum(1 for c in existing if c.startswith("**Occurrence "))
        url = tr.comment(repo, target.number, render_comment(draft, occurrence), budget())
        return Outcome("+1", sig, url, target.number, [f"issue: {target.url} +1"]), ""
    closed = sorted((i for i in matches if i.state != "open"), key=lambda i: (i.closed_at or "", i.number))
    if closed:
        closed_issue = closed[-1]
        if "wontfix" in closed_issue.labels:
            c = closed_issue
            return Outcome("suppressed", sig, c.url, c.number, [f"issue: not filed again: suppressed by #{c.number} (wontfix) {c.url}"]), ""
    title, body = render(draft, closed=closed_issue)
    with _ledger_lock():
        if _recent(repo, window) >= cap:
            reason = f"cap of {cap} new issues per {_window_text(window)} reached"
            span = "24-hour" if window == WINDOW_S else _window_text(window)
            line = f"issue: not filed: {reason}; kept pending, retried once the {span} window allows it"
            return Outcome("pending", sig, None, None, [line]), reason
        url = tr.create(repo, title, body, draft.label_list(), budget())
        _ledger_add(repo, sig, url, window)
    m = re.search(r"/issues/(\d+)\s*$", url)
    return Outcome("new", sig, url, int(m.group(1)) if m else None, [f"issue: {url} new"]), ""


def _pending(sig: str, reason: str) -> Outcome:
    return Outcome("pending", sig, None, None, [f"issue: not filed: {reason}; kept pending, retried at the next run store flush"])


def _file_with_reason(draft: Draft, run_id: str | None, timeout: float, cap: int, window: float) -> tuple[Outcome, str]:
    try:
        return _file(draft, run_id, timeout, cap, window)
    except TrackerError as e:
        reason = str(e) or "tracker error"
    except Exception as e:  # noqa: BLE001  (filing never raises)
        reason = f"{type(e).__name__}: {e}"
    return _pending(draft.signature, reason), reason


def file(draft: Draft, *, run_id: str | None = None, timeout: float = TIMEOUT_S, cap: int = CAP,
         window: float = WINDOW_S, record: bool = True) -> Outcome:
    """File, comment on, suppress or keep pending. Never raises. With record=True and a run id the result goes to
    `runs.filed`."""
    rid = run_id or draft.run_id
    # A live call (record=True) is a new occurrence even inside the same run; only a retry (record=False, from
    # retry_filing or a caller that repeats a filing) is idempotent per run and signature.
    out, _ = _file_with_reason(draft, None if record else rid, timeout, cap, window)
    if record and rid and out.result != "off":
        try:
            runs.filed(rid, draft.signature, out.url, out.result, filer="autoissue",
                       payload={"draft": draft.to_payload(), "cap": cap, "window": window})
        except Exception:  # noqa: BLE001
            pass
    return out


def retry_filing(entry: dict, timeout: float) -> tuple[str, str]:
    """087's filer. Raises RuntimeError(reason) while the filing is pending or off; else (url, result)."""
    payload = entry.get("payload") or {}
    draft = Draft.from_payload(payload["draft"])
    out, reason = _file_with_reason(draft, entry.get("run_id") or draft.run_id, timeout,
                                    int(payload.get("cap", CAP)), float(payload.get("window", WINDOW_S)))
    if out.result == "off":
        raise RuntimeError("automatic filing is off (CPLAT_AUTO_ISSUES=off)")
    if out.result == "pending":
        raise RuntimeError(reason or "pending")
    return out.url or "", out.result


# ---------------- crashes ----------------

def _crash_command(argv: list[str]) -> str:
    if not argv:
        return "cplat"
    command = f"cplat {argv[0]}"
    if argv[0] in SUBCOMMAND_GROUPS:
        skip = False
        for token in argv[1:]:
            if skip:
                skip = False
            elif token.startswith("--"):
                skip = "=" not in token
            elif re.fullmatch(r"[a-z][a-z-]*", token):
                return f"{command} {token}"
    return command


def _innermost_frame(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    root = Path(__file__).resolve().parent
    for fr in reversed(frames):
        try:
            rel = Path(fr.filename).resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        return f"{rel.as_posix()}:{fr.name}"
    return f"<outside>:{frames[-1].name if frames else '<module>'}"


def _git_branch(cwd: Path) -> str | None:
    try:
        out = core.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, check=False).stdout.strip()
        return out if out and out != "HEAD" else None
    except Exception:  # noqa: BLE001
        return None


def crash_draft(argv: list[str], exc: BaseException, run_id: str, cwd: Path) -> Draft:
    command = _crash_command(argv)
    sig = raw_signature("platform", command, type(exc).__name__, _innermost_frame(exc))
    rec = runs.active(run_id) or {}
    open_phases = [p["name"] for p in rec.get("phases", []) if p.get("ended_at") is None]
    first = (str(exc).strip().splitlines() or [""])[0]
    trace = "".join(traceback.format_exception(exc)).splitlines()[-20:]
    try:
        shape = core.read_stamp(Path(cwd)).get("shape", "none")
    except Exception:  # noqa: BLE001
        shape = "none"
    return Draft(kind="platform", signature=sig, reason=f"{command} crashed: {type(exc).__name__}: {first}", command=command,
                 phase=open_phases[-1] if open_phases else "none", evidence="\n".join(trace), run_id=run_id, shape=shape,
                 names=private_names(rec.get("repo"), rec.get("spec"), _git_branch(Path(cwd))),
                 environment=feedback.diagnostics(Path(cwd)))


def file_crash(argv: list[str], exc: BaseException, run_id: str, cwd: Path) -> Outcome:
    return file(crash_draft(argv, exc, run_id, cwd), run_id=run_id)
