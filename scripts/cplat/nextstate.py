"""`cplat next` state (spec 192): every source the screen and the questions read, collected read-only.

Public API:
- `collect(repo_dir) -> state`: the `needs` items of the repo or system, release items, running work, the parked count,
  the notification channels, the notified age of each item and the size estimates. Each source is read in its own `try`;
  a failing one is listed under `state["unavailable"]` (`{source, error, kinds}`), never raised. Nothing here writes: no
  `gh` writing verb, no state file, no run record, no claim.
- `groups(state, later) -> (group, shown, also, later_count)`: the group that is shown (`stopped`, `specs`, `issues`,
  `release` or None), its items oldest first, the count per kind of every other waiting item not put off (in group
  order), and how many items `later` puts off.
- `plain(text)`: the plain words of the screen (no dispatcher, slot, unit, claim, escalation or held).
- `what(item)`, `size_of(criteria)`, `assumption_of(text)`: item descriptions the screen and the questions share.

State: `{repo, shape, system, items, running, slots, parked, channels, estimates, unavailable}`. An item is a needs item
plus `group`, `what`, `notified_at`, `waiting_minutes` and, for `answer` and `approve`, a `draft` dict (`spec`, `title`,
`tracks`, `criteria`, `size`, `assumptions`, `questions`, `problem`, `pr`, `url`). A release item (`kind: release`) has
`consequence.changes` (titles) and `consequence.since_tag`. A running entry is `{what, step, bar_step, spec, issue}`.
Git goes through the module-level `git(repo, *args)`, the clock through `notify.now`.
"""
from __future__ import annotations

import datetime
import json
import re
import statistics
from pathlib import Path

import comprelease
import dispatch_policy
import dispatch_state
import dispatch_notify
import dispatch_view
import needs
import notify
import notify_config
import runlist
import runs
import shapecmd
import spec as specmod
import stages
from core import run

GROUPS = ("stopped", "specs", "issues", "release")
GROUP_OF = {"escalation": "stopped", "stuck": "stopped", "budget": "stopped", "answer": "specs", "approve": "specs",
            "triage": "issues", "release": "release", "promote": "release", "review": "release"}
KINDS = ("escalation", "stuck", "budget", "answer", "approve", "triage", "release", "promote", "review")
MIN_COMPARABLE = 3
PROBLEM_LIMIT = 600
ASSUMPTION_LIMIT = 120
RELEASE_SHAPES = ("platform", "library-python")
CHANNELS = ("desktop", "github", "slack", "email")
_STEP = {"plan": "planning", "build": "building", "red-tests": "testing", "tests": "testing", "review": "review",
         "verify": "review", "pr": "landing", "land": "landing", "landing": "landing", "deploy": "deploying",
         "staging": "in staging"}
_STAGE = {"plan": "Plan", "pr": "Land", "land": "Land", "landing": "Land", "deploy": "Dev", "staging": "Staging"}
_UNITS = {"escalated": "stopped", "escalation": "stop", "escalate": "stop", "escalates": "stops", "escalating": "stopping"}


