"""`explore context`: read-only context for /component:explore and /system:explore (spec 188).

Given a topic it lists the specs, open issues and ADRs that mention it, the project map and, in a gitops-app repo, the
declared system. It reads files and runs `gh` for issues; it writes nothing. Issue text is untrusted and comes back fenced.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import gitops
import model
import shapecmd
import spec
import triage
from core import PlatformError

USAGE = 'usage: cplat explore context "<topic>" [--json]'
STOP = {"the", "and", "for", "with", "from", "into", "that", "this"}
LIMIT = 10
SKIP_DIRS = {"node_modules", "vendor", "target", "build", "dist", "venv", "__pycache__"}
ISSUE_TOKEN = re.compile(r"#(\d+)")
ADR_TITLE = re.compile(r"^#\s+ADR-\d+:\s*(.*)$")
ADR_STATUS = re.compile(r"\*\*Status:\*\*\s*(\w+)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat explore", description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    c = sub.add_parser("context", help="specs, open issues, ADRs and the project map for a topic")
    c.add_argument("topic", nargs="*", help="the topic words; #<n> adds that issue")
    c.add_argument("--json", action="store_true")
    c.add_argument("--repo", default=".", metavar="DIR")
    c.add_argument("--system", help="the system of a gitops-app repo with several")
    return p


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in STOP}


def rank(items: list[tuple[int, set[str], dict]], topic: set[str]) -> list[dict]:
    """Items whose words meet the topic, most matched words first, then the higher number."""
    hits = [(len(topic & text), n, item) for n, text, item in items if topic & text]
    return [item for _, _, item in sorted(hits, key=lambda h: (-h[0], -h[1]))[:LIMIT]]


def _number(text: str) -> int:
    m = re.match(r"\d+", text)
    return int(m.group()) if m else 0


def project_map(root: Path) -> list[str]:
    return sorted(f"{p.name}/" for p in root.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_DIRS)


def spec_text(s: spec.Spec) -> str:
    lines = [ln for ln in spec.sections(s.body).get("acceptance criteria", "").splitlines()
             if (m := spec.AC_LINE.match(ln)) and not m.group(1)]
    return " ".join([str(s.meta.get("title", "")), *lines])


def find_specs(root: Path, topic: set[str], tracked: set[str]) -> list[dict]:
    items = []
    for s in spec.scan(root)[0]:
        text = words(spec_text(s))
        if tracked & {d for t in s.meta.get("tracks") or [] for d in re.findall(r"\d+", str(t))}:
            text |= topic
        items.append((_number(s.number), text, {"id": s.id, "title": str(s.meta.get("title", "")), "status": s.status}))
    return rank(items, topic)


def find_adrs(root: Path, topic: set[str]) -> list[dict]:
    items = []
    for p in sorted((root / "docs" / "adr").glob("[0-9]*-*.md")):
        text = p.read_text(errors="replace")
        first = text.splitlines()[0] if text else ""
        m, st = ADR_TITLE.match(first), ADR_STATUS.search(text)
        title = m.group(1).strip() if m else first.lstrip("# ").strip()
        n = _number(p.name)
        items.append((n, words(title), {"number": n, "title": title, "status": st.group(1) if st else ""}))
    return rank(items, topic)


def read_issues(tokens: list[str], topic: set[str]) -> tuple[list[dict], list[dict], set[str], list[str]]:
    """Open issues matching the topic, the `#<n>` issues, their title words; a `gh` failure gives empty lists and a warning."""
    ns = SimpleNamespace(repo=None)
    try:
        topic_issues, extra = [], set()
        for n in tokens:
            issue = json.loads(triage.gh(["issue", "view", n, "--json", "number,title,body,state"]))
            title = triage.feedback.redact(issue.get("title", ""))
            extra |= words(title)
            topic_issues.append({"number": issue["number"], "title": title, "state": issue.get("state", ""),
                                 "body": triage.fenced(issue.get("body") or "", triage.BODY_LIMIT)})
        match = topic | extra
        items = [(i["number"], words(i["title"]), {"number": i["number"], "title": i["title"]})
                 for i in map(triage.summary, triage.fetch_issues(ns))]
        return rank(items, match), topic_issues, extra, []
    except (PlatformError, OSError, ValueError, KeyError) as e:
        reason = " ".join(str(e).split()) or type(e).__name__
        return [], [], set(), [f"open issues not read: {reason}"]


def system_part(root: Path, system: str | None) -> dict:
    apps = list((root / "applications").glob("*/system.yaml"))
    if not system and len(apps) > 1:
        raise PlatformError("several systems found", hint="pass --system NAME: " + ", ".join(sorted(p.parent.name for p in apps)))
    m = model.load_dir(gitops.find_app(root, system))
    return {
        "system": m.system,
        "components": [{"name": c.name, "type": c.type, "lang": c.lang} for c in m.components],
        "resources": [{"name": r.name, "type": r.type} for r in m.resources],
        "apis": [{"name": a.name, "type": a.type, "provider": a.provider, "consumers": list(a.consumers)} for a in m.apis],
    }


def context(ns: argparse.Namespace, topic_text: str) -> dict:
    root = Path(ns.repo).resolve()
    try:
        shape = shapecmd.resolve(root)
    except PlatformError:
        shape = None
    tokens = ISSUE_TOKEN.findall(topic_text)
    topic = words(topic_text)
    issues, topic_issues, extra, warnings = read_issues(tokens, topic)
    topic |= extra
    data = {
        "topic": topic_text, "shape": shape, "project_map": project_map(root),
        "specs": find_specs(root, topic, set(tokens)), "issues": issues, "adrs": find_adrs(root, topic),
        "topic_issues": topic_issues, "warnings": warnings,
    }
    if shape == "gitops-app":
        data.update(system_part(root, ns.system))
    return data


def _section(name: str, lines: list[str]) -> list[str]:
    return [f"{name}:", *(f"  {ln}" for ln in lines or ["none"])]


def render(d: dict) -> str:
    out = [f"shape: {d['shape'] or 'unknown'}", *_section("project map", d["project_map"]),
           *_section("specs", [f"{s['id']}  {s['status']}  {s['title']}" for s in d["specs"]]),
           *_section("issues", [f"#{i['number']}  {i['title']}" for i in d["issues"]]),
           *_section("adrs", [f"ADR-{a['number']:03d}  {a['status'] or '-'}  {a['title']}" for a in d["adrs"]])]
    if d["topic_issues"]:
        out += _section("topic issues", [f"#{i['number']}  {i['state']}  {i['title']}" for i in d["topic_issues"]])
    if "system" in d:
        out += [f"system: {d['system']}",
                *_section("components", [f"{c['name']}  {c['type']}  {c['lang']}" for c in d["components"]]),
                *_section("resources", [f"{r['name']}  {r['type']}" for r in d["resources"]]),
                *_section("apis", [f"{a['name']}  {a['type']}  provider {a['provider'] or '-'}  consumers {','.join(a['consumers']) or '-'}"
                                   for a in d["apis"]])]
    out += [f"warning: {w}" for w in d["warnings"]]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    topic_text = " ".join(ns.topic).strip()
    if not topic_text:
        print(USAGE, file=sys.stderr)
        return 2
    data = context(ns, topic_text)
    print(json.dumps(data, indent=2) if ns.json else render(data))
    return 0
