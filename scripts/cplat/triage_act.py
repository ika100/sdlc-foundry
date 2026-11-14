"""`triage_act`: apply the confirmed rows of a triage run, print the hand-over summary, publish the new specs (spec 176).

`act` validates every named issue first, then makes the labels and the `Triage:` comment of each row through `triage.apply_one`
(never a close, never a fix: a fix is queued by its labels and runs on its own). The summary lists what was done per group, the
next step per kind of result with who takes it, how to undo each change and the person's own next step as a choice. `publish_specs`
commits the new specs of the run on one `docs/triage-<date>` branch and opens or updates one draft PR for them.
"""
from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import pr_rules
import spec as specmod
import triage
import triage_batch
import triage_view as view
from core import PlatformError

WIDTH = 80
FIX_POINTER = "(cplat dispatch status, or the console Board)"
MARKER = "<!-- cplat:triage-specs -->"
BRANCH = re.compile(r"^docs/triage-(\d{4}-\d{2}-\d{2})(?:-\d+)?$")
FIX_CLASSES = ("bug", "small-change")
DONE_TEXT = {"question": "answered, labelled question", "duplicate": "marked as duplicate", "wontfix": "explained, labelled wontfix",
             "needs-info": "asked the reporter", "needs-exploring": "left to explore"}


# ---------------- git and gh seams (tests replace these) ----------------

def git(args: list[str], cwd: Path) -> tuple[int, str]:
    import spec_pr
    return spec_pr.git(args, cwd=cwd)


def gh(args: list[str], cwd: Path) -> tuple[int, str]:
    import spec_pr
    return spec_pr.gh(args, cwd=cwd)


# ---------------- act ----------------

def _numbers(batch: dict, numbers: str) -> list[int]:
    known = [i["number"] for i in batch["issues"]]
    if numbers.strip() == "all":
        return known
    try:
        named = [int(x) for x in numbers.split(",") if x.strip()]
    except ValueError as e:
        raise PlatformError("--rows takes `all` or issue numbers like 560,562") from e
    outside = [n for n in named if n not in known]
    if outside or not named:
        raise PlatformError("a number is not an issue of the batch" if outside else "no rows named",
                            hint=", ".join(f"#{n}" for n in outside) or "pass --rows all or --rows 560,562")
    return named


def _phrase(e: dict) -> str:
    issue, row = e["issue"], e["row"]
    handled = (issue["handled"] or {}).get("kind")
    if handled:
        return f"labelled {'tracked' if handled == 'spec' else 'duplicate'}"
    cls = row["class"]
    if cls in FIX_CLASSES:
        return f"queued for a fix ({cls}, {row['priority']})"
    if cls == "feature":
        return f"tracked in spec {view._number(row['spec'])}"
    return DONE_TEXT[cls]


def _wrap(text: str, first: str, rest: str) -> list[str]:
    return textwrap.fill(text, width=WIDTH, initial_indent=first, subsequent_indent=rest, break_on_hyphens=False).splitlines()


def _next(done: list[dict], entries: dict) -> list[dict]:
    rows = [(d, entries[d["number"]]) for d in done]
    out = []
    fixes = [d["number"] for d, _ in rows if d["class"] in FIX_CLASSES]
    if fixes:
        out.append({"kind": "fix runs on its own", "who": "on its own", "numbers": sorted(fixes), "command": None})
    new: dict[str, list[int]] = {}
    for d, e in rows:
        if e["row"] and e["row"]["class"] == "feature" and e["row"].get("new_spec"):
            new.setdefault(e["row"]["spec"], []).append(d["number"])
    for spec_id, nums in new.items():
        num = view._number(spec_id)
        out.append({"kind": f"approve spec {num} (you)", "who": "you", "numbers": sorted(nums), "command": f"/component:spec approve {num}"})
    explorer = "/system:explore" if _shape() == "gitops-app" else "/component:explore"
    for d, _ in rows:
        if d["class"] == "needs-exploring":
            out.append({"kind": f"explore #{d['number']} (you)", "who": "you", "numbers": [d["number"]],
                        "command": f"{explorer} #{d['number']}"})
    waiting = [d["number"] for d, _ in rows if d["class"] == "needs-info"]
    if waiting:
        out.append({"kind": "reporter answers", "who": "reporter", "numbers": sorted(waiting), "command": None})
    claimed = {n for item in out for n in item["numbers"]}
    nothing = sorted(d["number"] for d, _ in rows if d["number"] not in claimed)
    if nothing:
        out.append({"kind": "nothing", "who": "nobody", "numbers": nothing, "command": None})
    return out


