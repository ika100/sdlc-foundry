"""`cplat next` build state (spec 193): the queue, the running build, the stops, the release sections, the deploy steps and the
flow of the delivery process, read from local files and git (design.md `build`). Nothing here writes: no state file, no `gh`
writing verb, no claim.

Public API:
- `collect(repo_dir, slug, shape, local, items, src) -> dict | None`: the `build` object of the `--json` document (None in a repo
  where no queue, no build, no running item and no deploy step exists). `items` are the waiting needs items; each stopped one
  (`escalation`, `stuck`, `budget`) gets its `stop` here. Each source is read in its own `try`; a failing one is listed under
  `src` (`needs._Sources.fail`) and leaves its keys empty or null, never raised.
- `stop_of(item, slug, *, events=(), now=None) -> dict | None`: the `stop` of a stopped item (None when it is not a dispatcher
  unit's stop).
- `release_sections(repo_dir, shape, subjects) -> dict`: `{"Fixed", "Added", "Changed"}` lines of a release item (platform: the
  fragments of `docs/changelog.d`; other component shapes: the first-parent subjects).
- `ref_of(key)`, `key_of(item)`, `estimate(history, kind)`: item words and the median estimates the screens share.

Git goes through `nextstate.git`, GitHub through `needs.gh`, the clock through `dispatch_state.now` (local) and `notify.now` (UTC).
"""
from __future__ import annotations

import datetime
import re
import statistics
from pathlib import Path

import comprelease
import core
import dispatch_answer
import dispatch_budget
import dispatch_cycle
import dispatch_policy
import dispatch_setup
import dispatch_state as ds
import dispatch_units
import dispatch_view
import needs
import notify
import platrelease_changelog
import runlist
import runs
import runs_report

MIN_COMPARABLE = 3
SECTIONS = ("Fixed", "Added", "Changed")
EVENT_WORDS = ("started", "done", "escalated", "red", "stuck", "stale")
PERSON_DAYS = 366
NOT_COMPONENTS = ("gitops-app", "cluster-gitops")


def _git(repo: Path, *args: str) -> str:
    import nextstate
    return nextstate.git(repo, *args)