def git(repo: Path | str, *args: str) -> str:
    """`git -C repo args`, "" on failure (tests replace this)."""
    r = run(["git", "-C", str(repo), *args], check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


# ---------------- plain words and descriptions ----------------

def _keep_case(old: str, new: str) -> str:
    return new[:1].upper() + new[1:] if old[:1].isupper() else new


def plain(text: str) -> str:
    """The plain words of the screen: whole words, any case; JSON keys and ids keep their names."""
    def esc(m: re.Match) -> str:
        return _keep_case(m.group(0), _UNITS.get(m.group(0).lower(), "stopped"))
    text = re.sub(r"\bescalat\w*", esc, text, flags=re.I)
    for pattern, new in ((r"\bdispatchers?\b", "run queue"), (r"\bslots\b", "places"), (r"\bslot\b", "place"),
                         (r"\bunits\b", "runs"), (r"\bunit\b", "run"), (r"\bclaim\w*", "lock"), (r"\bheld\b", "waiting")):
        text = re.sub(pattern, lambda m, n=new: _keep_case(m.group(0), n), text, flags=re.I)
    return text


def size_of(criteria: int) -> str:
    """Active criteria 1-4 small, 5-8 medium, 9 and more large (0 counts as small)."""
    return "small" if criteria <= 4 else "medium" if criteria <= 8 else "large"


def assumption_of(text: str) -> str:
    """An assumption as the screen shows it: the `**A<n>**` marker and the ` (other option...)` tail removed, 120 characters."""
    text = re.sub(r"^\*\*A\d+\*\*\s*", "", text.strip())
    text = re.sub(r"\s*\(other options?\b.*\)\s*$", "", text, flags=re.I).strip()
    return text if len(text) <= ASSUMPTION_LIMIT else text[:ASSUMPTION_LIMIT - 1].rstrip() + "…"


def _title_of(spec_id: str | None, titles: dict[str, str]) -> str:
    if not spec_id:
        return ""
    number = spec_id.split("-", 1)[0]
    title = titles.get(spec_id)
    return f"{title} (spec {number})" if title else f"spec {number}"


def what(item: dict, titles: dict[str, str] | None = None) -> str:
    """One phrase for an item: a spec title, an issue title, `a fix for #N`, `<component> <version>`."""
    titles, kind, obj = titles or {}, item.get("kind"), item.get("object") or {}
    if kind in ("answer", "approve"):
        return (item.get("draft") or {}).get("title") or _title_of(obj.get("spec"), titles)
    if kind == "triage":
        return re.sub(r"\s*\(not routed yet\)$", "", item.get("reason") or "") or f"issue #{obj.get('issue')}"
    if kind == "budget":
        return "the daily budget"
    if kind == "release":
        return "a release"
    if kind == "promote":
        return f"{obj.get('component')} {obj.get('version')}".strip()
    if kind == "review":
        return f"a fix for #{obj['issue']}" if obj.get("issue") else f"a fix (PR #{obj.get('pr')})"
    if obj.get("issue"):
        return f"a fix for #{obj['issue']}"
    if obj.get("spec"):
        return _title_of(obj["spec"], titles)
    return "a run"


# ---------------- sources ----------------

def _draft(item: dict, local: dict[str, specmod.Spec], estimates: dict) -> None:
    obj = item["object"]
    parsed = needs.draft_spec(obj.get("repo"), obj.get("spec"))
    if parsed is None:
        return
    criteria = len(parsed.active_acs())
    size = size_of(criteria)
    problem = re.sub(r"\s+", " ", specmod.sections(parsed.body).get("problem", "")).strip()
    item["draft"] = {
        "spec": parsed.id, "title": str(parsed.meta.get("title") or parsed.id), "tracks": list(parsed.meta.get("tracks") or []),
        "criteria": criteria, "size": size, "estimate_minutes": estimates.get(size),
        "assumptions": [assumption_of(a) for a in parsed.assumptions()],
        "questions": [specmod._question(q) for q in parsed.open_questions()],
        "problem": problem[:PROBLEM_LIMIT], "pr": obj.get("pr"), "url": obj.get("url")}


def _minutes(row: dict) -> float | None:
    used = (row.get("budget") or {}).get("used") or {}
    if isinstance(used.get("minutes"), (int, float)):
        return float(used["minutes"])
    start, end = _when(row.get("started_at")), _when(row.get("ended_at"))
    return (end - start).total_seconds() / 60 if start and end else None


def _when(text: object) -> datetime.datetime | None:
    """An ISO time as an aware UTC time (a naive one counts as UTC), None when it cannot be read."""
    try:
        when = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _round5(minutes: float) -> int:
    return max(5, int(round(minutes / 5.0)) * 5)


def _estimates(slug: str, rows: list[dict], local: dict[str, specmod.Spec]) -> dict[str, int | None]:
    """Minutes per size: the median of at least three of this repo's done `ship` or `product-ship` runs (the latest per
    spec) whose local spec has that size, rounded to 5."""
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("repo") != slug or r.get("phase") != "done" or r.get("outcome") not in (None, "done"):
            continue
        if r.get("kind") not in ("ship", "product-ship") or r.get("spec") not in local:
            continue
        old = latest.get(r["spec"])
        if old is None or str(r.get("ended_at") or "") > str(old.get("ended_at") or ""):
            latest[r["spec"]] = r
    by_size: dict[str, list[float]] = {"small": [], "medium": [], "large": []}
    for sid, r in latest.items():
        minutes = _minutes(r)
        if minutes is not None:
            by_size[size_of(len(local[sid].active_acs()))].append(minutes)
    return {s: (_round5(statistics.median(v)) if len(v) >= MIN_COMPARABLE else None) for s, v in by_size.items()}


def _release_items(repo_dir: Path, slug: str, shape: str | None) -> list[dict]:
    """A release item when the repo has changes that are not released: fragments (platform) or commits since the last tag."""
    if shape not in RELEASE_SHAPES:
        return []
    tag = git(repo_dir, "describe", "--tags", "--abbrev=0", "--match", "v*") or None
    since, changes = "", []
    if shape == "platform":
        folder = repo_dir / "docs" / "changelog.d"
        files = sorted(p for p in folder.glob("*.md") if p.name != "README.md") if folder.is_dir() else []
        for p in files:
            first = next((ln.strip() for ln in p.read_text(errors="replace").splitlines() if ln.strip()), p.stem)
            changes.append(re.sub(r"\s*\(spec \d+\)\.?$", "", first.replace("**", "")).strip() or p.stem)
        stamps = [git(repo_dir, "log", "--diff-filter=A", "--format=%aI", "--", f"docs/changelog.d/{p.name}") for p in files]
        since = min((t.splitlines()[-1] for t in stamps if t), default="")
        command = "/platform:release"
    else:
        log = git(repo_dir, "log", "--no-merges", "--reverse", "--format=%cI|%s", f"{tag}..HEAD" if tag else "HEAD")
        found = [ln.split("|", 1) for ln in log.splitlines() if "|" in ln and not comprelease.FOLLOW_UP.match(ln.split("|", 1)[1])]
        changes, since = [s for _, s in found], (found[0][0] if found else "")
        command = "/component:release"
    if not changes:
        return []
    when = _when(since)
    since = when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if when else ""
    return [{"id": f"release:{slug}:{tag or 'first'}", "kind": "release", "stage": "Release",
             "object": needs._obj("release", slug, version=tag), "since": since or runs._iso(runs.utcnow()),
             "reason": f"{len(changes)} change{'s' if len(changes) != 1 else ''} since {tag or 'the start'}",
             "command": command, "cwd_repo": slug, "consequence": {"changes": changes, "since_tag": tag}, "way_back": None}]


def _running(repo_dir: Path, slug: str, rows: list[dict], shape: str | None, titles: dict[str, str],
             src: needs._Sources) -> tuple[list[dict], int | None]:
    """The running work, one entry per spec or issue (dispatcher units first, then active run rows), and the places total."""
    found: dict[str, dict] = {}
    slots = None

    def add(key: str, phase: str, spec_id: str | None, issue: int | None) -> None:
        if key in found:
            return
        stage = _STAGE.get(phase, "Build")
        found[key] = {"what": _title_of(spec_id, titles) if spec_id else f"a fix for #{issue}", "step": _STEP.get(phase, phase),
                      "bar_step": stages.bar_step(stage, shape), "spec": spec_id, "issue": issue}
    try:
        doc = dispatch_view.status_doc(repo_dir, slug, dispatch_policy.load(repo_dir))
        slots = int((doc.get("slots") or {}).get("total") or 0) or None
        for u in (doc.get("slots") or {}).get("units") or []:
            item = str(u.get("item") or "")
            m = re.fullmatch(r"(spec|issue)-(\d+)", item)
            if not m:
                continue
            if m.group(1) == "issue":
                add(f"issue-{m.group(2)}", str(u.get("phase") or ""), None, int(m.group(2)))
            else:
                sid = next((s for s in titles if s.split("-", 1)[0].lstrip("0") == m.group(2).lstrip("0")), None)
                add(f"spec-{int(m.group(2))}", str(u.get("phase") or ""), sid, None)
    except Exception as e:  # noqa: BLE001
        src.fail("dispatcher", e, ["budget", "stuck"])
    for r in rows:
        if r.get("repo") != slug or not r.get("active") or r.get("stopped"):
            continue
        issue = needs._issue_of(r)
        if r.get("spec"):
            add(f"spec-{int(r['spec'].split('-', 1)[0] or 0)}", str(r.get("phase") or ""), r["spec"], None)
        elif issue:
            add(f"issue-{issue['number']}", str(r.get("phase") or ""), None, issue["number"])
    return list(found.values()), slots


def _notified(state_files: list[Path], items: list[dict]) -> None:
    """`notified_at` and `waiting_minutes`: the earliest send that is not a held one, from the notifier state files."""
    sent: dict[str, str] = {}
    for path in state_files:
        events = (notify.load_state(path) or {}).get("events")
        for key, rec in (events or {}).items() if isinstance(events, dict) else []:
            for entry in ((rec or {}).get("sent") or {}).values():
                if isinstance(entry, dict) and entry.get("ref") != notify.HELD and entry.get("at"):
                    if key not in sent or str(entry["at"]) < sent[key]:
                        sent[key] = str(entry["at"])
    now = notify.now()
    now = now if now.tzinfo else now.astimezone()
    for item in items:
        at = _when(sent.get(item["id"]))
        if at is not None:
            item["notified_at"] = sent[item["id"]]
            item["waiting_minutes"] = max(0, int((now - at).total_seconds() // 60))


def _channels(shape: str | None, src: needs._Sources) -> list[str] | None:
    """The channels a stopped run reaches the person on, desktop first; None when the settings cannot be read."""
    try:
        cells = notify_config.cells_for(notify_config.load(), "escalation", shape)
    except Exception as e:  # noqa: BLE001
        src.fail("notifications", e, [])
        return None
    return [c for c in CHANNELS if cells.get(c, "off") != "off"]


def collect(repo_dir: Path | str) -> dict:
    """The state of one repo (see the module docstring); read-only, exits through `unavailable` rather than raising."""
    repo_dir = Path(repo_dir)
    slug = dispatch_state.slug_of(repo_dir)
    src = needs._Sources()
    try:
        shape = shapecmd.resolve(repo_dir)
    except Exception:  # noqa: BLE001 - an unreadable shape gets the release bar
        shape = None
    try:
        local = {s.id: s for s in specmod.scan(repo_dir)[0]}
    except Exception:  # noqa: BLE001
        local = {}
    titles = {sid: str(s.meta.get("title") or "") for sid, s in local.items() if s.meta.get("title")}
    try:
        rows = runlist.collect(30)["runs"]
    except Exception as e:  # noqa: BLE001
        rows = []
        src.fail("runs", e, ["escalation"])
    estimates = _estimates(slug, rows, local)
    system = False
    try:
        system = any(repo_dir.glob("applications/*/system.yaml"))
        doc = needs.collect(repo_dir) if system else needs.collect_repo(repo_dir)
    except Exception as e:  # noqa: BLE001
        doc = {"system": slug.rsplit("/", 1)[-1], "items": [], "unavailable": []}
        src.fail("github", e, ["approve", "answer", "triage"])
    items = [dict(i) for i in doc.get("items") or []]
    try:
        items += _release_items(repo_dir, slug, shape)
    except Exception as e:  # noqa: BLE001
        src.fail("github", e, ["release"])
    for item in items:
        item["group"] = GROUP_OF.get(item.get("kind"), "release")
        if item.get("kind") in ("answer", "approve"):
            _draft(item, local, estimates)
        item["what"] = what(item, titles)
    running, slots = _running(repo_dir, slug, rows, shape, titles, src)
    try:
        parked = len(dispatch_state.load(slug)["steering"]["skipped"])
    except Exception as e:  # noqa: BLE001
        parked = 0
        src.fail("dispatcher", e, ["budget", "stuck"])
    _notified([notify.state_path(str(doc.get("system") or slug.rsplit("/", 1)[-1])), dispatch_notify.notify_path(slug)], items)
    channels = _channels(shape, src)
    items.sort(key=lambda i: i.get("since") or "")
    return {"repo": slug, "shape": shape, "system": doc.get("system"), "items": items, "running": running, "slots": slots,
            "parked": parked, "channels": channels, "estimates": estimates,
            "unavailable": [*doc.get("unavailable", []), *src.listing()]}


# ---------------- grouping ----------------

def groups(state: dict, later=()) -> tuple[str | None, list[dict], dict[str, int], int]:
    """(group shown, its items oldest first, count per kind of every other waiting item not put off, items put off)."""
    later = set(later)
    waiting = [i for i in state["items"] if i["id"] not in later]
    group = next((g for g in GROUPS if any(i["group"] == g for i in waiting)), None)
    shown = sorted((i for i in waiting if i["group"] == group), key=lambda i: i.get("since") or "")
    other = [i for i in waiting if i["group"] != group]
    also = {k: n for k in KINDS if (n := sum(1 for i in other if i["kind"] == k))}
    return group, shown, also, sum(1 for i in state["items"] if i["id"] in later)


def dump(state: dict) -> str:
    """The state as JSON (for tests and debugging)."""
    return json.dumps(state, indent=2, default=str)
