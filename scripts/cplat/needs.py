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
TRIAGE_LABELS = {"alert", "smoke-failure"}
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
        items.append({
            "id": f"escalation:{r['run_id']}", "kind": "escalation", "stage": r.get("stage") or "Build",
            "object": _obj("run", r.get("repo"), spec=spec_id, run_id=r["run_id"], pr=pr.get("number"), url=pr.get("url")),
            "since": r.get("ended_at") or r.get("started_at") or "", "reason": reason,
            "command": f"/{r.get('level') or 'component'}:ship {number}".rstrip(), "cwd_repo": r.get("repo"),
            "consequence": {"branch": f"feature/{spec_id}" if spec_id else None, "pr": pr.get("number"), "deployed": False},
            "way_back": {"text": f"Stopping keeps the branch and{ref}; nothing was deployed."}})
    return items


def _promotions(rows: list[dict], repo_of: dict[str, str]) -> list[dict]:
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
        bad = [Path(m["file"]).name for m in migrations if not m.get("additive")]
        items.append({
            "id": f"promote:{name}:{to}", "kind": "promote", "stage": "Prod",
            "object": _obj("release", slug, component=name, version=to), "since": stg.get("verified_at") or "",
            "reason": f"{to} is verified in staging; prod runs {frm or 'nothing'}",
            "command": f"/instance:promote {name} --to prod --version {to}", "cwd_repo": slug,
            "consequence": {"from": frm, "to": to, "specs": between.get("specs") or [], "criteria": between.get("criteria"),
                            "commits": between.get("commits"), "migrations": migrations, "digest": digest,
                            "verified_digest": digest, "digest_matches": digest is not None},
            "way_back": {"command": f"/instance:promote {name} --to prod --version {frm}" if frm else None,
                         "warning": (f"migration {', '.join(bad)} is not additive" if bad else None)}})
    return items


def _triage(slug: str) -> list[dict]:
    issues = _json(["issue", "list", "-R", slug, "--state", "open", "--label", "triage",
                    "--json", "number,title,createdAt,url,labels"]) or []
    items = []
    for i in issues:
        names = {(x.get("name") if isinstance(x, dict) else x) for x in i.get("labels") or []}
        if "triage" not in names or not names & TRIAGE_LABELS:
            continue
        items.append({"id": f"triage:{slug}:{i['number']}", "kind": "triage", "stage": "Issue",
                      "object": _obj("issue", slug, issue=i["number"], url=i.get("url")), "since": i.get("createdAt") or "",
                      "reason": f"{i.get('title') or 'issue'} (not routed yet)", "command": f"/issue:triage {i['number']}",
                      "cwd_repo": slug, "consequence": None, "way_back": None})
    return items


def collect(repo_dir: Path, system: str | None = None) -> dict:
    """The needs document (schema 1); sources that fail are listed under `unavailable`."""
    app_dir = find_system(repo_dir, system)
    m = model.load_dir(app_dir)
    gitops_slug, repos = _repos(repo_dir, m)
    src, items = _Sources(), []
    done: list[dict] = []
    try:
        rows = runlist.collect(30)["runs"]
        done = [r for r in rows if r.get("phase") == "done"]
        items += _escalations(rows)
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
        _, _, status_rows, _ = status.collect(repo_dir, system, None)
        items += _promotions(status_rows, {c.name: c.repo for c in m.components if c.repo})
    except Exception as e:  # noqa: BLE001
        src.fail("cluster", e, ["promote"])
    items.sort(key=lambda i: i["since"] or "")
    return {"schema": SCHEMA, "system": app_dir.name, "read_at": runs._iso(runs.utcnow()), "items": items,
            "unavailable": src.listing()}


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
    return p


def main(argv: list[str]) -> int:
    try:
        ns = build_parser().parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    doc = collect(Path(ns.repo_dir), ns.system)
    print(json.dumps(doc, indent=2) if ns.json else render(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