def _shape() -> str | None:
    try:
        return specmod.repo_shape(Path.cwd())
    except PlatformError:
        return None


def _choice(nxt: list[dict]) -> dict:
    approve = [n for n in nxt if n["kind"].startswith("approve spec")]
    explore = [n for n in nxt if n["kind"].startswith("explore")]
    if approve:
        nums = ", ".join(n["kind"].split()[2] for n in approve)
        return {"text": f"The new spec{'s' if len(approve) > 1 else ''} ({nums}) wait{'' if len(approve) > 1 else 's'} for you. What next?",
                "options": [{"label": "Approve the new specs now (Recommended)", "recommended": True, "command": approve[0]["command"]},
                            {"label": "Read them first", "recommended": False, "command": None},
                            {"label": "Later", "recommended": False, "command": None}]}
    if explore:
        n = explore[0]["numbers"][0]
        return {"text": f"#{n} needs exploring before it is decided. What next?",
                "options": [{"label": f"Explore #{n} now (Recommended)", "recommended": True, "command": explore[0]["command"]},
                            {"label": "Later", "recommended": False, "command": None}]}
    return {"text": "The triage is done. What next?",
            "options": [{"label": "Done (Recommended)", "recommended": True, "command": None},
                        {"label": "Show the fix runs", "recommended": False, "command": "cplat dispatch status"}]}


def act(slug: str, batch: dict, rows: list[dict], numbers: str, dry_run: bool) -> dict:
    """Apply the actions of the named issues; returns {"done", "next", "undo", "choice"} (nothing is written when it raises)."""
    named = set(_numbers(batch, numbers))
    entries = {e["issue"]["number"]: e for e in view._entries(batch, rows)}
    errors = []
    for n in sorted(named):
        e = entries[n]
        if e["row"]:
            errors += [f"#{n}: {p}" for p in view._row(e["row"], e["issue"], True, Path.cwd())[1]]
    if errors:
        raise PlatformError("the proposals file is not valid for these rows", hint="\n".join(errors))
    done, undo = [], []
    for key, name in view.GROUPS:
        for n in sorted(named):
            e = entries[n]
            if e["group"] != key:
                continue
            handled = (e["issue"]["handled"] or {}).get("kind")
            if handled in ("claimed", "fixed") or (e["row"] and e["row"]["class"] == "needs-exploring"):
                if not handled:
                    done.append({"number": n, "group": name, "class": "needs-exploring", "added": [], "removed": [], "commented": False})
                continue
            a = view.actions(e["issue"], e["row"])
            if a["add"] or a["remove"] or a["comment"]:
                report = triage.apply_one(slug, n, a["add"], a["remove"], a["comment"] or "", dry_run)
                undo += [f"#{n}: {u}" for u in report.undo]
            done.append({"number": n, "group": name, "class": (e["row"] or {}).get("class") or handled,
                         "added": a["add"], "removed": a["remove"], "commented": bool(a["comment"])})
    specs_pr = batch.get("specs_pr")
    if specs_pr and not dry_run:
        undo.append(f"specs: close draft PR #{specs_pr['number']} and delete branch {specs_pr['branch']}")
    nxt = _next(done, entries)
    return {"done": done, "next": nxt, "undo": undo, "choice": _choice(nxt), "_entries": entries, "_specs_pr": specs_pr}


def render(result: dict, dry_run: bool) -> str:
    entries, specs_pr = result["_entries"], result["_specs_pr"]
    out = ["Will do" if dry_run else "Done"]
    for _, name in view.GROUPS:
        items = [f"#{d['number']} {_phrase(entries[d['number']])}" for d in result["done"] if d["group"] == name]
        if items:
            out += _wrap(f"{name}: " + "; ".join(items), "  ", " " * 6)
    out.append("Next")
    for item in result["next"]:
        tail = ""
        if item["kind"] == "fix runs on its own":
            tail = " " + FIX_POINTER
        elif item["command"] and item["kind"].startswith("approve spec") and specs_pr:
            tail = f" (draft PR #{specs_pr['number']})"
        if item["kind"].startswith(("approve", "explore")):
            body = item["command"]
        else:
            body = ", ".join(f"#{n}" for n in item["numbers"])
        out += _wrap(f"{item['kind']}: {body}{tail}", "  ", " " * 6)
    if result["undo"]:
        out += ["Undo", *[f"  {u}" for u in result["undo"]]]
    choice = result["choice"]
    out += ["", choice["text"], "Choose: " + " / ".join(o["label"] for o in choice["options"])]
    return "\n".join(out)


