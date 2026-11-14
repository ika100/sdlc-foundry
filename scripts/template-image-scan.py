#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Template image scan helpers (spec 189): pick the templates to scan and judge a trivy report.

    uv run scripts/template-image-scan.py select --event <name> [--base <sha>]
    uv run scripts/template-image-scan.py evaluate --template <t> --report <trivy.json> [--accepted <path>] [--today D]

Exit codes of `evaluate`: 0 clean, 1 unaccepted CRITICAL or entry problem, 2 usage or input error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import yaml

TEMPLATES = ["service-python", "service-java", "service-go", "web-nextjs"]
SELF_PATHS = {
    "scripts/template-image-scan.py",
    ".github/image-scan-accepted.yml",
    ".github/workflows/template-image-scan.yml",
}
DEFAULT_ACCEPTED = ".github/image-scan-accepted.yml"
MAX_DAYS = 90


class InputError(Exception):
    """A usage or input error (exit code 2)."""


def select_templates(event: str, changed_paths: list[str]) -> list[str]:
    """The templates to scan, in the fixed order."""
    if event != "pull_request":
        return list(TEMPLATES)
    paths = list(changed_paths)
    if any(p in SELF_PATHS for p in paths):
        return list(TEMPLATES)
    return [t for t in TEMPLATES if any(p.startswith(f"templates/{t}/") for p in paths)]


def _date(value: object, field: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise InputError(f"entry field {field} is not a date: {value!r}") from exc


def load_entries(text: str) -> list[dict]:
    """Parse and validate the accepted-finding list."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InputError(f"accepted list is not YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise InputError("accepted list needs a `findings` list")
    entries = []
    for raw in data["findings"]:
        if not isinstance(raw, dict):
            raise InputError(f"accepted entry is not a mapping: {raw!r}")
        for key in ("template", "cve", "added", "review_by"):
            if raw.get(key) in (None, ""):
                raise InputError(f"accepted entry {raw!r} lacks `{key}`")
        if raw["template"] not in TEMPLATES:
            raise InputError(f"accepted entry names unknown template {raw['template']!r}")
        reason = raw.get("reason")
        entries.append({
            "template": raw["template"],
            "cve": str(raw["cve"]),
            "reason": reason.strip() if isinstance(reason, str) else "",
            "added": _date(raw["added"], "added"),
            "review_by": _date(raw["review_by"], "review_by"),
        })
    return entries


def _findings(report: object) -> list[dict]:
    if not isinstance(report, dict):
        raise InputError("report is not a trivy JSON object")
    seen: set[tuple[str, str, str]] = set()
    found = []
    for result in report.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            key = (v["VulnerabilityID"], v.get("PkgName", ""), v.get("InstalledVersion", ""))
            if key in seen:
                continue
            seen.add(key)
            found.append(v)
    return found


def _describe(v: dict, template: str) -> str:
    fixed = v.get("FixedVersion")
    tail = f"(fixed in {fixed})" if fixed else "(no fix)"
    return f"{v['VulnerabilityID']} in {template}: {v.get('PkgName', '')} {v.get('InstalledVersion', '')} {tail}"


def evaluate(template: str, report: object, entries: list[dict], today: dt.date) -> tuple[int, list[str]]:
    """Judge one template's report; returns (exit code, output lines)."""
    findings = _findings(report)
    all_cves = {v["VulnerabilityID"] for v in findings}
    problems: list[str] = []
    valid: dict[str, dict] = {}
    for e in entries:
        if e["template"] != template:
            continue
        found = []
        if not e["reason"]:
            found.append("no reason")
        if e["review_by"] < today:
            found.append("review date passed")
        if e["review_by"] > e["added"] + dt.timedelta(days=MAX_DAYS):
            found.append("review date too far")
        if e["cve"] not in all_cves:
            found.append("no longer found")
        problems += [f"entry {e['cve']} in {template}: {p}" for p in found]
        if not found:
            valid[e["cve"]] = e
    crit_lines, high_lines, accepted_lines = [], [], []
    accepted_cves: set[str] = set()
    for v in findings:
        cve = v["VulnerabilityID"]
        if v.get("Severity") == "CRITICAL":
            if cve in valid:
                if cve not in accepted_cves:
                    accepted_cves.add(cve)
                    e = valid[cve]
                    accepted_lines.append(
                        f"accepted: {cve} in {template}: {e['reason']} (review by {e['review_by'].isoformat()})")
            else:
                crit_lines.append(f"CRITICAL: {_describe(v, template)}")
        elif v.get("Severity") == "HIGH":
            high_lines.append(f"HIGH: {_describe(v, template)}")
    summary = (f"scan {template}: {len(crit_lines)} critical, {len(high_lines)} high, "
               f"{len(accepted_lines)} accepted, {len(problems)} entry problems")
    lines = crit_lines + high_lines + accepted_lines + problems + [summary]
    return (1 if crit_lines or problems else 0), lines


def _cmd_select(args: argparse.Namespace) -> int:
    changed: list[str] = []
    if args.event == "pull_request":
        if not args.base:
            print("select: --base is required for pull_request", file=sys.stderr)
            return 2
        proc = subprocess.run(["git", "diff", "--name-only", f"{args.base}...HEAD"],
                              capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            print(f"select: git diff failed: {proc.stderr.strip()}", file=sys.stderr)
            return 2
        changed = proc.stdout.splitlines()
    chosen = select_templates(args.event, changed)
    print("templates=" + json.dumps(chosen, separators=(",", ":")))
    print("any=" + ("true" if chosen else "false"))
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    try:
        if args.template not in TEMPLATES:
            raise InputError(f"unknown template {args.template!r}")
        try:
            report = json.loads(Path(args.report).read_text())
        except (OSError, ValueError) as exc:
            raise InputError(f"cannot read report {args.report}: {exc}") from exc
        try:
            text = Path(args.accepted).read_text()
        except OSError as exc:
            raise InputError(f"cannot read accepted list {args.accepted}: {exc}") from exc
        today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
        code, lines = evaluate(args.template, report, load_entries(text), today)
    except (InputError, ValueError, KeyError, TypeError) as exc:
        print(f"evaluate: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--event", required=True)
    s.add_argument("--base")
    e = sub.add_parser("evaluate")
    e.add_argument("--template", required=True)
    e.add_argument("--report", required=True)
    e.add_argument("--accepted", default=DEFAULT_ACCEPTED)
    e.add_argument("--today")
    args = parser.parse_args(argv)
    return _cmd_select(args) if args.cmd == "select" else _cmd_evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
