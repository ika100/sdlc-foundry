"""`cplat platform hold` (spec 198, ADR-089): show or clear the release hold of a repo.

  cplat platform hold [--clear] [--json] [--repo DIR]

Without flags it prints the hold (`release hold on <owner>/<name>: release <version> since <time>, process <pid>,
running` or `stopped at confirm merge|tag, expires <time>`) or `no release hold on <owner>/<name>`; a hold whose
process is gone or whose expiry has passed shows as none and is left alone. `--json` prints the same as one object
(`null` when there is none). `--clear` removes the hold file (stale or live), prints `release hold of <owner>/<name>
cleared by hand` (with `--json`: `{"cleared": <the removed hold or null>}`); waiting merges then continue. Exit 0; 2 for
a usage error.

Public API: `main(argv) -> int`.
"""
from __future__ import annotations

import argparse
import json

import dispatch_state
import release_hold


def _view_of(h: release_hold.Hold) -> dict:
    state = "running" if h.state == "running" else f"stopped at confirm {h.confirm}"
    return {"version": h.version, "since": h.since, "pid": h.pid, "state": state, "expires": h.expires}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="cplat platform hold", description="Show or clear the release hold of a repo.")
    p.add_argument("--clear", action="store_true", help="remove the hold by hand")
    p.add_argument("--json", action="store_true", help="print one JSON object (null when there is no hold)")
    p.add_argument("--repo", default=".")
    args = p.parse_args(argv)
    slug = dispatch_state.slug_of(args.repo)
    if args.clear:
        removed = release_hold.clear(slug)
        v = None if removed is None else _view_of(removed)
        if args.json:
            print(json.dumps({"cleared": v}))
        elif removed is None:
            print(release_hold.text(slug, None))
        else:
            print(f"release hold of {slug} cleared by hand")
        return 0
    v = release_hold.view(slug)
    print(json.dumps(v) if args.json else release_hold.text(slug, v))
    return 0
