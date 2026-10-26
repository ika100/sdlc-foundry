"""`cplat platform runs usage <run_id> | --session <id> [--json]` (spec 099, ADR-035): tokens and estimated cost of one run or session."""
from __future__ import annotations

import argparse
import datetime
import json

import runs
import runs_report
import runs_store
import runs_usage
import runs_usage_report
from core import PlatformError


def _find(run_id: str) -> dict | None:
    """The last line with this run id: the local buffer first, then the store files of the run's day and the next."""
    for r in reversed(runs._safe_buffer()):
        if r.get("run_id") == run_id and not r.get("followup"):
            return r
    slug = runs.configured_repo()
    if slug is None:
        return None
    try:
        day = datetime.datetime.strptime(run_id[:8], "%Y%m%d").date()
    except ValueError:
        return None
    try:
        files = runs.open_store(slug).read([day, day + datetime.timedelta(days=1)])
    except runs_store.StoreError as e:
        raise PlatformError(f"run store {slug} is unreachable: {e}",
                            hint=f"gh repo view {slug}   (is gh logged in, and may it read the repo?)") from None
    records, _, _ = runs_report.parse([text for _, text in files])
    hits = [r for r in records if r.get("run_id") == run_id]
    return hits[-1] if hits else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform runs usage", description="Tokens and estimated cost of one run or session.")
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--session", metavar="ID")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    if bool(ns.run_id) == bool(ns.session):
        ap.error("give a run id or --session <id>")
    if ns.session:
        try:
            usage = runs_usage.for_session(ns.session)
        except LookupError:
            raise PlatformError(f"no transcript for session {ns.session} on this machine") from None
        if ns.json:
            print(json.dumps({"session": ns.session, "usage": usage}, indent=2))
        else:
            print(runs_usage_report.render_section(f"Usage of session {ns.session} (this machine)", usage, phases=False))
        return 0
    rec = _find(ns.run_id)
    if rec is None:
        slug = runs.configured_repo()
        where = f"the run store {slug} or the local buffer" if slug else "the local buffer (no run store configured)"
        raise PlatformError(f"run {ns.run_id} not found in {where}")
    usage = rec.get("usage")
    if not isinstance(usage, dict):
        raise PlatformError(f"run {ns.run_id} has no usage section (recorded before spec 099, or started outside a Claude Code session)")
    if ns.json:
        print(json.dumps({"run_id": ns.run_id, "kind": rec.get("kind"), "outcome": rec.get("outcome"), "usage": usage}, indent=2))
        return 0
    note = f"; incomplete: {usage['incomplete']}" if usage.get("incomplete") else ""
    header = (f"Usage of run {ns.run_id} ({rec.get('kind')}, {rec.get('outcome')}); "
              f"estimate from the price table of {usage.get('price_table')}{note}")
    print(runs_usage_report.render_section(header, usage, phases=True))
    return 0
