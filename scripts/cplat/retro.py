"""cplat platform retro: the weekly platform retro (spec 090, ADR-039).

  cplat platform retro [--week W] [--json] [--out DIR]       build the report of the last complete week (reads only)
  cplat platform retro propose --dir DIR [--model M] [--max-minutes N]   headless Claude writes DIR/proposals.json (always exit 0)
  cplat platform retro post [--dir DIR] [--week W]           check the proposals, post the public issue and the full report to the run store
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import autoissue
import core
import doctor
import retro_github
import retro_proposals
import retro_report
import runs
import runs_report
import runs_store
import spec as specmod
from core import PlatformError

_WEEK = re.compile(r"^\d{4}-W\d{2}$")
_ISSUE_TITLE = re.compile(r"^Weekly retro (\d{4})-W(\d{2})$")
_TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "RETRO_GH_TOKEN")
_NO_STEP = "no proposal step ran"
_INDEX_HEAD = "# Retros\n\n| Week | Report | Issue |\n|---|---|---|\n"
_WEEK_ERROR = "--week must be a complete ISO week before today, like 2026-W42"


def _now() -> str:
    return runs.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _week(arg: str | None) -> str:
    today = runs.utcnow().date()
    if arg is None:
        return retro_report.last_complete_week(today)
    try:
        if not _WEEK.match(arg):
            raise ValueError(arg)
        end = retro_report.week_bounds(arg)[1]
    except (ValueError, OverflowError):
        raise PlatformError(_WEEK_ERROR) from None
    if end.date() > today:
        raise PlatformError(_WEEK_ERROR)
    return arg


def _store():
    st = runs.store_status()
    if st.state != "ok":
        detail = f"{st.slug} unreachable: {st.detail}" if st.state == "unreachable" else st.detail
        raise PlatformError(f"run store not usable for the retro: {detail}", hint=doctor.run_store_check(st)["fix"])
    return st.slug, runs.open_store(st.slug)


def build_report(week: str) -> dict:
    slug, store = _store()
    first = retro_report.week_bounds(retro_report.previous_week(week))[0].date()
    days = [first + datetime.timedelta(days=i) for i in range(14)]
    try:
        texts = [t for _, t in store.read(days)]
    except runs_store.StoreError as e:
        raise PlatformError(f"run store {slug} cannot be read: {e}", hint=f"gh repo view {slug}") from None
    records, _followups, malformed = runs_report.parse(texts)
    repo = autoissue.default_repo()
    try:
        tracker = retro_github.tracker()
        autos = tracker.auto_issues(repo, since=f"{first.isoformat()}T00:00:00Z")
        opens = tracker.open_issues(repo)
    except autoissue.TrackerError as e:
        raise PlatformError(f"platform issues of {repo} cannot be read: {e}", hint="gh auth status") from None
    good, _bad = specmod.scan(core.PLATFORM_ROOT)
    specs = [{"number": s.number, "id": s.id, "title": str(s.meta.get("title", "")), "status": s.status,
              "tracks": list(s.meta.get("tracks") or [])}
             for s in good if s.status.lower() not in ("done", "superseded")]
    return retro_report.build(records, auto_issues=autos, open_issues=opens, specs=specs, week=week, store=slug,
                              generated_at=_now(), malformed=malformed)


# ---------------- report ----------------

def _report_mode(ns: argparse.Namespace) -> int:
    report = build_report(_week(ns.week))
    print(json.dumps(report, indent=2) if ns.json else retro_report.render_private(report, retro_proposals.not_generated(_NO_STEP)),
          end="\n" if ns.json else "")
    if ns.out:
        d = Path(ns.out)
        d.mkdir(parents=True, exist_ok=True)
        for stale in ("proposals.json", "proposals.error"):
            (d / stale).unlink(missing_ok=True)
        (d / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (d / "report.md").write_text(retro_report.render_private(report, retro_proposals.not_generated(_NO_STEP)), encoding="utf-8")
        (d / "prompt.md").write_text(retro_proposals.prompt(d), encoding="utf-8")
    return 0


# ---------------- propose ----------------

def _print_log_tail(log: Path, lines: int = 20) -> None:
    """The end of claude's output, for the job log only: the posted reason stays short (the platform repo may be public)."""
    try:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return
    for line in tail:
        print(f"  claude: {line}")


def _fail(d: Path, reason: str) -> int:
    try:
        (d / "proposals.error").write_text(reason + "\n", encoding="utf-8")
    except OSError:
        pass
    print(f"proposals: not generated ({reason})")
    return 0