def run_act(slug: str, proposals: str, numbers: str, dry_run: bool, as_json: bool) -> str:
    batch = triage_batch.load(slug)
    rows = view.load_proposals(proposals, batch)
    result = act(slug, batch, rows, numbers, dry_run)
    if as_json:
        return json.dumps({k: v for k, v in result.items() if not k.startswith("_")}, indent=2)
    return render(result, dry_run)


# ---------------- publish-specs ----------------

def _git_ok(root: Path, *args: str) -> str:
    rc, out = git(list(args), cwd=root)
    if rc != 0:
        raise PlatformError(f"`git {' '.join(args[:2])}` failed (exit {rc})")
    return out


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _find_pr(root: Path, branch: str) -> dict | None:
    rc, out = gh(["pr", "list", "--head", branch, "--state", "open", "--json", "number,url,body,headRefName"], cwd=root)
    for row in (_json(out) if rc == 0 else None) or []:
        if MARKER in (row.get("body") or "") and row.get("headRefName", branch) == branch:
            return row
    return None


def publish_specs(root: Path, slug: str, ids: list[str]) -> dict:
    """Commit each named spec folder, push the docs branch (never forced), open or update the one draft PR, record it in the batch."""
    branch = _git_ok(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    m = BRANCH.match(branch)
    if not m:
        raise PlatformError(f"on branch {branch or '?'}, not a triage docs branch (docs/triage-<date>)",
                            hint="git checkout -b docs/triage-<date> origin/main")
    found = [specmod.find(root, i) for i in ids]
    commits = [(s, pr_rules.fit(f"docs(spec): {s.id} — {s.meta.get('title') or s.id}")) for s in found]
    for s, message in commits:
        rel = f"docs/specs/{s.id}"
        _git_ok(root, "add", "--", rel)
        rc, _ = git(["commit", "-s", "-m", message, "--", rel], cwd=root)
        if rc != 0 and git(["diff", "--cached", "--quiet", "--", rel], cwd=root)[0] != 0:
            raise PlatformError(f"`git commit` failed (exit {rc})")   # a clean folder (nothing to commit) is fine
    _git_ok(root, "push", "-u", "origin", branch)
    numbers = ", ".join(view._number(s.id) for s in found)
    title = pr_rules.fit(f"docs(spec): triage {m.group(1)} — specs {numbers}")
    body = "New specs of this triage run:\n\n" + "\n".join(f"- {s.id}: {s.meta.get('title') or s.id}" for s in found) + f"\n\n{MARKER}\n"
    row = _find_pr(root, branch)
    if row is None:
        rc, out = gh(["pr", "create", "--draft", "--head", branch, "--title", title, "--body", body], cwd=root)
        url = out.strip().splitlines()[-1] if out.strip() else ""
        if rc != 0 or not re.search(r"/pull/\d+", url):
            raise PlatformError(f"opening the draft pull request failed (gh exit {rc})")
        rc, out = gh(["pr", "view", url, "--json", "number,url"], cwd=root)
        row = _json(out) if rc == 0 else None
        if not isinstance(row, dict) or "number" not in row:
            row = {"number": int(re.search(r"/pull/(\d+)", url).group(1)), "url": url}
    else:
        gh(["pr", "edit", str(row["number"]), "--title", title, "--body", body], cwd=root)
    info = {"number": int(row["number"]), "url": row.get("url") or "", "branch": branch, "specs": [s.id for s in found]}
    saved = triage_batch.load(slug)
    saved["specs_pr"] = info
    triage_batch.save(saved)
    return {"pr": info["number"], "url": info["url"], "branch": branch, "specs": info["specs"], "numbers": numbers}


def run_publish(slug: str, ids: list[str], as_json: bool) -> str:
    res = publish_specs(Path.cwd(), slug, ids)
    if as_json:
        return json.dumps({k: res[k] for k in ("pr", "url", "branch", "specs")}, indent=2)
    return f"specs {res['numbers']}: {res['url']}"

