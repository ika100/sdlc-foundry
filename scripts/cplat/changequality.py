"""`cplat platform change-quality` (spec 223): which releases caused fix entries, how far each reached, and the change-failure rate.

`aggregate` is pure (releases, fix entries, journeys and two injected readers in, one dict out); `render_text` and the JSON
document come from that dict; `main` reads the repo through changequality_sources. The JSON goes to stdout alone, progress to
stderr."""
from __future__ import annotations

import argparse
import datetime
import json
import re
from collections.abc import Callable
from pathlib import Path

import changequality_sources as src
import core
import feedback
import fixcause
from core import PlatformError

UNRELEASED = src.UNRELEASED
DEFAULT_DAYS = 90
_FOREVER = (10**9,)

Resolve = Callable[[fixcause.Cause], list[str | None]]
Fleet = Callable[[], "dict[str, list[str]] | src.FleetUnknown"]


def _key(version: str) -> tuple[int, ...]:
    return _FOREVER if version == UNRELEASED else core.vtuple(version)


def _short(entry: str) -> str:
    return " ".join(entry.split())[:100]


def _label(cause: fixcause.Cause | None) -> str | None:
    if cause is None:
        return None
    if cause.kind == "prs":
        return ", ".join(f"#{n}" for n in cause.prs)
    if cause.kind == "version":
        return f"v{cause.version}"
    return cause.kind