def _propose(ns: argparse.Namespace) -> int:
    d = Path(ns.dir)
    report_path = d / "report.json"
    if not report_path.is_file():
        return _fail(d, f"no report in {d}")
    if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        return _fail(d, "no Claude credential (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY is not set)")
    for stale in ("proposals.json", "proposals.error"):
        (d / stale).unlink(missing_ok=True)
    cmd = [os.environ.get("CPLAT_CLAUDE") or "claude", "-p", retro_proposals.prompt(d), "--permission-mode", "dontAsk",
           "--allowedTools", "Read,Write", "--output-format", "text"]
    if ns.model:
        cmd += ["--model", ns.model]
    env = {k: v for k, v in os.environ.items() if k not in _TOKENS}
    env["CPLAT_HEADLESS"] = "1"
    try:
        with (d / "propose.log").open("w", encoding="utf-8") as log:
            p = subprocess.run(cmd, cwd=d, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=ns.max_minutes * 60, check=False)
    except FileNotFoundError:
        return _fail(d, "claude is not installed on this machine")
    except subprocess.TimeoutExpired:
        return _fail(d, f"claude timed out after {ns.max_minutes:g} min")
    except OSError as e:
        return _fail(d, f"claude could not be started: {e.strerror or e}")
    if p.returncode != 0:
        _print_log_tail(d / "propose.log")
        return _fail(d, f"claude exited with {p.returncode}")
    if not (d / "proposals.json").is_file():
        return _fail(d, "no proposals.json written")
    try:
        data = retro_proposals.load(d / "proposals.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        checked = retro_proposals.validate(data, report)
    except (ValueError, OSError) as e:
        return _fail(d, str(e))
    print(f"proposals: written ({len(checked.specs)} spec(s), {len(checked.prompts)} prompt change(s))")
    return 0


# ---------------- post ----------------

def _index(old: str | None, week: str, url: str) -> str:
    rows: dict[str, str] = {}
    for line in (old or "").splitlines():
        m = re.match(r"^\| (\d{4}-W\d{2}) \|", line)
        if m:
            rows[m.group(1)] = line
    rows[week] = f"| {week} | [report]({week}.md) | {url} |"
    return _INDEX_HEAD + "".join(rows[w] + "\n" for w in sorted(rows, reverse=True))


def _load_proposals(d: Path | None, report: dict) -> tuple[str, str, retro_proposals.Checked | None]:
    """(public section, private section, checked or None)."""
    def none(reason: str):
        s = retro_proposals.not_generated(reason)
        return s, s, None
    if d is None:
        return none(_NO_STEP)
    if (d / "proposals.json").is_file():
        try:
            checked = retro_proposals.validate(retro_proposals.load(d / "proposals.json"), report)
        except ValueError as e:
            return none(str(e))
        for line in checked.refused:
            print(line, file=sys.stderr)
        return retro_proposals.render_public_section(checked), retro_proposals.render_private_section(checked), checked
    if (d / "proposals.error").is_file():
        first = (d / "proposals.error").read_text(encoding="utf-8").strip().splitlines()
        return none(first[0] if first else "unknown reason")
    return none(_NO_STEP)


def _post(ns: argparse.Namespace) -> int:
    d = Path(ns.dir) if ns.dir else None
    if d is not None:
        try:
            report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PlatformError(f"no usable report in {d}: {e}", hint="cplat platform retro --out DIR") from None
        slug, store = _store()
    else:
        report = build_report(_week(ns.week))
        slug, store = _store()
    week = report["week"]
    public_md, private_md, checked = _load_proposals(d, report)
    public = retro_report.render_public(report, public_md)
    private = autoissue.scrub(retro_report.render_private(report, private_md))
    found = retro_report.leaks(public, report)
    if found:
        raise PlatformError(f"the public retro would name {len(found)} private name(s); nothing was posted",
                            hint="fix the proposal text or report a platform bug with /issue:report")
    repo = autoissue.default_repo()
    title = f"Weekly retro {week}"
    try:
        tracker = retro_github.tracker()
        existing = tracker.retro_issues(repo)
        mine = sorted((i for i in existing if i.get("title") == title), key=lambda i: i["number"])
        if mine:
            url, verb = tracker.edit_body(repo, mine[0]["number"], public), "updated"
        else:
            url, verb = tracker.create(repo, title, public, [retro_github.LABEL]), "created"
        closed = 0
        for i in sorted(existing, key=lambda i: i["number"]):
            m = _ISSUE_TITLE.match(str(i.get("title")))
            if m and i.get("state") == "open" and f"{m.group(1)}-W{m.group(2)}" < week:
                tracker.comment(repo, i["number"], f"Superseded by the retro for {week}: {url}")
                tracker.close(repo, i["number"])
                closed += 1
    except autoissue.TrackerError as e:
        raise PlatformError(f"the retro issue of {repo} could not be written: {e}", hint="gh auth status") from None

    lines = private.splitlines()
    md = "\n".join(lines[:1] + [f"Issue: {url}"] + lines[1:]) + "\n"
    doc = {"report": report, "issue": url, "refused": checked.refused if checked else [],
           "proposals": {"specs": checked.specs, "prompts": checked.prompts} if checked else None}
    try:
        index = _index(store.read_file("retros/README.md"), week, url)
        store.put({f"retros/{week}.md": md, f"retros/{week}.json": autoissue.scrub(json.dumps(doc, indent=2)) + "\n",
                   "retros/README.md": index}, f"retro: {week}")
    except runs_store.StoreError as e:
        retry = f"cplat platform retro post --dir {d}" if d else "cplat platform retro post"
        raise PlatformError(f"retro posted as {url}, but the run store could not be updated: {e}",
                            hint=f"{retry}   (replaces the issue body and retries the store)") from None
    print(f"retro: {url} ({verb}); closed {closed} earlier retro issue(s); report in the run store")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform retro", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--week")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    if argv and argv[0] == "propose":
        pp = argparse.ArgumentParser(prog="cplat platform retro propose")
        pp.add_argument("--dir", required=True)
        pp.add_argument("--model")
        pp.add_argument("--max-minutes", type=float, default=20.0)
        return _propose(pp.parse_args(argv[1:]))
    if argv and argv[0] == "post":
        pp = argparse.ArgumentParser(prog="cplat platform retro post")
        pp.add_argument("--dir")
        pp.add_argument("--week")
        return _post(pp.parse_args(argv[1:]))
    return _report_mode(ap.parse_args(argv))
