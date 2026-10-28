"""`fleet update`: bring every repo built from the platform to the installed release (spec 096).

  cplat fleet update [--owner OWNER]... [--only OWNER/NAME]... [--ref TAG] [--timeout SECONDS] [--dry-run] [--json]

One PR per repo, made by `update-service`'s own resolve/execute on a fresh clone. A PR is squash-merged on green CI only
when the update is routine (nothing the repo added was overwritten, same major version, no conflict); every other PR stays
open with the label `platform-update: needs review` and a comment giving the reason. Exit 1 when any repo is left open or
failed.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import core
import fleet_pr
import runs
from core import PlatformError

ORDER = ["up to date", "would update", "merged", "left open", "failed", "skipped"]
LIST_FIELDS = "nameWithOwner,isArchived,isFork,defaultBranchRef"
RAW = ["-H", "Accept: application/vnd.github.raw"]
SLUG_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


def gh(args: list[str], *, cwd: Path | None = None, input: str | None = None, timeout: float = 60.0) -> tuple[int, str, str]:
    """subprocess `gh <args>` -> (exit code, stdout, stderr). Never raises. Tests replace this."""
    try:
        p = subprocess.run(["gh", *args], cwd=cwd, input=input, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", "gh is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return p.returncode, p.stdout, p.stderr


def clone(slug: str, dest: Path) -> None:
    rc, _, err = gh(["repo", "clone", slug, str(dest), "--", "--quiet"], timeout=600)
    if rc != 0:
        raise PlatformError(f"clone of {slug} failed: {_first(err)}")


def sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)


def say(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _first(text: str) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[0].strip() if lines else ""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cplat platform fleet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("update", help="bring every platform repo to the installed release")
    p.add_argument("--owner", action="append", default=[], help="repo owner (repeatable; default: the gh login)")
    p.add_argument("--only", action="append", default=[], metavar="OWNER/NAME", help="only these repos (repeatable)")
    p.add_argument("--ref", default=None, help="must equal the installed platform version (vX.Y.Z or X.Y.Z)")
    p.add_argument("--timeout", type=float, default=3600, help="CI wait per PR in seconds")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return ap


def check_target(ref: str | None) -> str:
    target = core.platform_version()
    if ref is None:
        return target
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", ref):
        raise PlatformError(f"--ref {ref} is not a version (expected vX.Y.Z)")
    if ref.lstrip("v") != target:
        raise PlatformError(f"--ref {ref} is not the platform this command runs ({target}); "
                            f"run it as CPLAT_REF={ref} cplat fleet update --ref {ref}")
    return target


def _row(slug: str, frm: str | None, to: str | None, outcome: str, reason: str | None = None, pr: str | None = None,
         nxt: list[str] | None = None) -> dict:
    return {"repo": slug, "from": frm, "to": to, "outcome": outcome, "reason": reason, "pr": pr, "next": nxt or []}


def _read(slug: str, path: str) -> str | None:
    """File text on the default branch; None when missing; PlatformError(cannot read ...) otherwise."""
    rc, out, err = gh(["api", f"repos/{slug}/contents/{path}", *RAW])
    if rc == 0:
        return out
    if "404" in err or "Not Found" in err:
        return None
    raise PlatformError(f"cannot read {path}: {_first(err)}")


def is_platform(answers: str, templates: set[str]) -> bool:
    m = re.search(r"^_src_path:\s*(.+?)\s*$", answers, re.M)
    if not m:
        return False
    src = m.group(1).strip("'\"").rstrip("/")
    return any(src.endswith(f"templates/{t}") for t in templates)


def _list_owner(owner: str) -> list[dict]:
    rc, out, err = gh(["repo", "list", owner, "--no-archived", "--source", "--json", LIST_FIELDS, "--limit", "1000"])
    if rc != 0:
        raise PlatformError(f"cannot list repos of {owner}: {_first(err)}")
    return [e for e in json.loads(out or "[]") if not e.get("isArchived") and not e.get("isFork")]


def _default(entry: dict) -> str:
    return (entry.get("defaultBranchRef") or {}).get("name") or "main"


def process(slug: str, entry: dict | None, only: bool, target: str, ref: str | None, timeout: float, dry: bool,
            templates: set[str]) -> dict | None:
    """One repo -> its row, or None when it is not a platform repo and `only` is off (left out of the report)."""
    if entry is None:                                       # --only: read the repo first
        rc, out, err = gh(["repo", "view", slug, "--json", LIST_FIELDS])
        if rc != 0:
            return _row(slug, None, None, "failed", f"cannot read {slug}: {_first(err)}")
        entry = json.loads(out)
        if entry.get("isArchived"):
            return _row(slug, None, None, "skipped", "archived")
        if entry.get("isFork"):
            return _row(slug, None, None, "skipped", "fork")
    try:
        stamp = _read(slug, ".platform-version")
        answers = _read(slug, ".copier-answers.yml") if stamp is not None else None
    except PlatformError as e:
        return _row(slug, None, None, "failed", str(e))
    if stamp is None and only:
        try:
            settings = _read(slug, ".platform-settings.yml")
        except PlatformError as e:
            return _row(slug, None, None, "failed", str(e))
        try:
            declared = yaml.safe_load(settings) if settings is not None else None
        except yaml.YAMLError:
            declared = None
        if isinstance(declared, dict) and declared.get("shape") == "platform":
            return _row(slug, None, None, "skipped", "the platform repo is not updated from a template")
    if stamp is None or answers is None or not is_platform(answers, templates):
        return _row(slug, None, None, "skipped", "not a platform repo") if only else None
    m = re.search(r"^platform:\s*(\d+\.\d+\.\d+)", stamp, re.M)
    old = m.group(1) if m else None
    frm = old or "none"
    if old and core.vtuple(old) >= core.vtuple(target):
        return _row(slug, frm, None, "up to date")
    default = _default(entry)
    if dry:
        return _dry(slug, default, frm, old, target)
    say(f"{slug}: updating {frm} → {target}")
    try:
        with tempfile.TemporaryDirectory(prefix="cplat-fleet-") as tmp:
            dest = Path(tmp) / "repo"
            clone(slug, dest)
            ctx = fleet_pr.Ctx(slug, dest, default, lambda *a, **k: gh(*a, **k), lambda s: sleep(s), timeout)
            with contextlib.redirect_stdout(sys.stderr):
                res = fleet_pr.update(ctx, old, target, ref)
    except Exception as e:  # noqa: BLE001  (one repo failing never stops the fleet)
        return _row(slug, frm, None, "failed", _first(str(e)) or type(e).__name__)
    to = None if res.outcome == "up to date" else target
    say(f"{slug}: {res.outcome}" + (f": {res.reason}" if res.reason else ""))
    return _row(slug, frm, to, res.outcome, res.reason, res.pr, res.next)


def _dry(slug: str, default: str, frm: str, old: str | None, target: str) -> dict:
    nxt = []
    rc, out, _ = gh(["pr", "list", "-R", slug, "--state", "open", "--json", "number,url,headRefName,labels", "--limit", "100"])
    if rc == 0:
        prs = [p for p in json.loads(out or "[]") if str(p.get("headRefName", "")).startswith(fleet_pr.BRANCH_PREFIX)]
        if prs:
            nxt.append("would update open PR " + max(prs, key=lambda p: p["number"])["url"])
    if old is not None and core.vtuple(old)[0] == 4 and core.vtuple(target)[0] >= 5:
        nxt.append("5.0 migration: merges on green CI when proved")
    elif old is None or core.vtuple(old)[0] < core.vtuple(target)[0]:
        nxt.append("major version: the PR will stay open")
    return _row(slug, frm, target, "would update", nxt=nxt)


def counts_of(rows: list[dict]) -> dict[str, int]:
    return {o: n for o in ORDER if (n := sum(1 for r in rows if r["outcome"] == o))}


def render(target: str, owners: list[str], only: list[str], dry: bool, rows: list[dict], counts: dict[str, int]) -> str:
    scope = f"only: {', '.join(only)}" if only else f"owners: {', '.join(owners)}"
    out = [f"Fleet update to platform {target} ({scope})" + (" — dry run, nothing was changed" if dry else ""), ""]
    if not rows:
        out.append("no platform repos found")
        return "\n".join(out)
    cells = [["repo", "from", "to", "outcome", "PR"]]
    for r in rows:
        outcome = r["outcome"] + (f": {r['reason']}" if r["reason"] else "")
        cells.append([r["repo"], r["from"] or "-", r["to"] or "-", outcome, r["pr"] or "-"])
    widths = [max(len(c[i]) for c in cells) for i in range(5)]
    fmt = lambda c: "  " + "  ".join(v.ljust(w) for v, w in zip(c, widths)).rstrip()  # noqa: E731
    out.append(fmt(cells[0]))
    for c, r in zip(cells[1:], rows):
        out.append(fmt(c))
        out += [f"      next: {s}" for s in r["next"]]
    out += ["", f"{len(rows)} repo(s): " + ", ".join(f"{o} {n}" for o, n in counts.items())]
    return "\n".join(out)


def _record(rid: str | None, row: dict) -> None:
    runs.event(rid, "repos", row["repo"], {k: row[k] for k in ("from", "to", "outcome", "reason", "pr")})


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    for s in ns.only:
        if not SLUG_RE.match(s):
            raise PlatformError(f"--only expects owner/name, got '{s}'")
    target = check_target(ns.ref)
    rid = None if ns.dry_run else runs.start("fleet", repo=None)
    owners: list[str] = []
    entries: dict[str, dict | None] = {}
    try:
        if ns.only:
            entries = {s: None for s in ns.only}
        else:
            if ns.owner:
                owners = list(dict.fromkeys(ns.owner))
            else:
                rc, out, _ = gh(["api", "user", "-q", ".login"])
                if rc != 0 or not out.strip():
                    raise PlatformError("gh is not logged in; fix: gh auth login")
                owners = [out.strip()]
            for owner in owners:
                for e in _list_owner(owner):
                    entries.setdefault(e["nameWithOwner"], e)
    except PlatformError:
        runs.finish(rid, "failed")
        raise
    templates = {s["template"] for s in core.registry.load()}
    rows: list[dict] = []
    for slug in sorted(entries, key=str.lower):
        row = process(slug, entries[slug], bool(ns.only), target, ns.ref, ns.timeout, ns.dry_run, templates)
        if row is None:
            continue
        rows.append(row)
        _record(rid, row)
    counts = counts_of(rows)
    code = 1 if counts.get("left open") or counts.get("failed") else 0
    if not ns.dry_run:
        runs.set_section(rid, "fleet", {"target": target, "ref": ns.ref, "owners": owners, "only": ns.only, "counts": counts})
        if counts.get("failed"):
            runs.finish(rid, "failed")
        elif counts.get("left open"):
            runs.finish(rid, "escalated", escalation={"reason": f"{counts['left open']} repo(s) left open for review",
                                                      "cause": "unknown"})
        else:
            runs.finish(rid, "done")
    if ns.json:
        print(json.dumps({"target": target, "ref": ns.ref, "owners": owners, "only": ns.only, "dry_run": ns.dry_run, "repos": rows,
                          "counts": counts, "exit": code}, indent=2))
    else:
        print(render(target, owners, ns.only, ns.dry_run, rows, counts))
    return code