def _pct(failed: int, total: int) -> int | None:
    return None if total == 0 else (100 * failed + total // 2) // total


def _rate(failed: int, total: int) -> dict:
    return {"failed": failed, "releases": total, "pct": _pct(failed, total)}


def affected_repos(stamps: "dict[str, list[str]] | src.FleetUnknown", release: str, first_carrier: str) -> tuple[list[str] | str, str | None]:
    """Repos whose `.platform-version` held a version v with release <= v < first carrier; ("unknown", reason) when unreadable."""
    if isinstance(stamps, src.FleetUnknown):
        return "unknown", stamps.reason
    low, high = _key(release), _key(first_carrier)
    return sorted(s for s, vs in stamps.items() if any(low <= core.vtuple(v) < high for v in vs)), None


def aggregate(releases: list[src.Release], fixes: list[tuple[str, str, str | None]],
              journeys: list[tuple[int, set[int]]], resolve: Resolve, fleet: Fleet, *,
              since: str | None, today: datetime.date) -> dict:
    """`fixes` are (carrier, entry, fragment id or None); carrier is a version or `Unreleased`."""
    ordered = sorted(releases, key=lambda r: core.vtuple(r.version))
    versions = {r.version for r in ordered}
    if since:
        floor = core.vtuple(since.lstrip("v"))
        window = [r for r in ordered if core.vtuple(r.version) >= floor]
    else:
        cutoff = (today - datetime.timedelta(days=DEFAULT_DAYS)).isoformat()
        window = [r for r in ordered if r.date >= cutoff]
    in_window = {r.version for r in window}
    counted = in_window | {UNRELEASED}

    caused: dict[str, list[dict]] = {r.version: [] for r in window}
    nums: dict[str, set[int]] = {r.version: set() for r in window}
    carriers: dict[str, set[str]] = {r.version: set() for r in window}
    caught: list[dict] = []
    unattributed: list[dict] = []
    none: list[dict] = []

    for carrier, entry, frag_id in fixes:
        cause = fixcause.parse_cause(entry)
        short = _short(entry)
        label = _label(cause)

        def unattr(reason: str) -> None:
            if carrier in counted:
                unattributed.append({"carrier": carrier, "cause": label, "reason": reason, "entry": short})

        if cause is None:
            unattr("no cause line")
            continue
        if cause.kind == "unknown":
            unattr("unknown")
            continue
        if cause.kind == "none":
            if carrier in counted:
                none.append({"carrier": carrier, "entry": short})
            continue
        if cause.kind == "version":
            if cause.version not in versions:
                unattr(f"no release {cause.version}")
                continue
            pairs: list[tuple[str, str]] = [(str(cause.version), f"v{cause.version}")]
        else:
            found = resolve(cause)
            missing = [n for n, v in zip(cause.prs, found) if v is None]
            if missing:
                unattr(f"#{missing[0]} not found")
                continue
            pairs = [(str(v), f"#{n}") for n, v in zip(cause.prs, found)]
        if any(_key(v) > _key(carrier) for v, _ in pairs):
            unattr("cause after the fix")
            continue
        before = [(v, lab) for v, lab in pairs if _key(v) < _key(carrier)]
        if not before:
            if carrier in counted:
                caught.append({"carrier": carrier, "cause": label, "entry": short})
            continue
        by_release: dict[str, list[str]] = {}
        for v, lab in before:
            by_release.setdefault(v, []).append(lab)
        for v, labs in by_release.items():
            if v in in_window:
                caused[v].append({"carrier": carrier, "cause": ", ".join(labs), "entry": short})
                nums[v] |= fixcause.numbers(entry, frag_id)
                carriers[v].add(carrier)

    stamps = None
    rows = []
    for r in window:
        row = {"version": r.version, "date": r.date, "caused": caused[r.version],
               "carried_by": sorted(carriers[r.version], key=_key), "stopped_journeys": [],
               "affected_repos": [], "affected_reason": None}
        if caused[r.version]:
            row["stopped_journeys"] = sorted(n for n, named in journeys if named & nums[r.version])
            if stamps is None:
                stamps = fleet()
            row["affected_repos"], row["affected_reason"] = affected_repos(stamps, r.version, row["carried_by"][0])
        rows.append(row)

    failed = sum(1 for r in rows if r["caused"])
    minor = [r for r in rows if r["version"].split(".")[2] == "0"]
    return {
        "window": {"since": since, "days": None if since else DEFAULT_DAYS,
                   "from": window[0].version if window else None, "until": window[-1].version if window else None,
                   "releases": len(window)},
        "releases": rows,
        "caught_before_release": caught,
        "unattributed": unattributed,
        "none": none,
        "change_failure_rate": _rate(failed, len(rows)),
        "change_failure_rate_minor": _rate(sum(1 for r in minor if r["caused"]), len(minor)),
    }


def _rate_text(rate: dict) -> str:
    pct = "n/a" if rate["pct"] is None else f"{rate['pct']}%"
    return f"{rate['failed']} of {rate['releases']} releases ({pct})"


def render_text(agg: dict) -> str:
    w = agg["window"]
    scope = f"since {w['since']}" if w["since"] else f"last {w['days']} days"
    lines = [f"Change quality {w['from'] or '-'} to {w['until'] or '-'} ({w['releases']} releases, {scope})",
             "Releases (fix entries caused, carried by; stopped journeys; downstream repos):"]
    for r in agg["releases"]:
        if not r["caused"]:
            lines.append(f"  {r['version']}: 0")
            continue
        journeys = ", ".join(str(n) for n in r["stopped_journeys"]) or "none"
        repos = r["affected_repos"]
        if repos == "unknown":
            shown = f"unknown ({r['affected_reason']})"
        else:
            shown = f"{len(repos)} ({', '.join(repos)})" if repos else "0"
        lines.append(f"  {r['version']}: {len(r['caused'])}, carried by {', '.join(r['carried_by'])}; "
                     f"stopped journeys: {journeys}; repos: {shown}")
    lines.append(f"caught before release: {len(agg['caught_before_release'])}")
    lines.append(f"unattributed: {len(agg['unattributed'])}")
    lines.append(f"none (not from a platform change): {len(agg['none'])}")
    lines.extend(f"  {n['carrier']}: {n['entry']}" for n in agg["none"])
    lines.append(f"change-failure rate: {_rate_text(agg['change_failure_rate'])}")
    lines.append(f"change-failure rate, minor and major releases: {_rate_text(agg['change_failure_rate_minor'])}")
    return "\n".join(lines)


def collect_fixes(repo: Path, rels: list[src.Release]) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    for r in rels:
        out.extend((r.version, e, None) for e in fixcause.entries(src.fixed_section(r.body)))
    out.extend((UNRELEASED, text.strip(), name) for name, text in src.fragment_fixes(repo))
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="cplat platform change-quality",
                                description="Fix causes, blast radius and change-failure rate of platform releases.")
    p.add_argument("--since", metavar="vX.Y.Z", help="window: releases from this version on (default: last 90 days)")
    p.add_argument("--json", action="store_true", help="print one JSON document")
    p.add_argument("--repo", default=".")
    args = p.parse_args(argv)
    repo = Path(args.repo)
    if not (repo / ".claude-plugin/marketplace.json").is_file():
        raise PlatformError(f"change-quality runs in the platform repo {feedback.REPO} (no .claude-plugin/marketplace.json here)")
    if args.since and not re.fullmatch(r"v\d+\.\d+\.\d+", args.since):
        raise PlatformError(f"--since expects a version like v5.30.0, got {args.since!r}")
    rels = src.releases(repo)
    if args.since and args.since[1:] not in {r.version for r in rels}:
        raise PlatformError(f"no release {args.since[1:]} in docs/CHANGELOG.md")
    src.say("reading the changelog and git history")

    def resolve(cause: fixcause.Cause) -> list[str | None]:
        return [src.pr_release(repo, n, slug=feedback.REPO) for n in cause.prs]

    def fleet():
        src.say("reading the fleet")
        return src.fleet_stamps()

    agg = aggregate(rels, collect_fixes(repo, rels), src.stopped_journeys(repo), resolve, fleet,
                    since=args.since, today=datetime.date.today())
    print(json.dumps(agg, indent=2) if args.json else render_text(agg))
    return 0