def _try(src, name: str, kinds: list[str], fn, default):
    """`fn()`, or `default` with the failure listed under `src` as `name`."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - a source that fails is unavailable, never raised
        src.fail(name, e, kinds)
        return default


# ---------------- item words ----------------

def ref_of(key: str) -> str:
    """`#123` for `issue-123`, `spec 123` for `spec-123`."""
    return f"#{key[6:]}" if key.startswith("issue-") else f"spec {int(key[5:])}"


def key_of(item: object) -> str | None:
    """The key of an item as an event or a unit writes it (`#7`, `issue-7`, `spec-7`), None when it names none."""
    try:
        return ds.parse_item(str(item))
    except ds.ItemRefused:
        return None


def _spec_key(spec_id: object) -> str | None:
    m = re.match(r"(\d+)", str(spec_id or ""))
    return f"spec-{int(m.group(1)):03d}" if m else None


def _spec_titles(local: dict) -> dict[str, str]:
    out = {}
    for sid, s in local.items():
        key = _spec_key(sid)
        if key and s.meta.get("title"):
            out[key] = str(s.meta["title"])
    return out


def _what(key: str, titles: dict[str, str]) -> str:
    return titles.get(key) or (f"a fix for #{key[6:]}" if key.startswith("issue-") else ref_of(key))


# ---------------- estimates ----------------

def _minutes(entry: dict) -> float | None:
    try:
        start = datetime.datetime.fromisoformat(str(entry["started_at"]))
        end = datetime.datetime.fromisoformat(str(entry["ended_at"]))
        if (start.tzinfo is None) != (end.tzinfo is None):
            return None
        return (end - start).total_seconds() / 60
    except (KeyError, ValueError):
        return None


def estimate(history: list[dict], kind: str) -> tuple[int | None, int | None]:
    """(minutes, tokens): the medians of at least three done runs of this kind with both times and a token count, minutes rounded
    to 5 (at least 5), tokens to 100,000 (at least 100,000); (None, None) below three."""
    rows = []
    for h in history:
        tokens = h.get("tokens")
        minutes = _minutes(h)
        if h.get("outcome") == "done" and h.get("kind") == kind and minutes is not None and minutes >= 0 \
                and isinstance(tokens, int) and not isinstance(tokens, bool):
            rows.append((minutes, tokens))
    if len(rows) < MIN_COMPARABLE:
        return None, None
    minutes = statistics.median(m for m, _ in rows)
    tokens = statistics.median(t for _, t in rows)
    return max(5, int(round(minutes / 5.0)) * 5), max(100_000, int(round(tokens / 100_000)) * 100_000)


# ---------------- release sections ----------------

def _summary(body: str) -> str:
    m = re.match(r"\s*\*\*(.+?)\*\*", body, re.S)
    first = m.group(1) if m else next((ln for ln in body.splitlines() if ln.strip()), "")
    return re.sub(r"\s+", " ", first.replace("**", "")).strip().rstrip(".").strip()


def release_sections(repo_dir: Path | str, shape: str | None, subjects: list[str]) -> dict[str, list[str]]:
    """The lines of a release item by section. Platform: the bold summary of each fragment without `**` and the final `.` (the
    section from the file name; a fragment that cannot be read is left out). Other shapes: each first-parent subject (not the
    release follow-up), `fix…:` as Fixed, `feat…:` as Added, anything else as Changed, as written."""
    out: dict[str, list[str]] = {s: [] for s in SECTIONS}
    if shape == "platform":
        for name, text in platrelease_changelog.read_fragments(repo_dir):
            title, body = platrelease_changelog.parse_fragment(name, text)
            if line := _summary(body):
                out.setdefault(title, []).append(line)
        return out
    for subject in subjects:
        if comprelease.FOLLOW_UP.match(subject):
            continue
        section = "Fixed" if re.match(r"fix(\([^)]*\))?!?:", subject, re.I) else \
            "Added" if re.match(r"feat(\([^)]*\))?!?:", subject, re.I) else "Changed"
        out[section].append(subject)
    return out


# ---------------- stops ----------------

def _now() -> datetime.datetime:
    when = notify.now()
    return when if when.tzinfo else when.astimezone()


def _asked_minutes(item: dict, now: datetime.datetime | None) -> int:
    import nextstate
    since = nextstate._when(item.get("since"))
    return max(0, int(((now or _now()) - since).total_seconds() // 60)) if since else 0


def _unit_key(item: dict) -> str | None:
    obj = item.get("object") or {}
    if obj.get("issue"):
        return f"issue-{int(obj['issue'])}"
    return _spec_key(obj.get("spec"))


def _question_of(q: object) -> dict | None:
    if isinstance(q, dict):
        text = str(q.get("text") or "").strip()
        options = [str(o) for o in q.get("options") or [] if str(o).strip()]
        if not options and q.get("suggested"):
            options = [str(q["suggested"])]       # a ship state written before spec 193 keeps only the suggested answer
        return {"text": text, "options": options} if text else None
    text = str(q or "").strip()
    return {"text": text, "options": []} if text else None


def stop_of(item: dict, slug: str, *, events=(), now: datetime.datetime | None = None) -> dict | None:
    """The `stop` of a stopped item (design.md): None for an item that is not a dispatcher unit's stop. A budget item gets
    `kind: budget`; a unit that ended `escalated` with cause `decision` is a decision, every other stop a failure."""
    kind = item.get("kind")
    asked = _asked_minutes(item, now)
    empty = {"key": None, "ref": None, "branch": None, "log": None, "phase": None, "worktree": None, "spec_path": None,
             "tried": [], "questions": [], "answered": [], "asked_minutes": asked}
    if kind == "budget":
        return {"kind": "budget", **empty}
    key = _unit_key(item)
    if kind not in ("escalation", "stuck") or key is None:
        return None
    worktree = ds.worktree_path(slug, key)
    unit = ds.read_unit(worktree) if worktree.is_dir() else None
    if unit is None:
        return None
    try:
        state = dispatch_answer._stop_state(worktree)
    except Exception:  # noqa: BLE001 - an unreadable ship state leaves the questions out
        state = None
    questions = [q for q in map(_question_of, (state or {}).get("questions") or []) if q]
    answered = sorted(int(k) for k in (unit.get("answers") or {}) if str(k).isdigit())
    name = unit.get("unit")
    red = any(e.get("kind") == "red" and e.get("unit") == name for e in events)
    tried = [*(["restarted once"] if int(unit.get("starts") or 0) >= 2 else []),
             *(["landing restarted once"] if int(unit.get("land_starts") or 0) >= 2 else []),
             *(["check rerun once"] if red else [])]
    spec_id = unit.get("spec") or (item.get("object") or {}).get("spec")
    decision = unit.get("status") == "escalated" and unit.get("cause") == "decision" and not red
    return {"kind": "decision" if decision else "failure", "key": key, "ref": ref_of(key), "branch": unit.get("branch"),
            "log": unit.get("log"), "reason": unit.get("reason"), "phase": (state or {}).get("phase"), "worktree": str(worktree),
            "spec_path": str(worktree / "docs" / "specs" / str(spec_id) / "spec.md") if spec_id and key.startswith("spec-") else None,
            "tried": tried, "questions": questions, "answered": answered, "asked_minutes": asked}


# ---------------- person time ----------------

def _person_lines() -> list[dict]:
    """The `person` follow-ups of the store (when one is configured) and the buffer, one per run id; raises when neither reads."""
    found: dict[str, dict] = {}
    if runs.configured_repo():
        status = runs.store_status()
        if status.state == "ok" and status.slug:
            now = runs.utcnow()
            days = [now.date() - datetime.timedelta(days=n) for n in range(PERSON_DAYS, -1, -1)]
            files = runlist.read_days(runs.open_store(status.slug), status.slug, days)
            for f in runs_report.parse([text for _, text in files])[1]:
                found[str(f.get("run_id"))] = f
    for f in runs._safe_buffer():
        if f.get("followup"):
            found[str(f.get("run_id"))] = f
    return [f for f in found.values() if f.get("followup") == "person"]


def _person_of(lines: list[dict], slug: str, keys: set[str]) -> tuple[int, float | None]:
    """(questions, minutes) of the person lines of these item keys; minutes is None without a matching line."""
    questions, minutes, seen = 0, 0.0, False
    for f in lines:
        if f.get("repo") != slug:
            continue
        key = f"issue-{int(f['issue'])}" if f.get("issue") is not None else _spec_key(f.get("spec"))
        if key in keys:
            seen = True
            questions += int(f.get("questions") or 0)
            minutes += float(f.get("minutes") or 0)
    return questions, round(minutes, 2) if seen else None


# ---------------- tags and deploy ----------------

def _tags(repo_dir: Path) -> list[tuple[str, datetime.datetime | None]]:
    """The `v*` tags, newest version first, with the local time each was created."""
    out = []
    for line in _git(repo_dir, "for-each-ref", "--sort=-v:refname", "--format=%(refname:short)|%(creatordate:unix)", "refs/tags/v*").splitlines():
        name, _, stamp = line.partition("|")
        try:
            when = datetime.datetime.fromtimestamp(int(stamp))
        except (ValueError, OSError, OverflowError):
            when = None
        if name:
            out.append((name, when))
    return out


def _head(repo_dir: Path) -> str:
    return _git(repo_dir, "rev-parse", "origin/main") or _git(repo_dir, "rev-parse", "HEAD")


def _deploy(repo_dir: Path, shape: str | None, items: list[dict], tags: list[tuple[str, object]]) -> dict | bool:
    """The deploy document of a deployable component repo, `False` when the repo is not linked to a gitops-app component."""
    import ship
    import staging
    found = staging._find(repo_dir, ship.gitops_apps(repo_dir), ship.service_name(repo_dir))
    if found is None:
        return False
    import comprelease
    app, _dir, comp, model, me = found
    name = comp.name
    promotion = "after-dev-smoke" if model.staging_promotion(comp) == "after-dev-smoke" else "manual"
    head = _head(repo_dir)
    step, version = None, None
    inst = model.instance(name, "staging")
    first = inst is None    # `release target` refuses without staging (comprelease.no_staging); its first promotion is manual (#920)
    if first or (promotion == "manual" and (not head or staging.resolve(me, inst.tag, repo_dir) != head)):
        step, version = "staging", head[:7] or None
    if step is None and any(i.get("kind") == "release" for i in items):
        # the release tags the commit staging runs: offered unless that commit is released already (`release target`, #920)
        runs_now = head if promotion == "manual" else staging.resolve(me, inst.tag, repo_dir)
        if not (runs_now and comprelease.released_as(repo_dir, runs_now)):
            step = "release"
    if step is None and tags:
        prod = model.instance(name, "prod")
        newest = tags[0][0]
        if prod is None or str(prod.tag).lstrip("v") != newest.lstrip("v"):
            step, version = "prod", newest
    return {"component": name, "staging": promotion, "step": step, "version": version, "head": head, "app": app,
            "first_staging": first and step == "staging",
            "missing_backups": needs.missing_prod_backups(model, [name]) if step == "prod" else []}


def promote_item(slug: str, deploy: dict, since: str) -> dict | None:
    """The promote item of the deploy step (staging or prod), None for the release step or none."""
    step, name, version = deploy.get("step"), deploy["component"], deploy.get("version")
    if step not in ("staging", "prod") or not version:
        return None
    shown = version if step == "staging" else version.lstrip("v")
    command = f"/instance:promote {name} --to staging" if step == "staging" else f"/instance:promote {name} --to prod --version {version}"
    first = bool(deploy.get("first_staging"))
    reason = f"{name} {shown} can go to {step}" + (": the first promotion to staging is manual" if first else "")
    consequence = {"env": step, "first": first, "app": deploy.get("app"),
                   "missing_backups": list(deploy.get("missing_backups") or [])}
    if step == "prod":
        consequence["staging_smoke"] = _staging_smoke(slug, version)
    return {"id": f"promote:{name}:{shown}", "kind": "promote", "stage": "Staging" if step == "staging" else "Prod",
            "object": needs._obj("component", slug, component=name, version=shown), "since": since,
            "reason": reason, "command": command, "cwd_repo": deploy.get("app") or slug,
            "consequence": consequence, "way_back": None}


def _staging_smoke(slug: str, version: str) -> str | None:
    """The outcome of the staging smoke of release `version` ("none" without a record, #946); None when no run store is set,
    so the question cannot tell."""
    import runs
    import status
    if not runs.configured_repo():
        return None
    return str((status._smoke(slug, version, "staging") or {}).get("outcome") or "none")


# ---------------- events ----------------

def _events(st: dict, current: dict | None, titles: dict[str, str]) -> list[dict]:
    if not current:
        return []
    since = str(current.get("started_at") or "")
    out = []
    for e in st.get("events") or []:
        if e.get("kind") not in EVENT_WORDS or str(e.get("at") or "") < since:
            continue
        key = key_of(e.get("item"))
        out.append({"seq": int(e.get("seq") or 0), "at": str(e.get("at") or ""), "time": str(e.get("at") or "")[11:16],
                    "kind": e["kind"], "key": key,
                    "ref": ref_of(key) if key else str(e.get("item") or ""), "unit": e.get("unit"),
                    "what": _what(key, titles) if key else "", "pr": e.get("pr")})
    return out


def _running(slug: str, titles: dict[str, str]) -> list[dict]:
    import nextstate
    out = []
    for u in ds.all_units(slug):
        if u.get("status") in dispatch_units.ENDED:
            continue
        key = u.get("key") or key_of(u.get("item"))
        if key:
            phase = dispatch_view._phase(u)
            out.append({"key": key, "ref": ref_of(key), "what": _what(key, titles), "step": nextstate._STEP.get(phase, phase)})
    return out


def _closed(slug: str, numbers: set[int]) -> list[int]:
    import json
    rows = json.loads(needs.gh(["issue", "list", "-R", slug, "--state", "closed", "--limit", "500", "--json", "number"]) or "[]")
    return sorted(n for n in (r.get("number") for r in rows if isinstance(r, dict)) if n in numbers)


# ---------------- collect ----------------

def _queue(repo_dir: Path, policy, history: list[dict]) -> list[dict]:
    out = []
    for q in dispatch_cycle.preview(repo_dir, policy):
        minutes, tokens = estimate(history, q.get("kind"))
        out.append({**q, "you_get": q.get("title"), "minutes": minutes, "tokens": tokens})
    return out


def collect(repo_dir: Path | str, slug: str, shape: str | None, local: dict, items: list[dict], src) -> dict | None:
    """The `build` object (module docstring); also puts each stopped item's `stop` into `items`."""
    repo_dir = Path(repo_dir)
    st = ds.load(slug)
    policy = _try(src, "dispatcher", ["build"], lambda: dispatch_policy.load(repo_dir), None)
    history = [h for h in st.get("history") or [] if isinstance(h, dict)]
    queue = _try(src, "dispatcher", ["build"], lambda: _queue(repo_dir, policy, history), []) if policy else []
    titles = {**_spec_titles(local), **{q["key"]: q["title"] for q in queue if q.get("title")}}
    events_all = st.get("events") or []
    for item in items:
        if item.get("kind") in ("budget", "escalation", "stuck"):
            item["stop"] = _try(src, "dispatcher", [str(item["kind"])], lambda i=item: stop_of(i, slug, events=events_all), None)
    current = ds.build_of(slug)
    running = _try(src, "dispatcher", [], lambda: _running(slug, titles), [])
    events = _events(st, current, titles)
    alive = ds.loop_alive(slug)
    deploy: dict | None | bool = False        # False: not a deployable component; None: the gitops-app could not be read
    deployable = False
    if shape and shape not in NOT_COMPONENTS:
        deployable = bool(_try(src, "repo", [], lambda: core.registry.get(shape)["deployable"], False))
    tags = _try(src, "repo", [], lambda: _tags(repo_dir), []) if deployable or current else []
    if deployable:
        deploy = _try(src, "gitops-app", ["promote", "release"], lambda: _deploy(repo_dir, shape, items, tags), None)
    if not (queue or current or running or isinstance(deploy, dict)):
        return None
    steering = st["steering"]
    started = [e for e in events if e["kind"] == "started"]
    ended = bool(current) and bool(started) and not running and not queue
    limit = used = None
    if policy:
        limit = _try(src, "dispatcher", [], lambda: dispatch_budget.limit_of(policy, slug), None)
        used = dispatch_budget.usage_today(slug).used
    minutes_all = [q["minutes"] for q in queue]
    tokens_all = [q["tokens"] for q in queue]
    build: dict = {
        "policy": bool(policy and policy.file), "setup": None, "queue": queue,
        "total_minutes": sum(minutes_all) if queue and None not in minutes_all else None,
        "need_tokens": sum(tokens_all) if queue and None not in tokens_all else None,
        "tokens": {"used": used or 0, "limit": limit, "raised": bool(policy) and limit != dispatch_budget.policy_limit(policy)},
        "loop": {"running": alive, "pid": ds.loop_pid(slug) if alive else None},
        "slots": int(steering.get("slots") or (policy.values["slots"] if policy else 0)) or None,
        "paused": steering.get("paused"), "current": current, "events": events,
        "last_seq": max([int(e.get("seq") or 0) for e in events_all] + [int(st.get("event_seq") or 0)]),
        "running": running, "ended": ended}
    if policy and not policy.file:
        def setup() -> dict:
            n = dispatch_setup.suggest(slug)
            return {"tokens_per_day": n, "file": dispatch_setup.text(n)}
        build["setup"] = _try(src, "dispatcher", ["build"], setup, {"tokens_per_day": None, "file": dispatch_setup.text(None)})
    keys = {e["key"] for e in events if e.get("key")}
    lines = None
    if current:
        lines = _try(src, "runs", [], _person_lines, None)
    if ended:
        build["totals"] = _totals(st, events, keys, lines, slug)
    if deploy is not False:
        build["deploy"] = deploy
    if current:
        build["flow"] = _flow(repo_dir, slug, local, st, keys, events, current, tags, lines, build, items, src)
    return build


def _totals(st: dict, events: list[dict], keys: set[str], lines: list[dict] | None, slug: str) -> dict:
    totals: dict = {}
    first = min((e["at"] for e in events if e["kind"] == "started"), default=None)
    last = max((e["at"] for e in events if e["kind"] == "done"), default=None)
    try:
        if first and last and last >= first:
            span = datetime.datetime.fromisoformat(last) - datetime.datetime.fromisoformat(first)
            totals["wall_minutes"] = int(span.total_seconds() // 60)
    except ValueError:
        pass
    units = {e["unit"] for e in events if e.get("unit")}
    counted = st.get("counted") or {}
    if units and all(isinstance(counted.get(u), int) for u in units):
        totals["tokens"] = sum(counted[u] for u in units)
    if lines is not None:
        totals["questions"] = _person_of(lines, slug, keys)[0]
    return totals


def _flow(repo_dir: Path, slug: str, local: dict, st: dict, keys: set[str], events: list[dict], current: dict,
          tags: list[tuple[str, datetime.datetime | None]], lines: list[dict] | None, build: dict, items: list[dict], src) -> dict:
    numbers = {int(k[6:]) for k in keys if k.startswith("issue-")}
    for sid, s in local.items():
        if _spec_key(sid) in keys:
            numbers |= {int(n) for n in s.meta.get("tracks") or [] if str(n).isdigit()}
    closed = _try(src, "github", [], lambda: _closed(slug, numbers), []) if numbers else []
    try:
        began = datetime.datetime.fromisoformat(str(current.get("started_at")))
    except ValueError:
        began = None
    released = next((name for name, when in tags if began and when and when >= began), None)
    minutes = _person_of(lines, slug, keys)[1] if lines is not None else None
    skipped = (st["steering"].get("skipped") or {})
    deploy = build.get("deploy")
    waiting = bool(items) or (isinstance(deploy, dict) and deploy.get("step") is not None)
    return {"done": bool(build["ended"] and released and not waiting), "issues_closed": closed, "released": released,
            "your_minutes": minutes, "parked": [{"ref": ref_of(k), "reason": str((v or {}).get("reason") or "")}
                                               for k, v in skipped.items() if k.startswith(("issue-", "spec-"))]}
