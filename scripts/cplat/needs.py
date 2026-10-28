"""`cplat needs [--json] [--repo-dir DIR] [--system NAME]`: every open decision point of a system (spec 122, AC-122.4).

Five kinds: a draft spec is `answer` (open questions) or `approve`, an escalated run is `escalation`, a release verified in
staging and not in prod is `promote`, an unrouted alert or smoke issue is `triage`. Each item carries the consequence and the
way back of its decision (AC-122.34, AC-122.35). A source that fails is listed under `unavailable` with the kinds it hides;
the exit stays 0. GitHub goes through the replaceable `gh`.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import re
import statistics
import sys
from pathlib import Path

import autonomy
import engine_issue
import gitops
import model
import releases
import runlist
import runs
import spec as specmod
import stages
import status
from core import PlatformError, run

SCHEMA = 1
MARKER = re.compile(r"<!--\s*cplat:spec\s+(\S+)\s*-->")
CREATED = re.compile(r"^\s*[-*]\s+(\d{4}-\d{2}-\d{2})\b", re.MULTILINE)
UNATTENDED = ["Plan", "Build", "Land", "Dev", "Staging"]
TRIAGE_LABELS = {"alert", "smoke-failure", "signal"}
MIN_COMPARABLE = 3


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


class _Sources:
    """Collects the failures of the sources, one entry per source and error, with the kinds each hides."""

    def __init__(self) -> None:
        self.failed: dict[tuple[str, str], list[str]] = {}

    def fail(self, source: str, error: object, kinds: list[str]) -> None:
        text = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        known = self.failed.setdefault((source, text), [])
        known.extend(k for k in kinds if k not in known)

    def listing(self) -> list[dict]:
        return [{"source": s, "error": e, "kinds": k} for (s, e), k in self.failed.items()]


def find_system(repo_dir: Path, system: str | None) -> Path:
    """The `applications/<system>` directory; without a system.yaml the error names the file and the directory searched."""
    try:
        return gitops.find_app(repo_dir, system)
    except PlatformError as e:
        if str(e).startswith("no applications/*/system.yaml"):
            raise PlatformError(f"no applications/<system>/system.yaml in {repo_dir}",
                                hint="run this inside a gitops-app repo, or pass --repo-dir") from None
        raise


def _slug_of(url: str | None) -> str | None:
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", (url or "").strip())
    return m.group(1) if m else None


def _repos(repo_dir: Path, m: model.Model) -> tuple[str | None, list[str]]:
    """(gitops repo slug or None, every repo of the system with the gitops repo first)."""
    gitops_slug = _slug_of(status.sh(["git", "-C", str(repo_dir), "remote", "get-url", "origin"]))
    repos = [gitops_slug] if gitops_slug else []
    repos.extend(c.repo for c in m.components if c.repo and c.repo not in repos)
    return gitops_slug, repos


def _json(call: list[str]):
    return json.loads(gh(call) or "null")


def _spec_text(slug: str, spec_id: str, ref: str | None = None) -> str | None:
    path = f"repos/{slug}/contents/docs/specs/{spec_id}/spec.md" + (f"?ref={ref}" if ref else "")
    try:
        out = gh(["api", path, "-H", "Accept: application/vnd.github.raw"])
    except Exception:  # noqa: BLE001 - a spec without spec.md is skipped
        return None
    if out and not out.lstrip().startswith(("---", "#")):
        try:
            return base64.b64decode(json.loads(out).get("content", "")).decode("utf-8", "replace")
        except (ValueError, AttributeError):
            return None
    return out or None


def _parse(spec_id: str, text: str) -> specmod.Spec | None:
    m = specmod.FRONT.match(text)
    if not m:
        return None
    try:
        meta = specmod.yaml.safe_load(m.group(1))
    except specmod.yaml.YAMLError:
        return None
    return specmod.Spec(Path(spec_id), meta, m.group(2)) if isinstance(meta, dict) else None


def _created(spec: specmod.Spec) -> str:
    m = CREATED.search(specmod.sections(spec.body).get("changelog", ""))
    return f"{m.group(1)}T00:00:00Z" if m else ""


def _drafts(slug: str) -> list[dict]:
    """Draft specs of one repo: from `main` and from open draft PRs (the PR wins): `{spec, repo, since, pr, url}`."""
    found: dict[str, dict] = {}
    for entry in _json(["api", f"repos/{slug}/contents/docs/specs"]) or []:
        if entry.get("type") != "dir":
            continue
        text = _spec_text(slug, entry["name"])
        parsed = _parse(entry["name"], text) if text else None
        if parsed and parsed.status == "draft":
            found[entry["name"]] = {"spec": parsed, "repo": slug, "since": _created(parsed), "pr": None, "url": None}
    prs = _json(["pr", "list", "-R", slug, "--state", "open", "--draft", "--json", "number,body,createdAt,url,headRefName"]) or []
    for pr in prs:
        m = MARKER.search(pr.get("body") or "")
        text = _spec_text(slug, m.group(1), pr.get("headRefName")) if m else None
        parsed = _parse(m.group(1), text) if m and text else None
        if parsed and parsed.status == "draft":
            found[m.group(1)] = {"spec": parsed, "repo": slug, "since": pr.get("createdAt") or _created(parsed),
                                 "pr": pr.get("number"), "url": pr.get("url")}
    return list(found.values())


def _obj(type_: str, repo: str | None = None, **kw) -> dict:
    base = {"type": type_, "repo": repo, "spec": None, "run_id": None, "issue": None, "component": None, "version": None,
            "pr": None, "url": None}
    return {**base, **kw}


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _estimate(done: list[dict], kind: str | None, level: str) -> dict | None:
    """The median of the comparable done runs of the same kind and level, None below three."""
    same = [r for r in done if r.get("kind") == kind and r.get("level") == level]
    if len(same) < MIN_COMPARABLE:
        return None
    used = [(r.get("budget") or {}).get("used") or {} for r in same]
    cost = [u["cost"] for u in used if isinstance(u.get("cost"), (int, float))]
    minutes = [u["minutes"] for u in used if isinstance(u.get("minutes"), (int, float))]
    return {"cost_usd": _median(cost), "minutes": _median(minutes), "runs": int(statistics.median(1 + len(r.get("children") or []) for r in same))}


def _draft_item(d: dict, gitops_slug: str | None, done: list[dict]) -> dict:
    spec, slug = d["spec"], d["repo"]
    sid, number = spec.id, spec.number
    level = "system" if slug == gitops_slug else "component"
    questions = spec.open_questions()
    item = {"id": f"{'answer' if questions else 'approve'}:{slug}:{sid}", "kind": "answer" if questions else "approve",
            "stage": "Spec", "object": _obj("spec", slug, spec=sid, pr=d["pr"], url=d["url"]), "since": d["since"],
            "cwd_repo": slug}
    if questions:
        item.update(reason=f"draft with {len(questions)} open question{'s' if len(questions) != 1 else ''}",
                    command=f"/{level}:spec --amend {number} <answers>", consequence={"questions": len(questions)}, way_back=None)
    else:
        item.update(reason="draft without open questions", command=f"/{level}:spec approve {number}",
                    consequence={"repos": [slug], "unattended": list(UNATTENDED), "estimate": _estimate(done, "ship" if level == "component" else "product-ship", level)},
                    way_back={"text": "The run can be paused at any stage; nothing reaches prod without you."})
    return item


def _escalations(rows: list[dict]) -> list[dict]:
    """Escalated runs with no newer active or done run of the same repo and spec."""
    items = []
    for r in rows:
        if r.get("phase") != "escalated":
            continue
        newer = [o for o in rows if o is not r and o.get("repo") == r.get("repo") and o.get("spec") == r.get("spec")
                 and (o.get("active") or o.get("phase") == "done") and str(o.get("started_at") or "") >= str(r.get("ended_at") or r.get("started_at") or "")]
        if newer:
            continue
        spec_id, pr = r.get("spec"), r.get("pr") or {}
        number = (spec_id or "").split("-", 1)[0]
        ref = f" pull request #{pr['number']}" if pr.get("number") else " any pull request"
        reason = (r.get("escalation") or {}).get("reason") or "run escalated"
        issue = r.get("issue") if r.get("engine") and isinstance(r.get("issue"), dict) else None
        command = f"/component:fix #{issue['number']}" if issue else f"/{r.get('level') or 'component'}:ship {number}".rstrip()
        items.append({
            "id": f"escalation:{r['run_id']}", "kind": "escalation", "stage": r.get("stage") or "Build",
            "object": _obj("run", r.get("repo"), spec=spec_id, run_id=r["run_id"], pr=pr.get("number"), url=pr.get("url")),
            "since": r.get("ended_at") or r.get("started_at") or "", "reason": reason,
            "command": command, "cwd_repo": issue.get("repo") if issue else r.get("repo"),
            "consequence": {"branch": f"feature/{spec_id}" if spec_id else None, "pr": pr.get("number"), "deployed": False},
            "way_back": {"text": f"Stopping keeps the branch and{ref}; nothing was deployed."}})
    return items


_GUARD_TEXT = {
    "autoMerge.routes": lambda f, p: f"route {f.get('route')}, auto-merge only for {', '.join(p['autoMerge']['routes'])}",
    "autoMerge.maxCriticality": lambda f, p: f"criticality {f.get('criticality')}, at most {p['autoMerge']['maxCriticality']}",
    "riskGate.maxFiles": lambda f, p: f"{(f.get('change') or {}).get('files')} files, at most {p['riskGate']['maxFiles']}",
    "riskGate.maxLines": lambda f, p: f"{(f.get('change') or {}).get('lines')} lines, at most {p['riskGate']['maxLines']}",
    "riskGate.regressionTest": lambda f, p: "no regression test that failed before the fix and passes after it",
    "riskGate.secondReview": lambda f, p: f"second review {(f.get('second_review') or {}).get('result') or 'missing'}",
    "window": lambda f, p: f"outside the window ({p['window']['from']} to {p['window']['to']} {p['window']['timezone']})",
}


def _why(guardrail: str, fix: dict, policy: dict, merges: int, runs_today: int) -> dict:
    if guardrail == "budget.mergesPerDay":
        text = f"{merges} merges today, at most {policy['budget']['mergesPerDay']}"
    elif guardrail == "budget.runsPerDay":
        text = f"{runs_today} runs today, at most {policy['budget']['runsPerDay']}"
    else:
        text = _GUARD_TEXT[guardrail](fix, policy)
    return {"guardrail": guardrail, "text": text}


def _ci(slug: str, number: int) -> tuple[str, bool]:
    """(`passed|failed|pending|unknown`, pull request still open); GitHub failing counts as unknown and open."""
    try:
        data = _json(["pr", "view", str(number), "-R", slug, "--json", "statusCheckRollup,state"]) or {}
    except Exception:  # noqa: BLE001
        return "unknown", True
    if str(data.get("state") or "OPEN").upper() != "OPEN":
        return "unknown", False
    checks = data.get("statusCheckRollup") or []
    bad = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
    if any(str(c.get("conclusion") or c.get("state") or "").upper() in bad for c in checks):
        return "failed", True
    if any(str(c.get("status") or "COMPLETED").upper() != "COMPLETED" or c.get("state") == "PENDING" for c in checks):
        return "pending", True
    return ("passed" if checks else "unknown"), True


def _reviews(rows: list[dict], m: model.Model, gitops_slug: str | None) -> list[dict]:
    """A `review` item per engine fix whose pull request is open and waits for a person: at `propose`, or at `act`
    when the fix is outside a guardrail (AC-124.14, AC-124.17)."""
    now = runs.utcnow()
    today = runs._iso(now)[:10]
    items = []
    for r in rows:
        pr = r.get("pr") or {}
        if not r.get("engine") or r.get("kind") != "fix" or r.get("stopped") or r.get("outcome") or not pr.get("number"):
            continue
        env = next((e for e in m.environments if e.name == r.get("environment")), None)
        inst = m.instance(r.get("component") or "", r.get("environment") or "")
        if env is None or not env.autonomy:
            continue
        level = (inst.autonomy.get("effective") if inst and inst.autonomy else None) or env.autonomy["effective"]
        fix = r.get("fix") or {}
        if level not in ("propose", "act") or (fix.get("decision") or {}).get("action") == "stop":
            continue
        same = [o for o in rows if o.get("engine") and o.get("environment") == r.get("environment") and str(o.get("started_at") or "").startswith(today)]
        merges = sum(1 for o in same if o is not r and ((o.get("fix") or {}).get("decision") or {}).get("action") == "merge")
        if level == "propose":
            why = [{"guardrail": "level", "text": "level propose: a person merges every fix"}]
        else:
            names = autonomy.outside(env.autonomy, {**fix, "route": fix.get("route")}, merges_today=merges, runs_today=len(same), now=now)
            why = [_why(g, fix, env.autonomy, merges, len(same)) for g in names]
        if not why:
            continue
        ci, is_open = _ci(pr.get("repo") or (r.get("repo") or ""), pr["number"])
        if not is_open:
            continue
        repo = r.get("repo")
        reason = "; ".join(f"outside {w['guardrail']} ({w['text']})" for w in why) if level == "act" else why[0]["text"]
        items.append({
            "id": f"review:{repo}#{pr['number']}", "kind": "review", "stage": "Land",
            "object": _obj("run", repo, run_id=r["run_id"], issue=(r.get("issue") or {}).get("number"), component=r.get("component"),
                           pr=pr["number"], url=pr.get("url"), engine=r.get("engine"), environment=r.get("environment")),
            "since": r.get("started_at") or "", "reason": reason, "command": f"/system:autonomy approve {repo}#{pr['number']}",
            "cwd_repo": gitops_slug,
            "consequence": {"why": why, "level": level, "regression": fix.get("regression"), "ci": ci,
                            "second_review": fix.get("second_review"), "summary": fix.get("summary"), "merges_to": "dev"},
            "way_back": {"text": "After the merge, Undo or a revert pull request takes the change back; the issue stays linked."}})
    return items


def _prod_promotion(m: model.Model) -> str:
    """The `promote` rule of prod; a missing rule is `manual` (the default of spec 114)."""
    prod = next((e for e in m.environments if e.name == "prod"), None)
    return (prod.promotion if prod else None) or "manual"


def _staging_smoke(slug: str | None, stg: dict) -> dict:
    """The run-store record of the staging smoke that verified this cell (`{at, digest}`); {} when it cannot be read."""
    tag = stg.get("release") or stg.get("tag") or stg.get("version")
    if not slug or not tag:
        return {}
    try:
        return status._smoke(slug, tag, "staging") or {}
    except Exception:  # noqa: BLE001
        return {}


def _commit_time(slug: str | None, ref: str | None) -> str:
    """When the commit (or tag) was committed, "" when GitHub cannot say."""
    if not slug or not ref:
        return ""
    try:
        data = _json(["api", f"repos/{slug}/commits/{ref}"]) or {}
        return str(((data.get("commit") or {}).get("committer") or {}).get("date") or "")
    except Exception:  # noqa: BLE001
        return ""


def _promotions(rows: list[dict], repo_of: dict[str, str], prod_promotion: str = "manual") -> list[dict]:
    """A promote item exists only where prod waits for a person (`manual`); otherwise the rule promotes by itself."""
    if prod_promotion != "manual":
        return []
    items = []
    for row in rows:
        cells = row.get("cells") or {}
        stg, prod = cells.get("staging"), cells.get("prod")
        if not stg or stg.get("state") != "verified" or not stg.get("version"):
            continue
        if prod and prod.get("version") == stg["version"]:
            continue
        name, slug, to = row["component"], repo_of.get(row["component"]), stg["version"]
        frm = (prod or {}).get("version") or (releases.previous_release(slug, to) if slug else None)
        between = releases.between(slug, frm, to) if slug and frm else {}
        migrations = between.get("migrations") or []
        digest = stg.get("digest")
        verified = _staging_smoke(slug, stg)
        since = verified.get("at") or _commit_time(slug, stg.get("release") or stg.get("tag")) or runs._iso(runs.utcnow())
        verified_digest = verified.get("digest") or digest   # the cell is `verified`: without a readable record, its own digest was
        bad = [Path(m["file"]).name for m in migrations if not m.get("additive")]
        items.append({
            "id": f"promote:{name}:{to}", "kind": "promote", "stage": "Prod",
            "object": _obj("release", slug, component=name, version=to), "since": since,
            "reason": f"{to} is verified in staging; prod runs {frm or 'nothing'}",
            "command": f"/instance:promote {name} --to prod --version {to}", "cwd_repo": slug,
            "consequence": {"from": frm, "to": to, "specs": between.get("specs") or [], "criteria": between.get("criteria"),
                            "commits": between.get("commits"), "migrations": migrations, "digest": digest,
                            "verified_digest": verified_digest, "digest_matches": digest is not None and digest == verified_digest},
            "way_back": {"command": f"/instance:promote {name} --to prod --version {frm}" if frm else None,
                         "warning": (f"migration {', '.join(bad)} is not additive" if bad else None)}})
    return items


def _section_text(body: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\n_Filed automatically|\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else ""


def _fact(text: str, key: str) -> str:
    m = re.search(rf"^- {re.escape(key)}: *(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def _last_error(evidence: str) -> str:
    lines = [ln.strip() for ln in evidence.splitlines() if ln.strip() and not ln.strip().startswith("`")]
    return lines[-1] if lines and lines[-1] != "(none)" else ""


def triage_detail(names: set[str], body: str) -> dict:
    """The failing check or test, criterion, last error and diagnosis of an alert (spec 092) or smoke-failure (spec 091)
    issue body; `{}` when the body has none of them."""
    body = body or ""
    out: dict[str, str] = {}
    if "smoke-failure" in names:
        smoke = _section_text(body, "Smoke")
        tests = re.findall(r"^\s+- (\S.*)$", smoke.split("- failing tests:", 1)[-1], re.M) if "- failing tests:" in smoke else []
        out["test"] = ", ".join(tests)
        out["criterion"] = ", ".join(dict.fromkeys(re.findall(r"AC-\d+\.\d+", " ".join(tests) + " " + _section_text(body, "Reason"))))
        out["error"] = _last_error(_section_text(body, "Evidence"))
        klass = _fact(smoke, "failure class")
        out["diagnosis"] = f"failure class {klass}" if klass and klass != "unknown" else _section_text(body, "Reason")
    elif "alert" in names:
        alert = _section_text(body, "Alert")
        out["check"] = _fact(alert, "alert")
        out["error"] = _section_text(body, "Summary") if _section_text(body, "Summary") != "(none)" else ""
        where = ", ".join(x for x in (_fact(alert, "severity"), _fact(alert, "environment"), _fact(alert, "service")) if x)
        out["diagnosis"] = f"alert firing ({where})" if where else ""
    return {k: v for k, v in out.items() if v}


def _engine_of(names) -> str | None:
    """The engine named by an `engine:<name>` label."""
    return next((n[len("engine:"):] for n in sorted(n for n in names if n) if n.startswith("engine:")), None)


def _triage(slug: str) -> list[dict]:
    issues = _json(["issue", "list", "-R", slug, "--state", "open", "--label", "triage",
                    "--json", "number,title,createdAt,url,labels,body"]) or []
    items = []
    for i in issues:
        names = {(x.get("name") if isinstance(x, dict) else x) for x in i.get("labels") or []}
        if "triage" not in names or not names & TRIAGE_LABELS:
            continue
        extra: dict = {}
        detail = triage_detail(names, i.get("body") or "")
        if "signal" in names:
            extra["engine"] = _engine_of(names)
            detail = {**detail, "signal": engine_issue.parse(i.get("body") or "", sorted(names))}
        items.append({"id": f"triage:{slug}:{i['number']}", "kind": "triage", "stage": "Issue",
                      "object": _obj("issue", slug, issue=i["number"], url=i.get("url"), detail=detail, **extra), "since": i.get("createdAt") or "",
                      "reason": f"{i.get('title') or 'issue'} (not routed yet)", "command": f"/issue:triage {i['number']}",
                      "cwd_repo": slug, "consequence": None, "way_back": None})
    return items


def _issues(slug: str, since_days: int) -> list[dict]:
    """Open issues of one repo without the `tracked` label, and closed ones of the last `since_days` days (the Board's
    Issue column and the Done view): `{repo, number, title, labels, state, created_at, closed_at, url}`."""
    cutoff = (runs.utcnow() - datetime.timedelta(days=since_days)).strftime("%Y-%m-%d")
    out = []
    for state, extra in (("open", []), ("closed", ["--search", f"closed:>={cutoff}"])):
        rows = _json(["issue", "list", "-R", slug, "--state", state, "--limit", "200", *extra,
                      "--json", "number,title,labels,createdAt,closedAt,url,body"]) or []
        for i in rows:
            names = [(x.get("name") if isinstance(x, dict) else str(x)) for x in i.get("labels") or []]
            if "tracked" in names:
                continue
            out.append({"repo": slug, "number": i.get("number"), "title": i.get("title") or "", "labels": names, "state": state,
                        "created_at": i.get("createdAt") or "", "closed_at": i.get("closedAt") or None, "url": i.get("url") or "",
                        "engine": _engine_of(names), "signal": engine_issue.parse(i.get("body") or "", names)})
    return out


def _releases(components: dict[str, str], since_days: int) -> list[dict]:
    """The releases of the components' repos published within `since_days`: `{repo, component, tag, published_at, url}`."""
    cutoff = (runs.utcnow() - datetime.timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for name, repo in components.items():
        for r in _json(["release", "list", "-R", repo, "--json", "tagName,publishedAt,url"]) or []:
            at = r.get("publishedAt") or ""
            if r.get("tagName") and at and at >= cutoff:
                out.append({"repo": repo, "component": name, "tag": r["tagName"], "published_at": at, "url": r.get("url") or ""})
    return sorted(out, key=lambda r: r["published_at"], reverse=True)


def collect(repo_dir: Path, system: str | None = None, since_days: int = 90) -> dict:
    """The needs document (schema 1); sources that fail are listed under `unavailable`. `issues` lists the untracked
    issues of the system's repos (open, and closed within `since_days`)."""
    app_dir = find_system(repo_dir, system)
    m = model.load_dir(app_dir)
    gitops_slug, repos = _repos(repo_dir, m)
    src, items, issues = _Sources(), [], []
    done: list[dict] = []
    try:
        rows = runlist.collect(30)["runs"]
        done = [r for r in rows if r.get("phase") == "done"]
        items += _escalations(rows)
        items += _reviews(rows, m, gitops_slug)
    except Exception as e:  # noqa: BLE001
        src.fail("runs", e, ["escalation"])
    for slug in repos:
        try:
            items += [_draft_item(d, gitops_slug, done) for d in _drafts(slug)]
        except Exception as e:  # noqa: BLE001
            src.fail("github", e, ["approve", "answer"])
        try:
            items += _triage(slug)
        except Exception as e:  # noqa: BLE001
            src.fail("github", e, ["triage"])
        try:
            issues += _issues(slug, since_days)
        except Exception as e:  # noqa: BLE001
            src.fail("github", e, ["issues"])
    try:
        _, _, status_rows, _ = status.collect(repo_dir, system, None)
        items += _promotions(status_rows, {c.name: c.repo for c in m.components if c.repo}, _prod_promotion(m))
    except Exception as e:  # noqa: BLE001
        src.fail("cluster", e, ["promote"])
    releases: list[dict] = []
    try:
        releases = _releases({c.name: c.repo for c in m.components if c.repo}, since_days)
    except Exception as e:  # noqa: BLE001
        src.fail("github", e, ["releases"])
    items.sort(key=lambda i: i["since"] or "")
    return {"schema": SCHEMA, "system": app_dir.name, "read_at": runs._iso(runs.utcnow()), "items": items,
            "issues": issues, "releases": releases, "unavailable": src.listing()}


def render(doc: dict) -> str:
    """One line per item, then the count."""
    lines = [f"{i['kind']:<10} {i['stage']:<8} {i['reason']}  [{i['command']}]" for i in doc["items"]]
    lines.append(f"{len(doc['items'])} item{'s' if len(doc['items']) != 1 else ''} need you")
    lines += [f"unavailable: {u['source']}: {u['error']} (hides {', '.join(u['kinds'])})" for u in doc["unavailable"]]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat needs", description="List the open decision points of a system (spec 122).")
    p.add_argument("--json", action="store_true")
    p.add_argument("--repo-dir", default=".", metavar="DIR", help="a gitops-app clone (default .)")
    p.add_argument("--system", metavar="NAME")
    p.add_argument("--since", type=int, default=90, metavar="DAYS", help="closed issues of the last DAYS days (default 90)")
    return p


def main(argv: list[str]) -> int:
    try:
        ns = build_parser().parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    doc = collect(Path(ns.repo_dir), ns.system, ns.since)
    print(json.dumps(doc, indent=2) if ns.json else render(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
